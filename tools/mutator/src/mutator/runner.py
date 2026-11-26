"""Run a project's tests, and decide the command for each language."""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

Command = str | list[str]


@dataclass(frozen=True)
class CommandResult:
    code: int
    timed_out: bool
    seconds: float
    output: str


def _worker_home(cwd: Path) -> Path | None:
    """The overlay root when cwd is inside target/mutation-workers."""

    for candidate in [cwd, *cwd.parents]:
        parent = candidate.parent
        if not candidate.name.startswith("worker-"):
            continue
        if not parent.name.startswith("run-"):
            continue
        if parent.parent.name == "mutation-workers":
            return candidate
    return None


def _source_entries(cwd: Path, worker: Path) -> list[str]:
    found = []
    for directory in (cwd / "src", cwd, worker / "src", worker):
        text = str(directory)
        if text in found:
            continue
        if directory.is_dir():
            found.append(text)
    return found


def _prefer_worker_sources(cwd: Path, environment: dict) -> None:
    """An editable install would otherwise import the unmutated tree."""

    worker = _worker_home(cwd)
    if worker is None:
        return
    entries = _source_entries(cwd, worker)
    current = environment.get("PYTHONPATH")
    if current:
        entries.append(current)
    if not entries:
        return
    environment["PYTHONPATH"] = os.pathsep.join(entries)


def display_command(command: Command) -> str:
    """A shell-looking rendering. A list is quoted so it can be pasted."""

    if isinstance(command, str):
        return command
    return " ".join(shlex.quote(part) for part in command)


class CommandRunner:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def run(self, command: Command, cwd: Path, timeout: float | None) -> CommandResult:
        """Run `command` in `cwd`.

        A list is an argument vector and does not go through a shell, so a
        path with spaces or metacharacters stays one argument. A string is a
        command the user typed in `--test-command` or `--coverage-command`.
        """

        if self.verbose:
            print(f"+ ({cwd}) {display_command(command)}", file=sys.stderr)
        started = time.monotonic()
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        _prefer_worker_sources(cwd, environment)
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                shell=isinstance(command, str),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
                env=environment,
            )
        except OSError as exc:
            seconds = time.monotonic() - started
            return CommandResult(code=127, timed_out=False, seconds=seconds, output=str(exc))
        try:
            output, _err = process.communicate(timeout=timeout)
            code = process.returncode if process.returncode is not None else 1
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _err = process.communicate()
            code = 124
            timed_out = True
        seconds = time.monotonic() - started
        return CommandResult(code=code, timed_out=timed_out, seconds=seconds, output=output or "")


def nearest(start: Path, marker: str, stop: Path) -> Path | None:
    current = start if start.is_dir() else start.parent
    stop = stop.resolve()
    current = current.resolve()
    while True:
        if (current / marker).is_file():
            return current
        if current == stop or current.parent == current:
            return None
        current = current.parent


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _clojure_command(directory: Path) -> list[str]:
    deps = directory / "deps.edn"
    bb = directory / "bb.edn"
    if bb.is_file() and not deps.is_file():
        text = _read(bb)
        if "spec" in text:
            return ["bb", "spec", "--tag", "~no-mutate"]
        return ["bb", "test"]
    text = _read(deps)
    if ":spec" in text and "speclj" in text:
        return ["clj", "-M:spec", "--tag", "~no-mutate"]
    if ":spec" in text:
        return ["clj", "-M:spec"]
    return ["clj", "-M:test"]


def _project_interpreter(directory: Path) -> str:
    """The project's virtualenv, or this process when the project has none.

    The path stays absolute and the symlink is left in place. A worker does
    not link ``.venv``, and resolving ``bin/python`` would leave the virtualenv.
    """

    for name in (".venv", "venv"):
        candidate = (directory / name / "bin" / "python").absolute()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def _python_command(directory: Path) -> list[str]:
    interpreter = _project_interpreter(directory)
    pyproject = _read(directory / "pyproject.toml")
    if (
        (directory / "pytest.ini").is_file()
        or (directory / "conftest.py").is_file()
        or "pytest" in pyproject
        or (directory / "setup.cfg").is_file() and "pytest" in _read(directory / "setup.cfg")
    ):
        return [interpreter, "-m", "pytest"]
    return [interpreter, "-m", "unittest", "discover"]


def _nearest_marker(source: Path, root: Path, markers: tuple[str, ...]) -> Path:
    for marker in markers:
        found = nearest(source, marker, root)
        if found is not None:
            return found
    return root


def _go_package(directory: Path, source: Path) -> str:
    relative = source.resolve().parent.relative_to(directory.resolve())
    if relative == Path("."):
        return "."
    return "./" + relative.as_posix()


def _clojure_plan(root: Path, source: Path) -> tuple[Command, Path]:
    directory = _nearest_marker(source, root, ("deps.edn", "bb.edn"))
    return _clojure_command(directory), directory


def _java_plan(root: Path, source: Path) -> tuple[Command, Path]:
    directory = _nearest_marker(source, root, ("pom.xml",))
    return ["mvn", "-q", "test", "-DexcludeTags=no-mutate"], directory


def _go_plan(root: Path, source: Path) -> tuple[Command, Path]:
    directory = _nearest_marker(source, root, ("go.mod",))
    return ["go", "test", "-count=1", _go_package(directory, source)], directory


def _typescript_plan(root: Path, source: Path) -> tuple[Command, Path]:
    directory = _nearest_marker(source, root, ("package.json",))
    return ["npm", "test"], directory


def _rust_plan(root: Path, source: Path) -> tuple[Command, Path]:
    directory = _nearest_marker(source, root, ("Cargo.toml",))
    return ["cargo", "test"], directory


_SKIPPED_DIRECTORIES = {".venv", "venv", "node_modules", "target", ".git", "__pycache__"}


def _related_tests(directory: Path, source: Path) -> list[str]:
    """Test files that import the source module, as paths relative to directory.

    Empty when none are found, so the caller keeps the full suite.
    """

    try:
        parts = source.resolve().relative_to(directory.resolve()).with_suffix("").parts
    except ValueError:
        return []
    candidates = [".".join(parts)]
    if parts and parts[0] == "src":
        candidates.append(".".join(parts[1:]))
    patterns = [re.compile(rf"\b{re.escape(name)}\b") for name in candidates if name]
    if len(parts) > 1:
        package = re.escape(".".join(parts[:-1]))
        patterns.append(re.compile(rf"from\s+{package}\s+import\s+[^\n]*\b{re.escape(parts[-1])}\b"))
    found = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [name for name in dirnames if name not in _SKIPPED_DIRECTORIES]
        for name in filenames:
            if not (name.startswith("test_") or name.endswith("_test.py")) or not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            text = _read(path)
            if any(pattern.search(text) for pattern in patterns):
                found.append(path.relative_to(directory).as_posix())
    return sorted(found)


def _python_plan(root: Path, source: Path) -> tuple[Command, Path]:
    directory = _nearest_marker(source, root, ("pyproject.toml", "pytest.ini", "setup.cfg"))
    command = _python_command(directory)
    if os.environ.get("MUTATOR_RELATED_TESTS") == "1" and command[-1] == "pytest":
        related = _related_tests(directory, source)
        if related:
            command = [*command, *related]
    return command, directory


_PLANS = {
    "clojure": _clojure_plan,
    "java": _java_plan,
    "go": _go_plan,
    "typescript": _typescript_plan,
    "rust": _rust_plan,
    "python": _python_plan,
}


def test_plan(root: Path, source: Path, language: str, override: str | None) -> tuple[Command, Path]:
    """The test command and the directory it runs in.

    A user override stays a shell string. Every generated command is an
    argument vector, so a package path is one argument.
    """

    root = root.resolve()
    if override:
        return override, root
    plan = _PLANS.get(language)
    if plan is None:
        return ["false"], root
    return plan(root, source)
