# Background Sync Architecture

## Why this exists

Personal Cloud is a long-running stateful service, not a web page that happens to fetch data.

The old model was request-driven:

```text
open page
   ↓
browser calls /api/bookmarks/sync
   ↓
X fetch
   ↓
D1 / KV
```

That makes freshness depend on human page visits and turns the UI into a scheduler.

The Cloud Profile now uses an event-driven model:

```text
Cloudflare Cron Trigger
        ↓
on_scheduled
        ↓
sync_service.perform_cloud_sync()
        ↓
X incremental fetch
        ↓
selected storage backend
        ↓
read-back verification
        ↓
sync status metadata

Browser
   ↓
GET /api/tweets
GET /api/sync/status
```

The browser observes state. It does not create freshness.

## Trigger model

All triggers converge on the same application service.

| Trigger | Role | Normal path? |
| --- | --- | --- |
| Cloudflare Cron | periodic background synchronization | yes, Personal Cloud |
| HTTP POST /api/bookmarks/sync | force sync / diagnostics | no, manual override |
| Page load | read persisted state only | never a sync trigger |
| Future Queue / Workflow | long-running enrichment / multi-source jobs | future |

This keeps **Trigger ≠ Sync Logic**.

## Default cadence

The example Personal Cloud profile uses:

```cron
*/15 * * * *
```

That means every 15 minutes.

Cron Triggers run on UTC, but an every-N-minutes cadence is timezone-independent.

The interval is intentionally conservative because Xcollect currently consumes X's Web GraphQL surface rather than a stable paid API contract. Incremental early-stop makes each steady-state run small.

### Positive vs negative events

Incremental sync is excellent at discovering **positive events**: a bookmark ID appears that the repository has never seen.

It cannot safely prove a **negative event** from a partial page: an old ID that is absent from the first 50 results may simply be on page 2, not deleted.

Therefore Cloud Profile uses a dual-speed policy:

```text
every Cron tick
   ↓
incremental scan
   ↓
fast discovery of new bookmarks

every reconcile_interval_hours (default 6h)
   ↓
full scan to natural X timeline end
   ↓
authoritative set difference
   ↓
remove IDs no longer bookmarked on X
```

The manual **立即同步** control always requests a full reconciliation, so it is suitable for validating an X-side unbookmark immediately.

A missing ID is deleted **only** when `scan_complete == true`. If the scan hits `max_sync_pages` before the X timeline ends, Xcollect records the incomplete reconciliation and performs no deletion.

Users can choose a slower Cron cadence in their private `wrangler.jsonc`, and can tune `sync.reconcile_interval_hours` in `config.toml`.

## Cloudflare configuration

```jsonc
{
  "triggers": {
    "crons": ["*/15 * * * *"]
  }
}
```

Deploying with `wrangler deploy` applies the Cron Trigger together with the Worker.

Xcollect's `predeploy` guard checks that a private `wrangler.jsonc` actually contains a cron schedule, so an existing cloud deployment cannot silently regress to manual-only operation.

## Runtime handler

The repository currently retains the legacy global Python Worker handler style because the deployed fetch path already uses it:

```python
async def on_fetch(request, env):
    ...

async def on_scheduled(event, env, ctx):
    ...
```

`wrangler.example.jsonc` explicitly includes `disable_python_no_global_handlers` to keep that compatibility intentional.

A later runtime-only migration may move both handlers to `WorkerEntrypoint`, but scheduled synchronization must not depend on that migration.

## Sync service

`src/sync_service.py` is the application boundary.

It owns:

1. credential validation;
2. active storage-plan discovery;
3. known-ID retrieval;
4. incremental X bookmark fetch;
5. persistence;
6. read-back verification;
7. synchronization status recording.

Neither HTTP routes nor Cron handlers implement those steps independently.

## Storage plan

The Cloud Profile selects one authoritative backend:

```text
D1 binding exists
   ↓
D1 is authoritative
   ↓
do not dual-write to KV
   ↓
D1 failure is visible

D1 binding absent
   ↓
KV binding exists
   ↓
KV is authoritative

neither exists
   ↓
configuration error
```

A transient D1 write error does not silently move new data into KV while reads continue to prefer D1. That would create split-brain state.

## Sync status state machine

The selected backend stores `x_sync_status` / `meta:sync_status`.

States:

```text
never
  ↓
running
  ├── success
  └── failed
```

Important fields:

- `trigger` — e.g. `cron:*/15 * * * *` or `manual`
- `last_attempt_at`
- `last_success_at`
- `error`
- `message`
- `pulled_count`
- `new_count`
- storage diagnostics

The UI reads this through `GET /api/sync/status`.

A failed cron invocation raises an exception after persisting diagnostics so Cloudflare Cron Past Events / Observability also marks the run as failed.

## Manual sync still exists

The button is intentionally retained as **立即同步**.

It is useful for:

- validating newly rotated X credentials;
- testing an X GraphQL protocol change;
- forcing a refresh before debugging;
- verifying D1 / KV connectivity.

It is not the normal freshness mechanism for Personal Cloud.

## Local Profile

Local Profile only exists while the user's process is running, so it currently uses on-demand synchronization.

A future optional local scheduler may run inside the process, but Cloudflare Cron must never become a dependency of Local Profile.

## Testing Cron locally

```bash
pnpm run dev:scheduled
```

Then trigger:

```bash
curl "http://localhost:8787/cdn-cgi/local/scheduled?format=json"
```

To simulate the configured expression:

```bash
curl "http://localhost:8787/cdn-cgi/local/scheduled?cron=*/15+*+*+*+*&format=json"
```

## Future: when to use Workflows

Cron Trigger is the correct primitive for the current bookmark sync because the job is short, incremental and idempotent.

Cloudflare Workflows becomes more appropriate when Xcollect starts doing durable multi-step jobs such as collect → normalize → AI enrich → embed → topology rebuild → resurface.

That transition should be driven by workflow complexity, not by a desire to make the basic scheduler more elaborate.
