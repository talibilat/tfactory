---
name: fix-bug
description: The bug track of the pipeline. Takes a bug ticket, or a bug described in the chat, from reproduce to a merged PR. Replays the bug live, writes a failing test, finds the root cause, plans with blueprint, builds with ship, and proves the fix with before and after pictures. Use when the user types fix-bug, or asks to fix a bug, an error or a broken behavior.
---

Never assume a requirement. Check Jira for the latest requirements before acting. If a requirement is unclear or cannot be verified, ask the user in plain language before proceeding with work that depends on it.

Do only what this skill says, in its order, and never step outside the system (see System rules in the conventions file).

# fix-bug

The track for a bug: something that worked, or should work, and does not. **A bug is never planned before it has been reproduced.**

First read `~/.agents/skills/blueprint/references/conventions.md`. The user's message outranks everything here (see "Your message comes first" in that file). This track joins the ticket's run, as "One run per ticket" in that file says. Called again, it resumes from what is already verified instead of starting over. Words the user adds to the call: `plan only` or `just blueprint` stops after step 4, `build only` stops after the build and its quality gates (each a finished narrower request, not a waiver), `agents N` or `no agents` sets the agent plan, `model <name>` sets the agents' model, `skip proof` waives the proof (only the user can say it).

## To-do list

```
python3 -I ~/.agents/tools/todo.py new fix-bug --key <KEY> --from ~/.agents/skills/fix-bug/SKILL.md
```

Leave out `--key` when the task has no key. Tick each item when its Done condition is met, with evidence. See "To-do lists" in the conventions file.

## 1. Agree the agent plan

Read `~/.agents/skills/agents-first/SKILL.md` and ask its one question, once, for the whole task. Recommend this plan with the counts filled in:

- **Research:** one read-only sub-agent per track in blueprint step 6, all at once. Collection tracks (`history`, `code-<repo>`, `tests-data`) on Haiku 5.5, Jira tracks on Sonnet 5.5, all at medium effort.
- **Cause unclear after reproduce:** 3 to 5 sub-agents, one theory each, each told to disprove the others' theories. When agent teams are on (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`), offer an agent team for this instead, as `agents-teams` says.
- **Build:** one Sonnet builder per subpart, each in its own slice worktree (ship step 1).
- **Check:** the four `inspect` reviewers and the live run, at once.

Start every agent brief with the preamble in `~/.agents/skills/blueprint/references/agent-brief.md`, with the role filled in.

Skip the question under `full-send`, or when the call already sets the agent count. Then use the recommended plan and say so in one line.

Done when the user picked a plan, or the call already set it.

## 2. Start the task

Run blueprint steps 1 to 4 (`~/.agents/skills/blueprint/SKILL.md`): find the task, claim it, write the ticket file with `Track: bug` as its first line, make the task folder and worktrees, and run the baseline.

Done when blueprint step 4 is done and the ticket file starts with `Track: bug`.

## 3. Reproduce first (a hard gate)

Run the `reproduce` skill. It checks the history, replays the bug step by step in the live environment (local Docker or a lane on the current default branch, or the deployed dev environment), saves the before proof through `proof before`, writes a failing test and names the root cause. It writes one result on the first line of `.scratch/<KEY>-repro.md`:

| Result | What you do |
|---|---|
| `Reproduced: yes` | Run the before gate below. Go on only when it passes |
| `Reproduced: no` | Stop. See below |
| `Reproduced: already fixed` | Stop. See below. The current code no longer shows the bug and the history names the change that fixed it |

```
python3 -I ~/.agents/tools/proof.py gate before <KEY>
```

It must print `before gate: PASS`. Paste its last line in chat. Fix whatever any FAIL line names before moving on.

On `no` or `already fixed`, `reproduce` has already tried 3 rounds to clear the blocker. Start no research and write no plan:

1. Post the short "Could not reproduce" report from `reproduce` step 4: what was tried, what blocks it, and how to resolve it.
2. Offer a draft Jira comment for the reporter. Post it only after the user says yes.
3. Show the "Could not reproduce" card from `blueprint/references/cards.md`, rename the chat to `Needs you <KEY>`, write `pause`, and wait. The claim and the worktrees stay.
4. When the user brings the missing detail, run `reproduce` again from its step 1.

Only the user can lift this gate, by saying so in the call ("plan without reproducing it"). Note in one line that the rule was set aside, and mark the plan "not reproduced" at the top.

When the root cause is still unclear after `reproduce`, run the theory agents from step 1 before planning. Each one writes `.scratch/<KEY>-research/theory-<n>.md` with evidence for and against.

Done when `gate before` prints PASS and the root cause has `file:line` evidence, or the could-not-reproduce report has been shown and the work has stopped.

## 4. Plan

Run blueprint steps 6 to 9. Add these to the plan:

- The Reproduction, Previous attempt and Why it came back sections, from `<KEY>-repro.md` and `<KEY>-history.md`.
- A checklist line "The failing test from reproduce passes", pointing to the subpart that fixes the cause.
- A checklist line for each repro step: "Step N now shows <expected>", proven by its after picture.

"plan only" or "just blueprint" stops here.

Done when blueprint step 9 has posted the plan.

## 5. Build, check and ship

Run `ship` with the key and the user's original message. The work is done when all of these hold on one commit:

- the failing test from `reproduce` passes
- every repro step shows the expected behavior, and `proof after` says `Proof: COMPLETE`
- `inspect` scores 100, the live run passes, and the QA verdict is Done or Done with notes

`ship` opens the PR, comments in Jira with the before and after proof, moves the ticket to Code Review, and hands the PR to `babysit`.

Done when the PR is merged, or the user stopped the work.

## Never

- Never research, decide or plan a bug that has not reproduced.
- Never fix a symptom when the root cause is known. The plan names the cause and fixes it there.
- Never skip the before proof. Only the user can waive it, by saying "skip proof".
- Never use Docker or a lane without the memory rules in the conventions file. Wait in the `lane up` queue, run lint, tests and builds through `lane heavy -- <command>`, and close every lane the moment testing ends.
