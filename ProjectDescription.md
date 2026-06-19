# Replayd Project Description

## What is Replayd?

Replayd is a deterministic record-and-replay reliability layer for LLM agents. It sits between an AI agent and a language model API (OpenAI, Anthropic, or any OpenAI-compatible provider) and records every API call the agent makes. Those recordings can be replayed exactly as they happened, branched from to try changes mid-run, and compared in regression tests when behavior drifts.

The mental model is a flight recorder for agent runs. When something fails in production, you do not reconstruct the conversation from sparse logs or hope a re-run reproduces the same trajectory. You have a byte-for-byte recording of every step. You can reproduce the failure locally, compare a new run against a known-good baseline, or change a prompt at step five without paying for or waiting on steps one through four again.

Replayd is built for production and self-hosting. The proxy, capture engine, replay engine, and management API can run entirely in your own environment. Customers bring their own provider API keys; Replayd never holds or bills for model usage. The core is open and self-hostable so security-conscious teams are not locked into a vendor's cloud.

## The Problem

LLM agents are non-deterministic pipelines. A single task may involve dozens of model calls, tool invocations, and retries. When behavior changes (model update, prompt edit, different tool output), debugging breaks down in predictable ways. Logs often omit full request and response bodies. Re-running the agent rarely reproduces the exact same path. There is no standard way to assert that one run should behave like another.

Replayd makes agent execution recordable, replayable, and testable without changing how the agent talks to the API. Point the agent at Replayd instead of the provider. Everything else stays the same.

## The Lifecycle

**Record.** The agent sends API requests through the Replayd proxy. Replayd forwards each request to the real provider using the customer's API key, captures the full request and response, and persists them. Multi-step workflows are grouped into runs via a run identifier the agent can attach to each request.

**Inspect.** Operators browse recorded runs, walk step-by-step through individual exchanges, and read full request and response bodies through a web dashboard or management API. This is the foundation for debugging, audit, and later automation.

**Replay.** The agent sends the same requests again in replay mode. Replayd serves recorded responses from storage instead of calling the model. Agent logic executes again, but model responses are deterministic because they come from the recording.

**Branch.** Starting from a parent run, Replayd replays matching steps from the recording and switches to live upstream calls on the first request that does not match. This supports questions like "what if I change the prompt at step three?" without redoing steps one and two.

**Test.** A regression test pins a baseline run. After recording a new candidate run of the same task, Replayd compares them step by step and reports pass or fail, including where and how they diverged.

## Core Concepts

An **exchange** is one HTTP request/response pair through the proxy: method, path, headers, bodies, status, timestamps, latency, and derived metadata such as detected model and token usage when the payload is parseable.

A **run** is an ordered sequence of exchanges sharing a run identifier. Steps are ordered by when they started. If the agent sends no run identifier, each exchange becomes its own single-step run. The proxy never forces grouping, which preserves transparency: pointing an agent at Replayd without any Replayd-specific headers still works exactly like talking to the provider directly.

In branch mode, a new run links back to a **parent run** via a parent run identifier. Each step in the branch is tagged with an **origin**: either replayed from the parent recording or captured live from upstream. The first live step is the **divergence point**, the moment the new trajectory meaningfully departs from the parent.

The system's central invariant is that every step passing through the proxy in capture mode must be stored losslessly and replayable byte-for-byte from the recorded trajectory.

## Replay Modes

All three modes share the same capture format but serve different purposes.

**Forensic replay** plays back the saved recording without calling the model or external tools. Responses are byte-for-byte faithful by construction because they are read from storage, not regenerated.

**Sandbox replay** re-runs agent logic while serving recorded responses for matched steps, making execution deterministic for the recorded portion. In this mode the proxy does not call upstream. It matches each incoming request to a recorded step by hashing the request body and returns that step's stored response. A request that matches no recorded step is a **divergence**. Replayed responses are not written back to storage.

**Branch replay** combines replay and live execution. For each request, the proxy tries to match the parent run by request body hash. On match, it returns the recorded response. On miss, it forwards to the live provider and captures the result. Every step lands in a new branch run tied to the parent. The first live capture marks where experimentation or drift began.

Agents and tooling activate these modes through optional control headers (run grouping, replay target, branch parent, project attribution). All such headers are stripped before traffic reaches the provider so they never leak upstream.

## Architecture

Replayd splits into two planes that share storage but serve different roles.

The **data plane** is a transparent reverse proxy. An agent pointed at it behaves identically to talking to the upstream API directly, including streaming responses. The proxy forwards traffic, captures exchanges on the live path, and implements replay and branch logic. It is the hot path and stays intentionally thin.

The **control plane** is a separate management API that reads from the same storage. It exposes runs, exchanges, regression tests, projects, ingest keys, and team membership. It handles authentication and orchestrates test execution. It does not sit in the request path for agent traffic.

The **dashboard** is a web application that is a pure client of the control plane. It never touches storage or the proxy directly. In authenticated deployments, the browser obtains an OIDC access token and the dashboard attaches it server-side when calling the API. In development, the dashboard can operate in an open mode without login.

Separating data and control planes keeps capture and forwarding simple while allowing the management surface to evolve independently. The relational store supports concurrent access from the proxy (writer) and control plane (reader). Local deployments use embedded SQLite with write-ahead logging; production deployments use Postgres.

## Storage

Storage has two layers: a relational index and a content-addressed blob store.

The relational index holds structured metadata: organizations, projects, users, memberships, invitations, exchange records (timestamps, paths, status, hashes, not full bodies), regression tests, test results, and hashed ingest key records. Schema changes are managed through versioned migrations that work on both SQLite and Postgres.

Full request and response bodies live in a swappable blob store keyed by SHA-256 digest. The same key layout is used whether blobs sit on the local filesystem or in S3-compatible object storage (including MinIO in containerized deployments). Deduplication happens naturally because identical bodies share a hash.

This split keeps queries fast and bodies cheap to store at scale while guaranteeing that replay can reconstruct exact bytes.

## Multi-Tenancy and Access Control

Data is organized as organizations containing projects. Runs, exchanges, and regression tests belong to a project. Users join an organization through membership with roles (owner, admin, member, viewer) that gate what they can read or change.

Two authentication surfaces reflect two kinds of caller. **Agents** authenticate to the data plane with per-project ingest keys, which attribute captured traffic to the right project. By default the proxy is lenient: a missing or invalid key still forwards the request and attributes it to a default project. Strict mode can reject bad keys before any upstream call. **Humans and automation** authenticate to the control plane with OIDC-backed JWTs, a shared service token suitable for CI, or anonymous access when auth is not configured in development.

The dashboard uses standard OIDC browser login and must obtain an access token scoped to the control plane audience. First login provisions a user record from the identity provider subject. Role-based permissions enforce what each principal can do within an organization and its projects.

## Regression Testing

A regression test references a baseline run and a comparison mode. **Exact** mode requires request and response body hashes to match at every step. **Semantic** mode compares structural decisions (model choice, message role sequence, finish reason, tool and function names, argument key sets) and tolerates wording-only differences in responses. A test passes when every step matches under the chosen mode and step counts are equal. It fails at the first mismatch and classifies the difference (for example request mismatch, tool call change, finish reason change, structural change, or tolerated wording drift).

Without a candidate run, the runner can perform a self-check against the baseline alone. With a candidate run, the comparison is the primary gate for detecting agent drift before or after deploy.

Semantic comparison is purpose-built for chat-completions-shaped payloads: it extracts structured meaning from JSON bodies rather than doing naive string equality, which is what makes semantic mode useful when models paraphrase but still make the same decisions.

## Production Stance

Replayd is async end to end, fully typed, and composed of small modules with clear responsibilities. Configuration comes from the environment, never from hardcoded secrets or URLs. Logging is structured; network failures on upstream calls are handled explicitly.

The proxy must remain transparent: it never alters request or response semantics on the forward path. Customers retain their provider keys; Replayd is infrastructure, not a model reseller. The stack is deployable from day one in Docker with Postgres, object storage, and a self-hosted identity provider, but the same code paths support a minimal local setup with SQLite and filesystem blobs.

The capture format is designed from the start to support forensic inspection, deterministic sandbox replay, and branch experimentation. Regression testing closes the loop for teams that need reliability guarantees as models, prompts, and tools evolve.

## Technical Stack

**Backend:** Python 3.12, FastAPI, uvicorn, httpx, Pydantic v2, pydantic-settings.

**Storage:** SQLAlchemy 2.0 (async), Alembic, SQLite via aiosqlite, Postgres via asyncpg, S3-compatible blobs via boto3.

**Auth:** PyJWT, OIDC with JWKS verification; Auth.js (next-auth) on the dashboard.

**Frontend:** Next.js (App Router), TypeScript, Tailwind CSS.

**Testing:** pytest, pytest-asyncio.

**Packaging and deployment:** hatchling, Docker Compose for production-shaped self-hosted stacks.
