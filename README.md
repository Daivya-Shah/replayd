# Replayd

Replayd is a recording proxy for LLM agents. Point your agent at it instead of the provider API and every request/response gets captured losslessly. Use the dashboard to inspect runs, replay them offline, branch from a divergence point, and regression-test behavior over time.

Your agent keeps sending its own provider API key. Replayd forwards it upstream and never stores or bills for model usage. Sensitive headers are redacted from what gets persisted.

For a deeper look at how the system works, see [ProjectDescription.md](ProjectDescription.md).

## Quickstart with Docker

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose).

```bash
docker compose up --build
```

Once everything is up:

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| Proxy (point your agent here) | http://localhost:8787/v1 |
| Control API | http://localhost:8788 |
| Logto (OIDC) | http://localhost:3001 |
| Logto Admin | http://localhost:3002 |

Set your OpenAI client `base_url` to `http://localhost:8787/v1` and send requests with your usual `OPENAI_API_KEY`. Replayd records automatically.

Docker runs Postgres for the relational index, MinIO for blob storage, and a one-shot migrate job before the proxy and control plane start. Copy [`.env.example`](.env.example) if you want to override defaults.

To use a different upstream provider, set `UPSTREAM_BASE_URL` on the `proxy` service in `docker-compose.yml` (Azure OpenAI, a local vLLM server, etc.).

## One-time Logto setup

Human login on the dashboard needs a few minutes of Logto configuration after the first `docker compose up`:

1. Open http://localhost:3002 and create the admin account.
2. Create an **API Resource** with identifier `http://localhost:8788` (must match `OIDC_AUDIENCE`).
3. Create a **Traditional Web Application** for the dashboard:
   - Redirect URI: `http://localhost:3000/api/auth/callback/oidc`
   - Post sign-out redirect: `http://localhost:3000`
   - Grant access to the API Resource from step 2.
4. Put the app ID and secret in your environment (see `.env.example`), then restart the dashboard service.

Verify control-plane connectivity:

```bash
python -m replayd.check_oidc
```

Or hit `GET http://localhost:8788/health/oidc`.

**Docker OIDC gotcha:** tokens use `iss` = `http://localhost:3001/oidc` (`OIDC_ISSUER`), but the control plane fetches JWKS from the internal URL `http://logto:3001/oidc/jwks` (`OIDC_JWKS_URL`). Same split for the dashboard: public issuer for browser redirects, internal issuer for server-side token exchange.

The proxy uses project ingest keys, not OIDC. Only the control plane validates JWTs.

## Grouping steps into runs

A **run** is an ordered sequence of exchanges sharing a run ID. Send the same header on every request in a task:

```
x-replayd-run-id: my-task-abc123
```

If you omit it, each exchange becomes its own singleton run. The proxy stays transparent either way.

## Replay, branch, and regression tests

**Sandbox replay** re-runs your agent logic against recorded responses. No upstream calls, no API cost. Send the baseline run ID in the replay header:

```
x-replayd-replay: <run-id-to-replay>
```

If the request body does not match any recorded step, you get a divergence error.

**Branch replay** replays matching steps from a parent run, then goes live on the first mismatch:

```
x-replayd-branch: <parent-run-id>
x-replayd-run-id: <new-branch-run-id>
```

Useful when you want to change a prompt or model partway through without redoing earlier steps.

**Regression tests** live in the dashboard under Tests. Save a run as a baseline, record a fresh candidate run of the same task, and compare. Semantic mode tolerates wording changes; exact mode requires byte-identical responses.

Demo scripts in `scripts/` show record, replay, branch, and regression flows. They load `.env` automatically.

## Control plane access

Recorded runs contain real prompts and responses. Lock down the control plane in production.

**OIDC (Logto, Docker default):** configure `OIDC_ISSUER`, `OIDC_JWKS_URL`, and `OIDC_AUDIENCE` on the control plane. Send `Authorization: Bearer <jwt>` with a Logto-issued access token.

**Shared token:** set `REPLAYD_API_TOKEN` on the control plane. When set (and no valid JWT is present), every `/api/*` request needs:

```
Authorization: Bearer <token>
```

(or `X-Replayd-Token: <token>`). `/health` and `/health/oidc` stay public.

If neither OIDC nor `REPLAYD_API_TOKEN` is configured, the API runs open with a warning logged at startup. Fine for local dev, not for production.

The dashboard uses Auth.js OIDC login when configured. Without OIDC env vars it runs fully open and talks directly to the control plane.

## Project ingest keys

Agents authenticate to the proxy with project ingest keys, not JWTs. Create keys in the dashboard under Keys and send:

```
x-replayd-key: rpd_...
```

By default, a missing or invalid key falls back to the default project and the request still forwards. Set `REQUIRE_INGEST_KEY=true` on the proxy to reject bad keys with 401 before calling upstream.

## Local development (without Docker)

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

Copy `.env.example` to `.env` if you want local overrides. Without `DATABASE_URL`, Replayd uses SQLite at `{STORAGE_DIR}/replayd.db`. Without S3 config, blobs stay on the filesystem at `{STORAGE_DIR}/blobs/`.

Start the data plane and control plane in separate terminals:

```bash
uvicorn replayd.main:app --host 127.0.0.1 --port 8787
uvicorn replayd.management:app --host 127.0.0.1 --port 8788
```

Dashboard:

```bash
cd web
npm install
npm run dev
```

Run tests:

```bash
pytest
```

Tests use SQLite by default. To also run storage and migration tests against Postgres, start a Postgres instance and set `REPLAYD_TEST_DATABASE_URL` (see `.env.example`).

## CLI

```bash
replayd-migrate          # run Alembic migrations
replayd-check-oidc       # verify OIDC/JWKS connectivity
replayd-test             # run regression tests from the command line
```
