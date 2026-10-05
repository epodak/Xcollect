# ADR-0001: Self-Calibrating Behavioral Learning for Discovery

- Status: Accepted
- Date: 2026-10-05
- Scope: Discovery ranking, feedback learning, telemetry, exploration
- Supersedes: fixed relative action magnitudes such as +1 / +10 / +50 / -10 / -50

## Context

Early Xcollect feedback used hand-written action magnitudes to express an
intuitive hierarchy:

- opening a card is weak positive evidence;
- opening the original post is stronger;
- bookmarking is strongest;
- false-positive rejection and semantic dislike are different negatives.

The ordering was useful. The numeric distances were not evidence-based.

Hard-coding those distances creates several problems:

1. The same action can mean different things in different domains.
2. Repeated funnel actions can be double-counted.
3. A large fixed bookmark reward can saturate the preference field.
4. Items below the viewport can be mistaken for ignored items.
5. The recommender can create a self-confirming loop by only showing what it
   already believes.
6. Raw Discovery events have a 24h TTL, but useful learning should not require
   permanently retaining the underlying unaccepted feed.

## Decision

### 1. Human policy defines topology, not metric distance

The stable policy is:

```text
open_detail < copy < open_original < bookmark
```

and:

```text
reject_candidate -> Discovery-quality axis
not_interested   -> semantic-preference axis
hide_author      -> author-preference axis
unbookmark       -> withdraw bookmark evidence
```

No fixed ratio such as 1:10:50 is an architectural invariant.

The legacy `feedback_events.weight` column is retained for compatibility, but
new events use sign-only values. Learning logic consumes action semantics rather
than those historical ratios.

### 2. Record real impressions

A Discovery card is considered viewed only when:

```text
intersection_ratio >= 0.50
AND visible_time >= 1500 ms
```

The impression records rank position and Discovery provenance.

Rendered-but-not-viewed candidates are unknown, not negative samples.

### 3. Learn positive action magnitude from bookmark conversion

Maintain aggregate decayed statistics:

```text
learning_action_stats
  action
  exposures
  conversions_to_bookmark
  updated_at
```

These statistics contain no tweet ID and no tweet content.

For non-terminal actions, estimate utility from:

```text
P(bookmark | action)
relative to
P(bookmark | impression)
```

Sparse-data bootstrap uses ordinal position only. As samples accumulate,
empirical conversion behavior takes control.

The current aggregate-stat half-life is 30 days.

### 4. Enforce monotonic ordering

Sampling noise must not produce nonsensical inversions such as:

```text
open_detail > open_original
```

Use isotonic regression / pooled-adjacent-violators so the learned utility
remains monotone under the product-defined order.

Bookmark is the normalized terminal positive anchor.

### 5. Resolve one semantic vote per item

For preference aggregation, a normal funnel:

```text
detail -> original -> bookmark
```

contributes the strongest surviving semantic action, not three additive votes.

`unbookmark` removes the bookmark vote. It does not automatically become
semantic dislike.

### 6. Learn query quality separately

Query correctness is modeled with accepted-vs-rejected observations:

```text
reject_candidate -> false positive
positive action  -> accepted candidate
impression only  -> unknown
not_interested   -> not a query-quality judgment
```

Use a Beta-Binomial posterior with bounded penalty.

This model must remain orthogonal to topic/author preference.

### 7. Keep two learning timescales

Fast raw evidence:

- Discovery candidate and its raw feedback;
- expires at 24h source-post age when not promoted.

Slow aggregate model state:

- action calibration sufficient statistics;
- contains no raw tweet identity/content;
- decays with a 30-day half-life.

Durable Bookmark evidence is exempt from Discovery TTL.

### 8. Preserve exploration

Reserve a small exploration budget among already-qualified candidates.
Current default: 8%.

Exploration must never bypass freshness, safety, relevance or quality gates.
Selection is deterministic per UTC day and tweet ID for reproducibility.

## Consequences

Positive:

- action magnitude becomes personalized rather than guessed;
- ranking can improve as real behavior accumulates;
- false-positive learning remains separate from taste;
- no permanent hidden archive of unaccepted tweets is required;
- recommendation collapse is reduced by bounded fields and exploration;
- learned utilities are inspectable through Discovery status.

Costs:

- the learner needs sufficient samples before empirical estimates dominate;
- bookmark conversion is only one proxy for value and may later need richer
  delayed outcomes;
- current calibration is global across content domains; future versions may
  condition by category, sub-category or context once sample size supports it.

## Rejected alternatives

### Keep fixed +1/+10/+50 ratios

Rejected because the ratios have no empirical basis and can overfit product
intuition.

### Treat every rendered card as an impression

Rejected because below-the-fold items would become false negatives.

### Add all funnel actions together

Rejected because normal user flow would inflate one item's evidence.

### Store all raw Discovery history forever

Rejected because short-lived feed observations should not silently become a
permanent behavioral dossier.

### Pure exploitation

Rejected because it creates a self-confirming recommendation loop.

## Validation

Executable contracts:

- `scripts/check_discovery.py`
- `scripts/check_related_hot.py`
- `scripts/check_feed_contract.py`
- `pnpm run check`

Operational guidance:

- `.agents/skills/discovery-plane/SKILL.md`

Canonical architecture:

- `docs/engineering/DISCOVERY_ENGINE.md`
