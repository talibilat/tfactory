"""Tests for tools/flow.py. Every repo, key and folder here is disposable.

Run with: python3 tools/tests/test_flow.py
"""
import contextlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import flow  # noqa: E402
from test_flow_approval import make_key, sign  # noqa: E402

KEY = "ARPP-1"
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.test",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.test",
}
PASS_COUNTS = {
    "baseline": ["tests=12", "failed=0", "new_failures=0"],
    "crap": ["functions=3", "scored=3", "over_threshold=0", "threshold=6"],
    "mutation": ["sites=8", "killed=8", "survived=0", "uncovered=0"],
}


def setUpModule():
    patcher = mock.patch.dict(os.environ, GIT_ENV)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def git(path, *args):
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result.stdout.strip()


def run(*argv):
    """Run flow.main in this process. Returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = flow.main(list(argv))
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="flow-")))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.scratch = self.root / ".scratch"
        self.scratch.mkdir()
        self.task = self.root / "worktrees" / KEY

    def make_repo(self, name, files=None):
        """A clone of a fresh origin in the task folder, on the task branch, with files committed."""
        origin = self.root / "origins" / f"{name}.git"
        seed = self.root / "seeds" / name
        seed.mkdir(parents=True)
        git(seed, "init", "-q", "-b", "main")
        (seed / "app.py").write_text("def add(a, b):\n    return a + b\n")
        git(seed, "add", ".")
        git(seed, "commit", "-q", "-m", "start")
        origin.parent.mkdir(parents=True, exist_ok=True)
        git(self.root, "clone", "-q", "--bare", str(seed), str(origin))
        path = self.task / name
        path.parent.mkdir(parents=True, exist_ok=True)
        git(self.root, "clone", "-q", str(origin), str(path))
        git(path, "checkout", "-q", "-b", KEY)
        if files:
            self.commit(path, files)
        return path

    def commit(self, path, files, message="change"):
        for rel, text in files.items():
            target = path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        git(path, "add", ".")
        git(path, "commit", "-q", "-m", message)
        return git(path, "rev-parse", "HEAD")

    def record(self, path, check, outcome="passed", counts=None, note=None):
        args = ["record", KEY, str(path), check, outcome, "--dir", str(self.scratch)]
        for pair in PASS_COUNTS[check] if counts is None else counts:
            args += ["--count", pair]
        if note:
            args += ["--note", note]
        return run(*args)

    def record_all(self, path):
        for check in flow.CHECKS:
            code, out, err = self.record(path, check)
            self.assertEqual(code, 0, err)

    def next(self, *extra):
        return run("next", KEY, "--dir", str(self.scratch), *extra)

    def status(self):
        return run("status", KEY, "--dir", str(self.scratch))

    def result_path(self, path, check):
        head = git(path, "rev-parse", "HEAD")
        return flow.results_dir(self.scratch, KEY, path.name, check) / f"{head}-1.json"

    def push_to_origin(self, name, files):
        """Someone else merges a commit into main on origin. The task clone has not fetched it."""
        other = self.root / "others" / name
        git(self.root, "clone", "-q", str(self.root / "origins" / f"{name}.git"), str(other))
        self.commit(other, files, "someone else")
        git(other, "push", "-q", "origin", "HEAD:main")
        return git(other, "rev-parse", "HEAD")

    def trust_file(self, exists):
        """Point flow_approval at a trust file that exists or not, for this test only."""
        path = self.root / "trust" / "allowed_signers"
        if exists:
            path.parent.mkdir()
            path.write_text("")
        patcher = mock.patch.object(flow.approval, "TRUST_FILE", str(path))
        patcher.start()
        self.addCleanup(patcher.stop)


class NoReports(Base):
    def test_board_says_done_but_no_reports(self):
        self.make_repo("be", {"app.py": "def add(a, b):\n    return b + a\n"})
        board = {"stages": {"ship-build": {"done": 4, "total": 4, "skipped": False, "note": ""}}}
        (self.scratch / f"{KEY}-progress.json").write_text(json.dumps(board))
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith(f"{KEY}: blocked. 3 items missing."))
        for check in flow.CHECKS:
            self.assertIn(f"BLOCKED be {check}: missing at ", out)
        self.assertIn("The progress board is not read.", out)

    def test_each_missing_item_names_how_to_unblock(self):
        path = self.make_repo("be", {"app.py": "x = 1\n"})
        _, out, _ = self.next()
        line = next(l for l in out.splitlines() if l.startswith("BLOCKED be mutation"))
        self.assertIn(f"flow.py record {KEY} {path} mutation", line)
        self.assertIn("--count sites=N --count killed=N --count survived=N --count uncovered=N", line)
        self.assertIn("flow_approval.py new ARPP-1 waive-mutation", out)

    def test_no_task_folder(self):
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED task worktrees: no task folder at", out)

    def test_no_changes_anywhere(self):
        self.make_repo("be")
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED task changes: no repo in the task folder has changes", out)

    def test_all_three_passing_is_ready(self):
        path = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(path)
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[0], f"{KEY}: ready for inspection.")
        self.assertNotIn("BLOCKED", out)


class TwoRepos(Base):
    def test_one_passing_one_missing(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.make_repo("fe", {"app.py": "y = 2\n"})
        self.record_all(be)
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        blocked = [l for l in out.splitlines() if l.startswith("BLOCKED")]
        self.assertEqual(len(blocked), 3)
        self.assertTrue(all(l.startswith("BLOCKED fe ") for l in blocked), blocked)
        _, full, _ = self.status()
        self.assertIn("  baseline  passed: tests 12, failed 0, new_failures 0", full)
        self.assertIn("  mutation  missing", full)

    def test_unchanged_repo_is_not_checked(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.make_repo("fe")
        self.record_all(be)
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        _, full, _ = self.status()
        self.assertIn("fe  no changes against origin/main", full)

    def test_slice_worktrees_and_plain_folders_are_ignored(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        git(be, "worktree", "add", "-q", "-b", "slice", str(self.task / "_be-s1"))
        (self.task / "notes").mkdir()
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertIn("SKIPPED _be-s1: the name starts with _, so it is not checked", out)
        self.assertIn("SKIPPED notes: not a git worktree", out)

    def test_next_lists_every_skipped_repo(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        fe = self.make_repo("fe")
        self.record_all(be)
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertIn(f"SKIPPED fe: no changes against origin/main ({git(fe, 'rev-parse', 'HEAD')[:12]})", out)


class HiddenFolders(Base):
    """A repo folder renamed to start with _ or . is not a repo, but its work must not vanish."""

    def setUp(self):
        super().setUp()
        self.fe = self.make_repo("fe", {"app.py": "y = 1\n"})
        self.record_all(self.fe)

    def assert_renamed_repo_blocks(self, hidden):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        be.rename(self.task / hidden)
        code, out, _ = self.next()
        self.assertEqual(code, 1, out)
        self.assertIn(
            f"BLOCKED {hidden} folder: the name starts with {hidden[0]}, so it is not checked, but it holds "
            "1 commit(s) that are on no repo folder's HEAD and not on origin/main",
            out,
        )

    def test_repo_renamed_with_underscore_blocks(self):
        self.assert_renamed_repo_blocks("_be")

    def test_repo_renamed_with_dot_blocks(self):
        self.assert_renamed_repo_blocks(".be")

    def test_renamed_repo_without_commits_is_listed_only(self):
        be = self.make_repo("be")
        be.rename(self.task / "_be")
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertIn("SKIPPED _be: the name starts with _, so it is not checked", out)

    def test_slice_made_by_worktree_sh_is_recognised(self):
        script = Path(flow.__file__).with_name("worktree.sh")
        # worktree.sh slice exits 1 even when it made the slice, so check the folder instead.
        subprocess.run(["bash", str(script), "slice", str(self.root), KEY, "fe", "s1"], capture_output=True)
        self.assertTrue((self.task / "_fe-s1" / ".git").exists())
        self.commit(self.task / "_fe-s1", {"slice.py": "z = 1\n"})  # work in progress, not merged yet
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertIn("SKIPPED _fe-s1: slice worktree of fe", out)

    def add_evidence_worktree(self, commit=True):
        """ship close out step 0, step 1: the orphan worktree that holds the proof images."""
        folder = self.task / "_evidence-fe"
        git(self.fe, "worktree", "add", "-q", "--orphan", "-b", f"evidence/{KEY}", str(folder))
        if commit:
            self.commit(folder, {f"{KEY}/compare/01-cart.png": "png bytes\n"}, "evidence")
        return folder

    def assert_evidence_worktree_is_listed_only(self, commit):
        self.add_evidence_worktree(commit)
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertIn("SKIPPED _evidence-fe: evidence worktree for the proof images", out)
        self.assertNotIn("Rename it back", out)

    def test_evidence_worktree_before_its_commit_is_listed_only(self):
        self.assert_evidence_worktree_is_listed_only(commit=False)

    def test_evidence_worktree_left_by_a_rejected_push_is_listed_only(self):
        self.assert_evidence_worktree_is_listed_only(commit=True)

    def test_repo_renamed_to_evidence_name_still_blocks(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        git(be, "checkout", "-q", "-b", f"evidence/{KEY}")
        be.rename(self.task / "_evidence-be")
        code, out, _ = self.next()
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED _evidence-be folder:", out)

    def test_slice_name_from_another_repo_is_not_a_slice(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        be.rename(self.task / "_fe-s1")
        code, out, _ = self.next()
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED _fe-s1 folder:", out)


class MovedBase(Base):
    """The base branch is read from the clone, so check it against origin before trusting it."""

    def setUp(self):
        super().setUp()
        self.be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(self.be)

    def test_base_moved_onto_head_blocks(self):
        fe = self.make_repo("fe", {"app.py": "y = 1\n"})
        git(fe, "update-ref", "refs/remotes/origin/main", "HEAD")
        code, out, _ = self.next()
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED fe base: origin/main here (", out)
        self.assertIn("holds commits that main on origin (", out)
        self.assertNotIn("SKIPPED fe", out)
        _, full, _ = self.status()
        self.assertIn("fe  base not confirmed:", full)

    def test_base_moved_part_way_blocks(self):
        fe = self.make_repo("fe", {"app.py": "y = 1\n"})
        self.commit(fe, {"app.py": "y = 2\n"})
        git(fe, "update-ref", "refs/remotes/origin/main", "HEAD~1")
        code, out, _ = self.next()
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED fe base:", out)

    def test_origin_head_pointed_at_another_branch_blocks(self):
        fe = self.make_repo("fe", {"app.py": "y = 1\n"})
        git(fe, "push", "-q", "origin", f"HEAD:{KEY}")
        git(fe, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{KEY}")
        code, out, _ = self.next()
        self.assertEqual(code, 1, out)
        self.assertIn(f"BLOCKED fe base: origin/HEAD here points to origin/{KEY}, but the default branch on origin is main", out)

    def test_unfetched_origin_asks_for_a_fetch(self):
        tip = self.push_to_origin("be", {"other.py": "o = 1\n"})
        code, out, _ = self.next()
        self.assertEqual(code, 1, out)
        self.assertIn(f"BLOCKED be base: main on origin is at {tip[:12]}, which this clone has not fetched", out)
        git(self.be, "fetch", "-q", "origin")
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)  # the base did not change, so the results still count

    def test_merged_branch_is_not_a_moved_base(self):
        fe = self.make_repo("fe", {"app.py": "y = 1\n"})
        git(fe, "push", "-q", "origin", "HEAD:main")
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertIn("SKIPPED fe: no changes against origin/main", out)

    def test_unreachable_origin_warns_and_falls_back(self):
        git(self.be, "remote", "set-url", "origin", str(self.root / "gone.git"))
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertIn("WARNING be base: cannot reach origin to confirm origin/main (git ls-remote failed:", out)
        self.assertIn("Using origin/main as last fetched", out)


class DocsOnly(Base):
    def test_docs_only_needs_baseline_only(self):
        docs = self.make_repo("docs", {"README.md": "# hi\n", "guide/intro.rst": "intro\n"})
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED docs baseline: missing", out)
        self.assertNotIn("BLOCKED docs crap", out)
        self.assertNotIn("BLOCKED docs mutation", out)
        self.assertEqual(self.record(docs, "baseline")[0], 0)
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        _, full, _ = self.status()
        self.assertIn(f"  crap      not applicable: {flow.DOCS_RULE}", full)

    def test_source_change_next_to_docs_is_not_docs_only(self):
        self.make_repo("be", {"README.md": "# hi\n", "schema.sql": "create table t (id int);\n"})
        _, out, _ = self.next()
        self.assertIn("BLOCKED be crap: missing", out)
        self.assertIn("BLOCKED be mutation: missing", out)

    def test_mdx_is_not_docs(self):
        self.make_repo("site", {"pages/index.mdx": "import Chart from './Chart'\n\n<Chart />\n"})
        _, out, _ = self.next()
        self.assertIn("BLOCKED site crap: missing", out)
        self.assertIn("BLOCKED site mutation: missing", out)

    def test_txt_is_not_docs(self):
        self.make_repo("be", {"requirements.txt": "requests==2.0\n"})
        _, out, _ = self.next()
        self.assertIn("BLOCKED be crap: missing", out)

    def test_unsupported_source_cannot_pass_with_nothing_scored(self):
        be = self.make_repo("be", {"schema.sql": "create table t (id int);\n"})
        code, _, err = self.record(be, "crap", counts=["functions=0", "scored=0", "over_threshold=0", "threshold=6"])
        self.assertEqual(code, 2)
        self.assertIn("passed with 0 functions scored", err)
        code, _, err = self.record(be, "mutation", counts=["sites=0", "killed=0", "survived=0", "uncovered=0"])
        self.assertEqual(code, 2)
        self.assertIn("passed with 0 mutants run", err)
        # A hand-written file that claims the same is not trusted either.
        target = self.result_path(be, "crap")
        target.parent.mkdir(parents=True)
        head = git(be, "rev-parse", "HEAD")
        base = git(be, "merge-base", "origin/main", "HEAD")
        target.write_text(json.dumps({
            "format": flow.FORMAT, "key": KEY, "repo": "be", "check": "crap", "base_ref": "origin/main",
            "base": base, "head": head, "outcome": "passed", "note": "", "recorded_at": "x",
            "counts": {"functions": 0, "scored": 0, "over_threshold": 0, "threshold": 6},
        }))
        _, out, _ = self.next()
        self.assertIn("BLOCKED be crap: invalid", out)
        self.assertIn("passed with 0 functions scored", out)


class Stale(Base):
    def test_new_commit_makes_every_result_stale(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        old = git(be, "rev-parse", "HEAD")
        self.assertEqual(self.next()[0], 0)
        new = self.commit(be, {"app.py": "x = 2\n"})
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        for check in flow.CHECKS:
            self.assertIn(
                f"BLOCKED be {check}: stale at {new[:12]} (the last result is for {old[:12]}, HEAD is {new[:12]})", out
            )

    def test_uncommitted_change_blocks(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        (be / "app.py").write_text("x = 3\n")
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED be worktree: 1 uncommitted file(s), first app.py", out)

    def test_quality_tool_output_is_not_dirt(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        (be / ".metrics" / "mutate").mkdir(parents=True)
        (be / ".metrics" / "crap.edn").write_text("{:entries []}\n")
        (be / ".metrics" / "mutate" / "app.edn").write_text("{}\n")
        self.record_all(be)
        self.assertEqual(self.next()[0], 0)
        (be / "new_module.py").write_text("y = 1\n")
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("first new_module.py", out)

    def test_skip_worktree_and_assume_unchanged_block(self):
        for flag in ("--skip-worktree", "--assume-unchanged"):
            with self.subTest(flag=flag):
                be = self.make_repo(f"be{flag}", {"app.py": "x = 1\n"})
                self.record_all(be)
                (be / "app.py").write_text("x = 3\n")
                git(be, "update-index", flag, "app.py")
                self.assertEqual(git(be, "status", "--porcelain"), "")  # git status cannot see the edit
                code, out, _ = self.next()
                self.assertEqual(code, 1, out)
                self.assertIn(
                    f"BLOCKED be{flag} worktree: 1 file(s) marked skip-worktree or assume-unchanged, first app.py", out
                )
                code, _, err = self.record(be, "baseline")
                self.assertEqual(code, 1)
                self.assertIn("marked skip-worktree or assume-unchanged", err)
                git(be, "update-index", f"--no-{flag[2:]}", "app.py")
                git(be, "checkout", "-q", "app.py")

    def test_sparse_checkout_is_not_hidden_dirt(self):
        be = self.make_repo("be", {"app.py": "x = 1\n", "docs/guide.md": "# guide\n"})
        git(be, "sparse-checkout", "set", "--no-cone", "/app.py")
        self.assertFalse((be / "docs" / "guide.md").exists())
        self.record_all(be)
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)

    def test_staged_rename_into_tool_output_is_dirt(self):
        be = self.make_repo("be", {"app.py": "x = 1\n", "lib.py": "y = 1\n"})
        self.record_all(be)
        (be / ".metrics").mkdir()
        git(be, "mv", "lib.py", ".metrics/lib.py")
        code, out, _ = self.next()
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED be worktree: 1 uncommitted file(s), first lib.py", out)

    def test_rename_inside_tool_output_is_not_dirt(self):
        be = self.make_repo("be", {"app.py": "x = 1\n", ".metrics/old.edn": "{}\n"})
        self.record_all(be)
        git(be, "mv", ".metrics/old.edn", ".metrics/new.edn")
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)

    def test_git_variables_cannot_point_at_another_repo(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        other = self.make_repo("other", {"app.py": "z = 1\n"})
        self.record_all(be)
        self.record_all(other)
        (be / "app.py").write_text("x = 3\n")
        env = {
            "GIT_DIR": str(other / ".git"),
            "GIT_WORK_TREE": str(other),
            "GIT_INDEX_FILE": str(other / ".git" / "index"),
            "GIT_CONFIG_PARAMETERS": "'core.fsmonitor'='true'",
        }
        with mock.patch.dict(os.environ, env):
            code, out, _ = self.next()
            kept = flow.git_env()
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED be worktree: 1 uncommitted file(s), first app.py", out)
        self.assertEqual(sorted(name for name in kept if name.startswith("GIT_")), [
            "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT",
        ])

    def test_fsmonitor_hook_does_not_run(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        marker = self.root / "hook-ran"
        hook = self.root / "fsmonitor-hook"
        hook.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\n")
        hook.chmod(0o755)
        git(be, "config", "core.fsmonitor", str(hook))
        self.record_all(be)
        marker.unlink(missing_ok=True)
        self.next()
        self.status()
        self.assertFalse(marker.exists())

    def test_latest_result_for_a_head_wins(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        self.record(be, "mutation", "failed", ["sites=8", "killed=7", "survived=1", "uncovered=0"])
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED be mutation: failed", out)
        self.record(be, "mutation")
        self.assertEqual(self.next()[0], 0)
        folder = flow.results_dir(self.scratch, KEY, "be", "mutation")
        self.assertEqual(len(list(folder.glob("*.json"))), 3)  # history is kept

    def test_result_for_another_base_is_invalid(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        target = self.result_path(be, "crap")
        data = json.loads(target.read_text())
        data["base"] = "0" * 40
        target.write_text(json.dumps(data))
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED be crap: invalid", out)
        self.assertIn("recorded against base 000000000000", out)

    def test_broken_result_file_is_invalid(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        self.result_path(be, "baseline").write_text("{not json")
        _, out, _ = self.next()
        self.assertIn("BLOCKED be baseline: invalid", out)

    def test_deeply_nested_result_is_invalid_not_a_crash(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        self.result_path(be, "baseline").write_text("[" * 30000 + "]" * 30000)
        self.result_path(be, "crap").write_text("[" * 40 + "]" * 40)  # parses, but deeper than any result
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED be baseline: invalid", out)
        self.assertIn("BLOCKED be crap: invalid", out)
        self.assertIn("nested too deeply", out)

    def test_result_name_with_a_newline_is_ignored(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        path = self.result_path(be, "crap")
        path.rename(path.with_name(path.name + "\n"))
        _, out, _ = self.next()
        self.assertIn("BLOCKED be crap: missing", out)

    def test_wrongly_named_or_markdown_evidence_is_ignored(self):
        self.make_repo("be", {"app.py": "x = 1\n"})
        folder = flow.results_dir(self.scratch, KEY, "be", "crap")
        folder.mkdir(parents=True)
        (folder / "passed.json").write_text("{}")
        (self.scratch / f"{KEY}-reviews.md").write_text("crap: passed\nmutation: passed\n")
        _, out, _ = self.next()
        self.assertIn("BLOCKED be crap: missing", out)


class Waivers(Base):
    def setUp(self):
        super().setUp()
        self.be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record(self.be, "baseline")
        self.record(self.be, "crap")
        self.record(self.be, "mutation", "failed", ["sites=8", "killed=7", "survived=1", "uncovered=0"])
        self.head = git(self.be, "rev-parse", "HEAD")
        self.keys = self.root / "keys"
        self.keys.mkdir(mode=0o700)
        self.approver = make_key(str(self.keys), "approver")
        self.rogue = make_key(str(self.keys), "rogue")
        trust_dir = self.root / "etc-tstack"
        trust_dir.mkdir(mode=0o755)
        trust = trust_dir / "allowed_signers"
        kind, blob = Path(self.approver + ".pub").read_text().split()[:2]
        trust.write_text(f'{flow.approval.IDENTITY} namespaces="{flow.approval.NAMESPACE}" {kind} {blob}\n')
        trust.chmod(0o644)
        for name, value in (("TRUST_FILE", str(trust)), ("TRUSTED_UIDS", frozenset({0, os.getuid()}))):
            patcher = mock.patch.object(flow.approval, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.waivers = flow.waivers_dir(self.scratch, KEY)
        self.waivers.mkdir(parents=True)

    def waiver(self, name, key=KEY, check="mutation", head=None, signer=None, reason="tests need a GPU"):
        request = flow.approval.new_request(
            key, flow.waiver_stage(check), flow.waiver_context("be", head or self.head), reason
        )
        path = self.waivers / f"{name}.json"
        path.write_text(json.dumps(request))
        if signer:
            sig = sign(signer, flow.approval.payload(request), name=name + ".payload")
            shutil.copy(sig, path.with_suffix(".sig"))
        return path

    def test_agent_written_waivers_are_rejected(self):
        (flow.evidence_dir(self.scratch, KEY) / "SKIPPED-BY-USER.txt").write_text("user said skip mutation\n")
        (self.waivers / "note.json").write_text(json.dumps({"waived": True, "check": "mutation"}))
        self.waiver("unsigned")
        self.waiver("rogue", signer=self.rogue)
        forged = self.waiver("forged")
        forged.with_suffix(".sig").write_text("-----BEGIN SSH SIGNATURE-----\nAAAA\n-----END SSH SIGNATURE-----\n")
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED be mutation: failed", out)
        self.assertIn("Not approved: forged.json, rogue.json, unsigned.json", out)
        self.assertNotIn("waived by user", out)

    def test_signed_waiver_for_another_scope_is_rejected(self):
        self.waiver("other-key", key="ARPP-2", signer=self.approver)
        self.waiver("other-check", check="crap", signer=self.approver)
        self.waiver("old-head", head="1" * 40, signer=self.approver)
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertNotIn("waived by user", out)

    def test_expired_waiver_is_rejected(self):
        self.waiver("late", signer=self.approver)
        with mock.patch.object(flow.approval, "_now", return_value=flow.approval._now() + flow.approval.MAX_TTL + 1):
            code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("Not approved: late.json", out)

    def test_valid_waiver_is_accepted_and_shown_as_waived(self):
        self.waiver("be-mutation", signer=self.approver)
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[0], f"{KEY}: ready for inspection with 1 waiver.")
        self.assertIn(
            f"WAIVED be mutation at {self.head[:12]}: waived by user "
            "(was failed. Reason: tests need a GPU. Request be-mutation.json)",
            out,
        )
        _, full, _ = self.status()
        self.assertIn("  mutation  waived by user: was failed.", full)
        self.assertNotIn("  mutation  passed", full)

    def test_waiver_does_not_survive_a_new_commit(self):
        self.waiver("be-mutation", signer=self.approver)
        self.assertEqual(self.next()[0], 0)
        self.commit(self.be, {"app.py": "x = 9\n"})
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertNotIn("waived by user", out)

    def test_waiver_does_not_cover_uncommitted_changes(self):
        self.waiver("be-mutation", signer=self.approver)
        (self.be / "app.py").write_text("x = 5\n")
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED be worktree", out)

    def test_unreadable_waiver_file_is_skipped_with_a_note(self):
        (self.waivers / "deep.json").write_text("[" * 30000 + "]" * 30000)
        (self.waivers / "broken.json").write_text("{not json")
        self.waiver("be-mutation", signer=self.approver)
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertIn("SKIPPED waiver deep.json: it cannot be read (file is nested too deeply)", out)
        self.assertIn("SKIPPED waiver broken.json: it cannot be read (", out)
        self.assertIn("WAIVED be mutation", out)

    def test_waiver_hint_matches_what_next_accepts(self):
        _, out, _ = self.next()
        hint = next(l for l in out.splitlines() if "flow_approval.py new" in l)
        self.assertIn(f"waive-mutation 'repo=be head={self.head}'", hint)
        # Run the printed command for real, with a reason in place of the placeholder.
        argv = shlex.split(hint.split("flow_approval.py ", 1)[1].replace("<reason>", "no GPU runner"))
        script = str(Path(flow.__file__).with_name("flow_approval.py"))
        made = subprocess.run([sys.executable, "-I", script, *argv], capture_output=True, text=True, check=True)
        request_file = self.waivers / "from-hint.json"
        request_file.write_text(made.stdout)
        request = json.loads(made.stdout)
        sig = sign(self.approver, flow.approval.payload(request), name="from-hint.payload")
        shutil.copy(sig, request_file.with_suffix(".sig"))
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertIn("Reason: no GPU runner. Request from-hint.json", out)


class Record(Base):
    def test_writes_the_documented_format(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        code, out, _ = self.record(be, "mutation", counts=PASS_COUNTS["mutation"] + ["timed_out=2"])
        self.assertEqual(code, 0)
        data = json.loads(self.result_path(be, "mutation").read_text())
        self.assertEqual(set(data), flow.RESULT_FIELDS)
        self.assertEqual(data["head"], git(be, "rev-parse", "HEAD"))
        self.assertEqual(data["base"], git(be, "rev-parse", "origin/main"))
        self.assertEqual(data["base_ref"], "origin/main")
        self.assertEqual(data["counts"], {"sites": 8, "killed": 8, "survived": 0, "uncovered": 0, "timed_out": 2})
        self.assertIn("recorded be mutation passed", out)

    def test_refuses_a_dirty_worktree(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        (be / "app.py").write_text("x = 2\n")
        code, _, err = self.record(be, "baseline")
        self.assertEqual(code, 1)
        self.assertIn("uncommitted", err)
        self.assertFalse(flow.results_dir(self.scratch, KEY, "be", "baseline").exists())

    def test_never_writes_waived_or_not_applicable(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        for outcome in ("waived", "not-applicable", "PASSED"):
            with self.subTest(outcome=outcome):
                self.assertEqual(self.record(be, "crap", outcome)[0], 2)

    def test_rejects_bad_input(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        cases = [
            ("lint", "passed", PASS_COUNTS["baseline"]),
            ("baseline", "passed", ["tests=12", "failed=0"]),
            ("baseline", "passed", ["tests=12", "failed=1", "new_failures=1"]),
            ("baseline", "passed", ["tests=0", "failed=0", "new_failures=0"]),
            ("baseline", "failed", ["tests=1", "failed=2", "new_failures=0"]),
            ("crap", "passed", ["functions=3", "scored=2", "over_threshold=0", "threshold=6"]),
            ("crap", "passed", ["functions=3", "scored=3", "over_threshold=1", "threshold=6"]),
            ("crap", "passed", ["functions=3", "scored=3", "over_threshold=0", "threshold=30"]),
            ("mutation", "passed", ["sites=8", "killed=7", "survived=1", "uncovered=0"]),
            ("mutation", "passed", ["sites=2", "killed=3", "survived=0", "uncovered=0"]),
            ("baseline", "passed", ["tests=1.5", "failed=0", "new_failures=0"]),
            ("baseline", "passed", ["tests=-1", "failed=0", "new_failures=0"]),
            ("baseline", "passed", ["tests=1", "tests=2", "failed=0", "new_failures=0"]),
            ("baseline", "passed", ["Tests=1", "failed=0", "new_failures=0"]),
            ("baseline", "blocked", []),
            ("baseline", "blocked", ["tests=12"]),
            ("mutation", "passed", ["sites=10", "killed=2", "survived=0", "uncovered=8"]),
            ("baseline", "passed", PASS_COUNTS["baseline"] + ["extra\n=1"]),
        ]
        for check, outcome, counts in cases:
            with self.subTest(check=check, outcome=outcome, counts=counts):
                self.assertEqual(self.record(be, check, outcome, counts)[0], 2)

    def test_untested_sites_are_not_a_pass(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        code, _, err = self.record(be, "mutation", counts=["sites=10", "killed=2", "survived=0", "uncovered=8"])
        self.assertEqual(code, 2)
        self.assertIn("passed with 8 untested site(s)", err)
        self.assertIn("Record it as failed, then add tests or ask the user for a waiver", err)
        code, _, err = self.record(be, "crap", counts=["functions=3", "scored=1", "over_threshold=0", "threshold=6"])
        self.assertEqual(code, 2)
        self.assertIn("2 function(s) not scored because they have no coverage. Add tests or ask the user for a waiver", err)
        # Recorded as failed, next names the gap and both ways out.
        self.record(be, "mutation", "failed", ["sites=10", "killed=2", "survived=0", "uncovered=8"])
        _, out, _ = self.next()
        self.assertIn("BLOCKED be mutation: failed at", out)
        self.assertIn("8 site(s) are untested. Add tests and commit them, then run the mutation check again", out)
        self.assertIn("or a user waiver: flow_approval.py new ARPP-1 waive-mutation", out)

    def test_hand_written_pass_with_untested_sites_is_invalid(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        target = self.result_path(be, "mutation")
        data = json.loads(target.read_text())
        data["counts"] = {"sites": 10, "killed": 2, "survived": 0, "uncovered": 8}
        target.write_text(json.dumps(data))
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED be mutation: invalid", out)
        self.assertIn("passed with 8 untested site(s)", out)

    def test_blocked_takes_no_counts(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        code, _, err = self.record(be, "mutation", "blocked", ["sites=0"], note="no Docker")
        self.assertEqual(code, 2)
        self.assertIn("a blocked result takes no counts", err)

    def test_repo_folder_name_with_a_newline_is_refused(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        odd = be.rename(self.task / "be\n")
        code, _, err = self.record(odd, "baseline")
        self.assertEqual(code, 2, err)
        self.assertIn("is not a plain short name", err)

    def test_patterns_refuse_a_trailing_newline(self):
        head = "a" * 40
        for pattern, good in (
            (flow.KEY_RE, KEY), (flow.REPO_RE, "be"), (flow.COUNT_RE, "tests"), (flow.RESULT_NAME_RE, f"{head}-1.json"),
        ):
            with self.subTest(pattern=pattern.pattern):
                self.assertTrue(pattern.match(good))
                self.assertIsNone(pattern.match(good + "\n"))

    def test_blocked_needs_only_a_note(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        code, _, _ = self.record(be, "mutation", "blocked", [], note="runner has no Docker")
        self.assertEqual(code, 0)
        _, out, _ = self.next()
        self.assertIn("BLOCKED be mutation: blocked at", out)
        self.assertIn("(runner has no Docker)", out)

    def test_numbering_keeps_history(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record(be, "baseline")
        self.record(be, "baseline")
        head = git(be, "rev-parse", "HEAD")
        names = sorted(p.name for p in flow.results_dir(self.scratch, KEY, "be", "baseline").iterdir())
        self.assertEqual(names, [f"{head}-1.json", f"{head}-2.json"])

    def test_not_a_repo(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual(self.record(plain, "baseline")[0], 1)


class Usage(Base):
    def test_bad_usage_exits_2(self):
        self.assertEqual(run()[0], 2)
        self.assertEqual(run("next")[0], 2)
        self.assertEqual(run("launch", KEY)[0], 2)
        self.assertEqual(run("next", "../evil", "--dir", str(self.scratch))[0], 2)
        self.assertEqual(run("next", f"{KEY}\n", "--dir", str(self.scratch))[0], 2)
        self.assertEqual(run("next", KEY, "--dir", str(self.root / "missing"))[0], 2)

    def test_output_is_deterministic_and_read_only(self):
        self.make_repo("be", {"app.py": "x = 1\n"})
        fe = self.make_repo("fe", {"app.py": "y = 1\n"})
        self.record_all(fe)
        before = sorted(str(p) for p in self.root.rglob("*") if ".git" not in p.parts)
        first = self.status()
        second = self.status()
        self.assertEqual(first, second)
        self.assertEqual(self.next(), self.next())
        after = sorted(str(p) for p in self.root.rglob("*") if ".git" not in p.parts)
        self.assertEqual(before, after)

    def test_says_when_waivers_are_not_set_up(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.trust_file(exists=False)
        _, out, _ = self.next()
        self.assertEqual(out.splitlines()[-1], flow.NO_WAIVERS)
        self.assertEqual(
            flow.NO_WAIVERS,
            "Waivers are not set up on this machine. See tools/flow-approval.md. "
            "Blocked gates cannot be waived until then.",
        )
        self.assertIn(flow.NO_WAIVERS, self.status()[1])
        self.record_all(be)
        code, out, _ = self.next()
        self.assertEqual(code, 0, out)
        self.assertNotIn(flow.NO_WAIVERS, out)

    def test_quiet_about_waivers_when_set_up(self):
        self.make_repo("be", {"app.py": "x = 1\n"})
        self.trust_file(exists=True)
        code, out, _ = self.next()
        self.assertEqual(code, 1)
        self.assertNotIn(flow.NO_WAIVERS, out)

    def test_root_option(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        elsewhere = self.root / "elsewhere" / ".scratch"
        shutil.copytree(self.scratch, elsewhere)
        code, out, _ = run("next", KEY, "--dir", str(elsewhere), "--root", str(self.root))
        self.assertEqual(code, 0, out)
        self.assertEqual(run("next", KEY, "--dir", str(elsewhere))[0], 1)

    def test_cli_runs_isolated(self):
        be = self.make_repo("be", {"app.py": "x = 1\n"})
        self.record_all(be)
        script = str(Path(flow.__file__).resolve())
        env = dict(os.environ, **GIT_ENV)
        result = subprocess.run(
            [sys.executable, "-I", script, "next", KEY, "--dir", str(self.scratch)],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], f"{KEY}: ready for inspection.")


if __name__ == "__main__":
    unittest.main()
