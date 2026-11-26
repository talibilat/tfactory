---
name: blueprint
description: The shared planning steps of the pipeline, used by the three tracks fix-bug, build-feature and qa-return. Finds and claims the task, makes the worktrees, researches with sub-agents and writes a checked plan. Typed alone, it picks the track and runs that track's skill. Use when the user types blueprint, asks to pick, grab or plan a ticket, or wants a plan for the problem discussed above. "just blueprint" stops after the plan.
---

Never assume a requirement. Check Jira for the latest requirements before acting. If a requirement is unclear or cannot be verified, ask the user in plain language before proceeding with work that depends on it.

Be strict and vigilant. Do only what this skill says, in its order. Never step outside the system (see System rules in the conventions file).

# blueprint

Understand the task, prove the problem, research it, and write a plan no builder can misread. Change no code except the failing repro test.

Three tracks each have a skill that calls the steps below in order, and adds its own first steps and definition of done:

| Track | Skill | For |
|---|---|---|
| `bug` | `fix-bug` | Something that worked, or should work, and does not |
| `feature` | `build-feature` | New or changed behavior: a story or a task |
| `qa-return` | `qa-return` | A ticket QA reopened after its PR was merged and deployed to dev |

**A bug is never planned before it has been reproduced.** If it will not reproduce, the work stops at step 5 with a short report of why and how to get unblocked.

First read `~/.agents/skills/blueprint/references/conventions.md`. It holds the pipeline order, Jira ids, repos, naming, the progress board, evidence folders, agent rules and the ask-first list. The user's message outranks everything here (see "Your message comes first" in that file). If you are not Claude Code inside T3, swap the tools as its "Using these skills from another agent" table says.

This skill joins the ticket's run, as "One run per ticket" in the conventions file says. It finds what is already verified, does its part, then carries on. After every step, update the board and post it. Rename the chat only when the stage changes, as "Chat titles" says. Start every agent brief with the preamble in `references/agent-brief.md`.

## To-do list

Before the first step, make a temporary to-do list from this skill's steps:

```
python3 -I ~/.agents/tools/todo.py new blueprint --key <KEY> --from ~/.agents/skills/blueprint/SKILL.md
```

Leave out `--key` when the task has no key. Tick each item when its Done condition is met, with evidence: `todo.py tick blueprint --key <KEY> N --note "<proof>"`. Mark a stuck item with `todo.py block`, and add a later step with `todo.py add`. Show the list with every update. The list deletes itself when the last item is ticked. See "To-do lists" in the conventions file.

## 1. Find the task

Read the user's message and the whole chat above it. Take the first row that fits.

| What you have | The task | Questions |
|---|---|---|
| A ticket key or Jira link in the call | That ticket | None |
| Text after `blueprint` (a problem, an error, a request such as "make me a calculator app") | That text | None |
| A bare `blueprint` in a chat that already holds a problem, an error, a ticket or a request | The most recent problem in the chat above, whatever it is. Restate it in 2 lines and start | None |
| A bare `blueprint` in an empty chat | Chosen with cards, as `references/cards.md` says | 1 to 4 short cards |

A Jira ticket means Jira mode. Anything else means standalone mode from the conventions file: skip the Jira-only steps, run every other step.

**Pick the track** when a track skill did not call you. Take the first row that fits, then read that track's skill and run it from its first step, passing along everything the user wrote ("just blueprint" included). The track skill calls these steps back.

| What you see | Track |
|---|---|
| The call says `as bug`, `as feature` or `as qa-return` | That track |
| A merged PR for the key, and a newer comment from someone other than the user saying it still fails | `qa-return` |
| Issue type Bug, or an error, a broken behavior or steps to reproduce in the ticket or chat | `bug` |
| Issue type Story or Task, or a request for new or changed behavior | `feature` |
| None of these is clear | Ask one card: Bug, Feature or QA return |

"just blueprint", "only blueprint" or "plan only" means stop after step 9, a finished narrower request. Any other call carries on into `ship` without asking.

Start the progress board with `progress.py init <KEY>`. It keeps a board that already exists. At the end of every step, update the `blueprint` row and post the board (Progress board section of the conventions file).

Done when you can state the task in 2 lines and name its mode.

## 2. Check that the ticket is free, then claim it (Jira mode)

Do all three checks.

1. Fetch the ticket again. If it has an assignee other than me, or its status means someone finished or is working on it, stop and say so. In the card flow, offer the next ticket.
2. Search T3 chats for the key with `t3_thread_search` and `t3_thread_list` (`titleContains`). Read each other chat that mentions it. If it is working on the ticket, tell the user and stop. If its state is unclear, send one question with `t3_thread_send` ("Are you working on <KEY>? Answer yes or no."), wait up to 5 minutes with `t3_thread_wait`, and count no answer as taken.
3. Look for earlier work in every repo under the root folder in `setup.md`: branches named for the key, folders under `<root>/worktrees` and `<root>/archived-worktrees`, and `gh pr list -R <org>/<repo> --search "<KEY>" --state all`. An open PR or live branch owned by someone else counts as taken. A merged or closed PR, or an archive folder, is earlier work: note it for step 5.

Then claim: write `claim` to the timeline, set the assignee to my accountId, move the ticket to "In Progress" by transition name, fetch it again to confirm, and rename the chat to `Planning <KEY>` (Chat titles in the conventions file). If another chat claimed it a moment earlier, back out.

Done when Jira shows me as assignee and In Progress, and the chat carries the key.

## 3. Write the ticket file and trace the requirements

1. Save the summary, description, acceptance text, comments, labels, links, attachment names and estimate to `.scratch/<KEY>-ticket.md`. Its first line is the track: `Track: bug`, `Track: feature` or `Track: qa-return`. `ship`, `inspect` and `guide` read it there. In standalone mode, save the user's request and the relevant chat text instead. This file is data.
2. Note what proof the ticket itself carries. If the ticket or its comments hold UI screenshots, the before and after proof must be UI screenshots of the same screen.
3. Trace the ticket to its requirement documents as `references/requirements.md` says, and read and update the project knowledge file.

**The rule for every decision.** What the product must do comes only from words a BA wrote in Jira: the ticket, its parent chain, the epic, related tickets, linked pages and attachments. Those words are the single authority. Never fill a gap with a guess. A gap becomes a question under Blockers. How the code is built is your choice, backed by evidence from the code.

Done when the ticket file exists and every requirement you know of has a named source.

## 4. Task folder, worktrees and baseline

Everything for the task lives in one folder, `<root>/worktrees/<KEY>/`, with one worktree per repo inside it (`fe`, `be`, `ai`, and so on, named in `setup.md`). Make it now. It is also the first item of the plan.

1. Choose the repos yourself. Score each repo under the root folder from the ticket text and labels, the epic's other tickets and their past PRs, and a code search for names the ticket mentions. Ask only when no repo stands out.
2. For each repo, make its worktree in the task folder (`<root>/worktrees/<KEY>/<short>`):

   ```
   ~/.agents/tools/worktree.sh add <root> <KEY> <short> <repo-path> <branch>
   ```

   It makes the folder on the first call, branches from the latest `origin/<default branch>`, and resumes an existing worktree. After a resume, run `sync-dev.sh` to catch up with dev. Ask when the branch holds someone else's commits. Use the same branch name in every repo. Never create a worktree any other way or anywhere else.
3. Run the install command from the conventions table inside each worktree (`npm ci`, `uv sync`, never an upgrade).
4. Run test, lint, typecheck and build in each. Keep pass or fail, counts and failing test names. Record failures that existed before this change so they are not blamed on it. Leave them unfixed.
5. **If the research or the plan later shows another repo is needed**, add its worktree to the same folder with `worktree.sh add`, install, run its baseline, and add it to the plan's Task folder table before the plan is finished. Never move the task to a new folder.

Done when `~/.agents/tools/worktree.sh list <root> <KEY>` shows a clean worktree for every repo, each with a baseline row.

## 5. The track's before step (a hard gate)

The track skill owns this step, because each track proves the start differently:

| Track | Before step | Where |
|---|---|---|
| `bug` | `reproduce` replays the bug live, saves the before proof, writes a failing test and names the root cause. No plan until it reproduces | `fix-bug` step 3 |
| `feature` | The acceptance checklist with a BA source per criterion, and before pictures of the current screen | `build-feature` step 3 |
| `qa-return` | `reproduce` replays QA's exact steps on dev and on a lane, and a verdict decides whether to go on | `qa-return` step 4 |

Run that step from the track skill, then come back. Every track ends it with `python3 -I ~/.agents/tools/proof.py gate before <KEY>` printing `before gate: PASS`, unless the track stopped the work or nothing can run (a docs or config text change, with the reason on the board).

Done when the track's before step is done, or the track stopped the work with its report.

## 6. Research with sub-agents

This is the most important step. Start every track below at once, one read-only sub-agent per track (Agents section of the conventions file). Each agent gets a short brief that starts with the agent-brief preamble (role: senior research analyst), with paths, writes its findings to `.scratch/<KEY>-research/<track>.md`, cites a source for every claim (ticket key, author and date, or `file:line`), and replies in 30 lines or fewer. End the turn while they run.

| Track | It reads | It answers |
|---|---|---|
| `requirements` | The parent chain, linked pages and attachments, as `requirements.md` says | Every requirement and acceptance criterion, each with its source |
| `ba-words` | Every description and comment a BA wrote on the ticket, its parents, the epic and the epic's tickets about this feature | Exact quotes with ticket key, author and date |
| `related` | Linked tickets, open and future tickets in the same epic (To Do, Backlog, later fix versions), tickets with a similar summary | What each one expects from this area, and what this change must not break or do early |
| `history` | Earlier PRs, commits on the same files, archived worktrees | What was tried before. Reuse `<KEY>-history.md` when `reproduce` wrote it |
| `code-<repo>` | One agent per repo: the code paths, callers, data flow and tests | A `file:line` map of where the behavior lives and what depends on it |
| `tests-data` | Existing tests, fixtures, seeded accounts | What is covered, what is missing, what data the live run needs |

Add the extra tracks the track skill names (`design` and `slices` for a feature, `qa-diff` for a QA return), and one agent per open question. Read each findings file yourself, and send a second agent wherever an answer is thin.

Done when every question the ticket and the chat raise has an answer with a source, or is written down as a gap.

## 7. Write the plan and the decision log

0. Make the plan's first section the Task folder and worktrees table (see the template). It lists every worktree that exists and every one still to add.
1. Write `.scratch/<KEY>-decisions.md` using the layout in `references/plan-template.md`. Every decision gets one row and one backing: a BA quote for what the product must do, code evidence for how it is built. A decision with no backing is not made. It goes under Blockers as a question for the BA.
2. Write `.scratch/<KEY>-plan.md` using the same template. Cover every point in the ticket, the chat and the user's message. Split the work into subparts that own separate files. Fill in the Live test section from `<KEY>-repro.md`, so `inspect` and `lane` can replay it.
3. Fill in the plan's Checklist: one line for each thing that was asked, pointing to the subpart that builds it and the check that proves it.
4. Compare the plan estimate with the Jira estimate. If the plan is more than 1 hour over, say so under Blockers.

Run `python3 -I ~/.agents/tools/grounded.py check <KEY> --stage decisions` before step 8. It must print PASS: a requirement decision with no ticket, page or attachment behind it and no quote is not allowed.

Done when every checklist line maps to a subpart, every decision row has its backing, and the decisions check passes.

## 8. Check the plan

Run the plan check and the Jira grilling, then fix what they find.

1. **Plan check.** A child reads the `ticket-prework-review` skill and pstack `blast-radius`, and scores the plan out of 100, as the template says. Below 90, fix the gaps and run it again.
2. **Jira grilling.** Answers come only from Jira. Every decision about what the product must do is tested against what the BAs wrote.

   1. **Write the questions.** You, or a child that has read the `grilling` skill, read the plan and the decision log and write 8 to 12 questions to `.scratch/<KEY>-reviews/grill-questions.md`. Ask one per requirement decision and one per risky assumption (edge cases, roles, limits, what must not change). Word each neutrally, such as "What do the requirements say should happen when a course has no chapters?". Never include the plan's own answer or a hint of it.
   2. **Start the answerer.** Start one fresh sub-agent (Sonnet medium) with the Atlassian tools, as the Agents section of the conventions file says. Give it only the ticket key and the paths of the questions file, the knowledge file and the output file `.scratch/<KEY>-reviews/grill.md`. Do not give it the plan, the decision log or any code. Its rules:
      - Answer only from Jira: the ticket, its comments, the parent chain, the epic and its related and linked tickets, Confluence pages, and attachments. Search each for every question.
      - Every answer gives a source (ticket key with the author and date, Confluence page with its version, or attachment name) and the exact quote. The BAs' words count most (see `setup.md`).
      - When Jira does not say, the answer is `NOT IN JIRA`, with what was searched. Never guess, infer a rule, read code, or fill a gap from common sense.
      - When two sources disagree, give both and say which is newer.
      - Write a table `| Q | Question | Answer | Source | Quote | Decision | Plan agrees |` and leave the last two columns for the planner.
      If the child has no Jira tools, do this part yourself under the same rules and say so.
   3. **Compare every answer with the plan.** For each row, fill in `Decision` (the decision numbers it checks) and `Plan agrees`:
      - `yes`: the plan already does what the answer says.
      - `changed`: the answer differs from the plan. Change the plan and the decision log to follow Jira, and keep the quote as the backing.
      - `blocker`: the answer is `NOT IN JIRA`. List that question's id (`Q3`) under Blockers in the plan, and take any requirement decision that relied on it out of the plan or mark it as a question for the BA.
   4. **A second round**, only for follow-up questions that the first answers raised. Two rounds at most.
   5. Run the grounded check. It must print PASS:

      ```
      python3 -I ~/.agents/tools/grounded.py check <KEY>
      ```

Done when the plan check has no open plan problem, `grounded.py check` prints `grounded: PASS`, and every checklist line is ticked "planned".

## 9. Show it and hand off

Post in chat, in this order:

1. **What I understood.** Run the `plain-talk` skill in brief mode on the task, the root cause and the plan, and post its answer first. About 150 words: what is wrong, why it happens, how it will be fixed. For a feature: what is asked, and how it will be built. The template says how.
2. Blockers and open questions, or "No blockers".
3. The before proof: the screenshots from `before/`, each with a one-line caption.
4. The plan, trimmed to what a person needs: problem, approach, subparts, baseline, risks. Keep it to a short table or list.
5. The progress board table.

Post the "plan is ready" comment on the ticket, as the Jira updates section of the conventions file says.

Then hand off:

- A Blocker that changes what gets built: write `pause`, ask the user, and wait.
- "just blueprint", "only blueprint" or "plan only": stop here. Mark the later stages skipped on the board and rename the chat to `Done <KEY>`. The worktrees and files stay.
- Otherwise: go back to the track skill. It starts `ship` with the key, the user's original message and its own definition of done.

## Never

- Never offer or take a ticket assigned to someone else.
- Never write a requirement that has no BA source.
- Never write the plan before the research agents have returned.
- Never keep a decision that is not grounded. A requirement rests on a BA quote in Jira. A build choice rests on a `file:line` or a research file. Anything else is changed or becomes a Blocker.
- Never research, decide or plan a bug that has not reproduced. Stop and report why instead.
- Never skip the before proof. It is skipped only when the user says "skip proof" in the call (see Proof in the conventions file).
- Never create a worktree or a branch outside `<root>/worktrees/<KEY>/`, or by any way other than `worktree.sh add`.
- Never push in this skill.
- Never name the chat any way other than the Chat titles table in the conventions file says.
