import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def lane_project(root, name):
    identity = hashlib.sha256(str(root).encode()).hexdigest()[:20]
    return f"lane-{identity}-{name}"


def check_isolation(config, project, root):
    for kind in ("networks", "volumes"):
        for key, resource in config.get(kind, {}).items():
            if resource.get("external") or resource.get("name") != f"{project}_{key}":
                raise ValueError(f"{kind}.{key}: use a Compose-managed name, not a shared resource")

    for service, settings in config.get("services", {}).items():
        fields = ("container_name", "network_mode", "privileged", "volumes_from", "devices")
        unsafe = [field for field in fields if settings.get(field)]
        unsafe.extend(field for field in ("ipc", "pid") if settings.get(field, "").startswith(("host", "container:")))
        if unsafe:
            raise ValueError(f"{service}: remove {', '.join(unsafe)} for lane isolation")
        for mount in settings.get("volumes", []):
            if mount["type"] == "bind" and (
                not mount.get("read_only") or not Path(mount["source"]).resolve().is_relative_to(root)
            ):
                raise ValueError(f"{service}: use named volumes for writes and read-only mounts inside the worktree")
        for port in settings.get("ports", []):
            if port.get("published") not in (None, "0", 0) or port.get("host_ip") not in ("127.0.0.1", "::1"):
                raise ValueError(f"{service}: publish ports dynamically to 127.0.0.1 or ::1")


def main():
    parser = argparse.ArgumentParser(prog="lane compose")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="worktree root (default: current directory)")
    parser.add_argument("-f", "--file", type=Path, action="append", help="Compose file relative to the worktree; can repeat")
    subcommands = parser.add_subparsers(dest="action", required=True)
    for action in ("up", "status", "logs", "port", "exec", "down"):
        sub = subcommands.add_parser(action)
        sub.add_argument("name", help="unique lane name in this worktree")
        if action == "up":
            sub.add_argument("--wait-timeout", type=int, default=120)
        if action == "logs":
            sub.add_argument("service", nargs="*")
        if action in ("port", "exec"):
            sub.add_argument("service")
            sub.add_argument("arguments", nargs=argparse.REMAINDER if action == "exec" else 1)
    args = parser.parse_args()
    if not args.name or len(args.name) > 24 or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in args.name):
        parser.error("lane names must be 1 to 24 lowercase letters, digits or hyphens")
    if args.action == "exec" and not args.arguments:
        parser.error("exec needs a command after the service name")
    if args.action == "up" and args.wait_timeout < 1:
        parser.error("--wait-timeout must be positive")

    root = args.project_dir.resolve()
    project = lane_project(root, args.name)
    command = ["docker", "compose", "--project-directory", str(root), "-p", project]
    files = args.file or [next((candidate for name in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")
                               if (candidate := root / name).is_file()), root / "compose.yaml")]
    for file in files:
        command.extend(("-f", str(root / file)))
    operations = {
        "up": ["up", "--build", "--wait", "--wait-timeout", str(getattr(args, "wait_timeout", ""))],
        "status": ["ps", "--all"],
        "logs": ["logs", "--no-color", *getattr(args, "service", [])] if args.action == "logs" else [],
        "port": ["port", "--", getattr(args, "service", ""), *getattr(args, "arguments", [])],
        "exec": ["exec", "-T", "--", getattr(args, "service", ""), *getattr(args, "arguments", [])],
        "down": ["down", "--volumes", "--remove-orphans"],
    }
    try:
        if args.action in {"up", "down"}:
            config = subprocess.check_output([*command, "config", "--format", "json"], cwd=root)
            check_isolation(json.loads(config), project, root)
        return subprocess.run([*command, *operations[args.action]], cwd=root).returncode
    except subprocess.CalledProcessError as error:
        return error.returncode
    except (OSError, ValueError) as error:
        print(f"lane: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
