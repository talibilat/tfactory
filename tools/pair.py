#!/usr/bin/env python3
"""pair.py: one annotated before and after picture per step.

The left half (before) is filled when the bug is reproduced. The right half (after)
is filled when the fix is ready, then every change is circled and numbered, each
step is checked against what was asked, and the picture is rebuilt.

  pair.py init     <KEY> [--force]               steps from <KEY>-repro.md. Run again after a
                                                 rename: it takes the new file names and keeps
                                                 every purpose, mark, verdict and reason.
                                                 --force starts over and drops them all
  pair.py item     <KEY> N [--looking-at T] [--asked T] [--allow-identical WHY]
                          [--allow-duplicate WHY] [--allow-generic WHY] [--allow-name WHY]
                          [--allow-small WHY]
  pair.py textshot <KEY> N before|after [--title "$ command"]
                                                 terminal output (.txt) as an image
  pair.py diff     <KEY> N                       list the changed regions
  pair.py mark     <KEY> N --box x,y,w,h --label T [--type change|look]
                          [--sides both|before|after] [--before-box x,y,w,h] | --clear
  pair.py ignore   <KEY> N --box x,y,w,h --reason T
  pair.py verdict  <KEY> N match|no-match --note T
  pair.py render   <KEY>                         build compare/<step>.png for every step
  pair.py check    <KEY> [--stage before|after]  COMPLETE or NOT COMPLETE (exit 0 or 1)
  pair.py shots    <KEY> [--stage before|after]  table of the shots in one set and what
                                                 changed since the previous shot
  check and shots both default to --stage after.

All options take --dir (default .scratch). Boxes use the 900 pixel wide view that
`diff` prints, not the raw screenshot size. Evidence lives in <dir>/<KEY>-evidence/
(before/, after/, compare/). The step list lives in <dir>/<KEY>-proof.json.

Every shot must prove something. `check` fails a shot that has a generic or repeated
'looking at' line (its purpose), a file name that is not NN-<words>.png with NN the step
number, the same picture as another step in the same set (byte for byte, or with no
change `diff` can see), or no step in the proof file at all. Only a recorded reason
lets one through: --allow-generic, --allow-name or --allow-duplicate on `item`. Every
reason needs at least three words. --allow-small lets proof.py pass a picture under
600x300, and only when the step's 'looking at' line says it is a crop or zoom.

A picture wider than 1800 px is compared at a larger size than the 900 px view, so a
changed digit in 16 px text on a 3840 px screenshot still counts. Its changes are
still given in the 900 px view.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import textwrap
import time
from collections import OrderedDict
from pathlib import Path

runtime = Path(__file__).resolve().parents[1] / ".venv"
if __name__ == "__main__" and (runtime / "bin/python").is_file() and Path(sys.prefix) != runtime:
    os.execv(runtime / "bin/python", [str(runtime / "bin/python"), "-I", __file__, *sys.argv[1:]])

from PIL import Image, ImageChops, ImageDraw, ImageFont

W = 900  # width of each half in the picture
GAP = 20
CELL = 12  # change detection grid
THRESH = 24  # colour difference that counts as a changed pixel
MIN_FRACTION = 0.02  # share of changed pixels that makes a grid cell changed
MIN_SIDE = 12  # ignore changed regions smaller than this
EXTS = (".png", ".jpg", ".jpeg", ".webp")
SHOT_NAME = re.compile(r"^(\d{2,3})-([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)$")  # NN-<words>, words joined by hyphens
# Words that say nothing about what a shot proves. A purpose needs two other words, a file name one.
FILLER = frozenset("""
a an the of on in at to for and or with this that it its is are was shows show showing shown
screenshot screenshots screen screens shot shots page pages step steps image images picture pictures
pic img view ui before after here see look looking capture captured proof evidence test tmp temp untitled
final png jpg jpeg webp
""".split())
MIN_REASON_WORDS = 3
REASONS = ("allow_identical", "allow_duplicate", "allow_generic", "allow_name", "allow_small")
# A placeholder as the templates write it: <what this shot shows and why it is here, in one line>.
# It starts with a lower case letter and has a space, so <select> and "3 < 5 and > 1" are not one.
PLACEHOLDER = re.compile(r"<[a-z][\w ,.:;'/()-]*\s[\w ,.:;'/()-]*>")
# Chinese and Japanese write no spaces between words, so each of these characters counts as a word.
NO_SPACE_SCRIPT = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
WORD = re.compile(rf"[{NO_SPACE_SCRIPT}]|[^\W_{NO_SPACE_SCRIPT}]+")
CROP_WORDS = re.compile(r"\b(crop\w*|zoom\w*|close-?up)\b", re.I)
RED, GREEN, GREY, BLUE, ORANGE = (200, 40, 40), (30, 140, 60), (110, 110, 110), (28, 126, 214), (232, 89, 12)


# ---------- paths and manifest ----------
def ev(args):
    return Path(args.dir) / f"{args.key}-evidence"


def manifest_path(args):
    return Path(args.dir) / f"{args.key}-proof.json"


def load(args):
    p = manifest_path(args)
    if not p.exists():
        sys.exit(f"no {p}. Run: pair.py init {args.key} --dir {args.dir}")
    return json.loads(p.read_text())


def save(args, data, rendered=False):
    now = time.time()
    data["modified"] = now
    if rendered:
        data["rendered"] = now
    manifest_path(args).write_text(json.dumps(data, indent=2) + "\n")


def get_item(data, n):
    for item in data["items"]:
        if item["n"] == n:
            return item
    sys.exit(f"no step {n}. Steps: {', '.join(str(i['n']) for i in data['items'])}")


def find_image(folder, stem):
    for ext in EXTS:
        p = folder / (stem + ext)
        if p.exists():
            return p
    if folder.is_dir():  # an upper case extension such as .PNG on a case-sensitive disk
        for p in sorted(folder.iterdir()):
            if p.stem == stem and p.suffix.lower() in EXTS and p.is_file():
                return p
    return None


def same_file(first, second):
    """True when two paths name one file, for example 02-a.png and 02-a.PNG on a macOS disk."""
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


# ---------- fonts and text ----------
def font(size, mono=False):
    names = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"] if mono else ["/System/Library/Fonts/Helvetica.ttc"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(draw, text, fnt, max_width):
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            trial = (line + " " + word).strip()
            if draw.textlength(trial, font=fnt) <= max_width:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = word
        lines.append(line)
    return lines


# ---------- images, changes, marks ----------
def regions(before, after):
    """Changed regions as (x, y, w, h) in the 900 wide view."""
    return compare_views(before, after)[0]


def compare_views(before, after, tolerance=6):
    """Changed regions as (x, y, w, h) in the views' own pixels (the 900 wide view, or a wider
    one for a wide picture), and a summary: the share of changed pixels in percent and the
    number of changed grid cells (CELL pixels square). A height difference over tolerance
    counts the extra rows as changed."""
    width, h = min(before.width, after.width), min(before.height, after.height)
    r, g, b = ImageChops.difference(before.crop((0, 0, width, h)), after.crop((0, 0, width, h))).split()
    diff = ImageChops.lighter(ImageChops.lighter(r, g), b)  # the biggest change in any colour channel
    mask = diff.point(lambda v: 255 if v > THRESH else 0)
    changed_px = mask.histogram()[255]
    sw, sh = grid(width, h)
    small = mask.resize((sw, sh), Image.Resampling.BOX)
    cells = {(i % sw, i // sw) for i, v in enumerate(small.tobytes()) if v > 255 * MIN_FRACTION}  # row by row, like getpixel
    found, seen = [], set()
    for start in sorted(cells):
        if start in seen:
            continue
        stack, group = [start], []
        seen.add(start)
        while stack:
            cx, cy = stack.pop()
            group.append((cx, cy))
            for dx in range(-1, 2):  # touching cells belong to the same change
                for dy in range(-1, 2):
                    nxt = (cx + dx, cy + dy)
                    if nxt in cells and nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
        xs, ys = [c[0] for c in group], [c[1] for c in group]
        x0, y0, x1, y1 = min(xs) * CELL, min(ys) * CELL, (max(xs) + 1) * CELL, (max(ys) + 1) * CELL
        x1, y1 = min(x1, width), min(y1, h)
        if x1 - x0 >= MIN_SIDE and y1 - y0 >= MIN_SIDE:
            found.append((x0, y0, x1 - x0, y1 - y0))
    extra = 0
    if abs(before.height - after.height) > tolerance:  # one picture is taller: the extra rows changed too
        tall, short = (before, after) if before.height > after.height else (after, before)
        found.append((0, short.height, width, tall.height - short.height))
        extra = tall.height - short.height
    summary = {
        "percent": 100 * (changed_px + extra * width) / (width * max(before.height, after.height)),
        "cells": len(cells) + -(-extra // CELL) * sw,
    }
    return sorted(found, key=lambda r: (r[1], r[0])), summary


def grid(width, height):
    """The size of the change grid for views of this size: one cell per CELL pixels."""
    return max(1, width // CELL), max(1, height // CELL + 1)


# ---------- the image cache ----------
# One cache for the whole run, keyed by a file's path, modified time, change time and size.
# Each picture is decoded once however many checks look at it, and a file rewritten on disk
# is read again. The views most recently used stay in memory up to VIEW_BUDGET bytes (Pillow
# keeps 4 bytes a pixel, so about 28 views of a 1440x4000 screenshot); an older one is made
# again from its file when needed.
VIEW_BUDGET = 256 * 1024 * 1024
THUMB_GAP = 40  # see likely_same
_shots = {}
_views = OrderedDict()
_diffs = {}


class ShotError(Exception):
    """A picture that cannot be opened or decoded."""


def detail_scale(width):
    """How many times the 900 px view's width to compare a picture at. Shrunk to 900 px, a
    3840 px screenshot turns 16 px text into 4 px and a changed digit disappears, so a picture
    wider than 2 x 900 px is compared at 900 x k px, half its own size or more. Pictures up
    to 1800 px wide are compared at 900 px, as before."""
    return max(1, -(-width // (2 * W)))


def decode(path):
    """The whole picture in RGB. Decoding all of it makes a truncated file fail here."""
    with Image.open(path) as raw:
        raw.load()
        return raw if raw.mode == "RGB" else raw.convert("RGB")  # convert would only copy an RGB picture


def view_height(size, k=1):
    width, height = size
    return max(1, round(height * W * k / width))


def make_view(img, k):
    return img.resize((W * k, view_height(img.size, k)), Image.Resampling.LANCZOS)


def thumbnail(view_img, height):
    """The view's top `height` rows averaged over the change grid, the same way compare_views
    averages its mask of changed pixels."""
    return view_img.crop((0, 0, view_img.width, height)).resize(grid(view_img.width, height), Image.Resampling.BOX)


def remember(key, k, view_img):
    _views[(key, k)] = view_img
    _views.move_to_end((key, k))
    while len(_views) > 1 and sum(v.width * v.height * 4 for v in _views.values()) > VIEW_BUDGET:
        _views.popitem(last=False)


def shot_info(path):
    """{key, digest, size, height, error, thumbs} for one picture, made once per version of the file.
    height is the 900 wide view's height. error says why the picture cannot be opened."""
    st = os.stat(path)
    key = (str(Path(path).resolve()), st.st_mtime_ns, st.st_ctime_ns, st.st_size)
    info = _shots.get(key)
    if info is None:
        info = {"key": key, "digest": digest(path), "size": None, "height": None, "error": None, "thumbs": {}}
        try:
            img = decode(path)
        except Exception as err:  # truncated, corrupt or not an image at all
            info["error"] = str(err) or type(err).__name__
        else:
            info["size"], info["height"] = img.size, view_height(img.size)
            for k in sorted({1, detail_scale(img.width)}):
                made = make_view(img, k)
                remember(key, k, made)
                info["thumbs"][(k, made.height)] = thumbnail(made, made.height)
        _shots[key] = info
    return info


def view(path, k=1):
    """The picture resized to 900 x k pixels wide. Raises ShotError when it cannot be opened."""
    info = shot_info(path)
    if info["error"]:
        raise ShotError(f"{Path(path).name} cannot be opened ({info['error']})")
    made = _views.get((info["key"], k))
    if made is None:
        made = make_view(decode(path), k)
    remember(info["key"], k, made)
    return made


def likely_same(earlier, later, k):
    """False when small thumbnails already prove the full comparison at scale k finds a change,
    so it can be skipped. True means the full comparison must run.

    Each thumbnail cell is the average of the view's pixels in one change grid cell, with the
    same weights compare_views uses to average its mask. If no more than a share m of a cell's
    pixels changed by more than THRESH, the averages in any colour differ by at most
    THRESH + (255 - THRESH) * m. A gap of THUMB_GAP (40) or more, less 2 for rounding, needs
    m above 6%, three times MIN_FRACTION, so that cell is changed for certain. Cells in the
    last, partial row are not used, because a change found only there can be too short to count.
    """
    a, b = shot_info(earlier), shot_info(later)
    height = min(view_height(a["size"], k), view_height(b["size"], k))
    rows = height // CELL
    if not rows:
        return True
    thumbs = []
    for path, info in ((earlier, a), (later, b)):
        made = info["thumbs"].get((k, height))
        if made is None:
            made = info["thumbs"][(k, height)] = thumbnail(view(path, k), height)
        thumbs.append(made)
    r, g, b_ = ImageChops.difference(*thumbs).split()
    gap = ImageChops.lighter(ImageChops.lighter(r, g), b_).crop((0, 0, thumbs[0].width, rows))
    return gap.getextrema()[1] < THUMB_GAP


def to_view(region, k, height):
    """A region found at scale k, given in the 900 wide view, at least MIN_SIDE pixels each way
    so pair.py mark accepts it as a box."""
    x, y, w, h = region
    sides = []
    for start, end, limit in ((x / k, (x + w) / k, W), (y / k, (y + h) / k, height)):
        if end - start < MIN_SIDE:  # grow it around its middle
            middle = (start + end) / 2
            start, end = middle - MIN_SIDE / 2, middle + MIN_SIDE / 2
        if start < 0:  # then slide it back inside the view
            start, end = 0, end - start
        if end > limit:
            start, end = max(0, start - (end - limit)), limit
        start, end = math.floor(start), min(limit, math.ceil(end))
        sides.append((start, end - start))
    (vx, vw), (vy, vh) = sides
    return vx, vy, vw, vh


def pair_diff(earlier, later):
    """Changed regions between two pictures as (x, y, w, h) in the 900 wide view, and the
    compare_views summary. A wide picture is compared at its detail scale. Raises ShotError."""
    a, b = shot_info(earlier), shot_info(later)
    memo = (a["key"], b["key"])
    if memo not in _diffs:
        k = detail_scale(max(a["size"][0], b["size"][0])) if a["size"] and b["size"] else 1
        found, summary = compare_views(view(earlier, k), view(later, k), tolerance=6 * k)
        if k > 1:
            found = [to_view(r, k, max(a["height"], b["height"])) for r in found]
        _diffs[memo] = (found, summary)
    return _diffs[memo]


def covered(region, boxes):
    """True when the marks together cover at least 40% of the changed region."""
    if not boxes:
        return False
    rx, ry, rw, rh = region
    points = [(rx + (i + 0.5) * rw / 12, ry + (j + 0.5) * rh / 12) for i in range(12) for j in range(12)]
    inside = sum(1 for px, py in points if any(x - 10 <= px <= x + w + 10 and y - 10 <= py <= y + h + 10 for x, y, w, h in boxes))
    return inside / len(points) >= 0.4


def parse_box(text):
    try:
        x, y, w, h = (int(float(v)) for v in text.split(","))
    except (ValueError, OverflowError):
        sys.exit(f"box '{text}' must be x,y,w,h in whole numbers")
    if w < 10 or h < 10 or x < 0 or y < 0:
        sys.exit("a box needs x and y of 0 or more, and a width and height of at least 10")
    return [x, y, w, h]


def draw_marks(panel, marks, side):
    draw = ImageDraw.Draw(panel)
    badge = font(22)
    for m in marks:
        if m["sides"] not in ("both", side):
            continue
        x, y, w, h = m["before_box"] if side == "before" and m.get("before_box") else m["box"]
        colour = BLUE if m["type"] == "look" else ORANGE
        rx, ry = w / 2 * 1.2 + 8, h / 2 * 1.2 + 8
        cx, cy = x + w / 2, y + h / 2
        if w > 2.5 * h:  # a wide, flat change gets a rounded box, because an oval would swallow its neighbours
            draw.rounded_rectangle((x - 8, y - 8, x + w + 8, y + h + 8), radius=22, outline=colour, width=5)
            rx, ry = w / 2 + 8, h / 2 + 8
        else:
            draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=colour, width=5)
        bx = min(max(cx - rx + 4, 20), W - 20)
        by = min(max(cy - ry + 4, 20), panel.height - 20)
        draw.ellipse((bx - 17, by - 17, bx + 17, by + 17), fill=colour)
        label = str(m["n"])
        draw.text((bx - draw.textlength(label, font=badge) / 2, by - 13), label, fill="white", font=badge)


# ---------- terminal output as an image ----------
def cmd_textshot(args):
    data = load(args)
    item = get_item(data, args.n)
    folder = ev(args) / args.stage
    source = folder / (item["step"] + ".txt")
    if not source.exists():
        sys.exit(f"{source} is missing. Save the real command output there first")
    fnt = font(20, mono=True)
    lines = [f"$ {args.title}"] if args.title else []
    text = source.read_text(errors="replace")
    if not text.strip():
        sys.exit(f"{source} is empty. Save the real command output there first")
    for raw in text.splitlines():
        lines += textwrap.wrap(raw, 100, replace_whitespace=False, drop_whitespace=False) or [""]
    if len(lines) > 60:  # keep the start and the end, because the error is often last
        lines = lines[:30] + [f"... {len(lines) - 58} lines left out, see {source.name} ..."] + lines[-28:]
    line_h, pad = 28, 28
    img = Image.new("RGB", (1200, max(400, len(lines) * line_h + pad * 2)), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        colour = (120, 200, 255) if args.title and i == 0 else (225, 225, 225)
        draw.text((pad, pad + i * line_h), line, fill=colour, font=fnt)
    target = folder / (item["step"] + ".png")
    img.save(target)
    print(f"wrote {target}")


# ---------- commands that edit the step list ----------
def rows_from_repro(args):
    repro = Path(args.dir) / f"{args.key}-repro.md"
    if not repro.exists():
        sys.exit(f"{repro} is missing. Write the repro steps first (reproduce step 1)")
    items = []
    for line in repro.read_text().splitlines():
        row = re.match(r"^\|\s*(\d+)\s*\|(.+)\|\s*([^|]+?)\s*\|\s*$", line)
        if not row:
            continue
        cells = [c.strip() for c in row.group(2).split("|")]
        name = row.group(3).strip().strip("`")
        items.append({
            "n": int(row.group(1)),
            "step": Path(name).stem,
            "kind": "terminal" if name.endswith(".txt") else "ui",
            "looking_at": cells[0] if cells else "",
            "asked": cells[1] if len(cells) > 1 else "",
            "marks": [], "ignore": [], "verdict": "pending", "note": "", **{field: "" for field in REASONS},
        })
    return items


def cmd_init(args):
    items = rows_from_repro(args)
    if not items:
        sys.exit("the repro file has no numbered step rows")
    if manifest_path(args).exists() and not args.force:
        data = load(args)
        have = {i["n"]: i for i in data["items"]}
        added = [i for i in items if i["n"] not in have]
        renamed = []
        for row in items:  # a renamed shot keeps its step: purpose, marks, verdict and reasons
            item = have.get(row["n"])
            if item and item["step"] != row["step"]:
                renamed.append(f"step {row['n']}: {item['step']} -> {row['step']}")
                drop_compare(args, item["step"])
                item["step"], item["kind"] = row["step"], row["kind"]
        data["items"] = sorted(data["items"] + added, key=lambda i: i["n"])
        save(args, data)
        print(f"kept {manifest_path(args).name}; added step(s) {[i['n'] for i in added] or 'none'}")
        for line in renamed:
            print(f"renamed {line}. Its purpose, marks, verdict and reasons are kept. Run pair.py render {args.key}")
        print("--force starts over and drops every purpose, mark, verdict and reason")
        return
    save(args, {"key": args.key, "items": items})
    print(f"created {manifest_path(args)} with {len(items)} step(s). Fix 'looking at' and 'asked' with: pair.py item")


def cmd_item(args):
    data = load(args)
    item = get_item(data, args.n)
    if args.looking_at is not None:
        item["looking_at"] = args.looking_at
    if args.asked is not None:
        item["asked"] = args.asked
    for field in REASONS:
        reason = getattr(args, field, None)
        if reason is None:
            continue
        if reason.strip() and len(reason.split()) < MIN_REASON_WORDS:
            sys.exit(f"--{field.replace('_', '-')} needs a real reason of at least {MIN_REASON_WORDS} words, or \"\" to remove it")
        item[field] = reason.strip()
    save(args, data)
    print(f"step {args.n}: looking at '{item['looking_at']}', asked '{item['asked']}'")
    for field in REASONS:
        if item.get(field):
            print(f"step {args.n}: {field.replace('_', ' ')} because: {item[field]}")
    vague = purpose_problem(item["looking_at"])
    if vague and not item.get("allow_generic"):
        print(f"warning: the 'looking at' line {vague}, so check will fail it. Say what this shot shows and why it is here")
    if item.get("allow_small") and not small_allowed(item):
        print("warning: --allow-small counts only when the 'looking at' line says the shot is a crop or zoom")


def small_allowed(item):
    """True when a shot under proof.py's size floor may pass: its 'looking at' line says it is a
    crop or zoom, and a reason is recorded with --allow-small."""
    return bool(item and item.get("allow_small") and CROP_WORDS.search(item.get("looking_at", "")))


def sizes(args, item):
    b = find_image(ev(args) / "before", item["step"])
    a = find_image(ev(args) / "after", item["step"])
    try:
        bn = view(b) if b else None
        an = view(a) if a else None
    except ShotError as err:
        sys.exit(f"{err}. Retake it")
    return b, a, bn, an


def cmd_mark(args):
    data = load(args)
    item = get_item(data, args.n)
    if args.clear:
        item["marks"] = []
        item["verdict"], item["note"] = "pending", ""
        save(args, data)
        print(f"step {args.n}: marks cleared")
        return
    if not args.box or not args.label:
        sys.exit("give --box x,y,w,h and --label \"what the reviewer should see\"")
    box = parse_box(args.box)
    _, _, bn, an = sizes(args, item)
    ref = an or bn
    if ref is not None and (box[0] + box[2] > W or box[1] + box[3] > ref.height):
        sys.exit(f"box is outside the {W}x{ref.height} view. Run: pair.py diff {args.key} {args.n}")
    mark = {"n": len(item["marks"]) + 1, "box": box, "label": args.label, "type": args.type, "sides": args.sides}
    if args.before_box:
        mark["before_box"] = parse_box(args.before_box)
        bx = mark["before_box"]
        if bn is not None and (bx[0] + bx[2] > W or bx[1] + bx[3] > bn.height):
            sys.exit(f"--before-box is outside the {W}x{bn.height} before view")
    item["marks"].append(mark)
    item["verdict"], item["note"] = "pending", ""  # a changed picture must be judged again
    save(args, data)
    print(f"step {args.n}: mark {mark['n']} added ({args.type}): {args.label}")


def cmd_ignore(args):
    data = load(args)
    item = get_item(data, args.n)
    item["ignore"].append({"box": parse_box(args.box), "reason": args.reason})
    save(args, data)
    print(f"step {args.n}: ignoring that box because: {args.reason}")


def cmd_verdict(args):
    data = load(args)
    item = get_item(data, args.n)
    if args.verdict == "no-match" and not args.note:
        sys.exit("say what does not match with --note")
    item["verdict"] = "match" if args.verdict == "match" else "no-match"
    item["note"] = args.note or ""
    save(args, data)
    print(f"step {args.n}: {item['verdict']}")


def cmd_diff(args):
    data = load(args)
    item = get_item(data, args.n)
    b, a, bn, an = sizes(args, item)
    if bn is None:
        sys.exit("no before image for this step")
    print(f"step {args.n} ({item['step']}): before view {W}x{bn.height}" + (f", after view {W}x{an.height}" if an else ", after not captured yet"))
    if an is None:
        return
    boxes = [m["box"] for m in item["marks"]] + [i["box"] for i in item["ignore"]]
    found = pair_diff(b, a)[0]
    if not found:
        print("no changed region found. The two pictures look the same")
    for i, r in enumerate(found, 1):
        state = "marked" if covered(r, boxes) else "NOT MARKED"
        print(f"change {i}: --box {r[0]},{r[1]},{r[2]},{r[3]}   {state}")


# ---------- rendering ----------
def render_item(args, item):
    b = find_image(ev(args) / "before", item["step"])
    a = find_image(ev(args) / "after", item["step"])
    if b is None:
        return None, "no before image"
    try:
        bn = view(b)
        an = view(a) if a else None
    except ShotError as err:
        return None, str(err)
    height = max(bn.height, an.height if an else bn.height)
    total_w = W * 2 + GAP

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f_txt, f_bar, f_big = font(22), font(34), font(26)
    caption = wrap(probe, f"LOOKING AT   {item['looking_at']}", f_txt, total_w - 40) + wrap(probe, f"ASKED   {item['asked']}", f_txt, total_w - 40)
    legend = []
    for m in item["marks"]:
        legend += wrap(probe, f"{m['n']}   {m['label']}", f_txt, total_w - 80)
    if item["note"]:
        legend += wrap(probe, f"Result: {item['note']}", f_txt, total_w - 40)
    bar_h, cap_h, leg_h = 64, 20 + 30 * len(caption), (20 + 30 * len(legend)) if legend else 0
    canvas = Image.new("RGB", (total_w, bar_h + cap_h + height + leg_h), "white")
    d = ImageDraw.Draw(canvas)

    d.rectangle([0, 0, W, bar_h], fill=RED)
    d.text((20, 14), f"{item['n']}.  BEFORE", fill="white", font=f_bar)
    d.rectangle([W + GAP, 0, total_w, bar_h], fill=GREEN if an else GREY)
    d.text((W + GAP + 20, 14), "AFTER" if an else "AFTER  (fills in when the fix is ready)", fill="white", font=f_bar)
    verdict = {"match": ("MATCHES WHAT WAS ASKED", (255, 255, 255)), "no-match": ("DOES NOT MATCH", (255, 220, 220))}.get(item["verdict"])
    if verdict and an:
        d.text((total_w - 20 - d.textlength(verdict[0], font=f_txt), 20), verdict[0], fill=verdict[1], font=f_txt)

    d.rectangle([0, bar_h, total_w, bar_h + cap_h], fill=(240, 240, 240))
    for i, line in enumerate(caption):
        d.text((20, bar_h + 12 + i * 30), line, fill=(30, 30, 30), font=f_txt)

    top = bar_h + cap_h
    left = bn.copy()
    draw_marks(left, item["marks"], "before")
    canvas.paste(left, (0, top))
    if an:
        right = an.copy()
        draw_marks(right, item["marks"], "after")
        canvas.paste(right, (W + GAP, top))
    else:
        d.rectangle([W + GAP, top, total_w, top + height], fill=(235, 235, 235))
        for i, line in enumerate(["AFTER is not captured yet.", "Run the same steps after the fix", "and it fills in here."]):
            d.text((W + GAP + 60, top + 80 + i * 38), line, fill=GREY, font=f_big)

    ly = top + height
    y = ly + 14
    for m in item["marks"]:
        colour = BLUE if m["type"] == "look" else ORANGE
        d.ellipse((20, y - 2, 46, y + 24), fill=colour)
        d.text((27, y), str(m["n"]), fill="white", font=font(20))
        for line in wrap(d, m["label"], f_txt, total_w - 90):
            d.text((60, y), line, fill=(30, 30, 30), font=f_txt)
            y += 30
    if item["note"]:
        for line in wrap(d, f"Result: {item['note']}", f_txt, total_w - 40):
            d.text((20, y), line, fill=(30, 30, 30), font=f_txt)
            y += 30

    out = ev(args) / "compare"
    out.mkdir(parents=True, exist_ok=True)
    drop_compare(args, item["step"])
    target = out / (item["step"] + ".png")
    canvas.save(target, optimize=True)
    if target.stat().st_size > 1_000_000:  # keep each image under 1 MB
        target.unlink()
        target = out / (item["step"] + ".jpg")
        canvas.save(target, quality=82, optimize=True)
    return target, "both halves" if an else "left half only (after pending)"


def drop_compare(args, step):
    """Delete a step's comparison image, so a stale one is never attached or published."""
    for ext in (".png", ".jpg"):
        stale = ev(args) / "compare" / (step + ext)
        if stale.exists():
            stale.unlink()


def cmd_render(args):
    data = load(args)
    rows, bad = [], 0
    for item in data["items"]:
        target, state = render_item(args, item)
        if target is None:
            print(f"FAIL  step {item['n']}: {state}")
            bad += 1
            continue
        print(f"ok    compare/{target.name}  ({state})")
        rows.append(f"| {item['n']} | {item['looking_at']} | {item['asked']} | {item['verdict']} | `compare/{target.name}` |")
    out = ev(args) / "compare"
    if rows:
        (out / "compare.md").write_text("| # | Looking at | Asked | Result | Picture |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    save(args, data, rendered=True)
    return 1 if bad else 0


# ---------- checks: every shot must prove something ----------
def words(text):
    """The words of a line in any script, lower case. A Chinese or Japanese character is one word."""
    return WORD.findall(str(text).lower())


def meaningful(text):
    """The words of a purpose line or file name that say something: no filler, no bare step numbers."""
    return [w for w in words(text) if w not in FILLER and (len(w) > 1 or re.match(f"[{NO_SPACE_SCRIPT}]", w))
            and not (w.isdigit() and len(w) <= 2)]


def purpose_problem(text):
    """Why a 'looking at' line does not tell a reader what the shot proves, or None when it does."""
    text = str(text).strip()
    if not text:
        return None  # an empty line has its own message in problems_before
    if PLACEHOLDER.search(text):
        return "is still a template placeholder"
    if len(meaningful(text)) < 2:
        return "is too generic"
    return None


def name_problem(item, path):
    """Why a shot's file name is not NN-<words> with NN the step number, or None when it is."""
    found = SHOT_NAME.match(path.stem)
    if not found:
        return f"{path.name} does not follow NN-<words>{path.suffix}, for example 03-save-button-after-empty-course.png"
    if int(found.group(1)) != item["n"]:
        return f"{path.name} starts with {found.group(1)} but this is step {item['n']}, so the names and the steps do not line up"
    if not meaningful(found.group(2).replace("-", " ")):
        return f"{path.name} says nothing about what it shows. Name the screen and the change, for example 03-save-button-after-empty-course.png"
    return None


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sameness(earlier, later):
    """How two shots are the same ('byte for byte' or 'no visible change'), or None when they differ.
    Both must open (see shot_info). The hash and the thumbnails settle most pairs, and only a
    pair they cannot tell apart gets the full comparison, with the same answer it gives."""
    first, second = shot_info(earlier), shot_info(later)
    if first["digest"] == second["digest"]:
        return "byte for byte"
    for path, info in ((earlier, first), (later, second)):
        if info["error"]:
            raise ShotError(f"{Path(path).name} cannot be opened ({info['error']})")
    if abs(first["height"] - second["height"]) > 6:
        return None
    if likely_same(earlier, later, detail_scale(max(first["size"][0], second["size"][0]))) and not pair_diff(earlier, later)[0]:
        return f"no change pair.py can see (every pixel within {THRESH} of the other, or only specks under {MIN_SIDE} px)"
    return None


def set_shots(args, data, stage):
    """The steps that have a picture in before/ or after/, in step order, and the pictures with no step.
    A file counts once, however its name is spelled (02-a.PNG is 02-a.png on a macOS disk)."""
    folder = ev(args) / stage
    steps = [(item, find_image(folder, item["step"])) for item in sorted(data["items"], key=lambda i: i["n"])]
    steps = [(item, path) for item, path in steps if path is not None]
    pictures = sorted(p for p in folder.glob("*") if p.suffix.lower() in EXTS and p.is_file()) if folder.is_dir() else []
    extra = [p for p in pictures if not any(same_file(p, known) for _, known in steps)]
    return steps, extra


def unreadable(paths):
    """{path: why} for the pictures that cannot be opened."""
    return {path: shot_info(path)["error"] for path in paths if shot_info(path)["error"]}


def item_shot_problems(args, data):
    """Purpose and file name problems for every step, whatever the set."""
    found, seen = [], {}
    for item in sorted(data["items"], key=lambda i: i["n"]):
        n = item["n"]
        line = " ".join(words(item["looking_at"]))  # the whole line, so 'before' and 'after' still count
        if not item.get("allow_generic"):
            vague = purpose_problem(item["looking_at"])
            if vague:
                found.append(f"step {n}: the 'looking at' line ('{item['looking_at']}') {vague}. Say what this shot shows and why it is here, "
                             f"for example 'Save button after saving a course with no chapters'. Fix it with pair.py item {args.key} {n} --looking-at, "
                             f"or record why with --allow-generic")
            elif line and line in seen:
                found.append(f"step {n}: the 'looking at' line is the same as step {seen[line]}'s, so a reader cannot tell the two shots apart. "
                             f"Say what is different, or record why with pair.py item {args.key} {n} --allow-generic")
        if line:
            seen.setdefault(line, n)
        if not item.get("allow_name"):
            for stage in ("before", "after"):
                path = find_image(ev(args) / stage, item["step"])
                bad = name_problem(item, path) if path else None
                if bad:
                    found.append(f"step {n}: {bad}. Rename it in the repro file and in before/ and after/, then run pair.py init {args.key}, "
                                 f"which keeps the step's purpose, marks and verdict. Or record why with pair.py item {args.key} {n} --allow-name")
                    break
    return found


def set_shot_problems(args, data, stage):
    """Problems inside one set: a picture that belongs to no step, or two steps with the same picture."""
    found = []
    steps, extra = set_shots(args, data, stage)
    for path in extra:
        found.append(f"{stage}/{path.name} is not a step in {manifest_path(args).name}, so nothing says why it is here. "
                     f"Add it to the repro file as a step with a purpose and run pair.py init {args.key}, or move it out of {stage}/")
    broken = unreadable([path for _, path in steps] + extra)
    for path, why in broken.items():
        found.append(f"{stage}/{path.name} cannot be opened ({why}), so it is left out of the comparisons. Retake it")
    steps = [(item, path) for item, path in steps if path not in broken]
    for j, (later, later_path) in enumerate(steps):
        if later.get("allow_duplicate"):
            continue
        for earlier, earlier_path in steps[:j]:
            how = sameness(earlier_path, later_path)
            if how:
                found.append(f"step {later['n']}: {stage}/{later_path.name} is the same picture as {stage}/{earlier_path.name} ({how}), "
                             f"so it shows nothing new. Retake it showing the change this step is about, drop the step, "
                             f"or record why with pair.py item {args.key} {later['n']} --allow-duplicate")
                break
    return found


def shot_table(args, stage):
    """A table of the shots in one set: step, file, purpose, and what changed since the previous shot."""
    if not manifest_path(args).exists():
        return []
    data = load(args)
    steps, extra = set_shots(args, data, stage)
    if not steps and not extra:
        return []
    shots = [*steps, *((None, p) for p in extra)]
    broken = unreadable([path for _, path in shots])
    lines = [f"-- shots in {stage}/ and what changed since the previous shot",
             "| Step | File | Purpose (looking at) | Changed vs previous shot |", "|---|---|---|---|"]
    previous = None
    for item, path in ((item, path) for item, path in shots if path not in broken):
        if previous is None:
            change = "first shot"
        else:
            how = sameness(previous, path)
            if how:
                change = f"SAME as {previous.name} ({how.split(' (')[0]})"
            else:
                found, summary = pair_diff(previous, path)
                found = found or [(0, 0, 0, 0)]  # not expected: sameness said they differ
                x0, y0 = min(r[0] for r in found), min(r[1] for r in found)
                x1, y1 = max(r[0] + r[2] for r in found), max(r[1] + r[3] for r in found)
                change = f"{summary['percent']:.2f}% of pixels, {summary['cells']} cells, in the box {x0},{y0},{x1 - x0},{y1 - y0}"
        purpose = (item["looking_at"] if item else "(no step: nothing says why it is here)").replace("|", "/")
        purpose = purpose if len(purpose) <= 70 else purpose[:67] + "..."
        lines.append(f"| {item['n'] if item else '-'} | {path.name} | {purpose} | {change} |")
        previous = path
    for path, why in broken.items():
        lines.append(f"left out: {stage}/{path.name} cannot be opened ({why})")
    for item in sorted(data["items"], key=lambda i: i["n"]):
        for field in REASONS:
            if item.get(field):
                lines.append(f"allowed: step {item['n']} {field.replace('allow_', '')} check, because: {item[field]}")
    return lines


# ---------- checks ----------
def problems_before(args):
    if not manifest_path(args).exists():
        return [f"no {manifest_path(args).name}. Run pair.py init {args.key}, then pair.py render {args.key}"]
    data = load(args)
    found = []
    have = {i["n"]: i for i in data["items"]}
    for row in rows_from_repro(args):
        if row["n"] not in have:
            found.append(f"step {row['n']} is in the repro file but not in the proof file. Run pair.py init {args.key} to add it")
        elif have[row["n"]]["step"] != row["step"]:
            found.append(f"step {row['n']}: the repro file names {row['step']} but the proof file has {have[row['n']]['step']}. "
                         f"Run pair.py init {args.key} to take the new name. It keeps the step's purpose, marks and verdict")
    for item in data["items"]:
        n = item["n"]
        if not item["looking_at"].strip() or not item["asked"].strip():
            found.append(f"step {n}: 'looking at' and 'asked' must both be written (pair.py item)")
        if find_image(ev(args) / "before", item["step"]) is None:
            found.append(f"step {n}: before/{item['step']} has no image" + (" (terminal step: run pair.py textshot)" if item["kind"] == "terminal" else ""))
        elif find_image(ev(args) / "compare", item["step"]) is None:
            found.append(f"step {n}: no left half yet. Run pair.py render {args.key}")
    found += item_shot_problems(args, data)
    found += set_shot_problems(args, data, "before")
    return found


def problems_after(args):
    found = problems_before(args)
    if not manifest_path(args).exists():
        return found
    data = load(args)
    for item in data["items"]:
        n = item["n"]
        b = find_image(ev(args) / "before", item["step"])
        a = find_image(ev(args) / "after", item["step"])
        if b is None:
            continue
        if a is None:
            found.append(f"step {n}: after not captured yet. Take it with the same steps and run pair.py render {args.key}")
            continue
        if unreadable([b, a]):
            continue  # set_shot_problems says it cannot be opened
        before_w, after_w = shot_info(b)["size"][0], shot_info(a)["size"][0]
        if abs(before_w - after_w) > 0.02 * before_w:
            found.append(f"step {n}: before is {before_w} px wide and after is {after_w}. Retake with the same window size")
            continue
        changes = pair_diff(b, a)[0]
        boxes = [m["box"] for m in item["marks"]] + [i["box"] for i in item["ignore"]]
        if not changes and not item["allow_identical"]:
            found.append(f"step {n}: before and after look the same, so nothing shows the fix. Check the fix is running, retake the after picture, "
                         f"or record why with pair.py item {args.key} {n} --allow-identical")
        for i, r in enumerate(changes, 1):
            if not covered(r, boxes):
                found.append(f"step {n}: change {i} at {r[0]},{r[1]},{r[2]},{r[3]} is not marked. Run pair.py diff {args.key} {n}, then pair.py mark with a label")
        if not item["marks"]:
            found.append(f"step {n}: nothing is circled. Add at least one numbered mark with a label")
        if item["verdict"] == "pending":
            found.append(f"step {n}: not judged yet. Compare it with what was asked, then run pair.py verdict")
        elif item["verdict"] == "no-match":
            found.append(f"step {n}: DOES NOT MATCH what was asked. {item['note']}")
        shown = find_image(ev(args) / "compare", item["step"])
        if data.get("rendered", 0) < data.get("modified", 0) or (shown and shown.stat().st_mtime < max(b.stat().st_mtime, a.stat().st_mtime)):
            found.append(f"step {n}: the picture is out of date. Run pair.py render {args.key}")
    found += set_shot_problems(args, data, "after")
    return list(dict.fromkeys(found))


def cmd_shots(args):
    data = load(args)
    for line in shot_table(args, args.stage) or [f"no shots in {args.stage}/ yet"]:
        print(line)
    found = item_shot_problems(args, data) + set_shot_problems(args, data, args.stage)
    for line in found:
        print(f"  - {line}")
    return 1 if found else 0


def cmd_check(args):
    if args.stage == "before":
        found = problems_before(args)
        label = "Proof (before half)"
    else:
        found = problems_after(args)
        label = "Proof"
    for stage in ("before",) if args.stage == "before" else ("before", "after"):
        for line in shot_table(args, stage):
            print(line)
    if not found:
        print(f"{label}: COMPLETE")
        return 0
    print(f"{label}: NOT COMPLETE. The work is not finished yet.")
    for line in found:
        print(f"  - {line}")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, n=False):
        sp = sub.add_parser(name)
        sp.add_argument("key")
        if n:
            sp.add_argument("n", type=int)
        sp.add_argument("--dir", default=".scratch")
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init).add_argument("--force", action="store_true")
    sp = add("item", cmd_item, True)
    sp.add_argument("--looking-at")
    sp.add_argument("--asked")
    sp.add_argument("--allow-identical", help="why the before and after of this step may look the same")
    sp.add_argument("--allow-duplicate", help="why this shot may match another shot in the same set")
    sp.add_argument("--allow-generic", help="why this shot's 'looking at' line may stay generic or repeated")
    sp.add_argument("--allow-name", help="why this shot's file name may break NN-<words>")
    sp.add_argument("--allow-small", help="why this crop or zoom may be under 600x300 (the 'looking at' line must say crop or zoom)")
    sp = add("textshot", cmd_textshot, True)
    sp.add_argument("stage", choices=["before", "after"])
    sp.add_argument("--title")
    add("diff", cmd_diff, True)
    sp = add("mark", cmd_mark, True)
    sp.add_argument("--box")
    sp.add_argument("--label")
    sp.add_argument("--type", choices=["change", "look"], default="change")
    sp.add_argument("--sides", choices=["both", "before", "after"], default="both")
    sp.add_argument("--before-box")
    sp.add_argument("--clear", action="store_true")
    sp = add("ignore", cmd_ignore, True)
    sp.add_argument("--box", required=True)
    sp.add_argument("--reason", required=True)
    sp = add("verdict", cmd_verdict, True)
    sp.add_argument("verdict", choices=["match", "no-match"])
    sp.add_argument("--note")
    add("render", cmd_render)
    add("check", cmd_check).add_argument("--stage", choices=["before", "after"], default="after")
    add("shots", cmd_shots).add_argument("--stage", choices=["before", "after"], default="after")

    args = ap.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
