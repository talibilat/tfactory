# Flow gate

`tools/flow.py` answers one question: can this exact change start inspection? If not, it names the repo, the check and what would unblock it.

It decides from git and from result files. It never reads the progress board, so a board that says "done" changes nothing. `next` and `status` only read. They write no file and take no git lock. They ask origin for its default branch with `git ls-remote`, which also writes nothing.

## Commands

```sh
python3 -I ~/.agents/tools/flow.py next   <KEY> [--dir .scratch] [--root PATH]
python3 -I ~/.agents/tools/flow.py status <KEY> [--dir .scratch] [--root PATH]
python3 -I ~/.agents/tools/flow.py record <KEY> <repo-path> <check> <outcome> [--count NAME=N ...] [--note TEXT] [--dir .scratch]
```

- `next` prints the decision on the first line, then one `BLOCKED` line per missing item. Each line names the repo, the check and the fix. An indented line under a check gives the `flow_approval.py new` command for a user waiver. After them come the lines that do not block:
  - `WAIVED` for each check the user waived.
  - `SKIPPED` for each repo with no changes, each folder in the task folder that is not checked, and each waiver file that cannot be read. Each line says why.
  - `WARNING` for each repo whose base branch could not be confirmed with origin.
- When anything is blocked and `/etc/tstack/allowed_signers` does not exist, the last line is `Waivers are not set up on this machine. See tools/flow-approval.md. Blocked gates cannot be waived until then.`
- `status` prints the same, plus every repo and every check with its counts.
- `record` saves one result for the repo's current commit. The skill calls it right after crapper, mutator or the baseline tests finish.

| Exit code | `next` and `status` | `record` |
|---|---|---|
| 0 | Inspection may start | The result file was written |
| 1 | Blocked | Refused: not a git repo, no base branch, uncommitted changes, or files hidden from `git status` |
| 2 | Bad usage, such as a bad key or a missing `--dir` folder | Bad usage, or counts that do not fit the outcome |

The same repos, commits, origin branches, result files and waivers always give the same text. The only clock input is waiver expiry (see below).

## Which repos it checks

The repos are the worktrees in the task folder, `<root>/worktrees/<KEY>/<short>`. `--root` defaults to the folder that holds `--dir`.

Every other folder in the task folder is skipped, and `next` prints a `SKIPPED` line for it:

- A folder that is not a git worktree.
- A slice worktree. `worktree.sh slice` names it `_<short>-<slice>` and puts it on the branch `<task branch>--<slice>`. `flow.py` treats a folder as a slice only when the repo folder `<short>` exists, shares its git repo with it, and the branch name matches.
- The evidence worktree that `ship` close out makes for the proof images, `_evidence-<short>` on the branch `evidence/<KEY>`. `flow.py` treats a folder as one only when its branch starts with `evidence/` and it has no commit yet or its history shares no commit with the base branch, as an orphan branch does. A repo renamed to `_evidence-<short>` still shares history with its base, so it is checked as the next line says.
- Any other git worktree whose name starts with `_` or `.`. This one is blocked instead of skipped when it holds commits that are neither on its base branch nor on any repo folder's `HEAD`. A repo folder renamed to `_be` or `.be` cannot hide its work that way.

For each repo:

- The base branch is `origin/HEAD`, else `origin/dev`, else `origin/main`. This is the same order `worktree.sh` uses. The base commit is the merge base of that branch and `HEAD`. `flow.py` does not fetch, so it uses the remote branches as they were last fetched.
- The base branch is checked against origin with `git ls-remote`, because the clone's copy can be moved by hand, for example with `git update-ref refs/remotes/origin/main HEAD`. A moved copy swallows the task's commits, so the repo looks unchanged. The repo is blocked when:
  - `origin/HEAD` in the clone points to a branch that is not origin's default branch.
  - origin has no branch of that name.
  - origin's branch is at a commit this clone has not fetched. The fix is `git fetch origin`. When the base did not change, the results recorded before the fetch still count.
  - the base commit is not on origin's branch. That means the clone's copy holds commits origin does not have.
- When origin cannot be reached, `next` prints a `WARNING` line and uses the branch as last fetched.
- A repo with no committed changes against its base and no uncommitted files is "no changes" and is not checked. `next` prints a `SKIPPED` line for it.
- A repo with uncommitted files is blocked until they are committed. Results describe a commit, so they cannot vouch for files that are not in it. Files under `.metrics/` do not count, because crapper and mutator write there. A staged rename or copy counts unless both its paths are under `.metrics/`.
- A repo with files marked `git update-index --skip-worktree` or `--assume-unchanged` is blocked, because `git status` does not show changes to them. `git ls-files -v` shows these files with the tag `S` or a lowercase tag. In a sparse checkout, git marks the files it left out as skip-worktree. Those count only when the file is on disk.
- When no repo has changes, inspection is blocked: there is nothing to inspect.

`flow.py` runs git with every `GIT_*` environment variable removed except `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_NOSYSTEM`. So `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` and `GIT_CONFIG_PARAMETERS` cannot point a check at another repo or index. It also passes `-c core.fsmonitor=false`, so `git status` runs no fsmonitor hook.

## The three checks

Each changed repo needs all three on its current `HEAD`.

| Check | What it is | Counts it must report | When `passed` is accepted |
|---|---|---|---|
| `baseline` | The baseline commands from blueprint step 4, run again (ship step 3) | `tests`, `failed`, `new_failures` | `tests` at least 1 and `new_failures` 0 |
| `crap` | Gate 1, `quality crapper --changed --base origin/<default> --threshold 6` | `functions`, `scored`, `over_threshold`, `threshold` | `functions` at least 1, every function `scored`, `over_threshold` 0, `threshold` from 1 to 6 |
| `mutation` | Gate 2, `quality mutator --changed --base origin/<default>` | `sites`, `killed`, `survived`, `uncovered` | at least 1 mutant run (`killed` + `survived`), `survived` 0 and `uncovered` 0 |

The counts must also add up: `new_failures <= failed <= tests`, `over_threshold <= scored <= functions`, and `killed + survived + uncovered <= sites`. `record` refuses counts that break these rules. `next` marks a hand-written file that breaks them as `invalid`. Extra counts, such as `timed_out=2`, are kept and shown.

This means a tool exit code of 0 is not enough on its own:

- crapper prints `No source files to analyze.` and exits 0 when nothing it supports changed. With 0 functions scored, `crap` cannot pass. Record it as `blocked` with a note that says why.
- crapper with `--no-coverage` prints `N/A` for coverage and CRAP. Those rows count in `functions` but not in `scored`, so `crap` cannot pass on complexity alone. Record it as `blocked` with a note that says why.
- mutator prints `No source files to mutate.` and exits 0 when nothing changed that it can mutate. With 0 mutants run, `mutation` cannot pass. Record it as `blocked` with a note that says why.
- mutator exits 0 when sites are `uncovered`, because it does not run a mutant on a line no test runs. An uncovered site is an untested changed line, so `mutation` cannot pass while `uncovered` is above 0. Record it as `failed` with the real counts. `next` then names the number of untested sites. Add tests that run those lines, or ask the user for a waiver.

Ask the user for a waiver if the change should go ahead without the check.

### Reading the counts from the tools

| Tool output | Counts | Outcome |
|---|---|---|
| crapper report rows | `functions` is the number of rows. `scored` is the rows with a number in the CRAP column, not `N/A`. `over_threshold` is the rows above the threshold. `threshold` is the `--threshold` value | exit 0 and the rules above: `passed`. Exit 2 with `CRAP threshold exceeded` on stderr: `failed`. Any other non-zero exit, such as a git error: `blocked`, with the message as the note |
| mutator `Total` row | `killed`, `survived`, `uncovered` and `sites` from that row | exit 0 and the rules above: `passed`. Exit 0 with `uncovered` above 0: `failed`. Exit 3: `failed`. Exit 2 when the baseline tests fail: record `mutation` as `blocked` with that message, and `baseline` as `failed`. Any other non-zero exit, such as missing crapper or a git error: `blocked`, with the message as the note |
| baseline test commands | `tests` run, `failed`, and `new_failures` that the blueprint baseline did not have | no new failures: `passed`. Any new failure: `failed` |

A check that could not run at all, such as a missing runner or a crash, is `blocked`. A `blocked` result needs `--note` and takes no counts. `record` refuses a `blocked` result with counts, and `next` marks such a file as `invalid`.

## Statuses

| Status | Meaning |
|---|---|
| `passed` | The newest result for this repo, check and `HEAD` says passed, and its counts support it |
| `failed` | The newest result for this `HEAD` says failed |
| `blocked` | The newest result for this `HEAD` says the check could not run |
| `missing` | No result for this repo and check at all |
| `stale` | Results exist, but none for the current `HEAD`. A new commit makes every earlier result stale |
| `invalid` | The newest result for this `HEAD` cannot be read, has the wrong fields, names another key, repo, check or base, or its counts do not support its outcome |
| `not applicable` | The docs-only rule applies |
| `waived by user` | One of the statuses above, except `passed`, with a valid user waiver. The output keeps the original status, for example `waived by user: was failed` |

Only `passed`, `not applicable` and `waived by user` let inspection start.

### Docs-only rule v2

When every file changed in a repo ends in `.adoc`, `.md` or `.rst`, `crap` and `mutation` are `not applicable`. `baseline` is still required. Any other file, including `.mdx`, `.txt`, `.sql`, `.json` or a deleted source file, means the repo needs all three. The rule is a constant in `flow.py` and the output names it.

Version 1 also counted `.mdx` as docs. Version 2 does not. An MDX file holds JSX and `import` lines, and a front-end build compiles it and runs it as code, so a change to one can break the app like any other source file.

Unsupported code is not exempt. A change in a language crapper does not score still needs a passing result or a waiver.

## Result file format

`record` writes one JSON file per result:

```
<dir>/<KEY>-evidence/results/<repo>/<check>/<head>-<n>.json
```

`<repo>` is the worktree folder name (`fe`, `be`). `<head>` is the full commit id. `<n>` counts from 1 for each commit. `record` never overwrites a file, so the history of retries stays. `next` reads only the file with the highest `<n>` for the current `HEAD`. Other names in the folder are ignored, and so is any Markdown evidence.

```json
{
  "base": "95da1c3c6618a2a95f5dbadebcd44418c175c0da",
  "base_ref": "origin/main",
  "check": "mutation",
  "counts": {"killed": 8, "sites": 10, "survived": 2, "uncovered": 0},
  "format": "tstack-flow-result/v1",
  "head": "37d1606e34fff5461c3853f329aa1629fa193a8c",
  "key": "ARPP-1234",
  "note": "",
  "outcome": "failed",
  "recorded_at": "2026-11-26T09:53:13Z",
  "repo": "be"
}
```

| Field | Value |
|---|---|
| `format` | Always `tstack-flow-result/v1` |
| `key`, `repo`, `check` | Must match the path and the question asked |
| `base_ref`, `base` | The base branch and the full merge-base commit id. `next` rejects a result whose `base` differs from the repo's base now, so a result cannot shrink the diff it covers |
| `head` | The full commit id of `HEAD` when `record` ran. Must match the file name |
| `outcome` | `passed`, `failed` or `blocked`. `record` never writes `waived` or `not applicable` |
| `counts` | Whole numbers of 0 or more, with `lower_snake_case` names. Floats are refused |
| `note` | Free text. Required for `blocked` |
| `recorded_at` | UTC time, for people. `next` uses it only to name the newest stale result |

`record` always binds the result to the repo's current `HEAD` and the base `next` uses. It refuses when the worktree has uncommitted files or files marked skip-worktree or assume-unchanged. Run it straight after the tool, before any new commit.

`next` reads at most 64 KiB of a result or waiver file, refuses floats, and treats a file whose lists and objects nest more than 32 levels deep as unreadable.

Example, after mutator printed a `Total` row of 8 killed, 2 survived, 0 uncovered, 10 sites and exited 3:

```sh
python3 -I ~/.agents/tools/flow.py record ARPP-1234 <root>/worktrees/ARPP-1234/be mutation failed \
  --count sites=10 --count killed=8 --count survived=2 --count uncovered=0
```

## Waivers

Only the user can waive a check. A waiver is a `tools/flow_approval.py` request that the user signed. `next` accepts it only when `flow_approval.verify` returns `True` and the request names:

| Request field | Value |
|---|---|
| `key` | The task key |
| `stage` | `waive-<check>`, for example `waive-mutation` |
| `context` | `repo=<repo> head=<full commit id>`, for example `repo=be head=37d1606e...` |

The `BLOCKED` line for each item prints the exact `flow_approval.py new` command. Save its output as `<dir>/<KEY>-evidence/waivers/<name>.json`. The user signs the payload as `tools/flow-approval.md` describes. Save the signature beside the request as `<name>.sig`, with the same `<name>`.

Waivers work only after the one-time setup in `tools/flow-approval.md` puts `/etc/tstack/allowed_signers` in place. Until then, `next` and `status` end any blocked report with a line that says waivers are not set up on this machine.

A `.json` file in the waivers folder that cannot be read, such as broken or deeply nested JSON, is left out with a `SKIPPED waiver` line. It does not stop the other waivers from counting.

These never count as a waiver:

- a note such as `SKIPPED-BY-USER.txt`, a line in `<KEY>-reviews.md`, or any other file an agent can write
- a request with no `.sig`, a bad signature, or a signature from a key not in `/etc/tstack/allowed_signers`
- a signed request for another key, another check, another repo or another commit. A new commit needs a new waiver
- an expired request

A waiver never covers uncommitted files or a git error, and it never turns into `passed`. The output shows `waived by user`, the original status, the reason the user signed and the request file. The first line says `ready for inspection with N waiver(s)`.

`flow_approval.verify` rejects a request after its expiry time, which is at most one hour after it was made. So a waiver counts only while it is live. Run `next` inside that hour. After it, the check shows as blocked again and needs a fresh request.

## What this does not protect against

- Result files are written by the agent, so they are only as honest as the agent that wrote the counts. `flow.py` checks that the counts are complete, consistent and bound to the right commit and base. It does not rerun crapper, mutator or the tests. Only waivers are protected by a key the agent cannot read.
- An agent that can edit `flow.py`, or skip calling it, can skip the check. The audit's second step moves enforcement into code the agent cannot change.
- `flow.py` does not fetch. When origin has moved on, `next` asks for a fetch instead of guessing.
- When origin cannot be reached, the base is not confirmed. The `WARNING` line says so, and a base branch moved by hand is not caught.
- The origin check trusts the repo's `origin` URL and the user's git config. An agent that points `origin` at a copy it controls can fake the answer.
- A folder whose name starts with `_` or `.` is checked for commits against its own base branch as last fetched. That base is not confirmed with origin.
- A slice worktree is never checked. Commits in a slice that `worktree.sh slice-done` has not merged into the repo folder are not part of the gate.
- Files that git ignores are not uncommitted changes. A test run can still read them.
- A repo whose real base is not `origin/HEAD`, `origin/dev` or `origin/main` is checked against the wrong base. `record` and `next` use the same rule, so they agree, but the diff may be wider than intended.
- Old task folders at `<root>/<repo>-worktrees/<KEY>` are not found. Move them into the task folder first, as the conventions file says.
- A dirty worktree check excludes only `.metrics/` at the repo root. Any other file the tools leave behind blocks the gate until it is committed, removed or ignored.

## Tests

```sh
python3 tools/tests/test_flow.py
```

The tests build disposable git repos with a bare `origin` under a temporary folder, so `git ls-remote` needs no network. They set `GIT_CONFIG_GLOBAL` to `/dev/null`, so the user's git settings do not change the result. Waiver tests sign with real `ssh-keygen` keys and point `flow_approval` at a temporary trust file inside the test process only, the same way `tools/tests/test_flow_approval.py` does.
