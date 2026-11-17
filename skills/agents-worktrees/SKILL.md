---
name: agents-worktrees
description: How to isolate parallel Claude Code sessions and subagents in git worktrees, from code.claude.com/docs/en/worktrees. The --worktree flag, EnterWorktree, .worktreeinclude, base branch, cleanup and isolation rules. Use when several agents or sessions edit the same repo, or the user asks for a worktree.
---

# agents-worktrees

A git worktree is a separate folder with its own files and branch that shares the repo's history. Giving each session or subagent its own worktree stops parallel edits from colliding. Source: https://code.claude.com/docs/en/worktrees

## Starting one

```bash
claude --worktree feature-auth   # .claude/worktrees/feature-auth on branch worktree-feature-auth
claude --worktree "#1234"        # branch from PR or MR 1234 (quote the #)
claude --worktree                # Claude picks a name
```

In a session, asking to "work in a worktree" makes Claude call `EnterWorktree`. Entering a path outside `.claude/worktrees/` asks for approval first.

Setup:
- Add `.claude/worktrees/` to `.gitignore`.
- A worktree is a fresh checkout: install dependencies in it.
- List gitignored files to copy into every new worktree in `.worktreeinclude` (gitignore syntax), such as `.env`, `.env.local` or `config/secrets.json`.

## Subagents in worktrees

Ask Claude to "use worktrees for your agents", or add `isolation: worktree` to an agent file's frontmatter. Each gets a temporary worktree, removed when it finishes with no changes. One with changes stays until the periodic sweep can remove it safely.

## Base branch

`worktree.baseRef` in settings: `"fresh"` (default) branches from the remote default branch; `"head"` branches from the current local HEAD, carrying unpushed commits. Use `"head"` when subagents must work on in-progress changes. For a specific existing branch, use `git worktree add` by hand.

## Cleanup

On exit from an interactive worktree session:
- Clean and unnamed: removed with its branch.
- Has changes or new commits: Claude asks to keep or remove. Removing deletes the folder, the branch and the work.
- To return later, run the `claude --worktree <name> --resume` line printed on exit.

`claude -p` runs leave their worktrees in place. Remove them with `git worktree remove` (run `git worktree unlock` first if git says it is locked). Subagent and background worktrees are swept after `cleanupPeriodDays`, but only when they hold no work.

## Isolation rules

While isolated, Claude Code blocks edits to the main checkout, commands run from it, git redirected into it (`git -C`, `--git-dir`, `GIT_DIR`, a `cd` then git), and commands whose git use it can't verify from the text. Plain `cp` or shell redirects into the main checkout are not caught.

## Shared with the main checkout

The `.git` folder, project-scope plugins, "don't ask again" approvals (saved to the main checkout's `.claude/settings.local.json`), and untracked `.claude/skills`, `.claude/agents` and `.claude/commands` when the worktree has none of its own. Hooks keep `${CLAUDE_PROJECT_DIR}` at the main checkout; read the hook input's `cwd` for the worktree path.

## By hand

```bash
git worktree add ../project-feature-a -b feature-a   # new branch
git worktree add ../project-bugfix fix-issue-456      # existing branch
git worktree list
git worktree remove ../project-feature-a
```

For SVN, Perforce or Mercurial, `WorktreeCreate` and `WorktreeRemove` hooks replace the git logic.
