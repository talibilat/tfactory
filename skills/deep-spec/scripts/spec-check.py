#!/usr/bin/env python3
"""spec-check.py: checks that every line of a deep-spec rests on a source.

  spec-check.py <KEY> [--dir .scratch]

Reads <dir>/<KEY>-spec/spec.md, approvals.md and claims.md.

Rules:
  every heading in the template is present
  requirement kind jira   Source names a Jira key, a Confluence page or an attachment, and the quote has 10+ characters
  requirement kind user   Source is an approval id (A1, A2, ...) that exists in approvals.md with the user's words
  requirement kind code   Source or evidence holds a file:line
  every Decisions row     has an approval id found in approvals.md and proof for the chosen option
  every claim in claims.md has a verdict (confirmed, wrong or unclear) and evidence
  "Owned elsewhere" rows name a Jira key or a PR
  acceptance criteria point to requirement ids that exist

Exit code 0 means PASS.
"""
import argparse
import re
import sys
from pathlib import Path

KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
FILE_LINE = re.compile(r"[\w./@-]+\.\w+:\d+")
APPROVAL = re.compile(r"\bA\d+\b")
PLACEHOLDER = re.compile(r"<[^>]*>|^\s*(tbd|todo|\.\.\.|n/?a|-)?\s*$", re.I)
HEADINGS = [
    "In plain words", "What changed from the ticket text", "Sub-tasks", "What exists today",
    "Owned elsewhere", "Design", "Decisions", "Requirements", "Acceptance criteria", "Security",
    "Known bugs and risks", "Test plan", "Open questions",
]
failures = []


def fail(text):
    failures.append(text)
    print(f"FAIL  {text}")


def ok(text):
    print(f"ok    {text}")


def real(text, minimum=1):
    return len(text.strip()) >= minimum and not PLACEHOLDER.search(text)


def section(text, name):
    m = re.search(rf"^##\s*{re.escape(name)}[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.S | re.M | re.I)
    return m.group(1) if m else None


def rows(text):
    """Data rows of the first markdown table in text, as lists of cells (header and rule skipped)."""
    out, seen_header = [], False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if not seen_header:
            seen_header = True
            continue
        out.append(cells)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--dir", default=".scratch")
    args = ap.parse_args()
    folder = Path(args.dir) / f"{args.key}-spec"
    spec_path, approvals_path, claims_path = folder / "spec.md", folder / "approvals.md", folder / "claims.md"
    for p in (spec_path, approvals_path, claims_path):
        if not p.exists():
            fail(f"{p} is missing")
    if failures:
        return 1
    spec = spec_path.read_text()

    for h in HEADINGS:
        if section(spec, h) is None:
            fail(f"spec.md has no '## {h}' section")

    approvals = {}
    for cells in rows(approvals_path.read_text()):
        if len(cells) >= 4 and APPROVAL.fullmatch(cells[0]):
            if real(cells[3], 3):
                approvals[cells[0]] = cells[3]
            else:
                fail(f"approval {cells[0]} has no user's words")

    req_ids = set()
    reqs = section(spec, "Requirements") or ""
    req_rows = [c for c in rows(reqs) if len(c) >= 5]
    if not req_rows:
        fail("the Requirements table has no rows")
    for rid, what, kind, source, proof in (c[:5] for c in req_rows):
        req_ids.add(rid)
        kind = kind.lower()
        if not real(what, 5):
            fail(f"{rid} is empty")
        elif kind == "jira":
            if not (KEY.search(source) or re.search(r"confluence|attachment|page", source, re.I)):
                fail(f"{rid} is kind jira but names no Jira key, page or attachment")
            elif not real(proof, 10):
                fail(f"{rid} is kind jira with no quote")
            else:
                ok(f"{rid} rests on {source[:40]}")
        elif kind == "user":
            ids = APPROVAL.findall(source)
            missing = [i for i in ids if i not in approvals]
            if not ids:
                fail(f"{rid} is kind user but names no approval id")
            elif missing:
                fail(f"{rid} names {', '.join(missing)}, not found in approvals.md")
            else:
                ok(f"{rid} rests on the user's yes ({', '.join(ids)})")
        elif kind == "code":
            if FILE_LINE.search(source + " " + proof):
                ok(f"{rid} has code evidence")
            else:
                fail(f"{rid} is kind code with no file:line")
        else:
            fail(f"{rid} has kind '{kind}'. Use jira, user or code")

    decisions = section(spec, "Decisions") or ""
    for cells in rows(decisions):
        if len(cells) < 6 or not re.fullmatch(r"D\d+", cells[0]):
            continue
        did, ids = cells[0], APPROVAL.findall(cells[4])
        if not ids:
            fail(f"{did} has no approval id. Hard decisions are the user's")
        elif [i for i in ids if i not in approvals]:
            fail(f"{did} names an approval id not found in approvals.md")
        elif not real(cells[5], 5):
            fail(f"{did} has no proof for the chosen option")
        else:
            ok(f"{did} approved ({', '.join(ids)})")

    crit = section(spec, "Acceptance criteria") or ""
    for line in crit.splitlines():
        if re.match(r"^\s*\d+\.", line):
            refs = re.findall(r"\bR\d+\b", line)
            unknown = [r for r in refs if r not in req_ids]
            if not refs:
                fail(f"acceptance criterion with no requirement id: {line.strip()[:60]}")
            elif unknown:
                fail(f"acceptance criterion points to unknown {', '.join(unknown)}")

    owned = section(spec, "Owned elsewhere") or ""
    for cells in rows(owned):
        if len(cells) >= 2 and real(cells[0]) and not (KEY.search(cells[1]) or re.search(r"#\d+|/pull/\d+", cells[1])):
            fail(f"owned-elsewhere part '{cells[0][:40]}' names no ticket key or PR")

    for cells in rows(claims_path.read_text()):
        if len(cells) >= 5:
            verdict = cells[3].lower()
            if verdict not in ("confirmed", "wrong", "unclear"):
                fail(f"claim {cells[0]} has verdict '{cells[3]}'. Use confirmed, wrong or unclear")
            elif not real(cells[4], 3):
                fail(f"claim {cells[0]} has no evidence")

    print("spec: FAIL" if failures else "spec: PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
