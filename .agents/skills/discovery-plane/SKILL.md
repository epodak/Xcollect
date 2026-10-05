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

- Never hard-code action ratios such as `+1/+10/+50` as product truth.
- Human/product policy defines only:
  - semantic meaning;
  - positive/negative sign;
  - ordinal order (`open_detail < copy < open_original < bookmark`);
  - orthogonal scope (Discovery quality vs semantic preference).
- A valid `impression` requires at least 50% card visibility for at least 1.5 seconds.
- Rendered-but-never-viewed items are unknown, not negative examples.
- Positive action magnitude is calibrated from the user's own `P(bookmark | action)` statistics.
- Calibration state is aggregate sufficient statistics only; it must not retain tweet text or tweet IDs.
- Calibration statistics decay over time; current default half-life is 30 days.
- With sparse data, bootstrap from ordinal rank only; observed conversion data must progressively take control.
- Enforce monotonic utility with isotonic projection so sampling noise cannot invert the product order.
- Resolve one strongest semantic vote per tweet. A normal funnel (`detail -> original -> bookmark`) is not three additive votes.
- `unbookmark` withdraws the bookmark vote; it is not equivalent to “不想看这类”.
- Query quality is learned separately from a reject-vs-accepted posterior; semantic dislike must not punish the query.
- Raw unpromoted Discovery events expire with the 24h candidate TTL.
- Decayed aggregate calibration may survive raw-event deletion because it contains no raw candidate identity/content.
- Durable Bookmark evidence is exempt from Discovery TTL.
- Keep a small exploration budget among candidates that already passed quality gates.
- Preference and query-quality outputs must remain bounded.


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
