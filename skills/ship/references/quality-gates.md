# Quality gates

Two tool checks run in `ship` step 3, before `inspect`. Each gives a pass or a fail, so no agent judges them. Both tools are our forks of Uncle Bob's crapper and mutator, bundled in `~/.agents/skills/ship/scripts/vendor/`. `make install` in the tstack checkout installs them. Run them through `~/.agents/skills/ship/scripts/quality`, written `quality` below.

Run each tool from the task worktree root of the repo that changed. A task with several repos runs the gates once per changed repo. Always pass `--base origin/<default branch>`, so the gates check committed work as well as local edits.

## Gate 1: crapper (complexity and coverage)

```
~/.agents/skills/ship/scripts/quality crapper --changed --base origin/<default branch> --threshold 6
```

- Exit 0: pass.
- Exit 2: some changed function scores above 6. Start a cleaner.
- Exit 0 with `--no-coverage` output only: the repo has no coverage report. Run its baseline test command with coverage on, then run the gate again. Never pass the gate on complexity alone without saying so on the board.

Lower the limit for a repo only with a written reason in the plan.

### Cleaner

A fresh sub-agent, one per failing function group, on the same model rule as the builders. Brief, in this order:

- the task worktree path and the crapper table (worst functions first)
- "Lower the CRAP score of these functions below 6 without changing behavior. Split functions, remove branches, add tests for uncovered paths. Do not touch any other file. Do not commit or push. Run the repo's tests. Report the files changed and the new scores in under 10 lines."

Then commit with `<KEY>: <what changed>` and run Gate 1 again. Up to 3 cleaner rounds. A round that does not lower the worst score counts as stuck.

## Gate 2: mutator (are the tests strong)

Runs only after Gate 1 passes.

```
~/.agents/skills/ship/scripts/quality mutator --changed --base origin/<default branch>
```

- Exit 0: every mutant was killed. Pass.
- Exit 3: at least one mutant survived (the tests miss that change). Start a hardener.
- Exit 2: the baseline tests fail. This is a failed build, not a mutation result. Go back to step 2.

`--changed --base` runs only the lines added or edited since the base branch. Never run the whole repo inside `ship`. A full run is for a nightly job.

### Hardener

A fresh sub-agent that follows the `hardening` skill (`~/.agents/skills/hardening/SKILL.md`). Brief:

- the task worktree path and the survivor list (file, line, the change that survived)
- "For each survivor, add or strengthen a test so it fails when that line changes. Edit only test files, unless the survivor shows dead code, then say so and stop. Do not commit or push. Report the survivors you killed in under 10 lines."

Then commit with `<KEY>: <what changed>` and run Gate 2 again. Up to 3 hardener rounds. A survivor on dead code goes to the user as a finding, not a loop.

## After the gates

Write one line to the progress board rows "crap" and "mutation": worst score and its limit, survivors left. Pass those two lines to `inspect` so the reviewers do not re-judge complexity or test strength.

## When a gate is stuck

Three rounds without a pass: stop, show the table of what is left in 6 lines or fewer and a card: "Raise the limit for this repo", "Fix by hand", "Skip this gate with a reason". Wait for the answer. A skipped gate is recorded in `<KEY>-reviews.md`.

## Fails on the way back from inspect

`inspect` failing sends `ship` through steps 2, 3 and 4 again, so both gates run again on the fix. If the only finding is a weak test, run Gate 2 and the hardener, then `inspect`.
