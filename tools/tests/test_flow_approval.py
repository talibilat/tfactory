"""Tests for tools/flow_approval.py. Every key and directory here is disposable.

Run with: python3 tools/tests/test_flow_approval.py
"""
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import flow_approval as fa  # noqa: E402

KEYGEN = "/usr/bin/ssh-keygen"


def make_key(directory, name):
    path = os.path.join(directory, name)
    subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", path], check=True)
    return path


def public_line(key):
    with open(key + ".pub") as handle:
        kind, blob = handle.read().split()[:2]
    return kind, blob


def sign(key, data, namespace=fa.NAMESPACE, name="payload"):
    """Sign the way the human does, outside the module. Return the .sig path."""
    target = os.path.join(os.path.dirname(key), name)
    with open(target, "wb") as handle:
        handle.write(data)
    if os.path.exists(target + ".sig"):
        os.unlink(target + ".sig")
    subprocess.run([KEYGEN, "-Y", "sign", "-q", "-f", key, "-n", namespace, target], check=True)
    return target + ".sig"


class Base(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="flowapp-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.keys = os.path.join(self.root, "keys")
        os.mkdir(self.keys, 0o700)
        self.approver = make_key(self.keys, "approver")
        self.other = make_key(self.keys, "other")
        self.trust_dir = os.path.join(self.root, "etc-tstack")
        os.mkdir(self.trust_dir)
        os.chmod(self.trust_dir, 0o755)
        self.trust = os.path.join(self.trust_dir, "allowed_signers")
        self.write_trust(self.approver)
        # The temp tree belongs to this user, so trust this user in the tests only.
        self.patch(fa, "TRUSTED_UIDS", frozenset({0, os.getuid()}))
        self.patch(fa, "TRUST_FILE", self.trust)
        self.request = fa.new_request("ARPP-1", "merge", {"pr": "https://example.test/pr/1"}, "ship it")

    def patch(self, obj, name, value):
        patcher = mock.patch.object(obj, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_trust(self, key, identity=fa.IDENTITY, options=f'namespaces="{fa.NAMESPACE}"'):
        kind, blob = public_line(key)
        with open(self.trust, "w") as handle:
            handle.write(f"{identity} {options} {kind} {blob}\n")
        os.chmod(self.trust, 0o644)

    def signed(self, request=None, key=None, namespace=fa.NAMESPACE):
        request = request or self.request
        return sign(key or self.approver, fa.payload(request), namespace)


class NewRequest(unittest.TestCase):
    def test_fields_nonce_and_expiry(self):
        with mock.patch.object(fa, "_now", return_value=1000):
            first = fa.new_request("K-1", "plan", "ctx", "why")
        second = fa.new_request("K-1", "plan", "ctx", "why")
        self.assertEqual(set(first), fa.FIELDS)
        self.assertEqual(first["issued_at"], 1000)
        self.assertEqual(first["expires_at"], 1000 + fa.DEFAULT_TTL)
        self.assertEqual(len(first["nonce"]), 64)
        self.assertNotEqual(first["nonce"], second["nonce"])

    def test_custom_ttl(self):
        request = fa.new_request("K-1", "plan", "ctx", "why", ttl_seconds=60)
        self.assertEqual(request["expires_at"] - request["issued_at"], 60)

    def test_rejects_bad_input(self):
        bad = [
            ("", "s", "c", "r"),
            ("k", " ", "c", "r"),
            ("k", "s", "c", ""),
            (None, "s", "c", "r"),
            ("k", "s", 1.5, "r"),
            ("k", "s", {"a": float("nan")}, "r"),
            ("k", "s", {1: "x"}, "r"),
            ("k", "s", object(), "r"),
        ]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                fa.new_request(*args)

    def test_rejects_bad_ttl(self):
        for ttl in (0, -5, fa.MAX_TTL + 1, True, 1.5):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                fa.new_request("k", "s", "c", "r", ttl_seconds=ttl)

    def test_rejects_huge_context(self):
        with self.assertRaises(ValueError):
            fa.new_request("k", "s", "x" * (fa.MAX_PAYLOAD + 1), "r")

    def test_rejects_deep_context(self):
        deep = "x"
        for _ in range(fa.MAX_DEPTH + 2):
            deep = [deep]
        with self.assertRaises(ValueError):
            fa.new_request("k", "s", deep, "r")


class Payload(unittest.TestCase):
    def setUp(self):
        self.request = fa.new_request("ARPP-1", "merge", {"b": 1, "a": [True, None]}, "ship it")

    def test_is_bytes_and_stable(self):
        data = fa.payload(self.request)
        self.assertIsInstance(data, bytes)
        self.assertTrue(data.startswith(fa.HEADER))
        self.assertEqual(data, fa.payload(copy.deepcopy(self.request)))

    def test_ignores_key_order(self):
        shuffled = dict(reversed(list(self.request.items())))
        self.assertEqual(fa.payload(self.request), fa.payload(shuffled))

    def test_every_field_changes_the_bytes(self):
        base = fa.payload(self.request)
        changes = {
            "version": 2,
            "key": "ARPP-2",
            "stage": "other",
            "context": {"a": 1},
            "reason": "different",
            "nonce": "0" * 64,
            "issued_at": self.request["issued_at"] + 1,
            "expires_at": self.request["expires_at"] + 1,
        }
        for name, value in changes.items():
            altered = dict(self.request, **{name: value})
            with self.subTest(field=name):
                try:
                    self.assertNotEqual(base, fa.payload(altered))
                except ValueError:
                    pass  # a rejected request is also a changed outcome

    def test_non_ascii_is_escaped(self):
        request = dict(self.request, reason="payeс")  # Cyrillic s
        self.assertIn(b"\\u0441", fa.payload(request))

    def test_rejects_malformed(self):
        missing = {k: v for k, v in self.request.items() if k != "nonce"}
        cases = [
            missing,
            dict(self.request, extra="x"),
            dict(self.request, nonce="ABC"),
            dict(self.request, nonce="A" * 64),
            dict(self.request, issued_at=True),
            dict(self.request, expires_at="9999999999"),
            dict(self.request, version=True),
            dict(self.request, context=1.5),
            "not a dict",
            None,
        ]
        for case in cases:
            with self.subTest(case=str(case)[:60]), self.assertRaises(ValueError):
                fa.payload(case)


class Verify(Base):
    def test_good_signature(self):
        self.assertTrue(fa.verify(self.request, self.signed()))

    def test_accepts_str_and_path_signature(self):
        sig = self.signed()
        self.assertTrue(fa.verify(self.request, str(sig)))
        self.assertTrue(fa.verify(self.request, Path(sig)))

    def test_signature_for_other_request_is_refused(self):
        sig = self.signed()
        other = fa.new_request("ARPP-1", "merge", {"pr": "https://example.test/pr/1"}, "ship it")
        self.assertFalse(fa.verify(other, sig))

    def test_any_edit_after_signing_is_refused(self):
        sig = self.signed()
        edits = {
            "key": "ARPP-2",
            "stage": "deploy",
            "context": {"pr": "https://example.test/pr/2"},
            "reason": "changed",
            "nonce": "f" * 64,
            "expires_at": self.request["expires_at"] + 1,
            "issued_at": self.request["issued_at"] - 1,
        }
        for name, value in edits.items():
            with self.subTest(field=name):
                self.assertFalse(fa.verify(dict(self.request, **{name: value}), sig))

    def test_unknown_key_is_refused(self):
        self.assertFalse(fa.verify(self.request, self.signed(key=self.other)))

    def test_wrong_namespace_is_refused(self):
        self.assertFalse(fa.verify(self.request, self.signed(namespace="file")))

    def test_wrong_identity_is_refused(self):
        self.write_trust(self.approver, identity="someone-else")
        self.assertFalse(fa.verify(self.request, self.signed()))

    def test_trust_file_namespace_option_is_enforced_by_ssh_keygen(self):
        self.write_trust(self.approver, options='namespaces="other-ns"')
        self.assertFalse(fa.verify(self.request, self.signed()))

    def test_expired_is_refused(self):
        sig = self.signed()
        with mock.patch.object(fa, "_now", return_value=self.request["expires_at"]):
            self.assertFalse(fa.verify(self.request, sig))
        with mock.patch.object(fa, "_now", return_value=self.request["expires_at"] - 1):
            self.assertTrue(fa.verify(self.request, sig))

    def test_long_lived_request_is_refused(self):
        request = dict(self.request, expires_at=self.request["issued_at"] + fa.MAX_TTL + 1)
        self.assertFalse(fa.verify(request, self.signed(request)))

    def test_future_or_backwards_times_are_refused(self):
        future = dict(self.request, issued_at=fa._now() + fa.CLOCK_SKEW + 100)
        future["expires_at"] = future["issued_at"] + 60
        self.assertFalse(fa.verify(future, self.signed(future)))
        backwards = dict(self.request, expires_at=self.request["issued_at"] - 1)
        self.assertFalse(fa.verify(backwards, self.signed(backwards)))

    def test_bad_signature_files_are_refused(self):
        junk = os.path.join(self.root, "junk.sig")
        empty = os.path.join(self.root, "empty.sig")
        big = os.path.join(self.root, "big.sig")
        Path(junk).write_text("not a signature\n")
        Path(empty).write_bytes(b"")
        Path(big).write_bytes(b"x" * (fa.MAX_SIGNATURE + 1))
        for path in (junk, empty, big, os.path.join(self.root, "missing.sig"), self.root):
            with self.subTest(path=path):
                self.assertFalse(fa.verify(self.request, path))

    def test_truncated_signature_is_refused(self):
        sig = self.signed()
        data = Path(sig).read_bytes()
        Path(sig).write_bytes(data[: len(data) // 2])
        self.assertFalse(fa.verify(self.request, sig))

    def test_bad_inputs_return_false_not_raise(self):
        sig = self.signed()
        for request in (None, {}, "x", 5, dict(self.request, nonce="no")):
            with self.subTest(request=str(request)[:40]):
                self.assertFalse(fa.verify(request, sig))
        for path in (None, 5, "", b"\xff"):
            with self.subTest(path=path):
                self.assertFalse(fa.verify(self.request, path))

    def test_signature_cannot_look_like_an_option(self):
        os.chdir(self.root)
        self.addCleanup(os.chdir, "/")
        sig = self.signed()
        dash = os.path.join(self.root, "-n.sig")
        shutil.copy(sig, dash)
        self.assertTrue(fa.verify(self.request, "-n.sig"))
        with mock.patch.object(fa.subprocess, "run", wraps=fa.subprocess.run) as run:
            fa.verify(self.request, "-n.sig")
        self.assertEqual(run.call_args.args[0][-1], dash)

    def test_ssh_keygen_call_is_fixed(self):
        sig = self.signed()
        with mock.patch.object(fa.subprocess, "run", wraps=fa.subprocess.run) as run:
            self.assertTrue(fa.verify(self.request, sig))
        argv = run.call_args.args[0]
        self.assertEqual(
            argv,
            [KEYGEN, "-Y", "verify", "-f", self.trust, "-I", "tstack-approver", "-n", "tstack-flow", "-s", sig],
        )
        self.assertEqual(run.call_args.kwargs["env"], {"LC_ALL": "C"})
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_missing_ssh_keygen_fails_closed(self):
        sig = self.signed()
        self.patch(fa, "SSH_KEYGEN", os.path.join(self.root, "no-such-tool"))
        self.assertFalse(fa.verify(self.request, sig))

    def test_exit_zero_without_good_line_is_refused(self):
        sig = self.signed()
        fake = subprocess.CompletedProcess([], 0, stdout=b"hello\n", stderr=b"")
        with mock.patch.object(fa.subprocess, "run", return_value=fake):
            self.assertFalse(fa.verify(self.request, sig))

    def test_timeout_fails_closed(self):
        sig = self.signed()
        boom = subprocess.TimeoutExpired(cmd="x", timeout=1)
        with mock.patch.object(fa.subprocess, "run", side_effect=boom):
            self.assertFalse(fa.verify(self.request, sig))


class TrustFile(Base):
    def setUp(self):
        super().setUp()
        self.sig = self.signed()

    def test_baseline_is_accepted(self):
        self.assertTrue(fa.verify(self.request, self.sig))

    def test_missing_trust_file(self):
        os.unlink(self.trust)
        self.assertFalse(fa.verify(self.request, self.sig))

    def test_owner_must_be_trusted(self):
        self.patch(fa, "TRUSTED_UIDS", frozenset({0}))  # the real default
        self.assertFalse(fa.verify(self.request, self.sig))

    def test_file_writable_by_group_or_others(self):
        for mode in (0o664, 0o646, 0o666):
            os.chmod(self.trust, mode)
            with self.subTest(mode=oct(mode)):
                self.assertFalse(fa.verify(self.request, self.sig))

    def test_directory_writable_by_group_or_others(self):
        for mode in (0o775, 0o757, 0o777):
            os.chmod(self.trust_dir, mode)
            with self.subTest(mode=oct(mode)):
                self.assertFalse(fa.verify(self.request, self.sig))
        os.chmod(self.trust_dir, 0o755)

    def test_ancestor_writable_by_others(self):
        parent = os.path.join(self.root, "parent")
        child = os.path.join(parent, "child")
        os.makedirs(child)
        os.chmod(child, 0o755)
        os.chmod(parent, 0o755)
        self.patch(fa, "TRUST_FILE", os.path.join(child, "allowed_signers"))
        shutil.copy(self.trust, fa.TRUST_FILE)
        os.chmod(fa.TRUST_FILE, 0o644)
        self.assertTrue(fa.verify(self.request, self.sig))
        os.chmod(parent, 0o777)
        self.assertFalse(fa.verify(self.request, self.sig))

    def test_symlinked_directory_is_followed_like_macos_etc(self):
        link = os.path.join(self.root, "etc")
        os.symlink("etc-tstack", link)
        self.patch(fa, "TRUST_FILE", os.path.join(link, "allowed_signers"))
        self.assertTrue(fa.verify(self.request, self.sig))

    def test_symlink_to_unsafe_directory_is_refused(self):
        os.chmod(self.trust_dir, 0o777)
        link = os.path.join(self.root, "etc")
        os.symlink("etc-tstack", link)
        self.patch(fa, "TRUST_FILE", os.path.join(link, "allowed_signers"))
        self.assertFalse(fa.verify(self.request, self.sig))

    def test_symlink_owned_by_untrusted_user_is_refused(self):
        link = os.path.join(self.root, "etc")
        os.symlink("etc-tstack", link)
        self.patch(fa, "TRUST_FILE", os.path.join(link, "allowed_signers"))
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if path == link:
                return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink, 4242,
                                       info.st_gid, info.st_size, 0, 0, 0))
            return info

        with mock.patch.object(fa.os, "lstat", side_effect=lstat):
            self.assertFalse(fa.verify(self.request, self.sig))

    def test_trust_file_that_is_a_directory(self):
        os.unlink(self.trust)
        os.mkdir(self.trust)
        os.chmod(self.trust, 0o755)
        self.assertFalse(fa.verify(self.request, self.sig))

    def test_ancestor_that_is_a_file(self):
        flat = os.path.join(self.root, "flat")
        Path(flat).write_text("x")
        os.chmod(flat, 0o644)
        self.patch(fa, "TRUST_FILE", os.path.join(flat, "allowed_signers"))
        self.assertFalse(fa.verify(self.request, self.sig))

    def test_relative_or_unclean_trust_path(self):
        for path in ("allowed_signers", self.trust_dir + "/../etc-tstack/allowed_signers", self.trust + "/"):
            self.patch(fa, "TRUST_FILE", path)
            with self.subTest(path=path):
                self.assertFalse(fa.verify(self.request, self.sig))

    def test_trust_file_that_holds_no_key(self):
        Path(self.trust).write_text("")
        self.assertFalse(fa.verify(self.request, self.sig))


class Defaults(unittest.TestCase):
    def test_fixed_values(self):
        self.assertEqual(fa.SSH_KEYGEN, "/usr/bin/ssh-keygen")
        self.assertEqual(fa.TRUST_FILE, "/etc/tstack/allowed_signers")
        self.assertEqual(fa.IDENTITY, "tstack-approver")
        self.assertEqual(fa.NAMESPACE, "tstack-flow")
        self.assertEqual(fa.TRUSTED_UIDS, frozenset({0}))

    def test_environment_cannot_move_the_trust_file(self):
        names = ("TSTACK_ALLOWED_SIGNERS", "ALLOWED_SIGNERS", "TSTACK_TRUST_FILE", "TSTACK_APPROVER")
        with mock.patch.dict(os.environ, {name: "/tmp/evil" for name in names}):
            self.assertEqual(fa.TRUST_FILE, "/etc/tstack/allowed_signers")
        source = Path(fa.__file__).read_text()
        self.assertNotIn("os.environ", source)
        self.assertNotIn("getenv", source)

    def test_real_trust_file_cannot_be_forged_from_a_temp_dir(self):
        """A key the human never registered must not pass against the real defaults."""
        root = tempfile.mkdtemp(prefix="flowapp-")
        self.addCleanup(shutil.rmtree, root, True)
        key = make_key(root, "rogue")
        request = fa.new_request("K", "s", "c", "r")
        self.assertFalse(fa.verify(request, sign(key, fa.payload(request))))


class Cli(Base):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-I", fa.__file__, *args], capture_output=True, text=True, check=False
        )

    def test_new_payload_verify_round_trip(self):
        made = self.run_cli("new", "ARPP-9", "merge", "PR 9", "ready")
        self.assertEqual(made.returncode, 0, made.stderr)
        request_file = os.path.join(self.root, "request.json")
        Path(request_file).write_text(made.stdout)
        payload_file = os.path.join(self.root, "payload.txt")
        self.assertEqual(self.run_cli("payload", request_file, payload_file).returncode, 0)
        self.assertEqual(Path(payload_file).read_bytes(), fa.payload(fa._load(request_file)))
        # The CLI subprocess has the real trust file, so approval is refused there.
        sig = sign(self.approver, Path(payload_file).read_bytes())
        denied = self.run_cli("verify", request_file, sig)
        self.assertEqual(denied.returncode, 1)
        self.assertIn("not approved", denied.stdout)
        # In this process, with the disposable trust file, the same signature passes.
        self.assertTrue(fa.verify(fa._load(request_file), sig))

    def test_payload_refuses_to_overwrite(self):
        request_file = os.path.join(self.root, "request.json")
        Path(request_file).write_text(self.run_cli("new", "K", "s", "c", "r").stdout)
        out = os.path.join(self.root, "payload.txt")
        Path(out).write_text("keep")
        self.assertEqual(self.run_cli("payload", request_file, out).returncode, 1)
        self.assertEqual(Path(out).read_text(), "keep")

    def test_bad_request_file(self):
        bad = os.path.join(self.root, "bad.json")
        Path(bad).write_text("{not json")
        self.assertEqual(self.run_cli("payload", bad).returncode, 1)
        self.assertEqual(self.run_cli("verify", bad, bad).returncode, 1)

    def test_deeply_nested_request_file_is_refused_not_a_crash(self):
        deep = os.path.join(self.root, "deep.json")
        Path(deep).write_text("[" * 30000 + "]" * 30000)
        with self.assertRaises(ValueError):
            fa._load(deep)
        for args in (("payload", deep), ("verify", deep, deep)):
            with self.subTest(command=args[0]):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "error: request file is nested too deeply\n")


if __name__ == "__main__":
    unittest.main()
