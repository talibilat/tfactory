"""Tests for the "every shot must prove something" checks in tools/pair.py and tools/proof.py.

Every key, folder and picture here is disposable: the PNGs are drawn with Pillow in a
temporary folder.

Run with: python3 -B tools/tests/test_proof_meaningful.py
"""
import argparse
import contextlib
import io
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS))

from PIL import Image, ImageDraw  # noqa: E402

import pair  # noqa: E402

KEY = "TEST-1"
SIZE = (1200, 700)
GOOD = [
    (1, "01-course-list-before-save.png", "Course list with the Biology course and no chapters"),
    (2, "02-save-button-after-empty-course.png", "Save button after saving a course with no chapters"),
    (3, "03-error-toast-after-save.png", "Red error toast that appears after the save fails"),
]


def screen(seed_shape, shift=0):
    """A fake screenshot: a fixed noisy header (so the PNG is a realistic size) and one
    black box whose place depends on seed_shape. shift brightens every pixel a little."""
    rng = random.Random(7)
    img = Image.new("RGB", SIZE, (245, 245, 245))
    band = Image.frombytes("RGB", (SIZE[0], 120), rng.randbytes(SIZE[0] * 120 * 3))
    img.paste(band, (0, 0))
    draw = ImageDraw.Draw(img)
    x = 100 + 250 * seed_shape
    draw.rectangle((x, 250, x + 200, 450), fill=(20, 20, 20))
    if shift:
        img = img.point(lambda v: min(255, v + shift))
    return img


class Evidence:
    """A disposable .scratch folder with a repro file, a proof file and before/after shots."""

    def __init__(self, root, steps=GOOD):
        self.dir = Path(root)
        self.steps = steps
        self.ev = self.dir / f"{KEY}-evidence"
        for stage in ("before", "after"):
            (self.ev / stage).mkdir(parents=True, exist_ok=True)
        rows = "\n".join(f"| {n} | {purpose} | it works | `{name}` |" for n, name, purpose in steps)
        (self.dir / f"{KEY}-repro.md").write_text(
            "Reproduced: yes\nLive environment: lane 1\nMethod: visible Chrome\n\n"
            "| # | Action | Expected | Proof |\n|---|---|---|---|\n" + rows + "\n"
        )
        for stage in ("before", "after"):
            (self.ev / stage / "01-api-log.txt").write_text(f"{stage} log line\n")

    def args(self, stage="after"):
        return argparse.Namespace(key=KEY, dir=str(self.dir), stage=stage, force=False)

    def draw(self, stage, offset=0):
        for i, (_, name, _) in enumerate(self.steps):
            screen(i + offset).save(self.ev / stage / name)

    def init(self):
        quiet(pair.cmd_init, self.args())

    def render(self):
        quiet(pair.cmd_render, self.args())

    def item(self, n, **fields):
        base = {"looking_at": None, "asked": None, "allow_identical": None,
                "allow_duplicate": None, "allow_generic": None, "allow_name": None, "allow_small": None}
        base.update(fields)
        quiet(pair.cmd_item, argparse.Namespace(**vars(self.args()), n=n, **base))

    def before_problems(self):
        return pair.problems_before(self.args("before"))

    def after_problems(self):
        return pair.problems_after(self.args("after"))


def quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        fn(*args)
    return out.getvalue()


def about(problems, text):
    return [p for p in problems if text in p]


class ShotChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="proof-meaningful-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def evidence(self, steps=GOOD):
        e = Evidence(self.tmp, steps)
        e.draw("before")
        e.init()
        e.render()
        return e

    def test_good_set_passes(self):
        e = self.evidence()
        self.assertEqual(e.before_problems(), [])
        table = "\n".join(pair.shot_table(e.args("before"), "before"))
        self.assertIn("| 1 | 01-course-list-before-save.png |", table)
        self.assertIn("first shot", table)
        self.assertIn("% of pixels", table)
        self.assertNotIn("SAME", table)

    def test_byte_identical_shots_in_one_set_fail(self):
        e = self.evidence()
        shutil.copy(e.ev / "before" / GOOD[1][1], e.ev / "before" / GOOD[2][1])
        e.render()
        found = about(e.before_problems(), "same picture")
        self.assertEqual(len(found), 1)
        self.assertIn("step 3", found[0])
        self.assertIn("byte for byte", found[0])
        table = "\n".join(pair.shot_table(e.args("before"), "before"))
        self.assertIn(f"SAME as {GOOD[1][1]} (byte for byte)", table)

    def test_identical_shots_far_apart_fail(self):
        e = self.evidence()
        shutil.copy(e.ev / "before" / GOOD[0][1], e.ev / "before" / GOOD[2][1])
        e.render()
        found = about(e.before_problems(), "same picture")
        self.assertEqual(len(found), 1)
        self.assertIn(GOOD[0][1], found[0])

    def test_near_identical_shots_fail(self):
        e = self.evidence()
        screen(1, shift=10).save(e.ev / "before" / GOOD[2][1])  # every pixel moves by 10, under the change threshold
        e.render()
        self.assertNotEqual(pair.digest(e.ev / "before" / GOOD[1][1]), pair.digest(e.ev / "before" / GOOD[2][1]))
        found = about(e.before_problems(), "same picture")
        self.assertEqual(len(found), 1)
        self.assertIn("no change pair.py can see", found[0])

    def test_small_real_change_is_not_a_duplicate(self):
        e = self.evidence()
        img = screen(1)
        ImageDraw.Draw(img).rectangle((900, 600, 940, 640), fill=(200, 30, 30))  # a small red badge appears
        img.save(e.ev / "before" / GOOD[2][1])
        e.render()
        self.assertEqual(about(e.before_problems(), "same picture"), [])

    def test_duplicates_in_after_set_fail(self):
        e = self.evidence()
        e.draw("after", offset=1)
        shutil.copy(e.ev / "after" / GOOD[0][1], e.ev / "after" / GOOD[1][1])
        found = about(e.after_problems(), "after/")
        self.assertTrue(any("same picture" in p and "step 2" in p for p in found), found)

    def test_generic_purpose_fails(self):
        e = self.evidence()
        for text in ("Screenshot", "step 2", "page", "Courses page", "<the screen or call, in one line>"):
            e.item(2, looking_at=text)
            found = about(e.before_problems(), "'looking at' line")
            self.assertEqual(len(found), 1, text)
            self.assertIn("step 2", found[0])

    def test_repeated_purpose_fails(self):
        e = self.evidence()
        e.item(3, looking_at=GOOD[1][2] + ".")
        found = about(e.before_problems(), "same as step 2")
        self.assertEqual(len(found), 1)

    def test_purposes_that_differ_only_by_before_and_after_are_not_repeats(self):
        e = self.evidence()
        e.item(2, looking_at="Save button before saving the empty course")
        e.item(3, looking_at="Save button after saving the empty course")
        self.assertEqual(e.before_problems(), [])

    def test_empty_purpose_keeps_its_old_message(self):
        e = self.evidence()
        e.item(2, looking_at="")
        problems = e.before_problems()
        self.assertTrue(about(problems, "must both be written"))
        self.assertFalse(about(problems, "too generic"))

    def test_bad_file_names_fail(self):
        for name, says in (
            ("screenshot2.png", "does not follow NN-<words>"),
            ("02_save_button.png", "does not follow NN-<words>"),
            ("05-save-button.png", "starts with 05 but this is step 2"),
            ("02-screenshot.png", "says nothing about what it shows"),
            ("02-page-2.png", "says nothing about what it shows"),
        ):
            with self.subTest(name=name):
                shutil.rmtree(self.tmp)
                steps = [GOOD[0], (2, name, GOOD[1][2]), GOOD[2]]
                e = self.evidence(steps)
                found = about(e.before_problems(), says)
                self.assertEqual(len(found), 1, e.before_problems())
                self.assertIn("step 2", found[0])

    def test_picture_with_no_step_fails(self):
        e = self.evidence()
        screen(4).save(e.ev / "before" / "04-extra-dialog.png")
        found = about(e.before_problems(), "is not a step")
        self.assertEqual(len(found), 1)
        table = "\n".join(pair.shot_table(e.args("before"), "before"))
        self.assertIn("| - | 04-extra-dialog.png | (no step", table)

    def test_exception_with_reason_passes_and_is_reported(self):
        e = self.evidence()
        shutil.copy(e.ev / "before" / GOOD[1][1], e.ev / "before" / GOOD[2][1])
        e.render()
        e.item(3, allow_duplicate="Reload must leave the page exactly as it was")
        e.render()
        self.assertEqual(e.before_problems(), [])
        table = "\n".join(pair.shot_table(e.args("before"), "before"))
        self.assertIn("SAME as", table)  # still visible to the reviewer
        self.assertIn("allowed: step 3 duplicate check, because: Reload must leave the page exactly as it was", table)

    def test_generic_and_name_exceptions_with_reason_pass(self):
        steps = [GOOD[0], (2, "shot2.png", "Dashboard"), GOOD[2]]
        e = self.evidence(steps)
        self.assertEqual(len(e.before_problems()), 2)
        e.item(2, allow_generic="The ticket names this screen only as Dashboard", allow_name="File name comes from the QA report as given")
        e.render()
        self.assertEqual(e.before_problems(), [])

    def test_exception_needs_a_real_reason(self):
        e = self.evidence()
        with self.assertRaises(SystemExit):
            e.item(3, allow_duplicate="ok")
        self.assertEqual(pair.load(e.args())["items"][2]["allow_duplicate"], "")

    def test_old_proof_file_without_new_fields_still_works(self):
        e = self.evidence()
        data = pair.load(e.args())
        for item in data["items"]:
            for field in ("allow_duplicate", "allow_generic", "allow_name"):
                item.pop(field)
        pair.save(e.args(), data, rendered=True)
        self.assertEqual(e.before_problems(), [])

    def test_real_sentences_are_not_placeholders(self):
        e = self.evidence()
        for text in (
            "Country <select> after picking France shows its regions",
            "Range label reads 3 < 5 and > 1 after the filter",
            "زر الحفظ بعد حفظ دورة بدون فصول",
            "保存没有章节的课程后的保存按钮",
        ):
            e.item(2, looking_at=text)
            self.assertEqual(about(e.before_problems(), "'looking at' line"), [], text)

    def test_template_placeholder_still_fails(self):
        e = self.evidence()
        e.item(2, looking_at="<what this shot shows and why it is here, in one line>")
        found = about(e.before_problems(), "template placeholder")
        self.assertEqual(len(found), 1)

    def test_repeated_non_latin_purpose_fails(self):
        e = self.evidence()
        e.item(2, looking_at="保存没有章节的课程后的保存按钮")
        e.item(3, looking_at="保存没有章节的课程后的保存按钮")
        self.assertEqual(len(about(e.before_problems(), "same as step 2")), 1)

    def test_allow_identical_needs_a_real_reason(self):
        e = self.evidence()
        with self.assertRaises(SystemExit):
            e.item(3, allow_identical="ok")
        e.item(3, allow_identical="The fix changes only the server log")
        self.assertEqual(pair.load(e.args())["items"][2]["allow_identical"], "The fix changes only the server log")

    def test_old_short_allow_identical_still_counts(self):
        e = self.evidence()
        e.draw("after")  # after is the same picture as before for every step
        data = pair.load(e.args())
        data["items"][0]["allow_identical"] = "ok"  # written before the three word rule
        pair.save(e.args(), data)
        problems = e.after_problems()
        self.assertFalse([p for p in about(problems, "look the same") if "step 1" in p], problems)
        self.assertTrue([p for p in about(problems, "look the same") if "step 2" in p], problems)

    def test_init_takes_a_renamed_shot_and_keeps_the_step(self):
        e = self.evidence()
        e.item(2, looking_at="Save button after saving a course with no chapters, zoomed",
               allow_duplicate="Reload must leave the page exactly as it was")
        quiet(pair.cmd_mark, argparse.Namespace(**vars(e.args()), n=2, box="10,10,40,40", label="the button",
                                                type="change", sides="both", before_box=None, clear=False))
        quiet(pair.cmd_verdict, argparse.Namespace(**vars(e.args()), n=2, verdict="match", note="as asked"))
        repro = e.dir / f"{KEY}-repro.md"
        repro.write_text(repro.read_text().replace(GOOD[1][1], "02-save-button-renamed.png"))
        (e.ev / "before" / GOOD[1][1]).rename(e.ev / "before" / "02-save-button-renamed.png")
        mismatch = about(e.before_problems(), "the repro file names")
        self.assertEqual(len(mismatch), 1)
        self.assertNotIn("--force", mismatch[0])
        self.assertIn(f"pair.py init {KEY}", mismatch[0])
        out = quiet(pair.cmd_init, e.args())
        self.assertIn("02-save-button-after-empty-course -> 02-save-button-renamed", out)
        item = pair.load(e.args())["items"][1]
        self.assertEqual(item["step"], "02-save-button-renamed")
        self.assertEqual(item["looking_at"], "Save button after saving a course with no chapters, zoomed")
        self.assertEqual(item["allow_duplicate"], "Reload must leave the page exactly as it was")
        self.assertEqual(len(item["marks"]), 1)
        self.assertEqual(item["verdict"], "match")
        self.assertFalse((e.ev / "compare" / (GOOD[1][1])).exists(), "the old comparison image is left behind")
        e.render()
        self.assertEqual(e.before_problems(), [])

    def test_bad_name_advice_does_not_say_force(self):
        steps = [GOOD[0], (2, "05-save-button.png", GOOD[1][2]), GOOD[2]]
        e = self.evidence(steps)
        found = about(e.before_problems(), "starts with 05")
        self.assertEqual(len(found), 1)
        self.assertNotIn("--force", found[0])

    def test_upper_case_extension_is_one_shot(self):
        steps = [GOOD[0], (2, "02-save-error-toast.PNG", GOOD[1][2]), GOOD[2]]
        e = self.evidence(steps)
        problems = e.before_problems()
        self.assertEqual(about(problems, "is not a step"), [], problems)
        self.assertEqual(about(problems, "has no image"), [], problems)
        table = "\n".join(pair.shot_table(e.args("before"), "before"))
        self.assertEqual(table.count("02-save-error-toast"), 1, table)

    def test_unreadable_shot_is_reported_not_a_crash(self):
        e = self.evidence()
        good = (e.ev / "before" / GOOD[1][1]).read_bytes()
        (e.ev / "before" / GOOD[1][1]).write_bytes(good[: len(good) // 2])  # truncated
        (e.ev / "before" / "04-stray-dialog.png").write_bytes(b"\x89PNG\r\n\x1a\n not really")
        problems = e.before_problems()
        self.assertTrue([p for p in about(problems, "cannot be opened") if GOOD[1][1] in p], problems)
        self.assertTrue([p for p in about(problems, "cannot be opened") if "04-stray-dialog" in p], problems)
        table = "\n".join(pair.shot_table(e.args("before"), "before"))
        self.assertNotIn(f"| 2 | {GOOD[1][1]}", table)
        self.assertIn(f"| 3 | {GOOD[2][1]}", table)
        self.assertIn(f"left out: before/{GOOD[1][1]} cannot be opened", table)
        quiet(pair.cmd_render, e.args())  # must not raise either

    def test_wide_screenshot_keeps_small_text_changes(self):
        def page(count):
            img = Image.new("RGB", (3840, 2000), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            for i in range(30):
                draw.text((40, 140 + i * 30), f"Row {i}: Biology course, chapter list item", fill=(40, 40, 40), font=pair.font(14))
            draw.text((40, 60), f"Cart: {count} items", fill=(40, 40, 40), font=pair.font(16))
            return img
        folder = Path(self.tmp)
        page(3).save(folder / "a.png")
        page(4).save(folder / "b.png")
        page(3).save(folder / "c.png")
        self.assertIsNone(pair.sameness(folder / "a.png", folder / "b.png"))
        found, _ = pair.pair_diff(folder / "a.png", folder / "b.png")
        self.assertTrue(found)
        x, y, w, h = found[0]
        self.assertTrue(w >= pair.MIN_SIDE and h >= pair.MIN_SIDE and x + w <= pair.W, found)
        self.assertLess(y, 60 * pair.W / 3840 + 20, found)  # in the 900 wide view, where the cart line is
        self.assertEqual(pair.sameness(folder / "a.png", folder / "c.png"), "byte for byte")

    def test_image_cache_reuses_and_refreshes(self):
        folder = Path(self.tmp)
        first, second = folder / "01-a.png", folder / "02-b.png"
        screen(0).save(first)
        screen(0, shift=10).save(second)  # every pixel moves by 10: no change pair.py can see
        opened = []
        real_open = pair.Image.open
        with unittest.mock.patch.object(pair.Image, "open", side_effect=lambda *a, **k: opened.append(a[0]) or real_open(*a, **k)):
            self.assertIn("no change", pair.sameness(first, second))
            self.assertIn("no change", pair.sameness(first, second))
            pair.view(first)
            self.assertEqual(sorted(map(str, opened)), sorted([str(first), str(second)]), "each file is decoded once")
            screen(2).save(second)  # the file changes on disk
            self.assertIsNone(pair.sameness(first, second))
        self.assertEqual(len(opened), 3)

    def test_cached_check_matches_the_full_comparison(self):
        folder = Path(self.tmp)
        variants = {
            "base": screen(1), "shifted": screen(1, shift=10), "moved": screen(2), "far": screen(0),
            "badge": screen(1), "speck": screen(1), "taller": screen(1).resize((SIZE[0], SIZE[1] + 4)),
        }
        ImageDraw.Draw(variants["badge"]).rectangle((900, 600, 940, 640), fill=(200, 30, 30))
        ImageDraw.Draw(variants["speck"]).rectangle((900, 600, 903, 603), fill=(200, 30, 30))
        for name, img in variants.items():
            img.save(folder / f"{name}.png")

        def full(a, b):  # the comparison as it was before the cache
            va = pair.Image.open(a).convert("RGB")
            vb = pair.Image.open(b).convert("RGB")
            va = va.resize((pair.W, max(1, round(va.height * pair.W / va.width))), pair.Image.Resampling.LANCZOS)
            vb = vb.resize((pair.W, max(1, round(vb.height * pair.W / vb.width))), pair.Image.Resampling.LANCZOS)
            if pair.digest(a) == pair.digest(b):
                return "byte for byte"
            return "same" if abs(va.height - vb.height) <= 6 and not pair.regions(va, vb) else None

        for a in variants:
            for b in variants:
                got = pair.sameness(folder / f"{a}.png", folder / f"{b}.png")
                want = full(folder / f"{a}.png", folder / f"{b}.png")
                self.assertEqual(bool(got), bool(want), (a, b, got))

    def test_regions_unchanged_by_refactor(self):
        first = screen(0).resize((pair.W, round(SIZE[1] * pair.W / SIZE[0])))
        second = screen(1).resize(first.size)
        found, summary = pair.compare_views(first, second)
        self.assertEqual(found, pair.regions(first, second))
        self.assertTrue(found)
        self.assertGreater(summary["percent"], 0)
        self.assertGreater(summary["cells"], 0)
        self.assertEqual(pair.compare_views(first, first.copy()), ([], {"percent": 0.0, "cells": 0}))


class GateRuns(unittest.TestCase):
    """proof.py gate run as a command, the way the skills call it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="proof-gate-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def gate(self, stage):
        return subprocess.run(
            [sys.executable, "-B", str(TOOLS / "proof.py"), "gate", stage, KEY, "--dir", self.tmp],
            capture_output=True, text=True, check=False,
        )

    def test_gate_before_passes_good_set_and_prints_table(self):
        e = Evidence(self.tmp)
        e.draw("before")
        e.init()
        e.render()
        run = self.gate("before")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("before gate: PASS", run.stdout)
        self.assertIn("-- shots in before/ and what changed since the previous shot", run.stdout)
        self.assertIn("| Step | File | Purpose (looking at) | Changed vs previous shot |", run.stdout)

    def test_gate_before_fails_duplicate(self):
        e = Evidence(self.tmp)
        e.draw("before")
        shutil.copy(e.ev / "before" / GOOD[0][1], e.ev / "before" / GOOD[1][1])
        e.init()
        e.render()
        run = self.gate("before")
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("FAIL  step 2: before/02-save-button-after-empty-course.png is the same picture", run.stdout)
        self.assertIn("SAME as 01-course-list-before-save.png", run.stdout)

    CROPS = [
        (1, "01-cart-badge-before-add.png", "Cart badge in the header before adding a course, cropped to the badge"),
        (2, "02-cart-badge-after-add.png", "Cart badge in the header after adding a course, cropped to the badge"),
    ]

    def crops(self, steps=CROPS):
        e = Evidence(self.tmp, steps)
        for i, (_, name, _) in enumerate(steps):
            img = Image.new("RGB", (400, 160), (245, 245, 245))
            ImageDraw.Draw(img).rectangle((40 + 150 * i, 40, 120 + 150 * i, 120), fill=(200, 30, 30))
            img.save(e.ev / "before" / name)
        e.init()
        e.render()
        return e

    def test_gate_fails_small_crop_and_says_how(self):
        self.crops()
        run = self.gate("before")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertRegex(run.stdout, r"FAIL  01-cart-badge-before-add.png is .*too small to be a real screenshot")
        self.assertIn(f"pair.py item {KEY} 1 --allow-small", run.stdout)

    def test_gate_passes_crop_with_purpose_and_reason(self):
        e = self.crops()
        for n in (1, 2):
            e.item(n, allow_small="The change is a 12 px badge in a 1440 px header")
        run = self.gate("before")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("allowed: step 1 small check, because: The change is a 12 px badge", run.stdout)

    def test_allow_small_needs_crop_in_the_purpose(self):
        steps = [(1, "01-cart-badge-before-add.png", "Cart badge in the header before adding a course"), self.CROPS[1]]
        e = self.crops(steps)
        for n in (1, 2):
            e.item(n, allow_small="The change is a 12 px badge in a 1440 px header")
        run = self.gate("before")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("does not say it is a crop or zoom", run.stdout)
        self.assertIn("01-cart-badge-before-add.png", run.stdout)
        self.assertNotIn("FAIL  02-cart-badge-after-add.png", run.stdout)

    def test_allow_small_needs_a_real_reason(self):
        e = self.crops()
        with self.assertRaises(SystemExit):
            e.item(1, allow_small="tiny")

    def test_gate_reports_unreadable_shot_and_finishes(self):
        e = Evidence(self.tmp)
        e.draw("before")
        e.init()
        e.render()
        good = (e.ev / "before" / GOOD[1][1]).read_bytes()
        (e.ev / "before" / GOOD[1][1]).write_bytes(good[: len(good) // 2])
        run = self.gate("before")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertNotIn("Traceback", run.stderr)
        self.assertIn(f"FAIL  {GOOD[1][1]} cannot be opened", run.stdout)
        self.assertEqual(run.stdout.count("cannot be opened"), 2, run.stdout)  # the FAIL line and the table note
        self.assertIn(f"| 3 | {GOOD[2][1]}", run.stdout)
        self.assertIn("before gate: FAIL", run.stdout)

    def test_gate_after_reports_after_set(self):
        e = Evidence(self.tmp)
        e.draw("before")
        e.draw("after", offset=1)
        shutil.copy(e.ev / "after" / GOOD[1][1], e.ev / "after" / GOOD[2][1])
        e.init()
        e.render()
        run = self.gate("after")
        self.assertEqual(run.returncode, 1)
        self.assertIn("-- shots in after/", run.stdout)
        self.assertIn("FAIL  step 3: after/03-error-toast-after-save.png is the same picture", run.stdout)


if __name__ == "__main__":
    unittest.main()
