"""Tests for tools/progress.py. Every board lives in a temporary folder.

Run with: python3 tools/tests/test_progress.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "progress.py"
sys.path.insert(0, str(TOOL.parent))

import progress  # noqa: E402

KEY = "TEST-1"
GATE_ROWS = ["ship-build", "crap", "mutation", "inspect-interrogate"]


def run(folder, *args):
    return subprocess.run(
        [sys.executable, "-I", str(TOOL), *args, "--dir", str(folder)],
        capture_output=True,
        text=True,
    )


class BoardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.assertEqual(run(self.dir, "init", KEY).returncode, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def board(self):
        return json.loads((self.dir / f"{KEY}-progress.json").read_text())

    def set(self, stage, done, total):
        return run(self.dir, "set", KEY, stage, str(done), str(total))

    def finish_build(self):
        # Planning stops at step 5 until the before proof is done.
        for stage, done, total in [("blueprint", 5, 9), ("repro", 6, 6), ("blueprint", 9, 9), ("ship-build", 4, 4)]:
            result = self.set(stage, done, total)
            self.assertEqual(result.returncode, 0, result.stderr)


class StageOrderTest(unittest.TestCase):
    def test_gate_rows_sit_between_build_and_inspect(self):
        ids = progress.IDS
        self.assertEqual(ids[ids.index("ship-build"): ids.index("inspect-interrogate") + 1], GATE_ROWS)

    def test_every_inspect_row_needs_both_gates(self):
        for stage in progress.INSPECT:
            needs = [name for name, _ in progress.NEEDS[stage]]
            self.assertIn("crap", needs, stage)
            self.assertIn("mutation", needs, stage)


class GateOrderTest(BoardTest):
    def test_new_board_has_gate_rows(self):
        stages = self.board()["stages"]
        self.assertEqual(list(stages), progress.IDS)
        self.assertEqual(stages["crap"], {"done": 0, "total": 2, "skipped": False, "note": ""})
        self.assertEqual(stages["mutation"]["total"], 2)

    def test_crap_waits_for_the_build(self):
        result = self.set("crap", 1, 2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED: crap cannot advance. ship-build is not finished (0 of 4)", result.stderr)

    def test_mutation_waits_for_crap(self):
        self.finish_build()
        result = self.set("mutation", 1, 2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("crap is not finished (0 of 2)", result.stderr)

    def test_inspect_waits_for_both_gates(self):
        self.finish_build()
        result = self.set("inspect-qa", 1, 5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("crap is not finished", result.stderr)

        self.assertEqual(self.set("crap", 2, 2).returncode, 0)
        result = self.set("inspect-postwork", 1, 3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mutation is not finished (0 of 2)", result.stderr)

        self.assertEqual(self.set("mutation", 2, 2).returncode, 0)
        for stage in progress.INSPECT:
            self.assertEqual(self.set(stage, 1, 3).returncode, 0, stage)

    def test_skipping_both_gates_still_needs_the_build(self):
        run(self.dir, "skip", KEY, "crap", "--note", "user skipped the gates")
        run(self.dir, "skip", KEY, "mutation", "--note", "user skipped the gates")
        result = self.set("inspect-thermo", 1, 3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ship-build is not finished", result.stderr)

        self.finish_build()
        self.assertEqual(self.set("inspect-thermo", 1, 3).returncode, 0)

    def test_going_back_is_always_allowed(self):
        self.finish_build()
        self.assertEqual(self.set("crap", 2, 2).returncode, 0)
        self.assertEqual(self.set("ship-build", 2, 4).returncode, 0)
        self.assertEqual(self.set("crap", 0, 2).returncode, 0)

    def test_show_lists_the_gate_rows_with_their_notes(self):
        self.finish_build()
        run(self.dir, "set", KEY, "crap", "2", "2", "--note", "worst CRAP 4.1, limit 6")
        out = run(self.dir, "show", KEY).stdout
        self.assertIn("| ship: gate 1 crapper | 2 of 2 | 0 | 100% | worst CRAP 4.1, limit 6 |", out)
        self.assertIn("| ship: gate 2 mutator | 0 of 2 | 2 | 0% |  |", out)


class OldBoardTest(BoardTest):
    """A board written before the gate rows existed."""

    def setUp(self):
        super().setUp()
        data = self.board()
        for stage in ("crap", "mutation"):
            del data["stages"][stage]
        for stage, total in [("blueprint", 9), ("repro", 6), ("ship-build", 4)]:
            data["stages"][stage]["done"] = total
        data["stages"]["inspect-qa"]["done"] = 2
        (self.dir / f"{KEY}-progress.json").write_text(json.dumps(data))

    def test_show_reads_it_and_adds_the_rows_unpassed(self):
        result = run(self.dir, "show", KEY)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| ship: gate 1 crapper | 0 of 2 |", result.stdout)
        self.assertIn("| inspect: QA validation and live run | 2 of 5 |", result.stdout)
        self.assertEqual(list(self.board()["stages"]), progress.IDS)

    def test_show_says_the_gate_rows_were_added(self):
        note = (
            "Note: this board is older than the ship: gate 1 crapper and ship: gate 2 mutator row(s). "
            "They were added at 0 and nothing is recorded for them yet."
        )
        for _ in range(2):  # the first show saves the upgraded board. The note must survive that
            out = run(self.dir, "show", KEY).stdout
            self.assertEqual(out.count(note), 1, out)
        self.assertEqual(self.set("crap", 2, 2).returncode, 0)
        out = run(self.dir, "show", KEY).stdout
        self.assertIn("older than the ship: gate 2 mutator row(s)", out)
        run(self.dir, "skip", KEY, "mutation", "--note", "user skipped")
        self.assertNotIn("Note: this board is older", run(self.dir, "show", KEY).stdout)

    def test_new_board_has_no_note(self):
        fresh = self.dir / "fresh"
        self.assertEqual(run(fresh, "init", KEY).returncode, 0)
        self.assertNotIn("Note:", run(fresh, "show", KEY).stdout)

    def test_list_reads_it(self):
        result = run(self.dir, "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"{KEY}: ", result.stdout)
        self.assertIn("current stage crap", result.stdout)

    def test_inspect_does_not_advance_until_the_gates_are_recorded(self):
        result = self.set("inspect-qa", 3, 5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("crap is not finished", result.stderr)


class MissingBoardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_mistyped_dir_creates_nothing(self):
        typo = self.dir / "scrach"
        for command in (["show", KEY], ["set", KEY, "blueprint", "1", "9"], ["now", KEY, "x"], ["due", KEY]):
            with self.subTest(command=command[0]):
                result = run(typo, *command)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("no progress file at", result.stderr)
                self.assertFalse(typo.exists())

    def test_missing_board_leaves_no_lock_file(self):
        result = run(self.dir, "show", KEY)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_init_makes_the_folder(self):
        target = self.dir / "new" / "scratch"
        self.assertEqual(run(target, "init", KEY).returncode, 0)
        self.assertTrue((target / f"{KEY}-progress.json").exists())

    def test_bad_key_is_refused(self):
        inner = self.dir / "inner"
        inner.mkdir()
        for key in ("../escaped", "a/b", ".hidden", f"{KEY}\n", ""):
            with self.subTest(key=key):
                result = run(inner, "init", key)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("bad key", result.stderr)
        self.assertEqual(list(inner.iterdir()), [])
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["inner"])

    def test_key_pattern_matches_flow(self):
        import flow  # noqa: E402

        self.assertEqual(progress.KEY_RE.pattern, flow.KEY_RE.pattern)


class ParallelUpdateTest(BoardTest):
    def test_parallel_agents_do_not_lose_updates(self):
        notes = [f"agent {n}" for n in range(12)]
        with ThreadPoolExecutor(max_workers=len(notes)) as pool:
            results = list(pool.map(lambda note: run(self.dir, "now", KEY, note), notes))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        logged = [entry["what"] for entry in self.board()["log"]]
        self.assertEqual(sorted(logged), sorted(notes))
        self.assertEqual([p.name for p in self.dir.glob("*-progress.json")], [f"{KEY}-progress.json"])
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
