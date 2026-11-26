# Tools

Every command-line tool the skills run lives here. `make install` links this folder to `~/.agents/tools`, so skills call `~/.agents/tools/<tool>` on any machine. It also puts `crapper`, `mutator`, `harden` and `lane` in `~/.local/bin`.

| Tool | Used by | What it does |
|---|---|---|
| `crapper/` | `ship` Gate 1 | CRAP score per function: complexity x missing test coverage |
| `mutator/` | `ship` Gate 2, `hardening` | Mutation testing: changes one operator at a time and checks the tests fail |
| `quality` | `ship` | Runs crapper or mutator with the checkout's `.venv`: `quality crapper ...`, `quality mutator ...` |
| `harden` | `hardening` | `harden <base-ref>` runs mutator on everything changed since the base |
| `lane/` | `lane`, `reproduce`, `inspect`, `ship`, `proof` | Private app copy per agent. `lane compose` for any Docker Compose project, plain `lane` for Aruva. Also holds the browser scripts, flows and `sync-dev.sh` |
| `todo.py` | every skill | Temporary to-do list for one skill run |
| `progress.py` | every pipeline skill | Progress board per ticket, with a row per stage including the `crap` and `mutation` gates. Locks the board, so parallel agents can update it. Tests: `python3 tools/tests/test_progress.py` |
| `flow.py` | `ship`, `inspect` | `record` saves a baseline, crapper or mutator result for a repo's commit. `next <KEY> --root <root>` reads them and exits 0 only when inspection may start. It lists the `_evidence-<short>` worktree from ship's close out without blocking. See `flow-gate.md`. Tests: `python3 -B tools/tests/test_flow.py` |
| `flow_approval.py` | the user | Checks a waiver the user signed. An agent can ask for one with `python3 -I ~/.agents/tools/flow_approval.py new ...`, never grant one. Needs a one-time sudo setup of `/etc/tstack/allowed_signers` (see Install in the top README). See `flow-approval.md` |
| `skills.py` | `guide` | Lists every skill installed for each agent |
| `proof.py` | `reproduce`, `ship`, `inspect` | Before and after proof gates. Each gate also fails a shot that proves nothing (generic purpose, a name that is not `NN-<words>.png`, the same picture as another step) or cannot be opened, and prints a table of what changed between shots. A crop under 600x300 passes only with `pair.py item --allow-small` and a purpose that says crop or zoom. Tests: `python3 -B tools/tests/test_proof_meaningful.py` |
| `pair.py`, `annotate.py` | `proof` | Builds the annotated before and after pictures. `check` and `shots` run the "every shot must prove something" checks, both on the after set unless `--stage before`. Only an `item --allow-*` reason of three or more words lets a shot through. Run `init` again after renaming a shot: it keeps each step's purpose, marks and verdict |
| `grounded.py` | `blueprint` | Fails a plan decision that has no Jira source |
| `worktree.sh` | `blueprint`, `ship` | Task and slice worktrees |
| `jira-attach.py` | `babysit`, Jira updates in the conventions file | Uploads screenshots to a Jira ticket |
| `pr-status.py` | `babysit` | PR checks and review state |
| `spec-check.py` | `deep-spec` | Checks a rewritten spec against its sources |

## crapper and mutator

These are snapshots of public forks of Uncle Bob Martin's tools, with their upstream licenses and tests. Each fork adds `--base`, so the gates check commits as well as local edits. The files here match these fork commits. To update one, change the fork, then copy its `src/` here.

| Tool | Source commit |
| --- | --- |
| crapper | [talibilat/crapper at db7918f](https://github.com/talibilat/crapper/tree/db7918fc981bd818794ece51703eeb59abf62d00) |
| mutator | [talibilat/mutator at 36a4dd4](https://github.com/talibilat/mutator/tree/36a4dd44feb4fae125605fdb708bff889a79a8d9) |
