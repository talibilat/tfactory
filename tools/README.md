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
| `progress.py` | every pipeline skill | Progress board per ticket |
| `skills.py` | `guide` | Lists every skill installed for each agent |
| `proof.py` | `reproduce`, `ship`, `inspect` | Before and after proof gates |
| `pair.py`, `annotate.py` | `proof` | Builds the annotated before and after pictures |
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
