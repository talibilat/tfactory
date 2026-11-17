---
name: agents-models
description: Which Claude model and effort level to use for which task or agent, from code.claude.com/docs/en/model-config. Aliases, prices, effort levels, and how to set the model of a subagent, teammate or workflow agent. Use when picking a model for the session or for any agent, or the user asks which model fits a task.
---

# agents-models

Pick the cheapest model and lowest effort that still does the job well, and raise them only for hard parts. Source: https://code.claude.com/docs/en/model-config

## Models

| Alias | Model (Anthropic API) | Use for | Price per million tokens in / out |
|---|---|---|---|
| `haiku` | Haiku 5.5 | Simple, fast jobs: searching files, reading, short summaries, renames | $0.10 / $0.50 |
| `sonnet` | Sonnet 5.5 | Everyday coding | $2 / $10 |
| `opus` | Opus 5.5 | Complex reasoning: tricky bugs, design choices, big changes | $4 / $20 |
| `fable` | Fable 5.2 | The hardest and longest jobs: root causes, outages, architecture decisions | $8 / $40 |
| `opusplan` | Opus, then Sonnet | Opus plans in plan mode, Sonnet builds | Mixed |

Other providers map the aliases to older versions; check `/model`. To pin a version, use the full ID, such as `claude-opus-5-5`.

For `fable`: describe the outcome rather than the steps, hand it unclear problems and large tasks, and skip reminders to verify, since it checks its own work. Requests its safety checks flag, mostly in security and biology, can fall back to another model.

## Effort

| Level | Use for |
|---|---|
| `low` | Quick exchanges you review yourself: brainstorming, a first sketch, a rename |
| `medium` | Clear, scoped work such as a new feature. The default on Opus 5.5, Sonnet 5.5 and Haiku 5.5 |
| `high` | Work where edge cases matter, such as fixing a bug in existing code |
| `xhigh` | Deeper reasoning at higher token spend |
| `max` | Hard problems Claude works through alone, such as hunting security holes. Can overthink; test before using widely |

Set it with `/effort`, `--effort`, `CLAUDE_CODE_EFFORT_LEVEL`, or `effortLevel` in settings.

## Defaults for agents

These are house defaults, not doc rules:

| Agent's job | Model and effort |
|---|---|
| Searching, reading, collecting files or logs | `haiku`, low or medium |
| Building from a clear plan, reviewing code, writing tests | `sonnet`, medium |
| Planning, judging trade-offs, merging other agents' findings | `opus`, high |
| Unclear root cause, architecture, long runs alone | `fable`, high |

## Setting an agent's model

- Subagents and teammates use the main model unless told otherwise. Switching `/model` also moves subagents that inherit it.
- Set `model` and `effort` in the agent file's frontmatter to keep one on a cheaper model.
- Name the model in the request: "Spawn 4 teammates, use Sonnet for each".
- In a workflow script, pass the model on each `agent()` call for the stages that need less.
- `CLAUDE_CODE_SUBAGENT_MODEL` sets a model for all subagents; add `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` to override agent files too.
