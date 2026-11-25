---
name: ship
description: Builds a planned task with parallel sub-agents, each in its own slice worktree, calls inspect and loops on fixes until both are satisfied, captures the after proof with lane, opens the PR and updates Jira with before and after screenshots, then watches the PR until it is merged. Use when the user types ship, when blueprint hands off, or to build and ship a ticket or request. Plans first with blueprint when no plan exists.
---

Never assume a requirement. Check Jira for the latest requirements before acting. If a requirement is unclear or cannot be verified, ask the user in plain language before proceeding with work that depends on it.

Be strict and vigilant. Do only what this skill says, in its order, and never step outside the system (see System rules in the conventions file).

# ship

Turn a plan into a merged-quality PR. Work only inside the task's worktree. The user's message outranks everything here (see "Your message comes first" in the conventions file).

First read `~/.agents/skills/blueprint/references/conventions.md`. Read `references/quality-gates.md` before step 3, `~/.agents/skills/inspect/SKILL.md` before step 4, and `references/closeout.md` before step 6. If you are not Claude Code inside T3, read the "Using these skills from another agent" table and swap the tools as it says.

Keep the user informed as the Progress board section of the conventions file says. Before each piece of work, record what you are fixing and why with `progress.py now`. Post an update (the table plus a few simple sentences: this part is fixed, this is why, now I am fixing that) whenever `progress.py due <KEY>` says "due".

## To-do list

Before the first step, make a temporary to-do list from this skill's steps:

```
python3 -I ~/.agents/skills/guide/scripts/todo.py new ship --key <KEY> --from ~/.agents/skills/ship/SKILL.md
```

Leave out `--key` when the task has no key. Tick each item when its Done condition is met, with evidence: `todo.py tick ship --key <KEY> N --note "<proof>"`. Mark a stuck item with `todo.py block`. Add a step you find later with `todo.py add`. Show the list with every update. The list deletes itself when the last item is ticked. See "To-do lists" in the conventions file.

## 0. Get ready

1. Take the key from the call or from the chat. No key and plain instructions means standalone mode.
2. Look for `.scratch/<KEY>-ticket.md`, `-plan.md`, `-decisions.md`, `-repro.md`, `-timeline.md`, the `before/` proof and the worktree.
   - All present: a track skill ran first. Reuse them.
   - Plan missing: read `~/.agents/skills/blueprint/SKILL.md`, let its step 1 pick the track, and run only that track's steps up to and including its plan step. Its last step ("Build, check and ship") does not run now. Then continue here.
   - The first line of `<KEY>-ticket.md` names the track (`Track: bug`, `feature` or `qa-return`). Read that track's skill (`fix-bug`, `build-feature` or `qa-return`). Its last step says what "done" means and how close-out differs.
   - Use exactly the task folder `<root>/worktrees/<KEY>/` and the worktrees `blueprint` made. Run `~/.agents/skills/blueprint/scripts/worktree.sh list <root> <KEY>`: it must show a worktree for every repo in the plan's Task folder table. Never create a task worktree or a branch of your own (the slice worktrees in step 1 are the one exception). A repo is missing: add it with `~/.agents/skills/blueprint/scripts/worktree.sh add`, install, and run its baseline. The folder was archived: move its worktrees back with the commands in its `archive.md`.
3. Check the track's starting proof. If it is missing, do not build. Run the track skill for this key instead:
   - `bug` and `qa-return`: the first line of `<KEY>-repro.md` is `Reproduced: yes`, its second line names the live environment, and `before/` holds the proof. A `qa-return` also has line 1 of `<KEY>-qa-return.md` reading `Verdict: fix incomplete` or `Verdict: broken later`.
   - `feature`: `<KEY>-acceptance.md` has a BA source on every row, and `before/` holds the proof of the current screen, or the board records why there is nothing to run.
4. Check the plan against the requirement documents and the knowledge file. A plan written before a requirement changed is replanned first.
5. Recap the plan in about 5 lines, then start building at once.

"build only" means build only: stop after step 3 and say that QA, proof and the PR were skipped.

Done when the plan, the decision log, the before proof and the worktree are all in place.

## 1. Build

Every builder works in its own slice worktree, so parallel edits never collide. The briefs also give each builder separate files, so the slices merge cleanly.

1. Read the plan's Subparts table. Order the subparts by dependency into batches. Subparts in one batch own separate files and run in parallel.
2. For each subpart in the batch, make its slice worktree from the task worktree's current commit:

   ```
   ~/.agents/skills/blueprint/scripts/worktree.sh slice <root> <KEY> <short> <subpart-id>
   ```

   It makes `<root>/worktrees/<KEY>/_<short>-<subpart-id>` on branch `<branch>--<subpart-id>` and links `node_modules` from the task worktree when it can. When it prints "install needed", run the install command from the conventions table in the slice before the builder starts. Env files are not copied, so a test that needs one runs in the task worktree after the merge. A subpart that spans repos gets one slice per repo.
3. Start one builder per subpart, as the Agents section of the conventions file says. Each brief must stand on its own:
   - the slice worktree path, the plan path and the decision log path
   - the subpart id, what it must do, the files it owns, and the test that must pass
   - the checklist lines it covers
   - the do-not-touch list
   - "Work only in your slice worktree. Edit only your files. Do not commit or push. Do not run installs. If the plan is unclear or wrong, stop and say so instead of guessing. Report the files you changed and the test result in under 15 lines."
4. End the turn. The completions wake the chat.
5. After each batch, in the main chat, for each slice:
   - `git -C <slice> status --porcelain`. Every changed file must belong to that subpart. Revert or ask about anything else.
   - Run the tests the subpart names, in the slice.
   - Commit in the slice with the identity from the conventions file. Message: `<KEY>: <what changed>`.
   - Merge it back: `worktree.sh slice-done <root> <KEY> <short> <subpart-id>`. It merges the slice into the task branch and removes the slice worktree and branch. A merge conflict means two subparts touched the same lines. Nothing is merged, so fix the plan's file ownership, then merge again.
   - Tick "built" on the checklist lines that subpart covers.
6. Run the batch's tests again in the task worktree, then start the next batch from the new commit.
7. Check the overrun rule at every batch boundary. Replace a failed builder once, then ask.

A single subpart or a fix of a few lines may skip the slice and be built in the task worktree by one builder.

Done when every subpart is merged into the task branch, no slice worktree is left, and every checklist line is ticked "built".

## 2. Re-check the starting point

Run the track's own check. If it fails, the build is not done. Go back to the plan, not to a guess.

- `bug`: the failing test from `reproduce` now passes.
- `feature`: every row of `<KEY>-acceptance.md` has its test, and every one passes.
- `qa-return`: the failing test made from QA's steps now passes, and the earlier PR's tests still pass.

## 3. Prove nothing else broke, and run the quality gates

Run the baseline commands again. Every command must do at least as well as the baseline, with no new failures. Then check scope:

- `git -C <wt> diff --name-only origin/<default branch>...HEAD` lists only files the plan lists, plus the repro test.
- Any extra file needs a written reason in the plan or gets reverted.
- Lockfiles, dependency files, CI config and anything on the do-not-touch list stay unchanged unless a subpart lists them.

Then run the two quality gates in `references/quality-gates.md`, in order:

1. Gate 1, `quality crapper --changed --base origin/<default branch> --threshold 6`. A failure starts a cleaner, then the gate runs again.
2. Gate 2, `quality mutator --changed --base origin/<default branch>`, only after Gate 1 passes. A survivor starts a hardener (the `hardening` skill), then the gate runs again.

Each gate allows 3 fix rounds. Record "crap" and "mutation" on the progress board and hand both lines to `inspect`. Skip a gate only when the user says so in the call, and write that in `<KEY>-reviews.md`.

Done when the baseline is no worse, the scope check is clean, and both gates pass on the current commit.

## 4. inspect, and the loop

Follow `~/.agents/skills/inspect/SKILL.md` in pipeline mode. It runs the four code reviewers, the live run and the QA validation, and returns a score, a verdict and the findings.

`ship` and `inspect` are satisfied only when all of these hold on the current commit:

- combined score 100, with postwork PASS
- live run PASS with proof for every step
- QA verdict Done or Done with notes
- every checklist line ticked "verified"
- every edge case that Jira does not cover has the user's answer in the decision log

Anything less is a failed round:

1. Write the phase 2 plan from the findings, as `inspect/references/review-loop.md` says, and show it in chat.
2. Start a fresh builder per independent group of findings.
3. Run steps 2 and 3 again, commit the fixes, and run `inspect` again on the new commit.

Round limits, the stuck rule and the diagnosis are in the same file. "Needs BA input" stops the work and shows the question.

Done when all four conditions hold on one commit.

## 5. After proof, and the comparison

Run this on the final commit, after the loop ends. The before half from `reproduce` is already on the left of each picture. Keep `before/` untouched.

1. Sync every repo with dev (`~/.agents/skills/lane/scripts/sync-dev.sh <worktree> ...`). If a worktree moved, rebuild the lane and run the baseline again.
2. Call the `proof` skill in `after` mode. It captures the same steps in the same place, with the same account, data and method, fills the right half, circles and numbers every change, writes what is being looked at and what was asked, and checks each step against the requirements. Pass it:

   > `proof after <KEY>. Same steps, same place, same account and data. Requirements: .scratch/<KEY>-plan.md checklist and .scratch/<KEY>-decisions.md. Fill the right half, circle and number every change, judge each step against what was asked, and reply COMPLETE or NOT COMPLETE with the items.`

3. Read its reply.
   - `Proof: COMPLETE`: go on.
   - `Proof: NOT COMPLETE`: the work is not finished, so treat it as a failed round. Write the phase 2 plan from the items it lists (a step that does not match is a High finding), fix the code, run steps 2 and 3 of this skill again, then call `proof after` again. Never edit a verdict to get past it.
4. Close every window and tab you opened, and give the lane back with `lane down N`. Run `lane ls` and `lane queue` and confirm nothing of yours is left.
5. Run the after gate. It re-checks the before side, rejects an after image identical to its before image, and runs the `proof` check:

   ```
   python3 -I ~/.agents/skills/blueprint/scripts/proof.py gate after <KEY>
   ```

6. Open every picture in `compare/` and look at it: the circles sit on the real changes, the labels are readable, and the left and right show the same screen. `python3 -I ~/.agents/skills/blueprint/scripts/proof.py compare <KEY>` rebuilds them.

The after shots `inspect` saved during its live run count, when they were taken on this same commit and cover every step. `proof` still builds and checks the pictures.

Done when `gate after` prints `after gate: PASS` and every picture has been looked at.

## 6. Close out

Read the close-out notes in the track skill's last step first. They add to `references/closeout.md` (a QA return opens a new PR from the same branch and tags nobody). Then follow `references/closeout.md`, which ends only when the PR is merged. In order: publish the proof, push, open the PR with the before and after table, comment in Jira with the same proof and attach the screenshots, archive and delete the worktree, hand the PR to `babysit` (fix CI, resolve every comment), move the ticket to Code Review and log work, then stay until it merges. Keep Jira current at each milestone.

## The annotated pair

The `proof` skill builds the before and after pictures (see `proof` for the tool and prompts). `reproduce` calls it in `before` mode (left half only). `ship` and `inspect` call it in `after` mode.

## Proof gate, no exceptions

No PR, no Jira comment, no Jira attachment and no ticket move until the before and after screenshots exist, are real, and show the fix. "Real" means:

1. Every step has a `before/` and an `after/` screenshot of the live app (UI whenever the bug shows in the UI). Logs, transcripts and text are extra, never a replacement.
2. `proof.py gate before` and `gate after` both print PASS. The gate fully decodes each image, rejects blank, tiny or corrupt files and files that are not PNG, JPEG or WebP.
3. Open every image yourself (Read it) and check it shows the right screen, the bug on the before side, and the fixed behavior on the after side. A page that only shows a login, an error page, a blank screen or the wrong course is not proof. Retake it.
4. After you upload to GitHub or Jira, download or open the uploaded image and check it renders. A broken image link or a corrupted upload counts as not published. Fix it, then re-check.
5. If you cannot produce the screenshots (lane will not start, key invalid, blocked), stop and tell the user why. Do not open the PR or comment on Jira without them. Only the user can waive this, by saying "skip proof" in the call.

## Never

- Never skip the requirement documents. Re-check them when the loop is stuck.
- Never create a worktree or a branch except slice worktrees through `worktree.sh slice`. Work only in the task folder `blueprint` made.
- Never let a sub-agent commit or push.
- Never edit outside the plan's files without a written reason.
- Never run a bigger model without a card.
- Never start `inspect` before both quality gates pass or are skipped by the user.
- Never run a full-repo mutation run inside this skill. Use `--changed`.
- Never call the work done below 100, or without a live run PASS on the current commit.
- Never open a PR or update Jira without the before and after comparison. Only the user can waive it, by saying "skip proof" in the call.
- Never merge the PR yourself.
- Never poll an agent. Watch PRs only the way `babysit` says.
- Never end the chat's work before the PR is merged, unless the user stopped it.
