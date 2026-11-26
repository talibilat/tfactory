---
name: build-feature
description: The feature track of the pipeline. Takes a story or task, or a new feature described in the chat, to a merged PR. Turns the BA's acceptance criteria into a checklist, captures the current screen as the before proof, plans parallel slices with blueprint, builds with ship, and proves each criterion with its own test and after picture. Use when the user types build-feature, or asks to build, add or change a feature, screen or endpoint.
---

Never assume a requirement. Check Jira for the latest requirements before acting. If a requirement is unclear or cannot be verified, ask the user in plain language before proceeding with work that depends on it.

Do only what this skill says, in its order, and never step outside the system (see System rules in the conventions file).

# build-feature

The track for new or changed behavior. There is no bug to reproduce. Write down every acceptance criterion with its BA source before planning, and prove each one at the end.

First read `~/.agents/skills/blueprint/references/conventions.md`. The user's message outranks everything here (see "Your message comes first" in that file). This track joins the ticket's run, as "One run per ticket" in that file says. Called again, it resumes from what is already verified instead of starting over. Words the user adds to the call: `plan only` or `just blueprint` stops after step 5, `build only` stops after the build and its quality gates (each a finished narrower request, not a waiver), `agents N` or `no agents` sets the agent plan, `model <name>` sets the agents' model, `skip proof` waives the proof (only the user can say it).

## To-do list

```
python3 -I ~/.agents/tools/todo.py new build-feature --key <KEY> --from ~/.agents/skills/build-feature/SKILL.md
```

Leave out `--key` when the task has no key. Tick each item when its Done condition is met, with evidence. See "To-do lists" in the conventions file.

## 1. Agree the agent plan

Read `~/.agents/skills/agents-first/SKILL.md` and ask its one question, once, for the whole task. Recommend this plan with the counts filled in:

- **Research:** one read-only sub-agent per track in blueprint step 6, plus the `design` and `slices` tracks from step 4 below, all at once. Collection tracks (`history`, `code-<repo>`, `tests-data`) on Haiku 5.5, Jira and design tracks on Sonnet 5.5, all at medium effort.
- **Build:** one Sonnet builder per slice, each in its own slice worktree (ship step 1), batched by dependency.
- **Check:** the four `inspect` reviewers and the live run, at once.
- **Very large features** (more than about 25 files, or slices that keep going after the first batch): offer a workflow instead of separate builders, as `agents-workflows` says, and try it on one slice first.

Skip the question under `full-send`, or when the call already sets the agent count. Then use the recommended plan and say so in one line.

Done when the user picked a plan, or the call already set it.

## 2. Start the task

Run blueprint steps 1 to 4 (`~/.agents/skills/blueprint/SKILL.md`): find the task, claim it, write the ticket file with `Track: feature` as its first line, make the task folder and worktrees, and run the baseline.

Done when blueprint step 4 is done and the ticket file starts with `Track: feature`.

## 3. Acceptance checklist and before proof

1. Write `.scratch/<KEY>-acceptance.md` from the BA's words: the ticket's acceptance criteria and description, its parent chain and epic, linked pages and attachments, traced as `blueprint/references/requirements.md` says.

   ```
   | # | Criterion (the BA's exact words) | Source (key, author, date) | Test that proves it | After picture or API proof |
   ```

   One row per criterion. A criterion with no BA quote is not a criterion: it goes under Blockers as a question. Fill the last two columns in step 5.
2. Write the steps to `.scratch/<KEY>-repro.md` with the template in `reproduce` step 1, so the after proof replays the same steps. Its first line is `Reproduced: not a bug`. Keep the `Live environment:` and `Method:` lines and one numbered row per step with a proof file name. Leave the "What the report says happens" column as "-". Cover every screen or endpoint the feature changes. For a new screen, capture where it will appear, such as the menu or the page that links to it.
3. Capture the current state with `lane` (or the browser tools) and `proof before`, which saves each step's picture under the row's file name and writes the proof manifest.
4. Run the before gate and paste its last line, then mark the stage done on the board:

   ```
   python3 -I ~/.agents/tools/proof.py gate before <KEY>
   python3 -I ~/.agents/tools/progress.py set <KEY> repro 6 6 --note "before proof of the current screen"
   ```

Work with nothing to run, such as a docs or config text change, skips the before proof: run `progress.py skip <KEY> repro --note "<why>"` instead.

Done when every criterion has a row with its source, and `gate before` prints PASS or the skip is on the board.

## 4. Research

Run blueprint step 6 with two extra tracks:

| Track | It reads | It answers |
|---|---|---|
| `design` | Mockups, Figma links and attachments on the ticket and epic, and the closest existing screens or endpoints in the code | What it must look like and which existing patterns, components and styles to reuse, with `file:line` |
| `slices` | The code map, the acceptance checklist and the repos | How to split the work into slices that own separate files (for example API, data, screen, tests), and which slices depend on which |

Done when every track has returned and every question has an answer with a source, or is written down as a gap.

## 5. Plan

Run blueprint steps 7 to 9. On this track the plan also holds:

- A Subparts table built from the `slices` track: each slice owns separate files, has its own test, and names the slices it waits for.
- One checklist line per acceptance row, pointing to the slice that builds it, its test, and its after picture or API proof. Fill the last two columns of `<KEY>-acceptance.md` from it.
- Feature flags, migrations or new settings only where a BA quote or the code's existing pattern calls for them.

"plan only" or "just blueprint" stops here.

Done when blueprint step 9 has posted the plan and every acceptance row maps to a slice, a test and a proof.

## 6. Build, check and ship

Run `ship` with the key and the user's original message. The work is done when all of these hold on one commit:

- every acceptance row's test passes
- every acceptance row has its after picture or API proof, and `proof after` says `Proof: COMPLETE`
- `inspect` scores 100, the live run passes, and the QA verdict is Done or Done with notes

`ship` opens the PR with the acceptance table and the before and after proof, comments in Jira, moves the ticket to Code Review, and hands the PR to `babysit`.

Done when the PR is merged, or the user stopped the work.

## Never

- Never build a criterion that has no BA source. It is a question for the BA.
- Never let two slices own the same file.
- Never mark a criterion done without its own passing test and its own proof.
- Never use Docker or a lane without the memory rules in the conventions file. Wait in the `lane up` queue, run lint, tests and builds through `lane heavy -- <command>`, and close every lane the moment testing ends.
