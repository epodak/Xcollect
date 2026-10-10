# AGENTS.md - Project Operating Rules & Invariants

> Single Source of Truth: All cross-agent collaborative guidelines follow C:\Users\root\AGENTS.md.

## Non-negotiable rules

1. **Invariants outrank aesthetic or creative freedom.**
   Backward compatibility, API contracts, zero-breaking-change guarantees, and architectural invariants strictly outrank "looks cleaner".

2. **Configuration hygiene (Agent Relay Hygiene).**
   - Sensitive credentials belong strictly in local private `.env` only (never committed).
   - `.env.example` is the 100% desensitized shadow mirror of `.env` (1:1 key parity).
   - Non-sensitive decoupling configs belong in `config.toml` (committed to repo).

3. **Node.js package manager invariant (pnpm only).**
   - Strictly use `pnpm` for all package management and script execution (`pnpm install`, `pnpm run dev`, `pnpm build`, `pnpm test`).
   - Using `npm` or `yarn` is strictly prohibited. Never commit `package-lock.json` or `yarn.lock`.

4. **Evaluation closes the loop.**
   A task recipe without an objective evaluation criterion (test assertion, exit code, typecheck) is incomplete. Execution stops only when acceptance gates pass (`python local_server.py --check`).


5. **Deployment profile invariant (progressive capability enhancement).**
   - Local Profile is first-class and is the default onboarding path: Python + local JSON + X credentials.
   - Cloudflare is optional remote-access infrastructure, never a prerequisite for basic use.
   - D1/KV/Workers AI may enhance capability but must not raise the minimum installation floor.
   - `scripts/seed_data.json` is a repository seed/demo asset; mutable user data belongs under ignored runtime storage such as `data/xcollect.json`.
   - Documentation must explain Local Profile before Cloud Profile.
   - See `docs/engineering/DEPLOYMENT_PROFILES.md`.


6. **Background execution invariant (Personal Cloud).**
   - Personal Cloud freshness is event-driven: Cloudflare Cron -> `on_scheduled` -> `sync_service`.
   - Page load must never trigger source synchronization.
   - `POST /api/bookmarks/sync` is a force-sync / diagnostic control, not the normal scheduler.
   - HTTP, Cron and future Queue/Workflow triggers must share one application sync service.
   - D1 and KV are alternative authoritative backends; never silently dual-write or create split-brain state.
   - See `docs/engineering/BACKGROUND_SYNC.md`.


7. **Negative-event reconciliation invariant.**
   - Incremental source polling may add/update items but must not infer deletions from a partial page.
   - Source-side removals are applied only after a complete authoritative scan reaches the natural source timeline end.
   - If pagination is truncated by `max_sync_pages`, missing IDs must be preserved.
   - Manual force-sync may request full reconciliation; normal cloud Cron remains mostly incremental with periodic full reconciliation.
   - Direct write-back deletion remains immediate: delete on source first, then delete the same item from the selected repository.


8. **Canonical content invariant.**
   - Cards are previews; the detail reader must not simply enlarge the card snippet.
   - Source adapters normalize the richest available content at ingestion time: X Article -> Note Tweet -> legacy full_text.
   - `snippet` is for preview/search; `body_raw` is the canonical reader source.
   - Full reconciliation may refresh source-owned content for existing IDs so parser upgrades can repair historical records without overwriting Xcollect semantic enrichment.
   - Do not claim full thread reconstruction until the conversation graph has actually been fetched and normalized.
   - See `docs/engineering/CONTENT_NORMALIZATION.md`.

9. **Discovery Plane separation invariant.**
   - Bookmarks are durable user-owned knowledge assets; discovery candidates are ephemeral external observations.
   - Never silently insert a recommendation into the bookmark knowledge base.
   - The frontend may project `related_hot_score`, but recommendation intelligence belongs in backend ranking/enrichment.
   - `feedback_events` is append-only within its retention window: raw events are never rewritten into hidden state, but stale Discovery-only events must be physically garbage-collected with their expired candidate. Durable Bookmark evidence is exempt.
   - Discovery freshness is a rolling UTC source-time invariant, not a calendar-day bucket. Any non-durable candidate whose source post is >= 24h old must be absent from the feed and physically deleted together with its ephemeral feedback evidence.
   - Discovery jobs must be resumable/idempotent and should apply freshness/reply/spam/promo/NSFW gates before expensive AI inference.
   - Search/Discovery source failure must never corrupt or delete bookmark-plane data; the two Cron jobs may report a composite failure but execute independently.
   - Discovery cards expose Copy / Not Interested / Original, plus a separate corner × for false positives; neither card nor reader sends X bookmark mutations.
   - A discovery candidate enters `tweets` only when X Bookmarks Sync returns it and persistence is confirmed. The legacy `saved_pending` route is not a user-interface action.
   - Only successful X membership readback, paired with eligible Discovery provenance, produces terminal `bookmark` learning events. The browser feedback route must reject self-reported bookmark events.
   - Human policy defines action semantics, sign and ordinal order only; learned behavior defines magnitude. Do not encode hand-written ratios such as +1/+10/+50 as recommendation truth. Positive order is detail/open < copy < open-original < bookmark; false-positive `×` remains Discovery-quality only; “不想看这类” remains semantic preference only.
   - Discovery rejection has two orthogonal meanings:
     - card-corner `×` = false positive / wrong candidate; remove it from Discovery without lowering topic/author preference, while feeding Discovery quality learning;
     - “不想看这类” = semantic preference feedback; lower similar topic/author recommendations.
   - A valid Discovery impression requires >=50% card visibility for >=1.5s; merely being rendered is not negative evidence.
   - Action magnitude is self-calibrated from decayed aggregate sufficient statistics (not retained raw tweet content/IDs), with monotonic ordering and bounded preference fields.
   - Selection must keep a small exploration budget among already-qualified candidates so the learner does not only confirm prior beliefs.
   - Source-query intent is enforced again after ingestion: replies that leak through X SearchTimeline despite `-filter:replies` are rejected by the cheap gate.
   - Daily selection must optimize diversity, not plain Top-K popularity.
   - Architecture/rationale: `docs/engineering/DISCOVERY_ENGINE.md`.
   - Operational change procedure: `.agents/skills/discovery-plane/SKILL.md`.
   - Executable contracts: `scripts/check_discovery.py`, `scripts/check_feed_contract.py`, `scripts/check_related_hot.py`.

