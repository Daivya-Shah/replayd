# Replayd

A record-and-replay layer for LLM agents. Point your agent at Replayd instead of the provider API. Replayd forwards traffic transparently, saves every request and response, and lets you replay runs, branch from a parent recording, and compare behavior over time.

You keep your own API keys. Replayd does not call models on your behalf outside of normal proxy forwarding, and the whole stack can run on your infrastructure.

## Why it exists

Agent runs are hard to debug. Logs rarely include full request and response bodies, re-running the same task often produces a different path, and there is no standard way to say "this run should behave like that one."

Replayd treats an agent run like a flight recording. When something breaks, you can inspect the exact steps, replay them without calling the model again, fork from step three with a new prompt, or gate a deploy on a regression test.

## How it works

Replayd sits between your agent and an OpenAI-compatible API (OpenAI, Anthropic via compatibility shims, Azure, local vLLM, and so on).

```
Agent  -->  Replayd proxy (:8787)  -->  Provider API
                |
                v
           Storage (SQLite or Postgres + blob store)
                ^
                |
         Control plane (:8788)  <--  Dashboard (:3000)
```

Two backend processes share storage:

- **Data plane (proxy)** on port 8787. The hot path. Forwards requests, captures exchanges, handles replay and branch modes. Streaming responses pass through unchanged.
- **Control plane** on port 8788. A read-only management API for runs, exchanges, regression tests, projects, and team settings. The dashboard talks to this, not to storage directly.

## Quick start (local)

Requirements: Python 3.12+

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

By default Replayd uses SQLite at `./data/replayd.db` and stores request/response bodies under `./data/blobs/`. Migrations run automatically on startup.

Point your OpenAI SDK (or any HTTP client) at the proxy:

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url="http://127.0.0.1:8787/v1",
    default_headers={"x-replayd-run-id": "my-run-001"},
)
```

Or try the included demo script (requires `OPENAI_API_KEY`):

```bash
python scripts/demo_agent.py
```

The script prints a run id. Use it with the other scripts in `scripts/` to replay, branch, or run a regression comparison.

Browse recorded runs at `http://127.0.0.1:8788/api/runs` or start the dashboard (see below).

## Docker Compose

For a production-shaped local stack with Postgres, MinIO (S3-compatible blobs), and Logto (OIDC):

```bash
docker compose up --build
```

| Service        | URL                         |
|----------------|-----------------------------|
| Proxy          | http://localhost:8787       |
| Control plane  | http://localhost:8788       |
| Dashboard      | http://localhost:3000       |
| Logto admin    | http://localhost:3002       |
| MinIO console  | http://localhost:9001       |

First-time OIDC setup:

1. Open http://localhost:3002 and create a Logto admin account.
2. Create an API Resource whose indicator matches `OIDC_AUDIENCE` (default `http://localhost:8788`).
3. Verify connectivity: `replayd-check-oidc` or `GET http://localhost:8788/health/oidc`.

## Control headers

Replayd-specific headers are optional. Without them, the proxy still forwards traffic normally; each exchange just becomes its own single-step run.

All `x-replayd-*` headers are stripped before the request reaches the provider.

| Header | Default name | Purpose |
|--------|--------------|---------|
| Run id | `x-replayd-run-id` | Group steps into one run |
| Replay | `x-replayd-replay` | Target run id for sandbox replay (no upstream call) |
| Branch | `x-replayd-branch` | Parent run id for replay-then-live branching |
| Ingest key | `x-replayd-key` | Attribute traffic to a project |

Header names are configurable via environment variables (`RUN_ID_HEADER`, `REPLAY_HEADER`, `BRANCH_HEADER`, `INGEST_KEY_HEADER`).

## Replay modes

**Record (default).** Forward to the provider and capture the exchange. Responses stream through to the client exactly as the provider sent them.

**Sandbox replay.** Set `x-replayd-replay` to a recorded run id. Replayd matches each incoming request to a stored step by request body hash and returns the recorded response bytes. No upstream call. An unmatched request returns a divergence error.

**Branch.** Set `x-replayd-branch` to a parent run id. Matching steps are served from the recording; the first request that does not match goes live to the provider and gets captured. All steps land in a new run linked to the parent. The first live step is the divergence point.

Example:

```bash
# Record
python scripts/demo_agent.py

# Replay (no API key needed beyond a dummy value)
REPLAYD_REPLAY_RUN_ID=<run-id> python scripts/replay_agent.py

# Branch from a parent run
python scripts/branch_agent.py <parent-run-id>
```

## Regression tests

Create a test that pins a baseline run, then compare a candidate run step by step.

```bash
curl -X POST http://127.0.0.1:8788/api/tests \
  -H "Content-Type: application/json" \
  -d '{"name": "trip planner", "baseline_run_id": "<run-id>", "mode": "semantic"}'
```

Comparison modes:

- **exact**: request and response body hashes must match at every step.
- **semantic**: compares structural decisions (model, message roles, finish reason, tool names, argument keys) and tolerates wording-only differences.

Run a test from the CLI (useful in CI):

```bash
# Compare against an existing candidate run
replayd-test run <test-id> --candidate <candidate-run-id>

# Record a fresh candidate via your agent, then compare
replayd-test run <test-id> -- python scripts/demo_agent.py
```

Exit codes: `0` pass, `1` fail, `2` error.

## Dashboard

The web UI lives in `web/`. It is a Next.js app and a pure client of the control plane API.

Local dev without Docker:

```bash
cd web
npm install
npm run dev
```

Set `NEXT_PUBLIC_REPLAYD_API_URL=http://127.0.0.1:8788` for open dev mode (no login). In Docker, OIDC login is enabled by default via Logto.

Pages include run lists, step-by-step run detail, exchange bodies, regression tests, ingest keys, and team management.

## Configuration

All settings come from environment variables or a `.env` file. Common ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `UPSTREAM_BASE_URL` | `https://api.openai.com` | Provider API base URL |
| `LISTEN_PORT` | `8787` | Proxy port |
| `MGMT_PORT` | `8788` | Control plane port |
| `STORAGE_DIR` | `./data` | SQLite path and filesystem blob root |
| `DATABASE_URL` | (unset) | Postgres URL; unset uses SQLite |
| `BLOB_STORAGE_BACKEND` | `filesystem` | `filesystem` or `s3` |
| `CAPTURE_ENABLED` | `true` | Toggle capture on the proxy |
| `REQUIRE_INGEST_KEY` | `false` | Reject proxy traffic without a valid ingest key |
| `OIDC_ISSUER` | (unset) | Enable OIDC auth on the control plane |
| `OIDC_AUDIENCE` | (unset) | Expected JWT audience |
| `REPLAYD_API_TOKEN` | (unset) | Shared bearer token for CI/service access |

See `src/replayd/config.py` for the full list.

## Project layout

```
src/replayd/
  main.py           Data plane (proxy)
  proxy.py          Forward, replay, branch logic
  management.py     Control plane REST API
  testing.py        Regression test runner
  semantics.py      Semantic diff for chat completions
  storage/          SQL index + blob stores
  auth/             OIDC, RBAC, multi-tenancy
  migrations/       Alembic schema migrations

web/                Next.js dashboard
tests/              pytest suite
scripts/            Demo agents for record, replay, branch
```

## Development

Run tests:

```bash
pytest
```

Run migrations manually:

```bash
replayd-migrate
```

Useful scripts:

| Script | What it does |
|--------|--------------|
| `scripts/demo_agent.py` | Record a multi-step run |
| `scripts/replay_agent.py` | Sandbox replay of a run |
| `scripts/branch_agent.py` | Branch from a parent run |
| `scripts/regression_demo.py` | Record a candidate and compare to baseline |
| `scripts/list_runs.py` | List runs from storage |

When you add or change dependencies in `pyproject.toml`, reinstall with `pip install -e .` in your venv before testing.

## Multi-tenancy

Data is organized as organizations containing projects. Runs, exchanges, and tests belong to a project. Users join an organization with a role (owner, admin, member, viewer).

Agents authenticate to the proxy with per-project ingest keys (`rpd_` tokens). Humans authenticate to the control plane with OIDC or a service token. Until you configure auth, everything lands in a default organization and project.

## Core guarantee

Every step captured through the proxy in record mode is stored losslessly. Replay returns the recorded bytes, not a regenerated model response. That is what makes forensic inspection and deterministic sandbox replay possible.
