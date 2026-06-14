# replayd

replayd is a transparent recording proxy for LLM agents. Point your agent at it instead of the provider API and every request/response is captured losslessly. Use the dashboard to inspect runs, deterministically replay them, branch from a divergence point, and regression-test behavior over time. Bring-your-own-key: your agent sends its own provider API key on each request; replayd forwards it upstream and **never stores or bills for model usage** (sensitive headers are redacted from persisted records).

## Quickstart (Docker)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose).

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| Proxy (point your agent here) | http://localhost:8787/v1 |
| Control API | http://localhost:8788 |
| Logto (OIDC / auth API) | http://localhost:3001 |
| Logto Admin Console | http://localhost:3002 |

Set your OpenAI client `base_url` to `http://localhost:8787/v1` and send requests with your usual `OPENAI_API_KEY`. replayd records automatically.

**Storage in Docker:** the relational index lives in **Postgres 16** (`DATABASE_URL=postgresql+asyncpg://replayd:replayd@postgres:5432/replayd` by default). Request/response bodies are stored in **MinIO** (S3-compatible) via `BLOB_STORAGE_BACKEND=s3` — the `minio` service on port 9000 (console on 9001). A one-shot **`migrate`** service runs `replayd-migrate` after Postgres is healthy and before the proxy and control-plane start (`RUN_MIGRATIONS_ON_STARTUP=false`). `S3BlobStore.init()` creates the `replayd` bucket if needed.

**Identity (Logto):** Docker Compose bundles **Logto** as the self-hosted OIDC provider. Logto uses a separate Postgres database (`logto`) on the same `postgres` service. A one-shot **`logto-db-init`** service creates that database if it is missing; Logto seeds its own schema on first start.

Override Postgres, MinIO, Logto, or blob settings via environment variables — see [`.env.example`](.env.example). Defaults work for a first `docker compose up --build`, but OIDC requires a **one-time Logto console setup** (below) before human JWT login works.

## One-time Logto setup (OIDC)

After `docker compose up --build`:

1. Open the **Logto Admin Console** at http://localhost:3002 and create the initial admin account.
2. Create an **API Resource** for the replayd control-plane API. Set its **API identifier** to `http://localhost:8788` (must match `OIDC_AUDIENCE` / `AUTH_OIDC_AUDIENCE`).
3. Create a **Traditional Web Application** for the dashboard:
   - **Redirect URI:** `http://localhost:3000/api/auth/callback/oidc`
   - **Post sign-out redirect URI:** `http://localhost:3000`
   - Grant the application access to the API Resource from step 2.
   - Copy the **App ID** and **App secret** into your environment (see below).
4. Set dashboard auth env (`.env` or shell before `docker compose up`):

   | Variable | Example | Purpose |
   |----------|---------|---------|
   | `AUTH_SECRET` | output of `openssl rand -base64 32` | Auth.js session encryption |
   | `AUTH_URL` | `http://localhost:3000` | Dashboard public URL (Auth.js) |
   | `AUTH_OIDC_ISSUER` | `http://localhost:3001/oidc` | Public issuer (browser redirect + id_token `iss`) |
   | `AUTH_OIDC_INTERNAL_ISSUER` | `http://logto:3001/oidc` | Internal issuer for server-side token/JWKS calls |
   | `AUTH_OIDC_ID` | from Logto app | OAuth client id |
   | `AUTH_OIDC_SECRET` | from Logto app | OAuth client secret |
   | `AUTH_OIDC_AUDIENCE` | `http://localhost:8788` | API resource indicator (RFC 8707 `resource` param) |

5. Verify control-plane ↔ Logto connectivity:

   ```bash
   python -m replayd.check_oidc
   ```

   Or `GET http://localhost:8788/health/oidc`.

6. Open http://localhost:3000 and sign in with OIDC. The dashboard requests the API resource so Logto issues an **access token** with `aud == OIDC_AUDIENCE`; the server-side `/api/replayd` proxy attaches it to control-plane calls.

**Docker OIDC gotcha (control plane):** tokens use `iss` = `http://localhost:3001/oidc` (`OIDC_ISSUER`). The control-plane fetches JWKS from the internal URL `http://logto:3001/oidc/jwks` (`OIDC_JWKS_URL`). Do not point `OIDC_JWKS_URL` at `localhost` from inside Docker.

**Docker OIDC gotcha (dashboard):** Auth.js runs server-side inside the dashboard container. `AUTH_OIDC_ISSUER` stays public (`http://localhost:3001/oidc`) for the browser authorization redirect and id_token `iss` validation. Server-side token exchange, userinfo, and JWKS use `AUTH_OIDC_INTERNAL_ISSUER` (`http://logto:3001/oidc` by default). API calls in OIDC mode go through the dashboard's `/api/replayd` proxy, which forwards server-side to `CONTROL_PLANE_URL` (`http://control-plane:8788` by default — internal Docker DNS, not `localhost:8788`).

| Variable | Default (Docker) | Purpose |
|----------|------------------|---------|
| `OIDC_ISSUER` | `http://localhost:3001/oidc` | Must match JWT `iss` (control-plane) |
| `OIDC_JWKS_URL` | `http://logto:3001/oidc/jwks` | Internal JWKS URL (control-plane) |
| `AUTH_OIDC_ISSUER` | `http://localhost:3001/oidc` | Public issuer (dashboard browser + id_token) |
| `AUTH_OIDC_INTERNAL_ISSUER` | `http://logto:3001/oidc` | Internal issuer (dashboard server-side OIDC) |
| `CONTROL_PLANE_URL` | `http://control-plane:8788` | Internal control-plane URL (dashboard `/api/replayd` proxy) |
| `OIDC_AUDIENCE` | `http://localhost:8788` | API resource indicator |
| `OIDC_ALGORITHMS` | `ES384,RS256` | Accepted JWT signing algorithms (Logto uses ES384) |

**Dev mode (no OIDC):** omit `AUTH_OIDC_*` and set `NEXT_PUBLIC_OIDC_ENABLED=false` (default for local `npm run dev`). The dashboard is fully open with no login; API calls go directly to `NEXT_PUBLIC_REPLAYD_API_URL`.

The proxy uses **project ingest keys**, not OIDC — only the control-plane validates JWTs.

To use a different upstream provider, set `UPSTREAM_BASE_URL` on the `proxy` service in `docker-compose.yml` (e.g. an Azure OpenAI endpoint or a local OpenAI-compatible server).

## Control plane access token

Recorded runs contain real prompts and responses. Authentication options:

- **OIDC (Logto, Docker default):** configure `OIDC_ISSUER`, `OIDC_JWKS_URL`, and `OIDC_AUDIENCE` on the control-plane (see One-time Logto setup above). Send `Authorization: Bearer <jwt>` from a Logto-issued access token.
- **Shared token:** set `REPLAYD_API_TOKEN` on the **control-plane** service. When set (and no valid JWT is presented), every `/api/*` request must include:

```
Authorization: Bearer <token>
```

(or `X-Replayd-Token: <token>`). `/health` and `/health/oidc` stay public. If neither OIDC nor `REPLAYD_API_TOKEN` is configured, the API runs unauthenticated (convenient for dev; a warning is logged at startup).

The dashboard uses **Auth.js OIDC login** when configured (see One-time Logto setup). In dev mode (OIDC unset), the dashboard is open with no login.

## Grouping steps into runs

A **run** is an ordered sequence of exchanges sharing a `run_id`. Send the same header on every request of a task:

```
x-replayd-run-id: <your-run-id>
```

If the header is absent, each exchange becomes its own singleton run (the proxy stays transparent).

## Replay, branch, and regression tests

**Sandbox replay** — re-run agent logic against recorded responses (no upstream calls):

```
x-replayd-replay: <run-id-to-replay>
```

**Branch replay** — replay matching steps from a parent run, then go live on divergence:

```
x-replayd-branch: <parent-run-id>
x-replayd-run-id: <new-branch-run-id>
```

**Regression tests** — in the dashboard (**Tests**), save a run as a baseline test, record a fresh candidate run of the same task, and compare. Semantic mode tolerates wording changes; exact mode requires byte-identical responses.

## Bring your own key

replayd does not hold provider credentials. Your agent (or SDK) attaches its API key to each request; the proxy forwards it to `UPSTREAM_BASE_URL` and redacts it from stored capture metadata. You are always billed by your provider, not by replayd.

## Development (without Docker)

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

Copy [`.env.example`](.env.example) to `.env` if you want local overrides. **Without `DATABASE_URL`**, replayd uses **SQLite** at `{STORAGE_DIR}/replayd.db`. **Without `BLOB_STORAGE_BACKEND=s3`**, blobs stay on the **local filesystem** at `{STORAGE_DIR}/blobs/` (default for non-Docker dev).

Start the data plane and control plane in separate terminals:

```bash
uvicorn replayd.main:app --host 127.0.0.1 --port 8787
uvicorn replayd.management:app --host 127.0.0.1 --port 8788
```

Dashboard (dev):

```bash
cd web
npm install
npm run dev
```

Run tests:

```bash
pytest
```

By default tests use **SQLite** only (fast, no Docker). To also run core storage/migration/replay/regression tests against Postgres, start a Postgres instance and set:

```bash
# Windows PowerShell
$env:REPLAYD_TEST_DATABASE_URL="postgresql+asyncpg://replayd:replayd@localhost:5432/replayd_test"
pytest
```

Demo scripts (`scripts/demo_agent.py`, `scripts/regression_demo.py`, etc.) load `.env` automatically via `python-dotenv`.
