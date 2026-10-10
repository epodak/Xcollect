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

`feedback_events` records immutable raw interaction evidence during its retention
window. It is not itself the learned model.

### Human policy vs learned magnitude

Product policy defines semantics and order:

```text
impression
  < open_detail
  < copy
  < open_original
  < bookmark
```

It also defines orthogonal negative meanings:

```text
reject_candidate  -> Discovery quality only
not_interested    -> semantic preference only
hide_author       -> author-level semantic rejection
unbookmark        -> withdraw bookmark evidence, not dislike
```

The earlier +1/+10/+50-style numbers were useful only to express an intuition
about ordering. They are no longer used as relative recommendation weights.
The persisted `weight` column remains for backward compatibility and now
contains sign-only legacy values.

### Valid exposure

An item is not negative merely because it was rendered. Discovery records an
`impression` only when a card is at least 50% visible for at least 1.5 seconds.

This prevents the learner from confusing:

```text
ranked below the fold / never seen
```

with:

```text
seen and ignored
```

The impression event also preserves rank position and normal Discovery
provenance for later evaluation.

### Self-calibrating positive actions

Xcollect estimates positive action utility from the user's own bookmark
conversion behavior:

```text
P(bookmark | impression)
P(bookmark | open_detail)
P(bookmark | copy)
P(bookmark | open_original)
```

The implementation stores only decayed aggregate sufficient statistics:

```text
action -> exposures, bookmark_conversions, updated_at
```

No tweet IDs or tweet text are stored in this calibration table.

Current calibration behavior:

- aggregate statistics have a 30-day half-life;
- sparse-data bootstrap comes only from ordinal rank (equal-spaced prior order),
  not from hand-written action ratios;
- observed conversion data progressively replaces the bootstrap prior;
- a pooled-adjacent-violators / isotonic projection guarantees
  `open_detail <= copy <= open_original <= bookmark` despite sampling noise;
- `bookmark` is the normalized terminal positive anchor at 1.0.

The current learned utilities are visible through `/api/discovery/status` for
inspection and future offline evaluation.

### One item, one semantic vote

A normal action funnel must not be counted additively:

```text
detail -> original -> bookmark
```

does **not** become three independent positive votes.

For each tweet, semantic preference uses the strongest surviving action.
`unbookmark` withdraws the bookmark vote, allowing weaker earlier engagement
to remain, but it does not become a semantic negative.

Topic/sub-topic/author fields aggregate these normalized item-level votes and
apply evidence-count confidence shrinkage before producing the bounded
`preference_boost`.

### Query quality is a different model

Discovery-quality learning does not share semantic preference magnitude.

For each `(query, tweet)`:

- `reject_candidate` is one false-positive observation;
- any positive engagement is one accepted observation;
- impression-only is unknown;
- `not_interested` does not judge query correctness.

A Beta-Binomial posterior estimates query false-positive risk. The prior
provides small-sample shrinkage and the final query penalty remains capped.
One accepted result must monotonically reduce the penalty created by the same
reject history.

### Fast raw memory, slow aggregate calibration

```text
Raw Discovery events
    -> 24h source-post TTL
    -> physically deleted when the unpromoted candidate expires

Aggregate action calibration
    -> no raw identity/content
    -> 30-day exponential half-life

Durable Bookmark evidence
    -> durable knowledge plane
    -> exempt from Discovery TTL
```

This lets Xcollect learn from yesterday without retaining yesterday's
unaccepted feed as a hidden permanent training corpus.

### Exploration

Pure exploitation creates a self-confirming loop: the model shows what it
already believes, then treats interaction with those items as proof that the
belief was correct.

The selector therefore reserves a small exploration budget (currently 8%) among
candidates that already passed freshness, spam, relevance and quality gates.
Exploration never bypasses quality gates. The sample is deterministic per
UTC day and tweet ID for reproducibility.

### Evaluation direction

The model should be judged by downstream behavior rather than whether a
hand-written score "looks right". Useful measurements include:

- valid-impression -> detail rate;
- valid-impression -> original rate;
- valid-impression -> bookmark rate;
- false-positive reject rate;
- semantic not-interested rate;
- NDCG / concentration of high-value actions near the top of the feed;
- calibration of predicted acceptance against observed acceptance;
- diversity / coverage under the exploration floor.

Raw events are evidence; learned sufficient statistics and bounded fields are
model state. The two should not be conflated.

## Discovery storage objects

### discovery_candidates

An observation of a potentially relevant external post. It stores source
provenance, normalized semantic/ranking features and candidate state.

Candidate states are expected to evolve through:

```text
candidate → rejected                 # AI gate or explicit card-corner × false-positive reject
candidate → selected → shown
selected → saved                      # X bookmarks sync plus D1 readback confirmation
selected → saved_pending → saved     # compatibility with legacy API write flow
selected → hidden                    # “不想看这类” semantic preference action
```

The two negative exits are intentionally not equivalent:

- `rejected` means “this item should not have entered Discovery”. It trains source/query/gate quality and must not lower topic/sub-category/author preference.
- `hidden` means “I do not want more content like this”. It remains a semantic preference signal.

Likewise, `saved_pending` is not a bookmark and only exists for legacy write API compatibility. Discovery exposes Copy, Not Interested, and Original (plus the independent false-positive ×). `open_original` remains weaker positive interest; it is not proof of a saved X bookmark. A terminal `bookmark` feedback event must come from an X Bookmarks fetch followed by D1 persistence and ID readback. Only a live Discovery candidate or legacy pending record may be attributed. Unconfirmed candidates still expire after 24 hours.

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

## Topic Watch: explicit user research intent

A Watch is a **durable search policy**, not a taxonomy node and not a saved discovery candidate. Its `title`, `intent`, optional `directions`, state, and generated query seeds persist in D1. Watch queries use a separate round-robin budget of two queries per eligible Discovery cycle; the existing global query budget is unchanged. Watch matches live in `watch_candidate_matches` (many-to-many) and point at the shared ephemeral `discovery_candidates` source record.

The Watch API is `GET/POST /api/watch`, `POST /api/watch/state` (active/paused), and `GET /api/watch/feed?id=<topic_id>`. Existing Cloudflare Access protection applies. Results enforce the same rolling source-time TTL, never materialize permanent copies, and never count as X bookmarks. Expired candidate references are cleaned during Discovery GC. Bookmark authority remains `tweets` after X sync.

Current v1 limits: query expansion is deterministic and keyword-based; personalized semantic intent scoring and model-generated query expansion remain future work. The Watch feed ranks its own matched candidates independently of Global Discovery's 300-item daily selection, while reusing candidate quality scores and rejection state. No background source poll starts from page load.
