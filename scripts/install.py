import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRAMMARS = "go java javascript python rust tsx typescript".split()


def link(target, destination, *, required=False, create=True):
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

    python = ROOT / ".venv/bin/python"
    vendor = ROOT / "skills/ship/scripts/vendor"
    if not python.is_file():
        run(sys.executable, "-m", "venv", ROOT / ".venv")
    run(python, "-m", "pip", "install", "-r", ROOT / "requirements.txt",
        "-e", vendor / "crapper", "-e", vendor / "mutator")
    run(python, "-c", "import sys; from tree_sitter_language_pack import download; download(sys.argv[1:])", *GRAMMARS)
    run("npm", "ci", "--prefix", ROOT / "skills/lane/scripts")

    for skill in skills:
        canonical = shared / skill.name
        link(skill, canonical, required=True)
        for agent in agents:
            link(canonical, agent / skill.name)

    bin_dir = home / ".local/bin"
    commands = {
        "crapper": python.with_name("crapper"),
        "mutator": python.with_name("mutator"),
        "harden": ROOT / "skills/hardening/scripts/harden",
        "lane": ROOT / "skills/lane/scripts/lane",
    }
    for command, target in commands.items():
        link(target, bin_dir / command)
    print(f"Installed {len(skills)} skills for Claude Code, Codex and Cursor.")
    if str(bin_dir) not in os.get_exec_path():
        print(f"For short commands, add {bin_dir} to PATH.")


if __name__ == "__main__":
    main()
