---
name: hardening
description: Runs mutation testing and adds focused tests for changes the existing suite misses. Use when ship finds a surviving mutant or an untested changed line, or the user asks to harden tests.
---

# Harden tests

Typed by the user, this skill joins the ticket's run, as "One run per ticket" in `~/.agents/skills/blueprint/references/conventions.md` says. Rename the chat to `Testing <KEY>` when it starts, as "Chat titles" says. "hardening only" stops after step 3 and renames the chat to `Done <KEY>`.

The board: typed alone, record each step with `progress.py now <KEY> "<what finished>" --why "<why>"` only (after `progress.py init <KEY>`, which keeps a board that exists), then post `progress.py show <KEY>`. Never call `progress.py set` on the `crap` or `mutation` rows. Those rows belong to `ship` step 3: each has 2 steps (the gate ran, it passed on the current commit), and `progress.py` refuses to advance `mutation` until `ship-build` and `crap` are done. This skill's 3 steps are not those 2. As a hardener that `ship` started, skip the board and the rename. `ship` sets the `mutation` row after it runs Gate 2 again.

If you start an agent, begin its brief with the preamble in `~/.agents/skills/blueprint/references/agent-brief.md`.

1. In the task worktree, run the bundled tool: `~/.agents/tools/harden <base-ref>`. Use the same Git base, coverage and test commands as `ship`. Pass extra options after the base ref, for example `--test-command "npm test"`.
2. On exit 3, or on exit 0 with `uncovered` above 0 in the `Total` row, read the survivor list and the functions with uncovered sites. Add or strengthen tests that fail for each surviving change, and add tests that run each uncovered line and fail when it changes. An uncovered site is not a pass. Edit tests only. If a survivor or an uncovered line points to dead code or is equivalent to the original, report it with evidence instead of changing production code or forcing a test.
3. Rerun the same command. Stop after three failed fix rounds. Exit 2 means resolve the baseline or setup failure before interpreting survivors. Report the tests changed, and the survivors and uncovered sites left. Do not commit or push unless asked.
