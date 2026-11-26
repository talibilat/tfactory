# Quality gates

Two tool checks run in `ship` step 3, before `inspect`. Each gives a pass or a fail, so no agent judges them. Both tools are our forks of Uncle Bob's crapper and mutator, bundled in `~/.agents/tools/`. `make install` in the tfactory checkout installs them. Run them through `~/.agents/tools/quality`, written `quality` below.

Run each tool from the task worktree root of the repo that changed. A task with several repos runs the gates once per changed repo. Always pass `--base origin/<default branch>`, so the gates check committed work as well as local edits.

## Record every result

Inspection starts only when `flow.py next` finds, for each changed repo's current commit, a passing baseline result, and a crapper and a mutator result that each passed, do not apply (a docs-only repo) or are waived by the user (see "Flow check before inspection" in the conventions file). It reads result files, never the board. So in each changed repo, straight after the baseline tests, crapper or mutator finish, and before any new commit, record the result. Run it from the chat's project folder:

```
python3 -I ~/.agents/tools/flow.py record <KEY> <worktree> <baseline|crap|mutation> <passed|failed|blocked> --count NAME=N ... [--note "<why>"] --dir .scratch
```

- The counts are the real numbers from the tool output, read as "Reading the counts from the tools" in `~/.agents/tools/flow-gate.md` says. Baseline: `tests`, `failed`, `new_failures`. Crapper: `functions`, `scored`, `over_threshold`, `threshold`. Mutator: `sites`, `killed`, `survived`, `uncovered`. Never guess a count or pick one to make a result pass.
- Exit 0 alone is not a pass. A tool that found nothing to check (`No source files to analyze.`, `No source files to mutate.`) or could not run is `blocked`, with a `--note` that says why and no counts.
- Untested sites are not a pass. An `uncovered` site is a changed line that no test runs, so mutator never tried it and exits 0 anyway. The mutation check passes only with `survived` 0 and `uncovered` 0. Record the real counts and the outcome `~/.agents/tools/flow-gate.md` gives, never `passed` while `uncovered` is above 0. Then either add tests that run those lines (a hardener, see Gate 2) or ask the user for a waiver.
- `record` refuses a worktree with uncommitted files. Commit first. Every new commit makes the earlier results stale, so after a cleaner or hardener commit, run the baseline and both gates again and record each one.
- A repo where every changed file is `.md`, `.rst` or `.adoc` needs only the baseline. A `.mdx` file holds code, so it needs all three. `flow.py` marks both gates `not applicable`, so record only the baseline there and run neither tool.

Without these results `flow.py next` blocks inspection, whatever the board says.

### Waivers

Only the user can waive a check. A waiver is the request that `flow.py next` prints for the blocked item as `flow_approval.py new ...`. Run it as `python3 -I ~/.agents/tools/flow_approval.py new ...`, so it works from any folder. It names the key, the check (`waive-<check>`), the repo and the full head commit, and the user signs it with their own key, as `~/.agents/tools/flow-approval.md` says. It expires within 1 hour, and a new commit needs a new waiver. Save the request and the user's signature in `.scratch/<KEY>-evidence/waivers/`, as "Waivers" in `~/.agents/tools/flow-gate.md` says. You may make the request and show it. You never sign it, and a note, a chat line or a line in `<KEY>-reviews.md` is never a waiver. Signing needs the user's one-time sudo setup ("One-time setup" in `~/.agents/tools/flow-approval.md`). Until it is done, no waiver can pass, so a blocked check must be fixed. Say so when you show the request.

## Gate 1: crapper (complexity and coverage)

```
~/.agents/tools/quality crapper --changed --base origin/<default branch> --threshold 6
```

- Exit 0: pass.
- Exit 2: some changed function scores above 6. Start a cleaner.
- Exit 0 with `--no-coverage` output only: the repo has no coverage report. Run its baseline test command with coverage on, then run the gate again. Rows with `N/A` are not scored, so `flow.py` never passes the gate on complexity alone.

Lower the limit for a repo only with a written reason in the plan.

### Cleaner

A fresh sub-agent, one per failing function group, on the same model rule as the builders. Brief, in this order:

- the agent-brief preamble from `~/.agents/skills/blueprint/references/agent-brief.md` (role: senior backend or frontend engineer, for the code it cleans)
- the task worktree path and the crapper table (worst functions first)
- "Lower the CRAP score of these functions below 6 without changing behavior. Split functions, remove branches, add tests for uncovered paths. Do not touch any other file. Do not commit or push. Run the repo's tests. Report the files changed and the new scores in under 10 lines."

Then commit with `<KEY>: <what changed>` and run Gate 1 again. Up to 3 cleaner rounds. A round that does not lower the worst score counts as stuck.

## Gate 2: mutator (are the tests strong)

Runs only after Gate 1 passes.

```
~/.agents/tools/quality mutator --changed --base origin/<default branch>
```

- Exit 0 with `survived` 0 and `uncovered` 0 in the `Total` row: pass.
- Exit 0 with `uncovered` above 0: not a pass. Start a hardener for the functions with uncovered sites, or ask the user for a waiver.
- Exit 3: at least one mutant survived (the tests miss that change). Start a hardener.
- Exit 2: the baseline tests fail. This is a failed build, not a mutation result. Record `mutation` as `blocked` with that message and `baseline` as `failed`, then go back to step 2.

`--changed --base` runs only the lines added or edited since the base branch. Never run the whole repo inside `ship`. A full run is for a nightly job.

### Hardener

A fresh sub-agent that follows the `hardening` skill (`~/.agents/skills/hardening/SKILL.md`). Brief:

- the agent-brief preamble (role: senior test engineer)
- the task worktree path, the survivor list (file, line, the change that survived) and the functions with uncovered sites
- "For each survivor, add or strengthen a test so it fails when that line changes. For each uncovered site, add a test that runs that line and fails when it changes. Edit only test files, unless a survivor or an uncovered line shows dead code, then say so and stop. Do not commit or push. Report the survivors you killed and the uncovered sites you covered in under 10 lines."

Then commit with `<KEY>: <what changed>` and run Gate 2 again. Up to 3 hardener rounds. A survivor or uncovered site on dead code goes to the user as a finding, not a loop.

## After the gates

Set the progress board rows `crap` and `mutation` (2 steps each: the gate ran, the gate passed), with one line as the note: worst score and its limit, survivors and uncovered sites left. For example `progress.py set <KEY> crap 2 2 --note "worst CRAP 4.1, limit 6"`. A row is done when, in every changed repo, the gate passed, was not applicable (docs only) or was waived by the user. Set it to 2 of 2 and name in the note each repo that did not plainly pass, for example `be passed, fe waived by user`. When no repo passed the gate, because each one is docs only or waived, use `progress.py skip <KEY> <crap|mutation> --note "<docs only, or waived by user>"` instead. Pass those two lines to `inspect` so the reviewers do not re-judge complexity or test strength.

Then run the flow check before inspection (see the conventions file). The board rows do not start inspection on their own.

## When a gate is stuck

Three rounds without a pass: stop, show the table of what is left in 6 lines or fewer and a card: "Raise the limit for this repo", "Fix by hand", "Skip this gate with a reason". Wait for the answer. A skipped gate is recorded in `<KEY>-reviews.md`, and inspection still needs the user's signed waiver for it (see "Waivers").

## Fails on the way back from inspect

`inspect` failing sends `ship` through steps 2, 3 and 4 again, so both gates run again on the fix. If the only finding is a weak test, run Gate 2 and the hardener, then `inspect`.
