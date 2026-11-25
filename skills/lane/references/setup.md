# lane setup

One-time setup per machine. `lane doctor` checks every item below.

## 1. Tools

Docker Desktop with Compose v2.20 or newer (the `include` key with `env_file`), `jq`, `python3`, `node` 18 or newer, and Google Chrome. Then install the browser driver into the skill's own folder, outside every repo:

```
npm --prefix ~/.agents/skills/lane/scripts install
```

This installs `playwright-core` only. It drives your existing Chrome, so no browser download.

## 2. The base stack

Lanes borrow stateless services from one always-on stack built from `origin/dev`. On the author's machine it is the compose project `qa-dev` in `ARUVA/qa-stack` (its README explains how it was built). Any base works if it has:

- a running compose project with the services `doc-parser-lb`, `content-extractor-lb`, `presidio-analyzer`, `presidio-anonymizer` and `presidio-image-redactor`;
- a folder with dev checkouts `uok-be`, `uok-ai`, `uok-fe`, each with a working `.env` (lanes read these `.env` files and never copy them into worktrees). `uok-be/.env` must hold the same `DOC_PARSER_INTERNAL_TOKEN` and `CONTENT_EXTRACTOR_INTERNAL_TOKEN` the base's parser and extractor use;
- built images for the backend, AI service and frontend, used by any lane that does not build that repo.

`lane up` attaches those five shared services to the Docker network `aruva-lanes-shared` with the aliases `shared-<service>`. This adds a network to running containers without restarting them. If the base stack is recreated, the next `lane up` attaches them again.

## 3. Config

Create `~/.config/ttl/aruva.env` (or point `TTL_CONFIG` at another file). It is machine-specific and never committed:

```
LANES_HOME=/path/to/ARUVA/lanes          # lane folders, logs and proofs
BASE_PROJECT=qa-dev                       # compose project of the base stack
BASE_DIR=/path/to/ARUVA/qa-stack          # holds uok-be, uok-ai, uok-fe checkouts with .env
BE_BASE_IMAGE=qa-dev-uok-be:local
AI_BASE_IMAGE=qa-dev-ai-backend:latest
FE_BASE_IMAGE=qa-dev-frontend:latest
PORT_BASE=20000                           # lane N uses PORT_BASE + N*100 + offset
MAX_LANES=3                               # more lanes than this wait in the queue
MIN_FREE_MIB=4096                         # lane up queues below this much free Docker memory
STALE_HOURS=2                             # lane sweep removes lanes idle longer than this
# Optional. Defaults shown.
# BUILD_MIN_FREE_MIB=6000                 # a build waits for this much free Docker memory
# MIN_MEM_LEVEL_PCT=20                    # lane up queues when the Mac has less memory free than this
# HEAVY_MIN_MEM_LEVEL_PCT=25              # lane heavy waits below this
# HEAVY_HEAP_MIB=3072                     # Node heap cap for lane heavy
# QUEUE_WAIT_MIN=90                       # give up waiting in a queue after this long
# DOCKER_VM_MAX_MIB=20480                 # lane doctor warns when Docker's VM is bigger than this
# LANE_MEM_API=2g LANE_MEM_AI=1536m LANE_MEM_FE=1g LANE_MEM_NEO4J=1g   # per-container caps
```

## 4. Install the skill

The skill lives in the skills repo, linked into each agent's folder:

```
ln -s <skills repo>/skills/lane ~/.agents/skills/lane
ln -s ~/.agents/skills/lane ~/.claude/skills/lane
ln -s ~/.agents/skills/lane ~/.codex/skills/lane
ln -s ~/.agents/skills/lane ~/.cursor/skills/lane
```

## Ports and memory

Lane N uses these host ports, all bound to 127.0.0.1:

| Service | Port | Lane 1 |
|---|---|---|
| Frontend | base + 0 | 20100 |
| AI service | base + 10 | 20110 |
| Postgres | base + 32 | 20132 |
| Qdrant HTTP, gRPC | base + 33, + 34 | 20133, 20134 |
| Neo4j HTTP | base + 74 | 20174 |
| Backend API | base + 80 | 20180 |
| Neo4j bolt | base + 87 | 20187 |

where base is `PORT_BASE + N*100`.

A lane uses about 2 GB of Docker memory while idle (backend in single-process mode about 400 MB, AI service 500 to 800 MB, Neo4j 600 MB, the rest small), measured on lane 1. Each container has a hard cap, so one runaway service cannot take all of Docker's memory.

Docker Desktop's memory limit should stay at or below `DOCKER_VM_MAX_MIB` (20 GB on this 48 GB Mac). It was 32 GB, which left 16 GB for macOS, T3 Code, Chrome and Teams, and the Mac ran out of memory. Change it by hand in Docker Desktop, Settings, Resources. This restarts Docker and stops every running stack, so tell the user first. `lane doctor` warns when the limit is too high. `MAX_LANES` sets the number of lanes at once, and further `lane up` calls wait in the queue.
