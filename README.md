# Replayd

Replayd is a recording proxy for LLM agents. Point your agent at it instead of the provider API and every request and response gets captured losslessly. From there you can inspect runs in the dashboard, replay them deterministically, branch off at a divergence point, and regression-test behavior as your agent evolves.

Your agent keeps using its own provider API key. Replayd forwards it upstream, redacts sensitive headers from stored records, and never bills you for model usage. The whole stack is self-hostable.

For a deeper conceptual overview, see [ProjectDescription.md](ProjectDescription.md).

## Quickstart with Docker

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker Engine with Compose.

```bash
docker compose up --build
```

Once everything is up:

- **Dashboard:** http://localhost:3000
- **Proxy (point your agent here):** http://localhost:8787/v1
- **Control API:** http://localhost:8788
- **Logto (OIDC):** http://localhost:3001
- **Logto admin console:** http://localhost:3002

Set your OpenAI client `base_url` to `http://localhost:8787/v1` and send requests with your usual `OPENAI_API_KEY`. Recording happens automatically.

Under the hood, Docker Compose runs Postgres for the relational index, MinIO for request/response bodies, and Logto for identity. A one-shot migrate job runs before the proxy and control plane start. See [`.env.example`](.env.example) if you want to override Postgres, MinIO, or blob settings.

The stack will boot without extra configuration, but dashboard login requires a one-time Logto setup (below).

## One-time Logto setup

If you want to sign into the dashboard with OIDC, do this once after `docker compose up --build`:

1. Open http://localhost:3002 and create the Logto admin account.
2. Create an **API Resource** with identifier `http://localhost:8788`. This must match `OIDC_AUDIENCE` and `AUTH_OIDC_AUDIENCE`.
3. Create a **Traditional Web Application** for the dashboard:
   - Redirect URI: `http://localhost:3000/api/auth/callback/oidc`
   - Post sign-out redirect URI: `http://localhost:3000`
   - Grant it access to the API Resource from step 2
   - Copy the App ID and App secret
4. Put these in a `.env` file (or export them before `docker compose up`):

   - `AUTH_SECRET` - generate with `openssl rand -base64 32`
   - `AUTH_URL` - `http://localhost:3000`
   - `AUTH_OIDC_ISSUER` - `http://localhost:3001/oidc` (public, browser-facing)
   - `AUTH_OIDC_INTERNAL_ISSUER` - `http://logto:3001/oidc` (internal, for server-side token calls)
   - `AUTH_OIDC_ID` and `AUTH_OIDC_SECRET` - from the Logto app
   - `AUTH_OIDC_AUDIENCE` - `http://localhost:8788`

5. Restart compose, then verify OIDC connectivity:

   ```bash
   python -m replayd.check_oidc
   ```

   Or hit `GET http://localhost:8788/health/oidc`.

6. Open http://localhost:3000 and sign in.

The dashboard requests the API resource so Logto issues an access token with the right audience. Server-side calls go through `/api/replayd`, which attaches that token to control-plane requests.

**A common Docker gotcha:** JWT `iss` must be the browser-facing issuer (`http://localhost:3001/oidc`), but JWKS fetching from inside containers must use internal DNS (`http://logto:3001/oidc/jwks`). Same idea on the dashboard side: public issuer for browser redirects, internal issuer for token exchange. Do not point internal JWKS URLs at `localhost` from inside Docker.

The proxy itself uses project ingest keys, not OIDC. Only the control plane validates human JWTs.

**Skip OIDC for local dashboard dev:** omit the `AUTH_OIDC_*` vars and set `NEXT_PUBLIC_OIDC_ENABLED=false`. The dashboard runs open with no login and talks directly to the control API.

## Control plane authentication

Recorded runs contain real prompts and responses. Lock down the control plane in production.

**OIDC (Logto in Docker):** configure `OIDC_ISSUER`, `OIDC_JWKS_URL`, and `OIDC_AUDIENCE` on the control-plane service. Send `Authorization: Bearer <jwt>` with a Logto-issued access token.

**Shared token:** set `REPLAYD_API_TOKEN` on the control-plane service. When set, every `/api/*` request needs:

```
Authorization: Bearer <token>
```

You can also use `X-Replayd-Token: <token>`. `/health` and `/health/oidc` stay public.

**Dev mode:** if neither OIDC nor `REPLAYD_API_TOKEN` is configured, the API runs unauthenticated. Convenient for local work; a warning is logged at startup.

## Grouping steps into runs

A run is an ordered sequence of exchanges that share a run ID. Send the same header on every request in a task:

```
x-replayd-run-id: my-task-001
```

If you omit it, each exchange becomes its own singleton run. The proxy stays transparent either way.

## Replay, branch, and regression tests

**Sandbox replay** re-runs your agent against recorded responses with no upstream calls:

```
x-replayd-replay: <run-id-to-replay>
```

**Branch replay** replays matching steps from a parent run, then goes live when something diverges:

```
x-replayd-branch: <parent-run-id>
x-replayd-run-id: <new-branch-run-id>
```

**Regression tests** live in the dashboard under Tests. Save a run as a baseline, record a fresh candidate run of the same task, and compare. Semantic mode tolerates wording changes; exact mode requires byte-identical responses.

## Project ingest keys

To attribute agent traffic to a project, create an ingest key in the dashboard (Keys page) and send it on proxy requests:

```
x-replayd-key: rpd_...
```

By default, a missing or invalid key falls back to the default project and the request still goes through. Set `REQUIRE_INGEST_KEY=true` on the proxy if you want to reject bad keys with 401.

## Bring your own key

Replayd does not hold provider credentials. Your agent attaches its API key to each request; the proxy forwards it to `UPSTREAM_BASE_URL` and redacts it from stored metadata. You are always billed by your provider, not by Replayd.

To point at a different upstream (Azure OpenAI, a local vLLM server, etc.), change `UPSTREAM_BASE_URL` on the proxy service in `docker-compose.yml`.

## Local development (without Docker)

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

Copy [`.env.example`](.env.example) to `.env` for local overrides. Without `DATABASE_URL`, Replayd uses SQLite at `{STORAGE_DIR}/replayd.db`. Without `BLOB_STORAGE_BACKEND=s3`, blobs stay on the filesystem at `{STORAGE_DIR}/blobs/`.

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

By default, tests use SQLite only (fast, no Docker). To also run storage and migration tests against Postgres:

```bash
# Windows PowerShell
$env:REPLAYD_TEST_DATABASE_URL="postgresql+asyncpg://replayd:replayd@localhost:5432/replayd_test"
pytest
```

Demo scripts in `scripts/` (`demo_agent.py`, `regression_demo.py`, `branch_agent.py`, and others) load `.env` automatically.
