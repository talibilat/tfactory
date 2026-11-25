---
name: lane
description: Starts a separate app copy per agent for live tests, screenshots and logs. Use lane compose for any Docker Compose project, or the Aruva profile for its shared services, fixtures and memory limits. Use when the user asks for a lane or another skill needs a private test environment.
---

Be strict and vigilant. Do only what this skill says, in its order, and never step outside the system (see System rules in the conventions file).

# lane

For projects other than Aruva, follow [Compose lanes](references/compose.md). Start with `lane compose up <name>` from the worktree. Save proof where the calling skill expects it and run `lane compose down <name>` when done. The rest of this skill applies only to Aruva.

A **lane** is one agent's private Aruva: its own database, Redis, Qdrant, Neo4j, backend, AI service and frontend, on its own ports. The heavy stateless services (document parser, content extractor, PII masking) are shared from the always-on base stack. Many agents can hold a lane at once without touching each other's data, ports or containers.

`lane shot` and the flows open real Google Chrome with a visible window. Set `HEADLESS=1` only when there is no other option, and write the reason on the `Method:` line of the repro file.

Everything goes through one command, `lane`, in the shared tools folder. Below, `lane` means `~/.agents/tools/lane/lane`.

**Memory comes first.** This Mac has 48 GB of RAM, shared by Docker, T3 Code, Chrome and every agent's lint and test runs. Once Docker took 32 GB and every app froze. The rules in "Memory rules" below stop that. They are not optional, and `lane` enforces most of them.

The pipeline uses a lane three times. Each use follows the steps below:

| Called by | Lane is built from | Proof goes to |
|---|---|---|
| `reproduce` (before proof) | The worktrees at the current default branch, before any fix | `.scratch/<KEY>-evidence/before/` |
| `inspect` (live run) | The worktrees at the commit under review | `.scratch/<KEY>-evidence/` and `after/` |
| `ship` step 5 (after proof) | The worktrees at the final commit | `.scratch/<KEY>-evidence/after/`, same file names as `before/` |

Take before and after the same way: follow `.scratch/<KEY>-repro.md` step by step, with the same account and data.

## To-do list

Before the first step, make a temporary to-do list from this skill's steps:

```
python3 -I ~/.agents/tools/todo.py new lane --key <KEY> --from ~/.agents/skills/lane/SKILL.md
```

Leave out `--key` when the task has no key. Tick each item when its Done condition is met, with evidence: `todo.py tick lane --key <KEY> N --note "<proof>"`. Mark a stuck item with `todo.py block`. Add a step you find later with `todo.py add`. Show the list with every update. The list deletes itself when the last item is ticked. See "To-do lists" in the conventions file.

## Steps

1. **Check.** Run `lane doctor`. Every line must say `ok` (an `info` line about the shared network is fine). On a `FAIL`, follow `references/setup.md` and stop if you cannot fix it. Tell the user about a `WARN` on Docker's memory limit in plain words ("Docker may take more than 20 GB of your Mac's memory; please lower it in Docker Desktop, Settings, Resources"). Do not change Docker Desktop's settings yourself, because that restarts every running stack. Run `lane mem` to see Docker, the Mac, the caps and who is waiting.
   Done when doctor prints no `FAIL`, and any `WARN` has been shown to the user.

2. **Sync, then claim a lane.** First run `~/.agents/tools/lane/sync-dev.sh <worktree> ...` for every worktree, so the lane is never behind dev. If it reports a dirty worktree or a conflict, stop and ask. Then pass the worktree of every repo your change touches, from the task folder (`<root>/worktrees/<KEY>/be`, `.../ai`, `.../fe`).

   ```
   lane up <TICKET-KEY> --be <uok-be worktree> --ai <uok-ai worktree> --fe <uok-fe worktree> --owner "<agent or chat name>"
   ```

   It prints the lane number `N` and the URLs. Measured: about 1 minute with no builds; 14 minutes for a first backend plus frontend build; under 1 minute when Docker's build cache already holds those layers.

   **The queue.** When Docker has under 4 GB free, the Mac has under 20% memory free, or all 3 lanes are taken, `lane up` joins a first-come queue. It prints your place and the reason every minute, removes lanes nobody has used for 2 hours, and starts when you are first and memory allows. Builds also run one at a time. Wait for it. Do not pass `--force`, do not start a second `lane up` for the same job, and do not stop another chat's lane. After 90 minutes it stops with an error: tell the user and stop. `lane queue` shows who is waiting.

   **Closing on failure.** If the lane does not start or you press Ctrl-C, `lane up` closes the half-built lane itself and keeps the log at `<LANES_HOME>/logs/lane-N.up.log`.

   **Prefer `lane run`** for a scripted test: `lane run <KEY> --be <dir> --owner "<chat>" -- <command>` starts the lane, runs the command with `LANE_N` set and always closes the lane afterwards, even when the command fails or is stopped.

   Leave out `--be`, `--ai` and `--fe` for any repo the change does not touch. Those repos run the base dev image, which skips a build and its memory spike. Check a new compose file or the memory caps without starting anything with `lane up <KEY> --dry-run`.
   Done when it prints `lane N is up` and the URL block.

3. **Test it live** on the commit you will ship. Use every mode that fits the change:

   | Change | How | Proof |
   |---|---|---|
   | Visible in the UI | `lane shot N <path> <file.png> --as <email>` for one page. For a journey, write a script with `~/.agents/tools/lane/browser.mjs` (`openLane`, `goto`) or run a ready flow: `lane flow N foundation --pdf <file>` | Numbered screenshots |
   | API | `TOKEN=$(lane login N <email>)` then `curl -H "authorization: Bearer $TOKEN" <api url>/...` | Request, status and body saved as `.txt` |
   | Worker, data or logs | `lane logs N api`, `lane exec N exec -T postgres psql -U postgres -d uok -c '...'` | The output saved as `.txt` |

   Flows: `foundation` (course, Course Foundation, upload, extraction, review, validate, approve, create the Smart Syllabus) is verified end to end. `generate` (upload a book asset to that syllabus, parse, Full AI Gen, publish) is verified up to the parse; generation needs a valid Gemini key, see troubleshooting.

   A flow writes `steps.log` and numbered screenshots. A `FINDING` line is a real product result on that PDF (for example a blocking validation issue), not a tool failure: report it. The flow waives a blocking issue once and stops if validation still blocks, because rejecting candidates needs a person. Resume a run with `--course <id> --from <step>`.

   Accounts and seeded courses are in `references/accounts.md`. After you change code, or after `sync-dev.sh` moves a worktree, run `lane rebuild N be|ai|fe` and test again.
   Done when every step of the ticket's live test has a result and a proof file.

4. **Save proof** into the task's evidence folder, in the subfolder the table above names. UI screenshots are the proof for anything that shows in the UI. Save the logs for the same action beside them: `lane logs N api > <folder>/NN-api-log.txt`, and the same for the AI service when it is involved. `lane proof N <label>` gives a folder inside the lane for scratch space. Strip tokens, secrets and personal data from text proof.
   Done when the evidence folder holds every proof file the repro steps and the live test name, and the logs for each.

5. **Give the lane back, every time.** Close every browser window and tab you opened. Run `lane down N` as soon as testing ends, also after a failure, a block or a stop. It deletes the lane's containers, data, volumes and built images, and copies anything under the lane's `proof/` folder to `<LANES_HOME>/proofs/`. When the last lane closes it also removes unused image layers and build cache older than 7 days. `lane down --owner "<your owner text>"` closes every lane you opened.
   Done when `lane ls` no longer shows lane N, and `lane queue` shows nothing of yours.

   Close the lane without waiting to be asked when: the after proof is saved and the proof gate passes, the PR is opened (babysit never needs the lane, and a fix that needs a retest gets a fresh `lane up`), the ticket is blocked or snoozed, the chat ends, or a test run fails and you stop. Before you end your turn, run `lane ls` and confirm none of your lanes is left. Never close a lane another chat owns, even if it looks idle.

## Rules

- Lanes are cheap to rebuild and expensive to leave running (8 containers each, about 1.9 GB while idle). An idle lane is a bug: close it.
- Work only in your own lane. Never run `docker compose` against the base stack (`qa-dev`) or another lane, and never edit the base stack's files.
- Keep the lane while you test and give it back as soon as you finish. Commands that use a lane reset its stale timer. `lane sweep` (dry run) and `lane sweep --yes` remove lanes untouched for `STALE_HOURS`.
- A lane's data starts from the e2e seed every time. Create what your test needs inside the lane.
- The live test result is valid only for the commit you built. Rebuild and retest after every code change.
- Lanes share some real outside services with dev: uploads land in the dev cloud storage bucket, AI calls use real model keys and cost money, and mail can really send. Use fixture accounts only and keep AI-heavy flows small (the small handbook PDFs).

## Memory rules

1. **One lane per agent, and only when the ticket needs a live run.** A change with no visible or API effect is proven by unit tests and needs no lane.
2. **Wait in the queue.** Never use `--force`, never start two lanes for one job, never raise `MAX_LANES` or lower `MIN_FREE_MIB` to get past a wait.
3. **Never run a heavy job beside a lane build, or beside another heavy job.** Run lint, type checks, test suites and builds on the Mac as `lane heavy -- <command>`. It queues them one at a time, waits until the Mac has 25% memory free and caps Node's memory at 3 GB. For example: `lane heavy --label ARPP-4268 -- npm run lint:ci`. Lint only the files you changed when the tool allows it. A whole-repo `eslint` run took 5.9 GB per process, twice at once, in the incident that started this.
4. **The caps are the limit.** Every container in a lane has a memory cap (backend 2 GB, AI service 1.5 GB, frontend 1 GB, Neo4j 1 GB, Postgres and Qdrant 512 MB, Redis 128 MB). If a container is killed (`docker ps -a` shows exit code 137), do not raise the cap. Report it with the service name and what you were doing.
5. **Close at once.** Close the lane the moment the last test result and proof file are saved. Then run `lane ls` and `lane queue` and confirm nothing of yours is left. This holds on success, failure, block and stop.
6. **Docker's size is the user's decision.** If `lane doctor` warns, tell the user. Never edit Docker Desktop's settings or restart Docker.

## Test books

For a test book or document, use the files in `~/Documents/Projects/ARUVA/Data` (Nokia, Telecom, Maths, Chemistry, Psychologu, Biology.pdf, AI-Security). Pick the smallest one that works. Biology.pdf is 136 MB, so avoid it.

When the ticket attaches the book that shows the bug, download that book from Jira and test with it. Keep the download in the scratchpad, never in a repo.

- Use them for testing only. Never attach them to a real course, ticket, PR or Jira comment.
- Check the lane first. If the book or course already exists there, or the upload would create a duplicate, use a different book or create a new course. Never reuse or overwrite the existing one.
- Local Gemini embeddings use the Vertex AI JSON key whose path is in `blueprint/references/setup.md`. Local only. Never commit it or paste its contents.

## The annotated pair

The `proof` skill builds the before and after pictures (see `proof` for the tool and prompts). `reproduce` calls it in `before` mode (left half only). `ship` and `inspect` call it in `after` mode.

## Proof gate, no exceptions

No PR, no Jira comment, no Jira attachment and no ticket move until the before and after screenshots exist, are real, and show the fix. "Real" means:

1. Every step has a `before/` and an `after/` screenshot of the live app (UI whenever the bug shows in the UI). Logs, transcripts and text are extra, never a replacement.
2. `proof.py gate before` and `gate after` both print PASS. The gate fully decodes each image, rejects blank, tiny or corrupt files and files that are not PNG, JPEG or WebP.
3. Open every image yourself (Read it) and check it shows the right screen, the bug on the before side, and the fixed behavior on the after side. A page that only shows a login, an error page, a blank screen or the wrong course is not proof. Retake it.
4. After you upload to GitHub or Jira, download or open the uploaded image and check it renders. A broken image link or a corrupted upload counts as not published. Fix it, then re-check.
5. If you cannot produce the screenshots (lane will not start, key invalid, blocked), stop and tell the user why. Do not open the PR or comment on Jira without them. Only the user can waive this, by saying "skip proof" in the call.

## When something breaks

`~/.agents/tools/lane/isolation-check.sh` proves that no lane can reach another lane's services. Run it if you suspect cross-talk. `lane repair N` re-attaches the shared services after the base stack was recreated. `references/troubleshooting.md` lists the failures seen while building this skill and the fix for each. Read it before you change `lane` itself.
