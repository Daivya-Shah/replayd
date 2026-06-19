# Replayd

Replayd is a record-and-replay layer for LLM agents. Point your agent at the proxy instead of the provider API, and every request/response pair gets captured losslessly. Later you can replay a run without calling the model, branch from a recorded trajectory, or run regression tests to catch drift.

Bring your own API key. Replayd forwards it to the upstream provider and never stores or bills for model usage. The proxy is designed to be transparent: streaming works, headers pass through, and agents behave the same as they would talking to OpenAI (or any compatible API) directly.

## How it works

Replayd runs two services that share storage:

| Service | Port | What it does |
|---------|------|--------------|
| **Proxy** (data plane) | 8787 | Transparent catch-all proxy. Captures traffic. Handles replay and branch modes. |
| **Control plane** | 8788 | Read-only management API. Powers the dashboard and the regression CLI. |

Captured request and response bodies go into a content-addressed blob store (local filesystem or S3). Metadata (runs, exchanges, tests, org/project info) lives in a relational database (SQLite locally, Postgres in production).

```
Agent  -->  Replayd proxy (:8787)  -->  OpenAI / Anthropic / etc.
                  |
                  v
            SQLite or Postgres + blob storage
                  ^
                  |
Dashboard (:3000) -->  Control plane (:8788)
```

## Quick start with Docker

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose).

The fastest way to run the full stack (Postgres, MinIO, Logto OIDC, proxy, control plane, dashboard):

```bash
docker compose up --build
```

Once everything is healthy:

| URL | Purpose |
|-----|---------|
| http://localhost:8787/v1 | Proxy (point your agent here) |
| http://localhost:8788 | Control plane API |
| http://localhost:3000 | Dashboard |
| http://localhost:3001 | Logto (OIDC) |
| http://localhost:3002 | Logto admin console (one-time setup) |

Set your OpenAI client `base_url` to `http://localhost:8787/v1` and send requests with your usual `OPENAI_API_KEY`. Replayd records automatically.

Docker runs Postgres for the relational index, MinIO for blob storage, and a one-shot migrate job before the proxy and control plane start. Copy `.env.example` if you want to override defaults. To use a different upstream provider, set `UPSTREAM_BASE_URL` on the `proxy` service in `docker-compose.yml` (Azure OpenAI, a local vLLM server, etc.).

**One-time Logto setup** (for dashboard login):

1. Open http://localhost:3002 and create the admin account.
2. Create an **API Resource** with identifier `http://localhost:8788` (must match `OIDC_AUDIENCE`).
3. Create a **Traditional Web Application** for the dashboard:
   - Redirect URI: `http://localhost:3000/api/auth/callback/oidc`
   - Post sign-out redirect: `http://localhost:3000`
   - Grant access to the API Resource from step 2.
4. Put the app ID and secret in your environment (`AUTH_OIDC_ID`, `AUTH_OIDC_SECRET`), then restart the dashboard service.

Verify control-plane connectivity:

```bash
replayd-check-oidc
# or
curl http://localhost:8788/health/oidc
```

**Docker OIDC gotcha:** tokens use `iss` = `http://localhost:3001/oidc` (`OIDC_ISSUER`), but the control plane fetches JWKS from the internal URL `http://logto:3001/oidc/jwks` (`OIDC_JWKS_URL`). Same split for the dashboard: public issuer for browser redirects, internal issuer for server-side token exchange. The proxy uses ingest keys, not OIDC.

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
# Terminal 1: data plane
uvicorn replayd.main:app --host 127.0.0.1 --port 8787

# Terminal 2: control plane
uvicorn replayd.management:app --host 127.0.0.1 --port 8788
```

By default this uses SQLite at `./data/replayd.db` and stores blobs under `./data/blobs/`. Migrations run automatically on startup. No auth is required in this mode (the control plane runs open). Copy `.env.example` to `.env` if you want local overrides.

Optional dashboard:

```bash
cd web
npm install
npm run dev
```

Set `NEXT_PUBLIC_REPLAYD_API_URL=http://localhost:8788` so the dashboard talks to your local control plane.

## Pointing an agent at the proxy

Set the OpenAI SDK base URL to the proxy and keep using your normal provider API key:

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url="http://localhost:8787/v1",
    default_headers={
        "x-replayd-run-id": "my-run-abc123",  # optional but recommended
    },
)
```

If you omit `x-replayd-run-id`, each exchange becomes its own singleton run. With a shared run id, all steps in an agent session are grouped together and ordered by timestamp.

Demo scripts in `scripts/` show multi-step recording, replay, and branch workflows:

```bash
# Record a multi-step run
python scripts/demo_agent.py

# Replay a run in sandbox mode (no upstream calls)
REPLAYD_REPLAY_RUN_ID=<run_id> python scripts/replay_agent.py

# Branch from a parent run (replay matched steps, go live on divergence)
REPLAYD_BRANCH_RUN_ID=<parent_run_id> REPLAYD_RUN_ID=<new_run_id> python scripts/branch_agent.py
```

## Control headers

All `x-replayd-*` headers are stripped before the request reaches the upstream provider.

| Header | Purpose |
|--------|---------|
| `x-replayd-run-id` | Groups exchanges into a run. Auto-generated if missing. |
| `x-replayd-replay` | Sandbox replay mode. Set to a baseline run id. No upstream call. |
| `x-replayd-branch` | Branch mode. Set to a parent run id. Replays matches, forwards misses live. |
| `x-replayd-key` | Project ingest key (`rpd_...`) for multi-tenant attribution. |

### Replay modes

**Forward (default)**  
Proxy the request upstream, stream the response back, capture everything.

**Replay** (`x-replayd-replay: <run_id>`)  
Match the incoming request against a recorded step in that run (by request body hash). Return the saved response byte-for-byte. No upstream call. A request with no match is a divergence (HTTP 422).

**Branch** (`x-replayd-branch: <parent_run_id>`)  
For each request, try to match a step in the parent run. On match, serve the recorded response. On miss, forward live to upstream. Every step is captured into a new run (from `x-replayd-run-id`), with `parent_run_id` pointing at the parent. The first live step is the divergence point.

## Regression tests

Create a test in the control plane that references a baseline run, then compare a candidate run against it:

```bash
# Create a test (via API or dashboard), then run it
curl -X POST http://localhost:8788/api/tests \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent-smoke", "baseline_run_id": "<run_id>", "mode": "semantic"}'

curl -X POST "http://localhost:8788/api/tests/<test_id>/run" \
  -H "Content-Type: application/json" \
  -d '{"candidate_run_id": "<candidate_run_id>"}'
```

Two comparison modes:

- **exact**: byte-for-byte request and response body hash comparison, step by step.
- **semantic**: compares structural decisions (model, message roles, tool names, argument keys, finish_reason). Wording-only differences are tolerated.

For CI, use the bundled CLI:

```bash
replayd-test <test_id> --candidate-run-id <run_id>
# or re-run an agent through the proxy first:
replayd-test <test_id> -- python scripts/demo_agent.py
```

Set `REPLAYD_API_TOKEN` when the control plane requires auth. Exit code 0 means pass, 1 means fail, 2 means error.

## Multi-tenancy and auth

**Data plane (agents):** pass a project ingest key in `x-replayd-key`. Keys are `rpd_` tokens stored hashed. By default, missing or invalid keys fall back to the default project and the request still goes through. Set `REQUIRE_INGEST_KEY=true` to reject bad keys with 401.

**Control plane (humans):** OIDC via Logto (or any compatible provider) plus an optional shared `REPLAYD_API_TOKEN` for CI/service access. When neither is configured, the API runs open (dev mode). Recorded runs contain real prompts and responses, so lock down the control plane in production. The dashboard uses Auth.js OIDC login when configured; without OIDC env vars it runs open and talks directly to the control plane.

Hierarchy: Organization → Project → runs, tests, ingest keys. Users join orgs via membership (owner, admin, member, viewer).

## Configuration

All settings come from environment variables (see `src/replayd/config.py`). Common ones:

| Variable | Default | Notes |
|----------|---------|-------|
| `UPSTREAM_BASE_URL` | `https://api.openai.com` | Change for Azure, vLLM, etc. |
| `LISTEN_PORT` | `8787` | Proxy port |
| `MGMT_PORT` | `8788` | Control plane port |
| `STORAGE_DIR` | `./data` | SQLite path and filesystem blobs |
| `DATABASE_URL` | (unset) | Set for Postgres (`postgresql+asyncpg://...`) |
| `BLOB_STORAGE_BACKEND` | `filesystem` | Set to `s3` for MinIO/AWS |
| `CAPTURE_ENABLED` | `true` | Toggle capture on the proxy |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` | Disable in Docker (use the `migrate` service) |
| `OIDC_ISSUER` | (unset) | Control plane OIDC |
| `OIDC_JWKS_URL` | (unset) | Internal JWKS URL (important in Docker) |
| `OIDC_AUDIENCE` | (unset) | API resource identifier |
| `REPLAYD_API_TOKEN` | (unset) | Shared bearer token for CI |

**Docker OIDC gotcha:** `OIDC_ISSUER` must match the token's `iss` claim (browser-facing, e.g. `http://localhost:3001/oidc`). `OIDC_JWKS_URL` must be reachable from inside the control-plane container (e.g. `http://logto:3001/oidc/jwks`).

## Project layout

```
src/replayd/          Python package (proxy, control plane, storage, auth, testing)
web/                  Next.js dashboard
tests/                pytest suite
scripts/              Demo agents and utilities
docker/               Backend Dockerfile, Postgres init
docker-compose.yml    Production-shaped local deployment
```

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

Tests cover proxy routing, capture, replay, branch, regression (exact and semantic), storage on SQLite and Postgres, blob backends, migrations, auth, RBAC, and the management API. To run storage and migration tests against Postgres, start a Postgres instance and set `REPLAYD_TEST_DATABASE_URL` (see `.env.example`).

## CLI tools

| Command | Purpose |
|---------|---------|
| `replayd-migrate` | Run Alembic migrations |
| `replayd-check-oidc` | Verify OIDC/JWKS connectivity |
| `replayd-test` | Run a saved regression test from CI |

## License

See the repository for license details.
