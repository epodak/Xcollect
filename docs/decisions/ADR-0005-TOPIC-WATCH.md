# ADR-0005 — Persistent Topic Watch over ephemeral Discovery

Status: Accepted, 2026-10-10

## Decision

User-defined `Topic Watch` is a durable **intent**, not a new category or a second bookmark store. Its search queries are scheduled independently of global taxonomy queries but reuse SearchTimeline, gates, quality scoring and a shared candidate pool. A many-to-many match table supports the same post belonging to multiple watches. Watch result queries apply rolling 24-hour source freshness; discovery GC removes orphan match references.

## Trade-offs

v1 has explicit, conservative deterministic query expansion rather than speculative LLM-generated searches. Watch rank reuses the shared candidate quality score and may initially contain keyword-level false positives. Intent-specific semantic relevance, per-watch acceptance learning and per-watch notification policy are deferred. A rejected candidate is currently a shared Discovery-level rejection, not a topic-local rejection.

## Invariants

Persistent intent never promotes an observation to a durable bookmark. X source bookmark sync remains authoritative. Expired non-bookmarked source text and identifiers are not retained as a watch archive. Global query budget is not displaced; pagination, freshness checks, authorization and spam gates remain in effect.
