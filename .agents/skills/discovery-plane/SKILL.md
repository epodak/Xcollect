# Discovery Plane Maintenance Skill

Use this skill whenever changing Xcollect discovery, feed scopes, recommendation feedback, bookmark promotion, ranking, or related UI state.

## Read first

1. `AGENTS.md` — project invariants, especially Invariant 9.
2. `docs/engineering/DISCOVERY_ENGINE.md` — canonical architecture and rationale.
3. `src/discovery.py`, `src/preferences.py`, `src/entry.py`, `src/sync_service.py`.
4. `public/js/app.js`, `public/js/render.js`.
5. `scripts/check_discovery.py`, `scripts/check_feed_contract.py`.

Do not invent a second state model in the UI.

## Canonical objects

| Object | Meaning | Durable? |
| --- | --- | --- |
| Discovery Candidate | External observation not yet accepted by the user | No |
| Bookmark | Explicitly accepted knowledge asset confirmed by bookmark sync/read-back | Yes |
| All | Read-only projection of active Discovery + durable Bookmarks | No new ownership state |

Invariant:

```text
ActiveDiscovery ∩ DurableBookmarks = ∅
All = ActiveDiscovery ∪ DurableBookmarks
ActiveDiscovery requires source_post_age < 24h UTC
```

Discovery is a rolling freshness window, not a calendar-day inbox. A non-durable
candidate that reaches 24h source age must disappear from projection immediately
and be physically garbage-collected with its ephemeral feedback evidence.

## Canonical state machine

```text
candidate
  ↓
selected
  ↓
shown
  ├─ corner × false positive ───────→ rejected
  ├─ “不想看这类” preference ──────→ hidden
  └─ bookmark ──────────────────────→ saved_pending
                                           ↓
                                  bookmark sync/read-back
                                           ↓
                                         saved
```

Never count `saved_pending` as a durable bookmark.

## Negative feedback is orthogonal

Two negative actions must never collapse into one signal.

### Corner × — false positive

Meaning: “This item should not have entered Discovery.”

Effects:
- state -> `rejected`;
- remove from active Discovery immediately;
- append `reject_candidate` feedback with `feedback_scope=discovery_quality`;
- preserve provenance such as `discovery_query`, `discovery_source`, reply metadata;
- may adjust query/source/gate quality;
- MUST NOT lower category, sub-category, or author preference.

### “不想看这类” — semantic dislike

Meaning: “The system found a valid candidate, but I want less content like this.”

Effects:
- state -> `hidden`;
- append normal preference feedback;
- may lower category/sub-category/author preference.

## Source-intent defense in depth

Do not trust SearchTimeline query syntax as the only gate.

Example: queries may use `-filter:replies`, but X can still leak replies. Normalize reply provenance and reject leaked replies in the cheap gate before expensive AI inference.

General pattern:

```text
source query intent
    ↓
normalize source facts
    ↓
cheap deterministic guard
    ↓
AI judge
```

## Bookmark promotion transaction

A Discovery save is not complete when the X CreateBookmark request succeeds.

Required transaction:

```text
X save accepted
   ↓
saved_pending
   ↓
bookmark sync
   ↓
tweets read-back contains ID
   ↓
saved
```

The UI may say “waiting for sync confirmation” while pending, but must not fabricate a bookmark count or durable state.

## UI projection rules

- “今日相关热点已全部阅毕” only when the unfiltered active Discovery scope total is zero.
- A category/search/high-like filter yielding zero means “no matches under current filters”, not Inbox Zero.
- Infinite scroll controls DOM rendering only. It must not redefine feed totals or scope semantics.
- Scope counters must derive from canonical state predicates, not duplicated ad-hoc conditions.

## Feedback learning rules

- Behavioral utilities are relative evidence units, not direct ranking points:
  - detail/title open ≈ +1;
  - copy ≈ +5;
  - open original ≈ +10;
  - bookmark ≈ +50;
  - corner × false positive ≈ -10 in Discovery-quality only;
  - “不想看这类” ≈ -50 in semantic preference;
  - unbookmark offsets prior bookmark evidence.
- Aggregate evidence first, then squash it into bounded fields; never add +50 directly to `related_hot_score`.
- `feedback_events` is immutable during its retention window, not eternal.
- When an unpromoted Discovery candidate expires at 24h source age, purge its ephemeral feedback events too.
- Durable Bookmark evidence is exempt from Discovery TTL.
- Preference aggregation must be reproducible from retained events.
- Discovery-quality events are excluded from topic/author preference aggregation.
- Query-quality penalties must be bounded; one accidental rejection must not destroy a useful discovery channel.
- Positive actions carrying discovery provenance may offset noisy-query penalties.

## Change procedure

When changing Discovery behavior:

1. Identify which object changes: Candidate, Bookmark, Projection, Feedback Event, or Ranking Feature.
2. Write the state transition before touching UI.
3. Decide which learning field receives the event:
   - discovery quality;
   - semantic preference;
   - neither.
4. Preserve provenance needed to reproduce the decision.
5. Keep backend state authoritative; frontend is a projection.
6. Update the canonical engineering document if semantics changed.
7. Update `AGENTS.md` only if a non-negotiable invariant changed.
8. Add/adjust executable acceptance checks.

## Acceptance gates

Run:

```bash
pnpm run check
```

At minimum the change must preserve:

- source posts >= 24h old are rejected before AI;
- stale non-durable candidates and their ephemeral feedback are physically purged;
- read projection cannot show expired rows between GC ticks;
- reply leakage rejected before AI;
- false-positive × does not alter topic preference;
- behavior utility hierarchy remains +1 / +10 / +50 and -10 / -50 before bounded squash;
- `saved_pending` is not counted as a bookmark;
- promotion only completes after durable read-back;
- filtered-zero is not Inbox Zero;
- infinite scroll does not overwrite feed count semantics.

A change is incomplete until the acceptance checks pass.
