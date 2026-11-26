#!/usr/bin/env python3
"""flow.py: can this exact change start inspection?

It decides from git and from result files, never from the progress board. For
each repo in the task folder that changed against its base, it needs a baseline
test result, a crapper result and a mutator result for the repo's current HEAD.
Only a user waiver signed with tools/flow_approval.py can stand in for one.

  flow.py next   <KEY> [--dir .scratch] [--root PATH]   the decision and each missing item
  flow.py status <KEY> [--dir .scratch] [--root PATH]   every repo and check, then the decision
  flow.py record <KEY> <repo-path> <check> <outcome> [--count NAME=N ...] [--note TEXT]
                 [--dir .scratch]                       save one result for the repo's HEAD

next and status exit 0 when inspection may start, 1 when it is blocked, 2 on bad usage.
record exits 0 when it wrote the file, 1 when git or the worktree refuses, 2 on bad usage.
Neither next nor status writes anything. They ask origin for its default branch with
git ls-remote, to catch a base branch moved by hand. See tools/flow-gate.md.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = "tstack-flow-result/v1"
CHECKS = ("baseline", "crap", "mutation")
OUTCOMES = ("passed", "failed", "blocked")
# The counts each check must report, in display order.
COUNTS = {
    "baseline": ("tests", "failed", "new_failures"),
    "crap": ("functions", "scored", "over_threshold", "threshold"),
    "mutation": ("sites", "killed", "survived", "uncovered"),
}
RESULT_FIELDS = frozenset(
    {"format", "key", "repo", "check", "base_ref", "base", "head", "outcome", "counts", "note", "recorded_at"}
)
CRAP_LIMIT = 6  # ship/references/quality-gates.md runs crapper with --threshold 6
# Docs-only rule v2: when every changed file ends in one of these, crap and mutation do not apply.
# .mdx is not on the list: an MDX file holds JSX and imports that a front-end build runs as code.
DOC_SUFFIXES = (".adoc", ".md", ".rst")
DOCS_RULE = "docs-only rule v2: every changed file ends in " + ", ".join(DOC_SUFFIXES)
TOOL_OUTPUT = ".metrics/"  # crapper and mutator write here; it does not make a worktree dirty
MAX_FILE = 65536
MAX_DEPTH = 32  # no result or waiver file nests this deep
# \Z, not $: $ also matches before a trailing newline.
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
COUNT_RE = re.compile(r"^[a-z][a-z0-9_]*\Z")
RESULT_NAME_RE = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})-([1-9][0-9]*)\.json\Z")
SHORT = 12  # characters of a commit id shown in the output
# git reads these two from the environment. Every other GIT_* variable is dropped (see git()).
KEEP_GIT_ENV = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"})
REMOTE_TIMEOUT = 20  # seconds for git ls-remote
NO_WAIVERS = (
    "Waivers are not set up on this machine. See tools/flow-approval.md. Blocked gates cannot be waived until then."
)


def _load_approval():
    """Load flow_approval.py from this folder. `python3 -I` leaves the folder off sys.path."""
    spec = importlib.util.spec_from_file_location("flow_approval", Path(__file__).with_name("flow_approval.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


approval = _load_approval()


class GitError(Exception):
    pass


class UsageError(Exception):
    pass


def git_env():
    """os.environ without GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE and every other GIT_* variable,
    so nothing outside the repo folder can point a command at another repo or index."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_") or name in KEEP_GIT_ENV}
    env.update(LC_ALL="C", GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    return env


def git(path, *args, timeout=60):
    """Run a read-only git command in path and return its output.

    core.fsmonitor is off, so git status runs no fsmonitor hook and asks no daemon which files changed.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "-c", "core.fsmonitor=false", *args],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=git_env(),
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitError(f"git {args[0]} failed: {error}") from error
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GitError(f"git {args[0]} failed: {message[-1] if message else 'exit ' + str(result.returncode)}")
    return result.stdout.decode("utf-8", "surrogateescape")


def short(sha):
    return sha[:SHORT]


def default_base_ref(path):
    """origin/HEAD, else origin/dev, else origin/main. The same order as worktree.sh."""
    candidates = []
    try:
        head = git(path, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD").strip()
        if head.startswith("origin/"):
            candidates.append(head[len("origin/"):])
    except GitError:
        pass
    candidates += ["dev", "main"]
    for name in candidates:
        try:
            git(path, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{name}^{{commit}}")
            return f"origin/{name}"
        except GitError:
            continue
    raise GitError("no origin/HEAD, origin/dev or origin/main")


def commit_of(path, ref):
    try:
        return git(path, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}").strip()
    except GitError as error:
        raise GitError(f"{ref} does not point to a commit") from error


def merge_base(path, ref, head):
    try:
        return git(path, "merge-base", ref, head).strip()
    except GitError as error:
        raise GitError(f"HEAD has no common commit with {ref}") from error


def dirty_paths(path):
    """Changed or untracked paths in the worktree, except the files the quality tools write.

    A rename or copy is left out only when both of its paths are under .metrics/.
    """
    out = git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    paths = []
    entries = out.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        status, names = entry[:2], [entry[3:]]
        if "R" in status or "C" in status:
            names.append(entries[index] if index < len(entries) else "")  # its source path
            index += 1
        outside = [name for name in names if not name.startswith(TOOL_OUTPUT)]
        if outside:
            paths.append(outside[0])
    return sorted(paths)


def hidden_paths(path):
    """Tracked files that git status does not look at: marked skip-worktree (S) or assume-unchanged (lowercase).

    In a sparse checkout git marks the files it left out skip-worktree. Those count only when the file is on disk.
    """
    sparse = git(path, "config", "--bool", "--default", "false", "core.sparseCheckout").strip() == "true"
    found = []
    for entry in git(path, "ls-files", "-v", "-z").split("\0"):
        if len(entry) < 3:
            continue
        tag, name = entry[0], entry[2:]
        if tag.islower() or (tag == "S" and (not sparse or os.path.lexists(Path(path) / name))):
            found.append(name)
    return sorted(found)


def changed_files(path, base, head):
    out = git(path, "diff", "--name-only", "--no-renames", "-z", base, head)
    return sorted(name for name in out.split("\0") if name)


def docs_only(files):
    return bool(files) and all(name.lower().endswith(DOC_SUFFIXES) for name in files)


@dataclass
class Repo:
    name: str
    path: Path
    base_ref: str = ""
    base: str = ""
    head: str = ""
    changed: list = field(default_factory=list)
    dirty: list = field(default_factory=list)
    hidden: list = field(default_factory=list)
    error: str = ""
    base_problem: str = ""  # the base cannot be trusted. Blocks like a git error
    warning: str = ""

    @property
    def touched(self):
        return bool(self.changed or self.dirty or self.hidden)


def read_repo(path):
    repo = Repo(path.name, path)
    try:
        repo.head = commit_of(path, "HEAD")
        repo.base_ref = default_base_ref(path)
        repo.base = merge_base(path, repo.base_ref, repo.head)
        repo.changed = changed_files(path, repo.base, repo.head)
        repo.dirty = dirty_paths(path)
        repo.hidden = hidden_paths(path)
        repo.base_problem, repo.warning = remote_base_problem(repo)
    except GitError as error:
        repo.error = str(error)
    return repo


def remote_base_problem(repo):
    """(problem, warning) after comparing the base branch here with the same branch on origin.

    A base branch moved by hand, for example with git update-ref, can swallow the task's commits so that
    the repo looks unchanged. The base commit must be on the branch as origin has it now.
    """
    branch = repo.base_ref[len("origin/"):]
    try:
        out = git(repo.path, "ls-remote", "--symref", "origin", "HEAD", f"refs/heads/{branch}", timeout=REMOTE_TIMEOUT)
    except GitError as error:
        return "", f"cannot reach origin to confirm {repo.base_ref} ({error}). Using {repo.base_ref} as last fetched"
    remote_default, tip = "", ""
    for line in out.splitlines():
        value, _, name = line.partition("\t")
        if name == "HEAD" and value.startswith("ref: refs/heads/"):
            remote_default = value[len("ref: refs/heads/"):]
        elif name == f"refs/heads/{branch}":
            tip = value
    try:
        origin_head = git(repo.path, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD").strip()
    except GitError:
        origin_head = ""
    if origin_head == repo.base_ref and remote_default and remote_default != branch:
        return (
            f"origin/HEAD here points to {repo.base_ref}, but the default branch on origin is {remote_default}. "
            "Run git remote set-head origin --auto, then run next again"
        ), ""
    if not tip:
        return f"origin has no branch {branch}. Run git fetch --prune origin, then run next again", ""
    local = commit_of(repo.path, repo.base_ref)
    if tip == local:
        return "", ""
    try:
        commit_of(repo.path, tip)
    except GitError:
        return (
            f"{branch} on origin is at {short(tip)}, which this clone has not fetched, so the base cannot be confirmed. "
            f"Run git fetch origin in {repo.path}, then run next again"
        ), ""
    if git(repo.path, "rev-list", "--count", repo.base, "--not", tip).strip() != "0":
        return (
            f"{repo.base_ref} here ({short(local)}) holds commits that {branch} on origin ({short(tip)}) does not, "
            f"so the base {short(repo.base)} leaves those commits out of the check. Run git fetch origin, then run next again"
        ), ""
    return "", ""


@dataclass
class Skipped:
    name: str
    reason: str
    problem: str = ""  # set when the folder holds work no repo folder has. Blocks


def slice_owner(path, repos):
    """The repo whose slice worktree this is, or None.

    worktree.sh slice makes _<short>-<slice> from the repo folder <short>, on branch <task branch>--<slice>.
    """
    try:
        common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        branch = git(path, "branch", "--show-current").strip()
    except GitError:
        return None
    for repo in repos:
        prefix = f"_{repo.name}-"
        if repo.error or not path.name.startswith(prefix) or len(path.name) == len(prefix):
            continue
        try:
            owner_common = git(repo.path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
            owner_branch = git(repo.path, "branch", "--show-current").strip()
        except GitError:
            continue
        if common == owner_common and owner_branch and branch == f"{owner_branch}--{path.name[len(prefix):]}":
            return repo
    return None


def evidence_worktree(path):
    """True for the worktree ship's close out makes for the proof images: _evidence-<short> on an
    evidence/<KEY> branch with no commits yet, or with history that shares nothing with the code."""
    if not path.name.startswith("_evidence-"):
        return False
    try:
        if not git(path, "branch", "--show-current").strip().startswith("evidence/"):
            return False
    except GitError:
        return False
    try:
        head = commit_of(path, "HEAD")
    except GitError:
        return True  # the orphan branch has no commit yet
    try:
        merge_base(path, default_base_ref(path), head)
    except GitError:
        return True  # an orphan history: images only, no code
    return False


def skipped_folder(path, repos):
    """Why a folder in the task folder is not a repo, and a problem when it holds commits nothing checks."""
    if not (path / ".git").exists():
        return Skipped(path.name, "not a git worktree")
    owner = slice_owner(path, repos)
    if owner:
        return Skipped(path.name, f"slice worktree of {owner.name}")
    if evidence_worktree(path):
        return Skipped(
            path.name,
            "evidence worktree for the proof images (ship close out), not code. "
            "Remove it with git worktree remove once evidence/<KEY> is pushed",
        )
    reason = f"the name starts with {path.name[0]}, so it is not checked"
    try:
        head = commit_of(path, "HEAD")
        base_ref = default_base_ref(path)
        heads = [repo.head for repo in repos if repo.head]
        count = int(git(path, "rev-list", "--count", "--ignore-missing", head, "--not", base_ref, *heads).strip())
    except (GitError, ValueError) as error:
        return Skipped(path.name, reason, f"it is a git worktree that cannot be read ({error})")
    if count:
        return Skipped(path.name, reason, f"it holds {count} commit(s) that are on no repo folder's HEAD and not on {base_ref}")
    return Skipped(path.name, reason)


def task_repos(root, key):
    """(folder, repos, skipped). Repos are the git worktrees in <root>/worktrees/<KEY>/ whose names
    do not start with _ (slice worktrees) or a dot. Every other folder there is listed in skipped."""
    folder = root / "worktrees" / key
    if not folder.is_dir():
        return folder, [], []
    repos, others = [], []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if entry.name.startswith(("_", ".")) or not (entry / ".git").exists():
            others.append(entry)
        else:
            repos.append(read_repo(entry))
    return folder, repos, [skipped_folder(entry, repos) for entry in others]


# ---- result files ----------------------------------------------------------


def evidence_dir(scratch, key):
    return scratch / f"{key}-evidence"


def results_dir(scratch, key, repo, check):
    return evidence_dir(scratch, key) / "results" / repo / check


def waivers_dir(scratch, key):
    return evidence_dir(scratch, key) / "waivers"


def _no_float(text):
    raise ValueError("floats are not allowed")


def _no_constant(text):
    raise ValueError(f"{text} is not allowed")


def too_deep(value):
    """True when lists and objects nest more than MAX_DEPTH levels. Walks without recursion."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, (dict, list)):
            if depth > MAX_DEPTH:
                return True
            stack.extend((child, depth + 1) for child in (item.values() if isinstance(item, dict) else item))
    return False


def load_json(path):
    """The parsed file. Raises ValueError for a file that is too large, too deep, not JSON or holds a float."""
    with open(path, "rb") as handle:
        raw = handle.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("file is too large")
    try:
        data = json.loads(raw.decode("utf-8"), parse_float=_no_float, parse_constant=_no_constant)
    except RecursionError:
        raise ValueError("file is nested too deeply") from None
    if too_deep(data):
        raise ValueError("file is nested too deeply")
    return data


def is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def counts_problem(check, outcome, counts, note):
    """The reason these counts and this outcome do not fit together, or None."""
    if not isinstance(counts, dict):
        return "counts is not an object"
    for name, value in counts.items():
        if not isinstance(name, str) or not COUNT_RE.match(name):
            return f"count name {name!r} is not lower_snake_case"
        if not is_count(value):
            return f"count {name} is not a whole number of 0 or more"
    if outcome == "blocked":
        if counts:
            return "a blocked result takes no counts, only a note that says why the check could not run"
        if not isinstance(note, str) or not note.strip():
            return "a blocked result needs a note that says why the check could not run"
        return None
    missing = [name for name in COUNTS[check] if name not in counts]
    if missing:
        return f"{outcome} result has no count for {', '.join(missing)}"
    c = counts
    if check == "baseline":
        if c["failed"] > c["tests"] or c["new_failures"] > c["failed"]:
            return "counts do not add up: need new_failures <= failed <= tests"
        if outcome == "passed" and c["tests"] < 1:
            return "passed with 0 tests run"
        if outcome == "passed" and c["new_failures"]:
            return f"passed with {c['new_failures']} new failure(s)"
    elif check == "crap":
        if c["scored"] > c["functions"] or c["over_threshold"] > c["scored"]:
            return "counts do not add up: need over_threshold <= scored <= functions"
        if outcome == "passed" and c["functions"] < 1:
            return "passed with 0 functions scored"
        if outcome == "passed" and c["scored"] < c["functions"]:
            return (
                f"passed with {c['functions'] - c['scored']} function(s) not scored because they have no coverage. "
                "Add tests or ask the user for a waiver"
            )
        if outcome == "passed" and c["over_threshold"]:
            return f"passed with {c['over_threshold']} function(s) over the threshold"
        if outcome == "passed" and not 1 <= c["threshold"] <= CRAP_LIMIT:
            return f"passed with threshold {c['threshold']}, outside 1 to {CRAP_LIMIT}"
    elif check == "mutation":
        if c["killed"] + c["survived"] + c["uncovered"] > c["sites"]:
            return "counts do not add up: need killed + survived + uncovered <= sites"
        if outcome == "passed" and c["killed"] + c["survived"] < 1:
            return "passed with 0 mutants run"
        if outcome == "passed" and c["survived"]:
            return f"passed with {c['survived']} surviving mutant(s)"
        if outcome == "passed" and c["uncovered"]:
            return (
                f"passed with {c['uncovered']} untested site(s): no test runs those changed lines, so no mutant "
                "was tried there. Record it as failed, then add tests or ask the user for a waiver"
            )
    return None


def untested(check, counts):
    """How much of the change no test reaches, from a result's counts, or ''."""
    if check == "mutation" and counts.get("uncovered"):
        return f"{counts['uncovered']} site(s) are untested"
    if check == "crap" and counts.get("functions", 0) > counts.get("scored", 0):
        return f"{counts['functions'] - counts['scored']} function(s) have no coverage"
    return ""


def result_problem(data, key, repo, check, head, base):
    """Why a result file does not describe this check on this commit, or None."""
    if not isinstance(data, dict) or set(data) != RESULT_FIELDS:
        return "the file has missing or extra fields"
    if data["format"] != FORMAT:
        return f"unknown format {data['format']!r}"
    expected = {"key": key, "repo": repo, "check": check, "head": head}
    for name, value in expected.items():
        if data[name] != value:
            return f"{name} is {data[name]!r}, expected {value!r}"
    if data["outcome"] not in OUTCOMES:
        return f"unknown outcome {data['outcome']!r}"
    if not isinstance(data["note"], str) or not isinstance(data["recorded_at"], str):
        return "note and recorded_at must be strings"
    if not isinstance(data["base_ref"], str):
        return "base_ref must be a string"
    if data["base"] != base:
        shown = short(data["base"]) if isinstance(data["base"], str) else repr(data["base"])
        return f"recorded against base {shown}, but the repo's base is {short(base)}"
    return counts_problem(check, data["outcome"], data["counts"], data["note"])


def result_files(folder):
    """{head: [(n, path), ...]} for every well-named file in the folder."""
    found = {}
    if not folder.is_dir():
        return found
    for entry in folder.iterdir():
        match = RESULT_NAME_RE.match(entry.name)
        if match and entry.is_file():
            found.setdefault(match.group(1), []).append((int(match.group(2)), entry))
    for files in found.values():
        files.sort()
    return found


def counts_text(check, counts):
    if not isinstance(counts, dict):
        return ""
    names = [n for n in COUNTS[check] if n in counts] + sorted(n for n in counts if n not in COUNTS[check])
    return ", ".join(f"{name} {counts[name]}" for name in names)


# ---- waivers ---------------------------------------------------------------


def waiver_stage(check):
    return f"waive-{check}"


def waiver_context(repo, head):
    return f"repo={repo} head={head}"


def read_waivers(scratch, key):
    """([(path, request), ...], notes) for the waiver requests of this task, by file name.

    A file that cannot be read is left out with a note, so it cannot stop the other waivers from counting.
    """
    folder = waivers_dir(scratch, key)
    found, notes = [], []
    if not folder.is_dir():
        return found, notes
    for entry in sorted(folder.glob("*.json"), key=lambda p: p.name):
        if not entry.is_file():
            continue
        try:
            request = load_json(entry)
        except (OSError, ValueError) as error:
            notes.append(f"SKIPPED waiver {entry.name}: it cannot be read ({error})")
            continue
        if isinstance(request, dict):
            found.append((entry, request))
    return found, notes


def find_waiver(waivers, key, repo, check, head):
    """(approved request, path) for the first signed waiver of this check, else (None, [unsigned paths])."""
    refused = []
    for entry, request in waivers:
        if (request.get("key"), request.get("stage"), request.get("context")) != (
            key, waiver_stage(check), waiver_context(repo, head)
        ):
            continue
        if approval.verify(request, entry.with_suffix(".sig")):
            return (request, entry), []
        refused.append(entry)
    return None, refused


# ---- the decision ----------------------------------------------------------


@dataclass
class Check:
    repo: str
    name: str
    status: str
    detail: str = ""
    unblock: str = ""
    waiver: str = ""

    @property
    def ok(self):
        return self.status in ("passed", "not applicable", "waived by user")


def record_hint(key, repo, check):
    counts = " ".join(f"--count {name}=N" for name in COUNTS[check])
    return (
        f"flow.py record {key} {repo.path} {check} <passed|failed> {counts}"
        f" (or {check} blocked --note '<why it could not run>', with no counts)"
    )


def waiver_hint(key, repo, check):
    return f"flow_approval.py new {key} {waiver_stage(check)} '{waiver_context(repo.name, repo.head)}' '<reason>'"


def judge(scratch, key, repo, check):
    """The status of one check on one repo, before any waiver."""
    if check in ("crap", "mutation") and docs_only(repo.changed):
        return Check(repo.name, check, "not applicable", DOCS_RULE)
    found = result_files(results_dir(scratch, key, repo.name, check))
    run_it = f"Run the {check} check on {short(repo.head)}, then: {record_hint(key, repo, check)}"
    if repo.head not in found:
        if not found:
            return Check(repo.name, check, "missing", "", run_it)
        newest = []
        for head, files in found.items():
            path = files[-1][1]
            try:
                stamp = load_json(path).get("recorded_at", "")
            except (OSError, ValueError, AttributeError):
                stamp = ""
            newest.append((stamp if isinstance(stamp, str) else "", head))
        last = max(newest)[1]
        return Check(
            repo.name, check, "stale",
            f"the last result is for {short(last)}, HEAD is {short(repo.head)}", run_it,
        )
    path = found[repo.head][-1][1]
    try:
        data = load_json(path)
    except (OSError, ValueError) as error:
        return Check(repo.name, check, "invalid", f"{path.name} cannot be read: {error}", run_it)
    problem = result_problem(data, key, repo.name, check, repo.head, repo.base)
    if problem:
        return Check(repo.name, check, "invalid", f"{path.name}: {problem}", run_it)
    detail = counts_text(check, data["counts"])
    if data["note"]:
        detail = f"{detail}. {data['note']}" if detail else data["note"]
    outcome = data["outcome"]
    if outcome == "passed":
        return Check(repo.name, check, "passed", detail)
    if outcome == "failed":
        gap = untested(check, data["counts"])
        if gap:
            fix = f"{gap}. Add tests and commit them, then run the {check} check again and record it"
        else:
            fix = f"Fix what failed, commit, run the {check} check again and record it"
        return Check(repo.name, check, "failed", detail, fix)
    fix = f"Fix why it could not run, then run the {check} check again and record it"
    return Check(repo.name, check, "blocked", detail, fix)


def decide(scratch, key, root):
    """(repos, checks, items, notes). An item is a blocking line. No items means inspection may start.

    A note is a SKIPPED or WARNING line. It names something not checked and does not block.
    """
    folder, repos, skipped = task_repos(root, key)
    checks, items, notes = [], [], []
    if not folder.is_dir():
        items.append(f"BLOCKED task worktrees: no task folder at {folder}. Make the worktrees with worktree.sh add")
        return repos, checks, items, notes
    for entry in skipped:
        if entry.problem:
            items.append(
                f"BLOCKED {entry.name} folder: {entry.reason}, but {entry.problem}. "
                f"Rename it back to the repo's short name, or move it out of {folder}"
            )
        else:
            notes.append(f"SKIPPED {entry.name}: {entry.reason}")
    if not repos:
        items.append(f"BLOCKED task worktrees: no repo worktree in {folder}. Make them with worktree.sh add")
        return repos, checks, items, notes
    if not any(r.error or r.base_problem or r.touched for r in repos):
        items.append("BLOCKED task changes: no repo in the task folder has changes against its base. Nothing to inspect")
    waivers, unreadable = read_waivers(scratch, key)
    notes += unreadable
    for repo in repos:
        if repo.warning:
            notes.append(f"WARNING {repo.name} base: {repo.warning}")
        if repo.error:
            items.append(f"BLOCKED {repo.name} git: {repo.error}. Fix the worktree at {repo.path}")
            continue
        if repo.base_problem:
            items.append(f"BLOCKED {repo.name} base: {repo.base_problem}")
            continue
        if not repo.touched:
            notes.append(f"SKIPPED {repo.name}: no changes against {repo.base_ref} ({short(repo.base)})")
            continue
        if repo.dirty:
            items.append(
                f"BLOCKED {repo.name} worktree: {len(repo.dirty)} uncommitted file(s), first {repo.dirty[0]}. "
                f"Commit them, then run every check again on the new commit"
            )
        if repo.hidden:
            items.append(
                f"BLOCKED {repo.name} worktree: {len(repo.hidden)} file(s) marked skip-worktree or assume-unchanged, "
                f"first {repo.hidden[0]}. git status does not show changes to them. Run "
                f"git update-index --no-skip-worktree --no-assume-unchanged -- <file> on each, "
                f"commit any change, then run every check again"
            )
        for name in CHECKS:
            check = judge(scratch, key, repo, name)
            if not check.ok:
                waiver, refused = find_waiver(waivers, key, repo.name, name, repo.head)
                if waiver:
                    request, path = waiver
                    check.waiver = f"was {check.status}. Reason: {request['reason']}. Request {path.name}"
                    check.status = "waived by user"
                elif refused:
                    names = ", ".join(p.name for p in refused)
                    check.detail = f"{check.detail}. Not approved: {names}".lstrip(". ")
            checks.append(check)
            if not check.ok:
                items.append(
                    f"BLOCKED {repo.name} {name}: {check.status} at {short(repo.head)}"
                    + (f" ({check.detail})" if check.detail else "")
                    + f". {check.unblock}."
                )
                items.append(f"  or a user waiver: {waiver_hint(key, repo, name)}")
    return repos, checks, items, notes


def verdict(key, checks, items):
    if items:
        count = sum(1 for line in items if line.startswith("BLOCKED"))
        return f"{key}: blocked. {count} item{'s' if count != 1 else ''} missing."
    waived = sum(1 for c in checks if c.status == "waived by user")
    if waived:
        return f"{key}: ready for inspection with {waived} waiver{'s' if waived != 1 else ''}."
    return f"{key}: ready for inspection."


def repo_lines(repos, checks):
    lines = []
    for repo in repos:
        if repo.error:
            lines.append(f"{repo.name}  cannot read: {repo.error}")
            continue
        if repo.base_problem:
            lines.append(f"{repo.name}  base not confirmed: {repo.base_problem}")
            continue
        if not repo.touched:
            lines.append(f"{repo.name}  no changes against {repo.base_ref} ({short(repo.base)}). Not checked")
            continue
        state = f", {len(repo.dirty)} uncommitted" if repo.dirty else ""
        state += f", {len(repo.hidden)} hidden from git status" if repo.hidden else ""
        lines.append(
            f"{repo.name}  head {short(repo.head)}  base {short(repo.base)} ({repo.base_ref})  "
            f"{len(repo.changed)} file(s) changed{state}"
        )
        for check in (c for c in checks if c.repo == repo.name):
            text = f"  {check.name:<9} {check.status}"
            extra = check.waiver or check.detail
            if extra:
                text += f": {extra}"
            lines.append(text)
    return lines


def waived_lines(checks, repos):
    heads = {r.name: r.head for r in repos}
    return [
        f"WAIVED {c.repo} {c.name} at {short(heads[c.repo])}: waived by user ({c.waiver})"
        for c in checks
        if c.status == "waived by user"
    ]


def scratch_dir(value):
    path = Path(value).resolve()
    if not path.is_dir():
        raise UsageError(f"no folder at {path}")
    return path


def check_key(key):
    if not KEY_RE.match(key):
        raise UsageError(f"bad key {key!r}: use letters, digits, dot, dash and underscore")
    return key


def cmd_report(args, full):
    key = check_key(args.key)
    scratch = scratch_dir(args.dir)
    root = Path(args.root).resolve() if args.root else scratch.parent
    repos, checks, items, notes = decide(scratch, key, root)
    lines = [verdict(key, checks, items)]
    lines.append(f"Task folder: {root / 'worktrees' / key}")
    lines.append(f"Results: {evidence_dir(scratch, key)}. The progress board is not read.")
    if full:
        lines.append("")
        lines += repo_lines(repos, checks) or ["no repos"]
    waived = waived_lines(checks, repos)
    if items or waived or notes:
        lines.append("")
        lines += items + waived + notes
    if any(line.startswith("  or a user waiver") for line in items):
        lines.append("")
        lines.append(
            f"A waiver counts only when the user signs it. Save the request as {waivers_dir(scratch, key)}/<name>.json "
            "and the user's signature beside it as <name>.sig. See tools/flow-gate.md."
        )
    if items and not os.path.exists(approval.TRUST_FILE):
        lines.append("")
        lines.append(NO_WAIVERS)
    print("\n".join(lines))
    return 1 if items else 0


def parse_counts(pairs):
    counts = {}
    for pair in pairs or []:
        name, sep, value = pair.partition("=")
        if not sep or not COUNT_RE.match(name) or not re.fullmatch(r"[0-9]+", value):
            raise UsageError(f"bad --count {pair!r}: use NAME=N with a whole number")
        if name in counts:
            raise UsageError(f"--count {name} is given twice")
        counts[name] = int(value)
    return counts


def cmd_record(args):
    key = check_key(args.key)
    scratch = scratch_dir(args.dir)
    if args.check not in CHECKS:
        raise UsageError(f"unknown check {args.check!r}. Use one of: {', '.join(CHECKS)}")
    if args.outcome not in OUTCOMES:
        raise UsageError(f"unknown outcome {args.outcome!r}. Use one of: {', '.join(OUTCOMES)}")
    counts = parse_counts(args.count)
    note = args.note or ""
    problem = counts_problem(args.check, args.outcome, counts, note)
    if problem:
        raise UsageError(problem)
    path = Path(args.repo).resolve()
    top = Path(git(path, "rev-parse", "--show-toplevel").removesuffix("\n")).resolve()  # a name may end in a newline
    if not REPO_RE.match(top.name):
        raise UsageError(f"repo folder name {top.name!r} is not a plain short name")
    head = commit_of(top, "HEAD")
    base_ref = default_base_ref(top)
    base = merge_base(top, base_ref, head)
    dirty = dirty_paths(top)
    if dirty:
        raise GitError(f"{top} has {len(dirty)} uncommitted file(s), first {dirty[0]}. Commit, rerun the check, then record")
    hidden = hidden_paths(top)
    if hidden:
        raise GitError(
            f"{top} has {len(hidden)} file(s) marked skip-worktree or assume-unchanged, first {hidden[0]}. "
            "Clear the marks with git update-index --no-skip-worktree --no-assume-unchanged, commit any change, "
            "rerun the check, then record"
        )
    data = {
        "format": FORMAT,
        "key": key,
        "repo": top.name,
        "check": args.check,
        "base_ref": base_ref,
        "base": base,
        "head": head,
        "outcome": args.outcome,
        "counts": counts,
        "note": note,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    folder = results_dir(scratch, key, top.name, args.check)
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    for _ in range(100):
        n = max((n for n, _ in result_files(folder).get(head, [])), default=0) + 1
        target = folder / f"{head}-{n}.json"
        try:
            with open(target, "x", encoding="utf-8") as handle:
                handle.write(text)
        except FileExistsError:
            continue
        print(f"recorded {top.name} {args.check} {args.outcome} at {short(head)}: {target}")
        return 0
    raise GitError(f"could not find a free file name in {folder}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("next", "status"):
        report = sub.add_parser(name)
        report.add_argument("key")
        report.add_argument("--dir", default=".scratch")
        report.add_argument("--root", help="folder that holds worktrees/<KEY>/ (default: the folder above --dir)")
    record = sub.add_parser("record")
    record.add_argument("key")
    record.add_argument("repo")
    record.add_argument("check")
    record.add_argument("outcome")
    record.add_argument("--count", action="append", metavar="NAME=N")
    record.add_argument("--note")
    record.add_argument("--dir", default=".scratch")
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            return cmd_record(args)
        return cmd_report(args, full=args.command == "status")
    except UsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (GitError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
