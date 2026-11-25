---
name: agents-view
description: How to run and watch background Claude Code sessions with agent view (claude agents), from code.claude.com/docs/en/agent-view. Dispatching, session states, attach and peek, shell commands, and defaults. Use when handing off separate jobs to run in the background, or checking on background sessions.
---

# agents-view

Agent view (`claude agents`) is one screen listing every background session by state, so the user sees which ones need them without reading transcripts. Each background session is a full Claude Code conversation that runs with no terminal attached. Research preview. Source: https://code.claude.com/docs/en/agent-view

## When it fits

Several separate jobs that run unwatched, such as a bug fix, a PR review and a flaky-test hunt side by side. The user checks back when a row needs input or has a result. Sessions report only to the user; to pass findings between them, use `agents-messaging`.

## Using it

```bash
claude agents                          # open agent view
claude agents --cwd ~/projects/my-app  # only sessions under one folder
claude --bg "investigate the flaky SettingsChangeDetector test"
claude --bg --name "flaky-test-fix" "..."
claude --agent code-reviewer --bg "address review comments on PR 1234"
claude --resume <session-id> --bg "finish the migration"
claude --bg --exec 'pytest -x'         # a shell command as a background job
```

In the view: type a prompt and press Enter to start a session. `Space` peeks at the latest output and lets you reply. `Enter` or `→` attaches, `←` on an empty prompt detaches. `/bg` inside a session sends it to the background.

Keys: `Ctrl+S` group by folder, `Ctrl+T` pin (keeps the process running), `Ctrl+R` rename, `Ctrl+X` twice stop and delete, `?` all keys.

## States

Working, Needs input, Idle, Completed, Failed, Stopped. Scripts read state with `claude agents --json`, where `state` is `working`, `blocked`, `done`, `failed` or `stopped`. Never parse files under `~/.claude/jobs/`.

## Managing sessions

| Command | Does |
|---|---|
| `claude attach <id or name>` | Attach in this terminal |
| `claude logs <id or name>` | Print recent output |
| `claude stop <id>` | Stop a session |
| `claude respawn <id>` or `--all` | Restart sessions |
| `claude rm <id>` | Remove from the list, transcript kept |
| `claude daemon status` | Check the supervisor process |

## How it behaves

- A supervisor process hosts the sessions, so they survive closing the terminal.
- Idle sessions may stop after about an hour to free memory, and resume on the next attach or reply. Pin with `Ctrl+T` to keep one running.
- Before a session edits files in a git repo, Claude moves it into its own worktree under `.claude/worktrees/`. Turn that off per repo with `{"worktree": {"bgIsolation": "none"}}`. Outside git there is no isolation.
- Background sessions read settings from their working folder. Put gateway settings in a settings file's `env` block so they reach every session.

## Defaults

- Open it by default: `/config defaultToAgentsView=true`.
- Defaults for new sessions: `claude agents --permission-mode plan --model opus --effort high`. Typing `/model`, `/effort` or `/fast` in the view sets them for that window.
- Notifications come through `preferredNotifChannel` and the `Notification` hook (`agent_needs_input`, `agent_completed`).
- Turn it off: `disableAgentView: true` or `CLAUDE_CODE_DISABLE_AGENT_VIEW`.
