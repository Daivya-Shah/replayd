# Replayd

Replayd is a record-and-replay layer for LLM agents. Point your agent at the proxy instead of the provider API, and every request/response pair gets captured. Later you can replay a run without calling the model, branch from a recorded trajectory, or run regression tests to catch drift.

Replayd sits between your agent and any OpenAI-compatible API. It does not hold provider keys for billing. Your agent sends its own API key through the proxy, same as always.

## How it works

Replayd runs two services that share storage:

| Service | Default port | What it does |
|---------|--------------|--------------|
| **Proxy** (data plane) | 8787 | Transparent reverse proxy. Records traffic, replays runs, handles branch mode. |
| **Control plane** | 8788 | Management API. Lists runs, serves bodies, manages tests, projects, and team settings. |

Captured request and response bodies go into a content-addressed blob store (local filesystem or S3). Metadata (runs, exchanges, tests, orgs) lives in SQLite or Postgres.

A **run** is an ordered list of **exchanges** (HTTP round-trips) that share a run id. Steps are matched by the SHA-256 hash of the request body.

## Quick start with Docker

The easiest way to run the full stack (Postgres, MinIO, Logto, proxy, control plane, dashboard):

```bash
docker compose up --build
```

Once everything is up:

| URL | Service |
|-----|---------|
| http://localhost:8787 | Proxy |
| http://localhost:8788 | Control plane API |
| http://localhost:3000 | Dashboard |
| http://localhost:3001 | Logto sign-in |
| http://localhost:3002 | Logto admin console |

**One-time Logto setup** (needed before dashboard login works):

1. Open http://localhost:3002 and create an admin account.
2. Create an **API Resource** with indicator `http://localhost:8788` (this becomes `OIDC_AUDIENCE`).
3. Create a **Traditional web app** for the dashboard. Set redirect URI to `http://localhost:3000/api/auth/callback/oidc`.
4. Copy the app id and secret into your environment (`AUTH_OIDC_ID`, `AUTH_OIDC_SECRET`) and restart the dashboard service.

Verify OIDC wiring:

```bash
python -m replayd.check_oidc
# or
curl http://localhost:8788/health/oidc
```

## Local development (no Docker)

Requires Python 3.12+.

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

Start the proxy and control plane in separate terminals:

```bash
uvicorn replayd.main:app --host 127.0.0.1 --port 8787
```

```bash
uvicorn replayd.management:app --host 127.0.0.1 --port 8788
```

By default this uses SQLite at `./data/replayd.db` and filesystem blobs at `./data/blobs/`. Migrations run automatically on startup.

Optional dashboard:

```bash
cd web
npm install
npm run dev
```

With no OIDC configured, the control plane and dashboard run in open dev mode (no login required).

## Point your agent at the proxy

Change your OpenAI client base URL to the proxy. Everything else stays the same.

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url="http://localhost:8787/v1",
    default_headers={
        "x-replayd-run-id": "my-run-id",  # optional but recommended
    },
)
```

Give every step in a multi-turn agent the same `x-replayd-run-id` so they land in one run. If you omit it, each exchange becomes its own singleton run.

Try the included demo (proxy must be running):

```bash
export OPENAI_API_KEY=sk-...
python scripts/demo_agent.py
```

The script prints a generated run id you can inspect in the dashboard or via the API.

## Proxy control headers

All `x-replayd-*` headers are stripped before the request reaches the upstream provider.

| Header | Purpose |
|--------|---------|
| `x-replayd-run-id` | Groups exchanges into a run. Auto-generated if missing during live capture. |
| `x-replayd-replay` | Sandbox replay. Set to a baseline run id. No upstream call; returns the recorded response for matching requests. |
| `x-replayd-branch` | Branch mode. Set to a parent run id. Replays matching steps from the parent, then goes live on the first miss. |
| `x-replayd-key` | Project ingest key (`rpd_...`). Attributes captured traffic to a project. |

### Replay (sandbox)

Serve recorded responses without calling the model:

```bash
export REPLAYD_REPLAY_RUN_ID=<baseline-run-id>
python scripts/replay_agent.py
```

If a request does not match any recorded step, the proxy returns HTTP 422 (divergence).

### Branch (replay then live)

Replay the parent run until the agent sends something new, then forward to the live API:

```bash
export REPLAYD_BRANCH_RUN_ID=<parent-run-id>
python scripts/branch_agent.py
```

The first live step is the divergence point. Everything lands in a new branch run with `parent_run_id` set.

### Replay capture

Re-run an agent in replay mode but record the results into a new run (useful for regression):

```bash
export REPLAYD_REPLAY_RUN_ID=<baseline-run-id>
export REPLAYD_RUN_ID=<candidate-run-id>
python scripts/demo_agent.py
```

## Control plane API

The control plane is read-heavy. It serves run lists, exchange details, raw request/response bodies, regression tests, projects, team membership, and ingest keys.

Examples:

```bash
curl http://localhost:8788/api/runs
curl http://localhost:8788/api/runs/<run-id>
curl http://localhost:8788/api/exchanges/<exchange-id>/request
```

When auth is enabled, pass a Bearer token (OIDC access token or `REPLAYD_API_TOKEN`).

Create a regression test from a baseline run:

```bash
curl -X POST http://localhost:8788/api/tests \
  -H "Content-Type: application/json" \
  -d '{"name": "my test", "baseline_run_id": "<run-id>", "mode": "semantic"}'
```

Run it against a candidate run:

```bash
curl -X POST http://localhost:8788/api/tests/<test-id>/run \
  -H "Content-Type: application/json" \
  -d '{"candidate_run_id": "<candidate-run-id>"}'
```

### Comparison modes

- **exact**: byte-for-byte body hash comparison at every step.
- **semantic**: compares model, message role sequence, tool/function names, argument key sets, and finish reasons. Wording-only differences are tolerated.

A test passes when every step matches and step counts are equal. It fails at the first mismatch.

## CLI: `replayd-test`

CI-friendly regression runner. Compare an existing candidate run:

```bash
export REPLAYD_API_TOKEN=your-token   # when auth is enabled
replayd-test run <test-id> --candidate <candidate-run-id>
```

Or drive your agent in replay-capture mode and compare automatically:

```bash
replayd-test run <test-id> -- python your_agent.py
```

Exit codes: `0` pass, `1` fail, `2` error.

Environment variables:

| Variable | Default |
|----------|---------|
| `REPLAYD_CONTROL_PLANE_URL` | `http://localhost:8788` |
| `REPLAYD_PROXY_URL` | `http://localhost:8787/v1` |
| `REPLAYD_API_TOKEN` | (none) |
| `REPLAYD_REPLAY_RUN_ID` | set by CLI during agent runs |
| `REPLAYD_RUN_ID` | set by CLI during agent runs |

## Dashboard

The Next.js app in `web/` is a client of the control plane. It shows runs, exchange details, regression tests, ingest keys, and team settings.

In dev mode it talks directly to `NEXT_PUBLIC_REPLAYD_API_URL` (default `http://localhost:8788`). In production/OIDC mode, browser API calls go through `/api/replayd/*`, which attaches the OIDC access token server-side.

## Authentication

Two separate auth surfaces:

**Control plane** (humans and CI):

- OIDC JWT (validated via JWKS). First login provisions a user automatically.
- Shared service token via `REPLAYD_API_TOKEN` (Bearer or `X-Replayd-Token` header).
- If neither is configured, the API is open (dev mode only).

**Proxy** (agents):

- Optional project ingest keys via `x-replayd-key`.
- Lenient by default: missing or invalid keys fall back to the default project.
- Set `REQUIRE_INGEST_KEY=true` to reject bad keys with 401 before forwarding.

**Multi-tenancy**: Organization → Project → runs/tests. Users join orgs with roles (owner, admin, member, viewer). RBAC gates key creation, invitations, and project management.

## Configuration

All settings come from environment variables or a `.env` file. Common ones:

| Variable | Default | Notes |
|----------|---------|-------|
| `UPSTREAM_BASE_URL` | `https://api.openai.com` | Where the proxy forwards live traffic |
| `LISTEN_PORT` | `8787` | Proxy port |
| `MGMT_PORT` | `8788` | Control plane port |
| `STORAGE_DIR` | `./data` | SQLite path and filesystem blob root |
| `DATABASE_URL` | (SQLite in `STORAGE_DIR`) | Set to `postgresql+asyncpg://...` for Postgres |
| `BLOB_STORAGE_BACKEND` | `filesystem` | `s3` for MinIO/S3 |
| `CAPTURE_ENABLED` | `true` | Toggle recording on the proxy |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` | Auto-run Alembic migrations |
| `OIDC_ISSUER` | (unset) | Enables OIDC when set |
| `OIDC_JWKS_URL` | (derived from issuer) | Use internal Docker URL in compose |
| `OIDC_AUDIENCE` | (unset) | Must match API resource indicator |
| `REPLAYD_API_TOKEN` | (unset) | Service token for CLI/CI |

Run migrations manually:

```bash
replayd-migrate
```

## Development

Run tests:

```bash
pytest
```

Useful scripts in `scripts/`:

| Script | What it does |
|--------|--------------|
| `demo_agent.py` | Record a multi-step run |
| `replay_agent.py` | Sandbox replay |
| `branch_agent.py` | Branch from a parent run |
| `diverging_demo_agent.py` | Trigger a replay divergence |
| `regression_demo.py` | Record and compare runs |
| `list_runs.py` | Print runs from storage |

Project layout:

```
src/replayd/          Python package (proxy, control plane, storage, auth)
web/                  Next.js dashboard
tests/                pytest suite
scripts/              Demo agents and utilities
docker/               Dockerfiles and Postgres init
docker-compose.yml    Production-shaped local deployment
```

## Design notes

- The proxy is transparent. Streaming responses pass through unchanged. Replayd control headers never reach the provider.
- Sensitive headers (`Authorization`, `x-api-key`, etc.) are redacted before storage.
- Bodies are content-addressed and deduplicated by SHA-256.
- SQLite runs in WAL mode so the proxy (writer) and control plane (reader) can share a local database across processes.
