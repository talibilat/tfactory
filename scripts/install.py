import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRAMMARS = "go java javascript python rust tsx typescript".split()


def stale(destination):
    """A link that points nowhere, or to an old location inside this checkout."""
    if not destination.is_symlink():
        return False
    pointed = Path(os.readlink(destination))
    pointed = pointed if pointed.is_absolute() else destination.parent / pointed
    return not destination.exists() or ROOT in pointed.parents and not pointed.exists()


def link(target, destination, *, required=False, create=True):
    if create and stale(destination):
        destination.unlink()
    if destination.is_symlink() or destination.exists():
        if destination.resolve() != target.resolve():
            message = f"Keep existing {destination}; it does not point to {target}"
            if required:
                raise SystemExit(message)
            if create:
                print(message, file=sys.stderr)
            return False
    elif create:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(target)
    return True


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("Install Python 3.11 or newer and run make install again.")
    if not shutil.which("npm"):
        raise SystemExit("Install Node.js with npm and run make install again.")

    home = Path.home()
    shared = home / ".agents/skills"
    agents = [
        Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude") / "skills",
        Path(os.environ.get("CODEX_HOME") or home / ".codex") / "skills",
        home / ".cursor/skills",
    ]
    skills = sorted(path.parent for path in (ROOT / "skills").glob("*/SKILL.md"))
    for skill in skills:
        link(skill, shared / skill.name, required=True, create=False)
    link(ROOT / "tools", home / ".agents/tools", required=True, create=False)

    python = ROOT / ".venv/bin/python"
    tools = ROOT / "tools"
    if not python.is_file():
        run(sys.executable, "-m", "venv", ROOT / ".venv")
    run(python, "-m", "pip", "install", "-r", ROOT / "requirements.txt",
        "-e", tools / "crapper", "-e", tools / "mutator")
    run(python, "-c", "import sys; from tree_sitter_language_pack import download; download(sys.argv[1:])", *GRAMMARS)
    run("npm", "ci", "--prefix", tools / "lane")

    for skill in skills:
        canonical = shared / skill.name
        link(skill, canonical, required=True)
        for agent in agents:
            link(canonical, agent / skill.name)

    link(tools, home / ".agents/tools", required=True)

    bin_dir = home / ".local/bin"
    commands = {
        "crapper": python.with_name("crapper"),
        "mutator": python.with_name("mutator"),
        "harden": ROOT / "tools/harden",
        "lane": ROOT / "tools/lane/lane",
    }
    for command, target in commands.items():
        link(target, bin_dir / command)
    print(f"Installed {len(skills)} skills for Claude Code, Codex and Cursor, and the tools at ~/.agents/tools.")
    if str(bin_dir) not in os.get_exec_path():
        print(f"For short commands, add {bin_dir} to PATH.")


if __name__ == "__main__":
    main()
