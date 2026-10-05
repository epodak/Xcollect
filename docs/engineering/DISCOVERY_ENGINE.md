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
= rolling UTC source-time window, not a calendar-day archive
= may be rejected, ranked, shown, ignored or promoted into bookmarks
```

A discovery recommendation is **not** a bookmark. The two objects must never be
silently merged.

The freshness invariant is hard:

```text
source_post_age < 24h UTC  -> eligible Discovery observation
source_post_age >= 24h UTC -> absent from feed + physically garbage-collected
```

For an unpromoted Discovery item, expiration removes the candidate, materialized
feed row and its ephemeral feedback events. Reading it, opening the original, or
ignoring it does not turn Discovery into a permanent history database. An
explicit bookmark promotion changes the object into the durable Bookmark Plane;
that durable object and its bookmark-derived evidence are exempt from Discovery
TTL.

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

| action | behavioral utility | learning projection |
| --- | ---: | --- |
| open_detail | +1 | semantic preference + query acceptance |
| copy | +5 | semantic preference + query acceptance |
| open_original | +10 | semantic preference + query acceptance |
| bookmark | +50 | strong semantic preference + query acceptance |
| unbookmark | -50 | cancels prior bookmark evidence; not equivalent to “不想看这类” |
| reject_candidate | -10 | Discovery-quality only |
| not_interested | -50 | semantic preference only |
| hide_author | -100 | explicit author-level semantic rejection |

The values are configuration, not hard-coded product truth. They are **relative
evidence units**, not direct ranking points. The learner first aggregates them,
then applies bounded `tanh` transforms. This preserves the intended hierarchy
(+1 << +10 << +50) without letting one bookmark permanently saturate the feed.

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
Aggregated preference models must be reproducible from the retained event log.

“Append-only” here means immutable during the retention window, not eternal
storage. Discovery-only evidence is physically deleted when its unpromoted
candidate expires at 24h source age. This deliberately makes short-lived
Discovery learning forget stale attention. Durable Bookmark evidence remains
available because the object has left the ephemeral Discovery Plane.

The first online trainer is deliberately small and bounded:

- repeated `(tweet, action)` pairs are deduplicated for learning;
- raw behavioral utility is aggregated into category, sub-category and author fields;
- category/sub-category/author fields use separate configurable `tanh` scales;
- the combined correction is bounded to approximately `[-0.22, +0.22]`;
- the correction modifies semantic relevance rather than replacing quality,
  freshness or velocity;
- query-quality uses a separate bounded field: false-positive × contributes -10,
  while detail/original/bookmark evidence can offset a noisy query;
- semantic “不想看这类” never punishes the discovery query itself.

This means a few actions can steer the feed, but cannot immediately collapse it
into an echo chamber.

The current bounded transforms are:

```text
category_signal    = tanh(sum(utility) / 150)
subcategory_signal = tanh(sum(utility) / 100)
author_signal      = tanh(sum(utility) / 100)

preference_boost
  = 0.06 * category_signal
  + 0.10 * subcategory_signal
  + 0.06 * author_signal

query_quality_penalty
  = 0.10 * tanh(max(0, -sum(query_utility)) / 30)
```

Therefore a single title open is weak evidence, opening the original is roughly
an order of magnitude stronger, and bookmarking is strong evidence without
being a literal +50 ranking-point jump. A single false-positive × creates only
a bounded query-quality penalty; an open-original (+10) on another result from
the same query can offset one × (-10).

## Two-timescale learning

Discovery intentionally has a fast and a slow memory:

```text
Fast field
= unpromoted Discovery interactions
= detail/original/copy/reject/not-interested
= expires with the source-post 24h window

Slow field
= objects explicitly promoted into Bookmarks
= durable knowledge + durable bookmark evidence
= not governed by Discovery TTL
```

This gives the system short-term adaptation without letting yesterday's
unaccepted feed become a permanent hidden training corpus.

Client feedback is best-effort and must never block reading, copying, opening X
or bookmark actions. Failed events are queued locally and retried later.

Feedback has two orthogonal learning projections:

```text
reject_candidate + feedback_scope=discovery_quality
    -> query/source/gate quality
    -> excluded from category/sub-category/author preference

not_interested + normal preference scope
    -> category/sub-category/author preference
```

This separation is intentional. “The system fetched the wrong object” is not the
same statement as “the system found the right object but I dislike the topic.”

## Discovery storage objects

### discovery_candidates

An observation of a potentially relevant external post. It stores source
provenance, normalized semantic/ranking features and candidate state.

Candidate states are expected to evolve through:

```text
candidate → rejected                 # AI gate or explicit card-corner × false-positive reject
candidate → selected → shown
selected → saved_pending → saved     # explicit X save, then bookmark sync/read-back confirmation
selected → hidden                    # “不想看这类” semantic preference action
```

The two negative exits are intentionally not equivalent:

- `rejected` means “this item should not have entered Discovery”. It trains source/query/gate quality and must not lower topic/sub-category/author preference.
- `hidden` means “I do not want more content like this”. It remains a semantic preference signal.

Likewise, `saved_pending` is not a bookmark. It only means X accepted the save request. The item becomes a durable bookmark after the bookmark plane synchronizes it into `tweets` and read-back confirms the ID.

### daily_feed

A materialized attention budget / snapshot. The historical table name remains
for compatibility, but `feed_date` is only a partition key. Eligibility is
defined by rolling source-post age, not by “same UTC calendar day”.

It stores the chosen order only. It does not imply permanent storage or a user
bookmark.

## Rolling discovery pipeline

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
- hard rejection for source posts outside the rolling 24h UTC window before AI inference;
- scheduler-tick garbage collection that physically deletes stale Discovery candidates, feed rows and non-durable feedback evidence;
- strict read-side freshness filtering so an expired item cannot remain visible while waiting for the next GC tick;
- hard rejection for sensitive / extremely short / obvious promo-spam content;
- reply provenance normalization plus a cheap-gate reply guard, so SearchTimeline leakage cannot bypass query intent such as `-filter:replies`;
- a distinct false-positive rejection path whose feedback is kept out of topic preference and instead contributes a bounded query-quality penalty;
- Workers AI micro-batch judging with deterministic fallback;
- related-hot scoring after learned preference correction;
- daily-feed materialization with author / sub-category / category caps;
- `/api/feed`, `/api/discovery/status`, `/api/discovery/run` and
  `/api/discovery/action`;
- distinct discovery-card interactions:
  - corner `×` for false-positive/wrong-candidate rejection;
  - “不想看这类” for semantic preference rejection;
  - save to X with two-phase `saved_pending -> saved` promotion confirmation.

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

## Maintenance contract

Future agents changing this subsystem should use `.agents/skills/discovery-plane/SKILL.md` as the operational playbook. The architectural invariant remains in `AGENTS.md`, while executable regressions are locked by `scripts/check_discovery.py`, `scripts/check_feed_contract.py`, and `scripts/check_related_hot.py`.
