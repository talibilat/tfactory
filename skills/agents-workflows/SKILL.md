---
name: agents-workflows
description: How to run Claude Code dynamic workflows, from code.claude.com/docs/en/workflows. A script that runs many subagents in the background, with approval, the /workflows view, saving, resuming, limits and cost. Use when a job outgrows a few subagents, needs findings checked against each other, or the user says workflow or ultracode.
---

# agents-workflows

A dynamic workflow is a JavaScript script that runs many subagents. Claude writes it, a runtime runs it in the background, and only the final answer reaches the chat. Source: https://code.claude.com/docs/en/workflows

## When it fits

Jobs too big for one conversation to coordinate, or that need a check across agents: a codebase bug sweep, a 500-file migration, research cross-checked between sources, a plan drafted from several angles.

| | Subagents | Agent teams | Workflows |
|---|---|---|---|
| Who decides what runs next | Claude, turn by turn | The lead, turn by turn | The script |
| Scale | A few per turn | A handful of long-running peers | Dozens to hundreds per run |
| After an interruption | The turn restarts | Teammates keep running | Resumes in the same session |

## Starting one

- The user says "use a workflow" or types `ultracode` in their own prompt. Choosing the workflow option in an `agents-first` question counts too.
- `/deep-research <question>` is the built-in one: it searches from several angles, checks sources and returns a cited report.
- `/effort ultracode` makes Claude plan a workflow for every substantial task in the session. It spends far more tokens. Turn it off with `/effort ultracode off`.

Before writing a script, load the `workflow-authoring` skill. The script shape:

```javascript
export const meta = { name: 'audit-routes', description: 'Audit every route handler for missing auth checks' }
const found = await agent('List every .ts file under src/routes/.', {
  schema: { type: 'object', required: ['files'], properties: { files: { type: 'array', items: { type: 'string' } } } },
})
const audits = await pipeline(found.files, file => agent(`Audit ${file} for missing authentication checks.`, { label: file }))
return audits.filter(Boolean)
```

`agent()` starts one subagent, `pipeline()` one per item, `parallel()` runs tasks at once, `phase()` groups agents in the progress view, `log()` prints a line. `Date.now()`, `Math.random()` and `new Date()` throw; pass timestamps in through `args`. No `import()`, no direct file or shell access: agents do that work.

## Approval

The CLI shows the planned phases with Yes, "don't ask again" (named workflows only), view script, and No. Auto mode asks on the first launch only. Bypass mode, `claude -p` and the Agent SDK show no prompt; allow it there with a `Workflow` permission rule. Before a long run, add the tools agents need to your allow rules.

## Watching and managing

`/workflows` lists runs. Keys: arrows select, Enter drills in, `f` filters by status, `p` pauses or resumes, `x` stops an agent or the run, `r` restarts an agent, `s` saves the script.

Resume a stopped run by asking Claude to relaunch the same script. Completed agents return saved results. The first changed or failed agent and every agent after it run again. In interactive sessions, a run that hits the usage limit pauses and continues after the reset.

## Saving and sharing

Press `s` in `/workflows`. Save to `.claude/workflows/` (shared with everyone who clones the repo) or `~/.claude/workflows/` (only you). It then runs as `/<name>`. A plugin's `workflows/` folder shares it across repos as `/<plugin>:<name>`. Saved workflows take input through the `args` global.

## Limits and cost

- Up to 16 agents at once (`CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS`, 1 to 256), 4,096 items per `parallel()` or `pipeline()`, 1,000 agents per run.
- Try a small slice first, such as one folder, then scale. `/workflows` shows tokens per agent.
- Past 25 agents or 1.5 million projected tokens a "Large workflow" warning appears.
- `workflowSizeGuideline` sets how many agents Claude aims for: `small` under 5, `medium` under 10 (default), `large` under 50, `unrestricted`.
- Name a smaller model for stages that don't need the strongest one (see `agents-models`).
- Turn workflows off with `disableWorkflows: true` or `CLAUDE_CODE_DISABLE_WORKFLOWS=1`.
