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

The first online trainer is deliberately small and bounded:

- repeated `(tweet, action)` pairs are deduplicated for learning;
- reward is aggregated into category, sub-category and author signals;
- signals are squashed with `tanh`;
- the combined correction is bounded to approximately `[-0.22, +0.22]`;
- the correction modifies semantic relevance rather than replacing quality,
  freshness or velocity.

This means a few actions can steer the feed, but cannot immediately collapse it
into an echo chamber.

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

The selector already enforces coarse-grained diversity instead of plain Top-K:

- per-author daily cap;
- per-sub-category daily cap;
- per-category share cap.

The next selector revision should add semantic near-duplicate clustering and
MMR-style relevance-versus-redundancy selection.

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

The live Discovery Plane now includes:

- a round-robin query plan in `prompts/discovery_queries.json`;
- dynamic SearchTimeline queryId / feature / transport resolution from the same
  external registry already used by the bookmark adapter;
- GET/POST transport fallback so X Web build changes do not silently couple the
  product to one request shape;
- candidate acquisition that remains independent from bookmark synchronization;
- hard rejection for sensitive / extremely short / obvious promo-spam content;
- Workers AI micro-batch judging with deterministic fallback;
- related-hot scoring after learned preference correction;
- daily-feed materialization with author / sub-category / category caps;
- `/api/feed`, `/api/discovery/status`, `/api/discovery/run` and
  `/api/discovery/action`;
- a distinct discovery-card interaction: save to X or mark as not interested.

The current judge deliberately uses small synchronous Workers AI micro-batches
(up to 12 candidates per call) because the existing Worker AI binding requires
no additional service credential. The durable D1 state is designed so this
judge can later be replaced by Cloudflare's asynchronous Batch API without
changing the candidate/feed contracts.

Still pending:

- semantic embedding / near-duplicate clustering;
- MMR selection;
- trusted-author graph expansion;
- learned query expansion from positive/negative feedback;
- asynchronous AI Batch submission and resume states.
