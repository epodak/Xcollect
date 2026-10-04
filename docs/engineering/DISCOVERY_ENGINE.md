# Personal Discovery Engine

## Product contract

Xcollect now has two different data planes:

```text
Bookmark Plane
= things the user explicitly saved
= durable knowledge assets
= X bookmark synchronization remains authoritative

Discovery Plane
= things the system found for the user
= ephemeral candidate stream
= may be rejected, ranked, shown, ignored or promoted into bookmarks
```

A discovery recommendation is **not** a bookmark. The two objects must never be
silently merged.

## Related-hot ranking

The UI default is `related_hot_desc`.

The frontend does not invent recommendation intelligence. It only sorts on the
backend-projected `related_hot_score`.

The score contract is:

```text
RelatedHot
  = relevance_weight × relevance
  + quality_weight × quality
  + novelty_weight × novelty
  + velocity_weight × engagement_velocity
  + source_weight × source
  + freshness_weight × freshness
  - penalty
```

All positive features and penalties are normalized to `[0, 1]`.

For existing bookmarks, deterministic proxies fill missing semantic features.
Future discovery enrichment may provide explicit AI fields such as
`relevance_score`, `quality_score`, `novelty_score`,
`promo_probability`, `nsfw_probability` and `spam_probability`.
The same ranking function then consumes the richer features without creating a
second code path.

Ranking weights and half-life parameters live in `config.toml`.

## Why engagement velocity matters

Lifetime likes are not a useful definition of "hot".

A 20-minute-old post with 300 likes may be a stronger emerging signal than an
18-hour-old post with 5,000 likes. The deterministic MVP therefore discounts
engagement by post age before bounding it into the ranking feature space.

This is a proxy only. Later versions should normalize velocity relative to the
author's own historical distribution.

## Cheap gate before expensive AI

The system should reject obvious low-value candidates before LLM inference.

```text
raw candidates
    ↓
cheap rules
    ↓
promo / NSFW / spam / low-signal penalty
    ↓
semantic relevance
    ↓
quality + novelty judge
    ↓
diversity selector
    ↓
daily feed
```

The current cheap gate is conservative: it lowers rank but does not delete
bookmarks. Discovery ingestion may later use a hard rejection threshold.

## Feedback as training data

`feedback_events` is append-only.

Current actions already produce preference signals:

| action | default reward |
| --- | ---: |
| open_detail | +0.15 |
| copy | +0.80 |
| open_original | +0.30 |
| bookmark | +1.00 |
| unbookmark | -1.00 |
| not_interested | -1.20 |
| hide_author | -2.00 |

The values are configuration, not hard-coded product truth.

The important invariant is:

```text
feed
  ↓
human action
  ↓
append-only feedback event
  ↓
future aggregation / preference model
  ↓
next feed
```

Raw events are never rewritten into a single mutable "preference" field.
Aggregated preference models must be reproducible from the event log.

Client feedback is best-effort and must never block reading, copying, opening X
or bookmark actions. Failed events are queued locally and retried later.

## Discovery storage objects

### discovery_candidates

An observation of a potentially relevant external post. It stores source
provenance, normalized semantic/ranking features and candidate state.

Candidate states are expected to evolve through:

```text
candidate → rejected
candidate → selected → shown
selected → saved
selected → hidden
```

### daily_feed

A materialized attention budget for one date.

It stores the chosen order only. It does not imply permanent storage or a user
bookmark.

## Daily discovery pipeline

Target architecture:

```text
taxonomy + trusted authors + learned preference
                    ↓
             query/seed expansion
                    ↓
              source discovery
                    ↓
                 candidates
                    ↓
               cheap filter
                    ↓
          Workers AI batch judge
                    ↓
         score + dedupe + diversity
                    ↓
                daily_feed
```

The future selector must enforce diversity rather than plain Top-K. Expected
constraints include:

- per-author daily cap;
- per-cluster cap;
- near-duplicate suppression;
- category/sub-category quotas;
- MMR-style relevance-versus-redundancy selection.

## State machine

Long-running discovery should be resumable and idempotent:

```text
DISCOVER
  ↓
FILTER
  ↓
AI_SUBMITTED
  ↓
AI_COMPLETED
  ↓
RANKED
  ↓
PUBLISHED
```

A Cron invocation should advance durable state, not require the entire pipeline
to finish in one Worker execution.

## Current implementation boundary

This change establishes:

- backend `related_hot_score`;
- default Related Hot UI ranking;
- deterministic fallback ranking for existing bookmarks;
- append-only feedback capture in D1/KV and Local Profile;
- schema objects for future discovery candidates and daily feed.

It does **not** yet claim to perform global X discovery. Candidate acquisition
must be implemented as a separate Discovery Plane source adapter, rather than
being hidden inside bookmark synchronization.
