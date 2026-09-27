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
