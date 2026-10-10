# ADR-0002 — Bookmark Retrieval and Typed Decision Boundary

- Date: 2026-10-09
- Status: Accepted for feature/retrieval-decision-cli; live deployment pending
- Scope: Local CLI, private cloud retrieval, explicit decision inference

## Context

Xcollect already has two authoritative storage profiles: Local JSON or Cloudflare D1/KV. Discovery items expire at source age >=24h unless the user explicitly saves them and synchronization verifies them as durable bookmarks. Existing /api/tweets reads bookmarks; /api/feed also exposes Discovery. Users need a CLI and agents need evidence, not another AI-created copy of the raw tweet.

## Decision

1. Adopt a portable, read-only retrieval core `src/retrieval.py` that accepts a list of **durable bookmarks**. Adapters supply data. The CLI never reads the combined Discovery feed.
2. First retrieval release is lexical, title/body/metadata weighted, Unicode-normalized, with **curated** aliases. It is not vector/semantic retrieval; keep the API's `score` explicitly lexical.
3. Keep local mode available without Cloudflare. Cloud read endpoints live under `/api/v1`, authenticated by the `XCOLLECT_API_TOKEN` Worker Secret. Missing secret denies service, rather than exporting private tweets.
4. Preserve original ID, URL, timestamps, and `body_raw` in JSONL; Markdown retains a full-text source copy. Mark fallback snippet explicitly when body is unavailable. AI judgments never replace source facts.
5. Use explicit `POST /api/v1/decide` only for individual already-saved bookmarks. Config switch defaults **off**. Model allowlist: Clef-flash, Clef, Jev; Jev requires an additional opt-in to avoid surprise third-party charges.
6. System One typed model questions are fixed in the adapter and answered as separate decision annotations, never probabilities that masquerade as objective technical truth. No AI invocation on sync, search or export.
7. Retrieval, source storage and decision provider stay separate; Vectorize/AI Search/MCP can be attached later as *rebuildable projections/adapters*.

## Security deployment constraint

This ADR does not make the existing browser routes private. `/api/tweets` and `/api/feed` existed without route-level bearer authentication, alongside read/write/sync endpoints. **Cloudflare Access must protect the whole deployed hostname**, not just `/api/v1`, before exposing personal data; close or equivalently protect unintended `workers.dev` routes. Token is only for CLI v1 and is never committed or exposed in frontend JS. Do not label production secure until the network-level Access and legacy APIs are audited.

## Failure semantics

- Local missing JSON: hard error, never silently substitute public seed data.
- Cloud v1 token absent: 503; unauthorized: 401; record missing: 404; bad query: 400.
- No AI binding / model failure: error (not fabricated probability).
- Decision disabled: 403; Jev not allowed: 403.
- No semantic retrieval claims until index/synonym evaluation tests exist.

## Rejected alternatives

- Direct D1 token from CLI: broad permissions and poor separation.
- Always-on AI scoring during bookmark sync: cost and source freshness impact.
- Automatic durable promotion of Discovery items: violates TTL and explicit user intent.
- Treating LLM summaries as raw source: violates traceability.
- Make Cloudflare mandatory for CLI: violates Local Profile contract.

## Follow-ups

- FTS5 index + paginated SQL retrieval to avoid selecting entire D1 table.
- Incremental local SQLite mirror with tombstones and robust sync cursor.
- Evaluate alias/query rewrite quality, calibrated reranking, Cloudflare AI Search versus Vectorize.
- HTTP Access integration test with real production secrets, rate limiting, quotas and observability.
- Optional MCP adapter after private API hardening.

References:
- https://developers.cloudflare.com/ai/models/%40cf/cloudflare/clef-flash/
- https://developers.cloudflare.com/ai/models/typesafe/jev/
- https://developers.cloudflare.com/d1/sql-api/sql-statements/
