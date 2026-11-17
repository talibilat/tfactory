---
name: agents-teams
description: How to run Claude Code agent teams, from code.claude.com/docs/en/agent-teams. A lead session with teammates who share a task list and message each other. Enabling, display modes, models, plan approval, hooks and limits. Use when workers must discuss or challenge each other, or the user asks for a team or teammates.
---

# agents-teams

An agent team is one lead session that starts teammates, gives out tasks and merges the results. Teammates are full Claude sessions with their own context. They share a task list and message each other directly, and the user can talk to any of them. Experimental and off by default. Source: https://code.claude.com/docs/en/agent-teams

## When it fits

- Research and review where teammates check and challenge each other's findings.
- A new feature split so each teammate owns separate files.
- Debugging with competing theories, each teammate trying to disprove the others.
- Work across front end, back end and tests, one owner each.

Use a single session or subagents for work that must happen in order, edits to the same file, many dependencies, or routine tasks. Every teammate is a separate Claude, so cost grows with team size.

| | Subagents | Agent team |
|---|---|---|
| Talks to | The caller only | Each other, directly |
| Coordination | The main agent runs everything | Shared task list plus messages |
| Best for | Focused jobs where only the result matters | Work that needs discussion |
| Cost | Lower | Higher |

## Turn it on

```json
{ "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" } }
```

Watch out: while it is on, any subagent Claude gives a name starts as a teammate, so teams can form unasked. Setting the value to `"0"` turns that off at once. Teammates never start in `claude -p` or Agent SDK sessions.

## Running a team

- Describe the team in words: "Spawn three teammates to review PR #142: one on security, one on performance, one on test coverage."
- Name each teammate in the request so later prompts can refer to it.
- Give each teammate the context in its spawn prompt. Teammates load CLAUDE.md, MCP servers and skills, but not the lead's chat.
- Reuse a role: "Spawn a teammate using the security-reviewer agent type". The agent file's `tools` and `model` apply; its `skills` do not.
- Plan first for risky work: put the lead in plan mode, then spawn the teammate. It plans, then builds once the plan is approved.
- Shut one down by name: "Ask the researcher teammate to shut down".

Model order: the model named in the spawn prompt, then the agent file's `model`, then `CLAUDE_CODE_SUBAGENT_MODEL`, then the lead's model.

## Display

- In-process (default, any terminal): the agent panel under the prompt. Up and down select a teammate, Enter opens it, `x` stops it, `Ctrl+T` shows the task list.
- Split panes: set `"teammateMode": "auto"` and run inside tmux or iTerm2 (with the `it2` CLI and the Python API on).

## Quality gates

Hooks that exit with code 2 send feedback and block: `TeammateIdle` keeps a teammate working, `TaskCreated` stops a task being made, `TaskCompleted` stops a task being closed.

## Sizing

Start with 3 to 5 teammates and 5 to 6 tasks each. Each task should end in one clear deliverable, such as a function, a test file or a review. Split files so no two teammates edit the same one; teams don't isolate teammates in worktrees.

## Limits

- `/resume` and `/rewind` don't bring back in-process teammates. Ask the lead to spawn new ones.
- Task status can lag and block dependent tasks; check and nudge.
- One team per session, no nested teams, and the lead can't change.
- Teammates start in the lead's permission mode, and their permission prompts appear in the lead. Pre-approve common commands to cut prompts.
- If the lead starts doing the work itself, say: "Wait for your teammates to complete their tasks before proceeding".
