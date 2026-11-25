from pathlib import Path


def paths_since_base(root: Path, top: Path, base: str, git) -> list[Path]:
    ref = git("rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}").strip()
    fork = git("merge-base", ref, "HEAD").strip()
    names = git("diff", "--name-only", "--no-renames", "--diff-filter=d", "-z", fork, "--", ".")
    paths = [(top / name).resolve() for name in names.split("\0") if name]
    return [path for path in paths if path.is_file() and path.is_relative_to(root)]
