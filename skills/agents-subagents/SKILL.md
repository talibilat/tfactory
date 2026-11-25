---
name: agents-subagents
description: How to use Claude Code subagents, from code.claude.com/docs/en/sub-agents. Built-in types, custom agent files in .claude/agents/, tools, models, worktree isolation, background runs and resuming. Use when handing a side task to a subagent, choosing a subagent type, or writing an agent file.
---

# agents-subagents

A subagent is a helper Claude the main Claude starts inside the session. It has its own context window, prompt, tools and permissions, and only its final summary comes back. Source: https://code.claude.com/docs/en/sub-agents

## When it fits

- A side task would fill the main chat with search results, logs or file contents.
- The work needs limits, such as a reviewer with read-only tools.
- Simple work can run on a cheaper model such as Haiku.

Keep work in the main chat for back-and-forth with the user, phases that share a lot of context, quick targeted changes, and when speed matters.

## Built-in types

| Type | Use for |
|---|---|
| `Explore` | Fast read-only search of the code. Say how deep: quick, medium or very thorough |
| `Plan` | Read-only research in plan mode |
| `general-purpose` | Multi-step jobs that need every tool, including edits |
| `claude-code-guide` | Questions about Claude Code itself (runs on Haiku) |
| `statusline-setup` | Setting up the status line |

## Custom agent files

A Markdown file with YAML frontmatter. The body becomes the system prompt.

```markdown
---
name: code-reviewer
description: Reviews code for quality and best practices. Use after code changes.
tools: Read, Glob, Grep
model: sonnet
---

You are a code reviewer. Give specific, actionable feedback on quality, security and best practices.
```

Where files live, highest priority first: managed settings, the `--agents` JSON flag (one session), `.claude/agents/` (this project, commit it to share), `~/.claude/agents/` (all your projects), a plugin's `agents/` folder. On a name clash the higher one wins.

Frontmatter fields: `name` and `description` are required. Optional: `tools` or `disallowedTools`, `model` (`sonnet`, `opus`, `haiku`, `fable`, a full model ID, or `inherit`), `permissionMode`, `maxTurns`, `skills` (preloaded), `mcpServers`, `hooks`, `memory` (`user`, `project`, `local`), `effort`, `isolation: worktree`, `background`, `omitClaudeMd`, `initialPrompt`. Plugin agents ignore `hooks`, `mcpServers` and `permissionMode`.

Keep each `description` short: past about 15,000 tokens of combined descriptions, Claude Code warns at startup. Put detail in the body, which loads only when the agent runs.

## Starting and steering

- Ask in words ("use the code-reviewer subagent to..."), or @-mention it: `@"code-reviewer (agent)"`.
- Run a whole session as one agent: `claude --agent code-reviewer`, or set `"agent"` in `.claude/settings.json`.
- Block one: `"permissions": {"deny": ["Agent(Explore)"]}`. Limit which agents a coordinator may start: `tools: Agent(worker, researcher), Read, Bash`.
- Model order: the model named on the call, then the file's `model`, then `CLAUDE_CODE_SUBAGENT_MODEL`, then the main model. `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` forces the variable on every subagent.

## What a subagent knows

It starts with only its prompt, your delegation message, the CLAUDE.md files, a git status snapshot and any preloaded skills. It gets no chat history, auto memory or output style, so the brief must carry everything it needs. A forked subagent (`/subtask`) inherits the full conversation instead.

## Limits

- Foreground subagents block the chat. Background ones run alongside it, with a smaller tool set, and their permission prompts appear in the main session.
- Nesting goes 3 levels deep (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`). Up to 20 run at once (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`).
- Resume a finished subagent with `SendMessage` and its ID or name. It keeps its full history.
- Transcripts sit under `~/.claude/projects/{project}/{sessionId}/subagents/` and are removed after 30 days by default.
- Every subagent counts toward the same usage limits as the main chat.
