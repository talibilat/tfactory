#!/usr/bin/env python3
"""Pipeline progress board for the blueprint, reproduce, ship, inspect and lane skills.

One JSON file per task: <dir>/<KEY>-progress.json. The skills call `set` when a
step finishes, `now` when they start a piece of work, and `show` to print the
update they post in chat after every step. Parallel agents may update the same
board: each command holds a lock on it while it reads and writes.

  progress.py init  <KEY> [--dir .scratch]
  progress.py set   <KEY> <stage> <done> <total> [--note TEXT]
  progress.py skip  <KEY> <stage> [--note TEXT]
  progress.py catchup <KEY> <stage> --why TEXT   resume mid-way: mark every earlier stage done
  progress.py now   <KEY> "<what I am doing>" --why "<why, in simple words>"
  progress.py show  <KEY>            prints the update and restarts the update timer
  progress.py due   <KEY>            says whether an update is due right now
  progress.py every <KEY> <minutes|default>   the user asked for another interval
  progress.py list                   one line per task found in the folder

Extra updates during a long step, by the local clock, unless `every` set another interval:
  07:00 to 18:00   every 10 minutes
  18:00 to 00:00   every 60 minutes
  00:00 to 07:00   no updates (the work continues)
"""
import argparse
import contextlib
import fcntl
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

# Stage id, label shown in the table, default number of steps.
STAGES = [
    ("blueprint", "blueprint: plan", 9),
    ("repro", "before proof (bug, feature or QA steps)", 6),
    ("ship-build", "ship: build", 4),
    ("crap", "ship: gate 1 crapper", 2),
    ("mutation", "ship: gate 2 mutator", 2),
    ("inspect-interrogate", "inspect: reviewer interrogate", 3),
    ("inspect-postwork", "inspect: reviewer postwork", 3),
    ("inspect-ponytail", "inspect: reviewer ponytail-review", 3),
    ("inspect-thermo", "inspect: reviewer thermo-nuclear", 3),
    ("inspect-qa", "inspect: QA validation and live run", 5),
    ("lane-after", "lane: after proof", 4),
    ("ship-close", "ship: PR and Jira", 6),
    ("ship-merge", "babysit: watch until merged", 2),
]
IDS = [s[0] for s in STAGES]
LABELS = {sid: label for sid, label, _ in STAGES}
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")  # the same pattern as KEY_RE in flow.py
DAY_START, EVENING_START = 7 * 60, 18 * 60  # minutes after midnight
DAY_MINUTES, EVENING_MINUTES = 10, 60


def path_for(args):
    return Path(args.dir) / f"{args.key}-progress.json"


def new_stage(total):
    return {"done": 0, "total": total, "skipped": False, "note": ""}


def upgrade(data):
    """Give a board made before a stage existed that stage's row, in table order.

    A new row starts at 0 done, so an old board never shows a gate as passed that it never recorded.
    The ids of the rows added are kept in "added_stages", so `show` can say so.
    """
    old = data["stages"]
    added = [sid for sid in IDS if not old.get(sid)]
    data["stages"] = {sid: old.get(sid) or new_stage(total) for sid, _, total in STAGES}
    if added:
        data["added_stages"] = [sid for sid in IDS if sid in added or sid in data.get("added_stages", [])]
    return data


def no_board(args):
    return f"no progress file at {path_for(args)}. Run: progress.py init {args.key} --dir {args.dir}"


def load(args):
    p = path_for(args)
    if not p.exists():
        sys.exit(no_board(args))
    return upgrade(json.loads(p.read_text()))


def write(args, data):
    """Write to a temporary file and rename it, so a reader never sees half a board."""
    p = path_for(args)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, p)


@contextlib.contextmanager
def locked(args):
    """Hold the board's lock while reading and writing, so parallel agents do not lose each other's updates."""
    p = path_for(args)
    with open(p.with_name(f".{p.name}.lock"), "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def save(args, data):
    """Write after a real change to the work, so `updated` marks the last step change."""
    data["updated"] = time.time()
    write(args, data)


def new_board(key):
    return {
        "key": key,
        "created": time.time(),
        "last_shown": 0,
        "every_minutes": None,
        "now": None,
        "log": [],
        "stages": {i: new_stage(t) for i, _, t in STAGES},
    }


def cmd_init(args):
    p = path_for(args)
    if p.exists() and not args.force:
        print(f"kept existing {p}")
        return
    save(args, new_board(args.key))
    print(f"created {p}")


def stage_or_exit(name):
    if name not in IDS:
        sys.exit(f"unknown stage '{name}'. Use one of: {', '.join(IDS)}")
    return name


# The order is enforced. A stage may advance only when the stages it needs are finished or skipped.
# (stage, minimum steps of that stage that must already be done)
# The two quality gates run in order after the build, and every inspect row waits for both
# (ship/references/quality-gates.md). A gate the user skipped counts as finished here.
INSPECT = ["inspect-interrogate", "inspect-postwork", "inspect-ponytail", "inspect-thermo", "inspect-qa"]
NEEDS = {
    "repro": [("blueprint", 4)],  # reproduce is step 5 of blueprint
    "ship-build": [("blueprint", None), ("repro", None)],
    "crap": [("ship-build", None)],
    "mutation": [("ship-build", None), ("crap", None)],
    "lane-after": [(i, None) for i in INSPECT],
    "ship-close": [("lane-after", None)],
    "ship-merge": [("ship-close", None)],
}
NEEDS.update({i: [("ship-build", None), ("crap", None), ("mutation", None)] for i in INSPECT})


def blocker(data, stage, new_done):
    """The reason this stage may not advance yet, or None."""
    if new_done <= data["stages"][stage]["done"]:
        return None  # going back or staying put is always allowed
    for need, minimum in NEEDS.get(stage, []):
        e = data["stages"][need]
        if e["skipped"]:
            continue
        if minimum is None and e["done"] < e["total"]:
            return f"{need} is not finished ({e['done']} of {e['total']}). Finish it first"
        if minimum is not None and e["done"] < minimum:
            return f"{need} has only done {e['done']} step(s), and {stage} starts after step {minimum}"
    if stage == "blueprint" and new_done > 5:  # planning follows the reproduce gate
        e = data["stages"]["repro"]
        if not e["skipped"] and e["done"] < e["total"]:
            return f"repro is not finished ({e['done']} of {e['total']}). A bug is not planned before it reproduces"
    return None


def cmd_set(args):
    data = load(args)
    stage = stage_or_exit(args.stage)
    if args.total < 1 or not 0 <= args.done <= args.total:
        sys.exit("done must be between 0 and total, and total at least 1")
    reason = blocker(data, stage, args.done)
    if reason:
        sys.exit(f"BLOCKED: {stage} cannot advance. {reason}.")
    entry = data["stages"][stage]
    entry.update(done=args.done, total=args.total, skipped=False)
    if args.note is not None:
        entry["note"] = args.note
    save(args, data)
    print(f"{stage}: {args.done}/{args.total}")


def cmd_skip(args):
    data = load(args)
    entry = data["stages"][stage_or_exit(args.stage)]
    entry["skipped"] = True
    entry["note"] = args.note or "skipped"
    save(args, data)
    print(f"{args.stage}: skipped")


def cmd_catchup(args):
    data = load(args)
    stage = stage_or_exit(args.stage)
    for sid in IDS[: IDS.index(stage)]:
        e = data["stages"][sid]
        if not e["skipped"]:
            e["done"] = e["total"]
    entry = {"at": time.time(), "what": f"Resumed at {stage}: earlier stages marked done", "why": args.why}
    data.setdefault("log", []).append(entry)
    save(args, data)
    print(f"everything before {stage} is marked done")


def cmd_now(args):
    data = load(args)
    entry = {"at": time.time(), "what": args.what, "why": args.why or ""}
    data["now"] = entry
    data.setdefault("log", []).append(entry)
    save(args, data)
    print("noted")


def cmd_every(args):
    data = load(args)
    if args.minutes == "default":
        data["every_minutes"] = None
    else:
        try:
            minutes = int(args.minutes)
        except ValueError:
            sys.exit("give a number of minutes, or 'default'")
        if minutes < 1:
            sys.exit("minutes must be at least 1")
        data["every_minutes"] = minutes
    write(args, data)
    print(f"updates every {data['every_minutes']} minutes" if data["every_minutes"] else "updates follow the clock schedule")


def interval_minutes(data, now=None):
    """Minutes between updates right now. None means quiet hours."""
    if data.get("every_minutes"):
        return data["every_minutes"]
    t = time.localtime(now)
    minute_of_day = t.tm_hour * 60 + t.tm_min
    if minute_of_day < DAY_START:
        return None
    return DAY_MINUTES if minute_of_day < EVENING_START else EVENING_MINUTES


def percent(done, total):
    return round(100 * done / total) if total else 0


def table(data):
    rows = ["| Stage | Steps done | Steps left | Complete | Note |", "|---|---|---|---|---|"]
    done_sum = total_sum = 0
    for sid, label, _ in STAGES:
        e = data["stages"][sid]
        if e["skipped"]:
            rows.append(f"| {label} | - | - | skipped | {e['note']} |")
            continue
        done_sum += e["done"]
        total_sum += e["total"]
        rows.append(
            f"| {label} | {e['done']} of {e['total']} | {e['total'] - e['done']} | "
            f"{percent(e['done'], e['total'])}% | {e['note']} |"
        )
    rows.append(f"\nOverall: {percent(done_sum, total_sum)}% ({done_sum} of {total_sum} steps) for {data['key']}")
    return "\n".join(rows)


def story(data):
    """What happened since the last update, and what is happening now, with the reasons."""
    lines = []
    since = [e for e in data.get("log", []) if e["at"] > data.get("last_shown", 0)]
    current = data.get("now")
    finished = [e for e in since if e != current]
    if finished:
        lines.append("\nSince the last update:")
        for e in finished:
            lines.append(f"- {e['what']}" + (f" Why: {e['why']}" if e["why"] else ""))
    if current:
        lines.append(f"\nNow: {current['what']}")
        if current["why"]:
            lines.append(f"Why: {current['why']}")
    return "\n".join(lines)


def todo_lists(args):
    """The to-do lists of every skill running for this task, drawn by todo.py."""
    spec = importlib.util.spec_from_file_location("todo", Path(__file__).with_name("todo.py"))
    todo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(todo)
    out = []
    for f in sorted(Path(args.dir).glob(f"todo-*-{args.key}.json")):
        out.append(todo.render(json.loads(f.read_text())))
    return "\n\n".join(out)


def added_note(data):
    """One line for an older board whose added rows have nothing recorded yet, or ''."""
    waiting = [
        LABELS[sid]
        for sid in data.get("added_stages", [])
        if sid in data["stages"] and data["stages"][sid]["done"] == 0 and not data["stages"][sid]["skipped"]
    ]
    if not waiting:
        return ""
    return (
        f"\nNote: this board is older than the {' and '.join(waiting)} row(s). "
        "They were added at 0 and nothing is recorded for them yet."
    )


def cmd_show(args):
    data = load(args)
    extra = todo_lists(args)
    print(table(data) + added_note(data) + story(data) + (("\n\n" + extra) if extra else ""))
    data["last_shown"] = time.time()
    write(args, data)


def cmd_due(args):
    data = load(args)
    every = interval_minutes(data)
    if every is None:
        print("quiet hours: no updates until 07:00. Keep working.")
        return
    waited = time.time() - data.get("last_shown", 0)
    left = every * 60 - waited
    print("due" if left <= 0 else f"not due ({int(left // 60) + 1} min left, updates every {every} min)")


def cmd_list(args):
    files = sorted(Path(args.dir).glob("*-progress.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        print(f"no tasks in {args.dir}")
        return
    for f in files:
        data = upgrade(json.loads(f.read_text()))
        live = [(sid, e) for sid, e in data["stages"].items() if not e["skipped"]]
        done_sum = sum(e["done"] for _, e in live)
        total_sum = sum(e["total"] for _, e in live)
        current = next((sid for sid, e in live if e["done"] < e["total"]), "finished")
        age = int((time.time() - data.get("updated", 0)) // 60)
        print(f"{data['key']}: {percent(done_sum, total_sum)}% done, current stage {current}, last change {age} min ago")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, key=True):
        sp = sub.add_parser(name)
        if key:
            sp.add_argument("key")
        sp.add_argument("--dir", default=".scratch")
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init).add_argument("--force", action="store_true")
    sp = add("set", cmd_set)
    sp.add_argument("stage")
    sp.add_argument("done", type=int)
    sp.add_argument("total", type=int)
    sp.add_argument("--note")
    sp = add("skip", cmd_skip)
    sp.add_argument("stage")
    sp.add_argument("--note")
    sp = add("catchup", cmd_catchup)
    sp.add_argument("stage")
    sp.add_argument("--why", required=True)
    sp = add("now", cmd_now)
    sp.add_argument("what")
    sp.add_argument("--why")
    add("every", cmd_every).add_argument("minutes")
    add("show", cmd_show)
    add("due", cmd_due)
    add("list", cmd_list, key=False)

    args = ap.parse_args()
    if args.fn is cmd_list:
        args.fn(args)
        return
    if not KEY_RE.match(args.key):
        sys.exit(f"bad key {args.key!r}: use letters, digits, dot, dash and underscore")
    if args.fn is cmd_init:
        Path(args.dir).mkdir(parents=True, exist_ok=True)
    elif not path_for(args).exists():
        sys.exit(no_board(args))  # before the lock, so a missing board or a mistyped --dir leaves no file behind
    with locked(args):
        args.fn(args)


if __name__ == "__main__":
    main()
