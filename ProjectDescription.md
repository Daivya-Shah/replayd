# Replayd: Project Description

Replayd is a recording and reliability layer for AI agents. An agent repeatedly calls a large language model, sending prompts, reading responses, invoking tools, and looping until a task completes. Replayd sits transparently between that agent and the provider (OpenAI, Anthropic, or any OpenAI-compatible API), forwarding every request and capturing every response without changing what the agent sees.

Agents are non-deterministic and hard to debug. Conventional logging rarely answers what was sent on a given step, whether a deploy changed behavior, or how to re-run a workflow offline. Replayd treats each execution as an ordered, lossless **run** that you can inspect, replay deterministically, branch from a chosen step, and compare against baselines over time.

Replayd never holds or bills for model usage. The agent sends its own provider API key; Replayd forwards it and redacts sensitive credentials from stored records. The system is fully self-hostable.

## Core Concepts

An **exchange** is one request/response pair through the proxy (e.g. a chat-completions call). Metadata (method, path, headers, status, latency, model, token usage) lives in a relational index; raw bodies live in a content-addressed blob store referenced by hash.

A **run** is an ordered sequence of exchanges sharing a run ID. Without a run ID, each exchange stands alone. Missing control headers never break the agent.

Three replay modes build on the same capture:

- **Forensic replay:** Read the saved recording as-is. No model calls. Faithful by construction.
- **Sandbox replay:** Agent logic runs again; the proxy serves recorded responses instead of calling upstream. Requests are matched by body hash. A mismatch is a **divergence**. Deterministic, no API cost.
- **Branch replay:** Replay matching steps from a parent run, then go live on the first mismatch. Steps are captured into a new run linked to the parent, each marked replayed or live. Supports what-if changes (prompt, model) without redoing earlier steps.

**Regression tests** pin a baseline run. **Exact** mode requires matching body hashes at every step. **Semantic** mode requires aligned structural decisions (model, message roles, finish reason, tool names, argument keys) but tolerates wording changes. Tests fail at the first mismatch with a categorized diff.

## Architecture

Two planes share storage but serve different roles.

The **data plane** is a transparent reverse proxy. It branches, sandbox-replays, or forwards live (including streaming), captures complete exchanges, and strips Replayd control headers before they reach the provider.

The **control plane** is a separate management API for runs, exchanges, regression tests, projects, team membership, and ingest keys. It does not proxy LLM traffic.

The **dashboard** is a control-plane client only. Production uses OIDC; local dev can run without auth.

Separating write-heavy capture from read-heavy inspection keeps the proxy path simple and allows independent scaling.

## Storage, Tenancy, and Auth

A relational database indexes tenancy (organizations, projects, users, memberships, invitations), exchange metadata, regression tests, and results. Bodies sit in a SHA-256 content-addressed blob store with automatic deduplication. Backends are swappable: SQLite or Postgres for the index, filesystem or S3 for blobs.

Organizations contain projects; projects scope runs, tests, and **ingest keys** (opaque tokens that attribute agent traffic). Membership roles (owner, admin, member, viewer) gate management actions.

Two auth surfaces: the control plane validates OIDC JWTs for humans (with just-in-time user provisioning) and optional shared API tokens for automation. The data plane accepts ingest keys only. Invalid keys fall back to a default project by default; strict mode can reject them. Human and agent credentials stay separate.

Provider API keys pass through and are redacted in storage. Recorded runs contain real prompts and completions, so production control-plane access should always be authenticated.

## Design Principles

**Transparency:** The agent must behave identically to calling the provider directly, streaming included.

**Lossless capture:** Every live step is stored for byte-for-byte replay.

**Deterministic sandbox replay:** Faithfulness comes from the record, not from asking the model twice.

**Explicit branching:** Parent runs, replayed vs live steps, and divergence points are always recorded.

**Self-hostable open-core:** No mandatory SaaS beyond your model provider and optional identity provider.

## What Replayd Is Not

Not a model host, agent framework, log aggregator, or billing gateway. It wraps the HTTP layer your agent already uses and structures data around replay semantics.

## Technical Stack

**Backend:** Python 3.12, FastAPI, uvicorn, httpx, Pydantic v2, pydantic-settings.

**Storage:** SQLAlchemy 2.0 async, Alembic, aiosqlite/asyncpg, content-addressed blobs (filesystem or S3 via boto3).

**Auth:** PyJWT with OIDC JWKS on the control plane; hashed ingest keys on the data plane.

**Dashboard:** Next.js, TypeScript, Tailwind, Auth.js.

**Testing:** pytest, pytest-asyncio.

**Deployment:** Docker Compose (Postgres, MinIO, Logto) or SQLite/filesystem for local dev.
