#!/usr/bin/env python3
"""flow_approval.py: check that a human signed off on a flow stage.

An agent asks for approval with new_request(). A human signs the bytes from
payload() with a private key the agent cannot read. verify() accepts the request
only when /usr/bin/ssh-keygen confirms the signature against the root-owned file
/etc/tstack/allowed_signers. Every error returns False. Nothing here lets an
agent grant approval to itself.

  flow_approval.py new KEY STAGE CONTEXT REASON [--ttl SECONDS]   print a request as JSON
  flow_approval.py payload REQUEST.json [OUT]                    write the bytes to sign
  flow_approval.py verify REQUEST.json SIGNATURE                 exit 0 approved, 1 not

See tools/flow-approval.md for the signing steps and the limits.
"""
import argparse
import json
import os
import secrets
import stat
import subprocess
import sys
import time

SSH_KEYGEN = "/usr/bin/ssh-keygen"
TRUST_FILE = "/etc/tstack/allowed_signers"
IDENTITY = "tstack-approver"
NAMESPACE = "tstack-flow"

# Only root may own the trust file and every directory above it. Tests widen this.
TRUSTED_UIDS = frozenset({0})

VERSION = 1
HEADER = b"tstack-flow-approval/v1\n"
FIELDS = frozenset(
    {"version", "key", "stage", "context", "reason", "nonce", "issued_at", "expires_at"}
)
DEFAULT_TTL = 900  # seconds a request stays valid
MAX_TTL = 3600  # verify() rejects any request that lives longer than this
CLOCK_SKEW = 60  # seconds an issue time may sit in the future
MAX_PAYLOAD = 65536
MAX_SIGNATURE = 16384
MAX_DEPTH = 8
VERIFY_TIMEOUT = 10


def _now():
    return int(time.time())


def _text(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _json_value(value, depth=0):
    """Allow strings, integers, booleans, null, lists and dicts. No floats."""
    if depth > MAX_DEPTH:
        raise ValueError("context is nested too deeply")
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item, depth + 1)
        return
    if isinstance(value, dict):
        for name, item in value.items():
            if not isinstance(name, str):
                raise ValueError("context keys must be strings")
            _json_value(item, depth + 1)
        return
    raise ValueError("context holds a value that is not plain JSON")


def _int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _checked(request):
    """Return the request fields after strict checks, or raise ValueError."""
    if not isinstance(request, dict) or set(request) != FIELDS:
        raise ValueError("request has missing or extra fields")
    if request["version"] != VERSION or isinstance(request["version"], bool):
        raise ValueError("unknown request version")
    for name in ("key", "stage", "reason"):
        _text(name, request[name])
    _json_value(request["context"])
    nonce = request["nonce"]
    if not isinstance(nonce, str) or len(nonce) != 64 or any(c not in "0123456789abcdef" for c in nonce):
        raise ValueError("nonce must be 64 lowercase hex characters")
    _int("issued_at", request["issued_at"])
    _int("expires_at", request["expires_at"])
    return request


def new_request(key, stage, context, reason, ttl_seconds=DEFAULT_TTL):
    """Build a request with a random nonce and an expiry time."""
    _text("key", key)
    _text("stage", stage)
    _text("reason", reason)
    _json_value(context)
    _int("ttl_seconds", ttl_seconds)
    if not 0 < ttl_seconds <= MAX_TTL:
        raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL}")
    issued = _now()
    request = {
        "version": VERSION,
        "key": key,
        "stage": stage,
        "context": context,
        "reason": reason,
        "nonce": secrets.token_hex(32),
        "issued_at": issued,
        "expires_at": issued + ttl_seconds,
    }
    payload(request)  # fail now if the request is too large
    return request


def payload(request):
    """Canonical bytes a human signs. The same request always gives the same bytes."""
    fields = _checked(request)
    body = json.dumps(
        {name: fields[name] for name in FIELDS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,  # look-alike characters show up as \\u escapes
        allow_nan=False,
    )
    data = HEADER + body.encode("ascii") + b"\n"
    if len(data) > MAX_PAYLOAD:
        raise ValueError("request is too large")
    return data


def _check_chain(path):
    """Every part of an absolute path must belong to a trusted owner.

    Directories and the file must not be writable by group or others. A symlink,
    such as /etc on macOS, must belong to a trusted owner too.
    """
    parts = [p for p in path.split("/") if p]
    current = "/"
    chain = ["/"]
    for part in parts:
        current = os.path.join(current, part)
        chain.append(current)
    for index, item in enumerate(chain):
        info = os.lstat(item)
        if info.st_uid not in TRUSTED_UIDS:
            raise PermissionError(f"{item} is not owned by a trusted user")
        if stat.S_ISLNK(info.st_mode):
            continue
        if info.st_mode & 0o022:
            raise PermissionError(f"{item} is writable by group or others")
        last = index == len(chain) - 1
        if not last and not stat.S_ISDIR(info.st_mode):
            raise PermissionError(f"{item} is not a directory")


def _check_trust_file():
    """Fail unless the trust file and all its ancestors are root controlled."""
    path = TRUST_FILE
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise PermissionError("trust file path is not clean and absolute")
    _check_chain(path)
    real = os.path.realpath(path)
    _check_chain(real)
    if not stat.S_ISREG(os.lstat(real).st_mode):
        raise PermissionError("trust file is not a regular file")


def _signature_path(signature_path):
    path = os.path.abspath(os.fspath(signature_path))
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SIGNATURE:
        raise ValueError("signature file is not a regular file of a sane size")
    return path


def _verify(request, signature_path):
    data = payload(request)
    now = _now()
    issued, expires = request["issued_at"], request["expires_at"]
    if expires <= now:
        return False
    if issued > now + CLOCK_SKEW or expires - issued > MAX_TTL or expires <= issued:
        return False
    _check_trust_file()
    signature = _signature_path(signature_path)
    result = subprocess.run(
        [
            SSH_KEYGEN,
            "-Y", "verify",
            "-f", TRUST_FILE,
            "-I", IDENTITY,
            "-n", NAMESPACE,
            "-s", signature,
        ],
        input=data,
        capture_output=True,
        timeout=VERIFY_TIMEOUT,
        env={"LC_ALL": "C"},
        check=False,
    )
    good = f'Good "{NAMESPACE}" signature for {IDENTITY} '.encode()
    return result.returncode == 0 and result.stdout.startswith(good)


def verify(request, signature_path):
    """True only for a live request with a valid signature from the trusted key."""
    try:
        return _verify(request, signature_path) is True
    except Exception:
        return False


def _load(path):
    with open(path, "rb") as handle:
        raw = handle.read(MAX_PAYLOAD + 1)
    if len(raw) > MAX_PAYLOAD:
        raise ValueError("request file is too large")
    try:
        return json.loads(raw.decode("utf-8"), parse_float=_no_float)
    except RecursionError:
        raise ValueError("request file is nested too deeply") from None


def _no_float(text):
    raise ValueError("floats are not allowed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("new")
    make.add_argument("key")
    make.add_argument("stage")
    make.add_argument("context")
    make.add_argument("reason")
    make.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    show = sub.add_parser("payload")
    show.add_argument("request")
    show.add_argument("out", nargs="?")
    check = sub.add_parser("verify")
    check.add_argument("request")
    check.add_argument("signature")
    args = parser.parse_args(argv)

    try:
        if args.command == "new":
            request = new_request(args.key, args.stage, args.context, args.reason, args.ttl)
            print(json.dumps(request, indent=2, sort_keys=True))
            return 0
        if args.command == "payload":
            data = payload(_load(args.request))
            if args.out:
                with open(args.out, "xb") as handle:
                    handle.write(data)
            else:
                sys.stdout.buffer.write(data)
            return 0
        approved = verify(_load(args.request), args.signature)
        print("approved" if approved else "not approved")
        return 0 if approved else 1
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
