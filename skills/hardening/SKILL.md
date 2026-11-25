---
name: hardening
description: Runs mutation testing and adds focused tests for changes the existing suite misses. Use when ship finds a surviving mutant or the user asks to harden tests.
---

# Harden tests

1. In the task worktree, run the bundled tool: `~/.agents/tools/harden <base-ref>`. Use the same Git base, coverage and test commands as `ship`. Pass extra options after the base ref, for example `--test-command "npm test"`.
2. On exit 3, read the survivor list. Add or strengthen tests that fail for each surviving change. Edit tests only. If a survivor points to dead code or is equivalent to the original, report it with evidence instead of changing production code or forcing a test.
3. Rerun the same command. Stop after three failed fix rounds. Exit 2 means resolve the baseline or setup failure before interpreting survivors. Report the tests changed and survivors left. Do not commit or push unless asked.
