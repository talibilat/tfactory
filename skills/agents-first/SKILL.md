---
name: agents-first
description: Default start for every task when Claude is the main model. Checks whether the task splits across several agents, asks the user before spinning them up, then picks the approach (subagents, agent view, agent teams, workflows, worktrees, messaging) and the model for each agent. Use at the start of every task, and when the user asks how to run work in parallel.
---

# agents-first

Run this at the start of every task while Claude is the main model. When the work splits, ask the user before starting agents, then run the plan they pick.

## 1. Does the task split?

The task **splits** when any of these is true:

- It has two or more parts that don't depend on each other.
- Answering means reading across many files, logs or web pages.
- It deserves review from several angles, such as security, speed and tests.
- The cause is unclear and several theories can be tested at once.
- The same change repeats across many files.

A quick single step (one answer, a one-line edit), a chain where each step needs the last, or a back-and-forth with the user stays in this chat. Ask nothing.

Done when you can name each part, or know there is only one.

## 2. Pick the approach

| The work | Approach | Read |
|---|---|---|
| A side job that would fill the chat with search results, logs or file contents | Subagents | `agents-subagents` |
| Separate jobs the user hands off and checks on later | Agent view | `agents-view` |
| Workers who must discuss and challenge each other's findings | Agent team (experimental) | `agents-teams` |
| Too big for a few subagents: a codebase audit, a many-file migration, research checked across sources | Workflow | `agents-workflows` |
| Several agents editing the same repo | Add a worktree per agent | `agents-worktrees` |
| Sessions the user runs that need to pass findings to each other | Cross-session messaging | `agents-messaging` |

Pick the model and effort for each agent with `agents-models`.

Done when every part has an approach, an agent count and a model.

## 3. Ask before spinning up

Ask with `AskUserQuestion` before you start any agent. One question with 2 to 4 options:

- Your plan first, marked "(Recommended)": the approach, how many agents, which model each runs, and what each one does.
- A smaller or cheaper plan, when one exists.
- "Do it in this chat, no extra agents".

Say in the question that every extra agent spends its own tokens.

Skip the question when this turn already says how to run the work ("use a workflow", "3 agents", "no agents", "full send", "don't ask"). When the session can't show a question (`claude -p`, or no `AskUserQuestion` tool), run the recommended plan and say so in one line.

Picking a workflow option counts as the user's opt-in to the `Workflow` tool.

Done when the user has picked an option, or their words already picked one.

## 4. Run it

Read the skill for the approach they picked and follow it. Brief each agent as a peer: the goal, the files to read, what is already ruled out, and what done looks like. Give each agent that edits the repo its own worktree. Wait for the results and use them. Work you handed to an agent stays with that agent.

The host's tool rules come first: when the host (for example T3 Code) names the tool for a background agent or an agent on another provider, use that tool.

Done when every agent has reported, their results are merged into one answer, and the user has seen it.
