# X Bookmark Sync & D1 Persistence Contract

> Production path: Cloudflare Python Workers + D1

## 1. Sync invariant

Each bookmark synchronization run — scheduled or forced manually — is deliberately:

```text
X GraphQL
   ↓
Fetch / Parse
   ↓
Rule Projection (zero remote AI calls)
   ↓
D1 upsert
   ↓
D1 read-back / status
   ↓
Optional AI deep classification
```

`sync_service.perform_cloud_sync()` MUST NOT call one remote AI request per bookmark.
AI enrichment is a separate lifecycle through `POST /api/bookmarks/classify`.

Repeated X syncs refresh source facts such as text, author, metrics and media,
but MUST NOT overwrite an existing user's semantic classification.

## 2. Production credentials

The deployed Worker reads these secrets:

- `X_AUTH_TOKEN`
- `X_CT0`

Cloudflare Worker Secrets cannot be persisted by an application HTTP request.
Therefore production `POST /api/auth/save` explicitly reports that runtime secret
writes are unsupported instead of pretending that credentials were saved.

Configure production secrets from the operator environment:

```bash
npx wrangler secret put X_AUTH_TOKEN
npx wrangler secret put X_CT0
```

Both values must come from the same authenticated `x.com` browser session.

## 3. X GraphQL queryId rotation

X Web GraphQL query IDs are implementation details and may rotate.

Resolution order for `Bookmarks`:

1. live registry configured by `twitter.query_id_registry_url`;
2. `twitter.query_id_bookmarks`;
3. `twitter.query_id_bookmarks_fallbacks`.

A single hard-coded queryId is not a stable integration contract.

## 4. D1 query-budget invariant

Xcollect targets Cloudflare Workers Free as a supported deployment mode.

Do **not** write one bookmark with one D1 query. A sync may contain hundreds of
bookmarks, while a Free Worker invocation has a bounded subrequest/query budget.

The persistence path therefore uses a JSON bulk UPSERT:

```text
Python list[bookmark]
        ↓ JSON
one/few bound payloads
        ↓
json_each(?)
        ↓
INSERT ... SELECT ... ON CONFLICT DO UPDATE
```

This keeps D1 round trips approximately O(payload chunks), not O(bookmarks).

The current sync response exposes `storage.d1_queries` so this invariant remains observable.

## 5. Bookmark-order invariant

Tweet `created_at` is **not** bookmark time. A user can bookmark a five-year-old
post today.

X's timeline entries contain `sortIndex`, which defines timeline ordering. The
adapter preserves that ordering, and D1 stores the current bookmark ID order in
`meta_kv.x_bookmark_order`.

`GET /api/tweets` adds:

- `bookmark_position = 0` for the newest bookmark;
- increasing positions for older bookmarks.

The frontend defaults to `bookmark_desc` ("最近收藏") rather than engagement
sorting.

## 6. Persistence truth

A successful sync means both:

1. X returned a parseable bookmark timeline; and
2. the payload was accepted by an available persistence backend.

The sync response includes:

- `pulled_count`
- `fetch.query_id`
- `fetch.query_id_candidates`
- `fetch.pages_fetched`
- `fetch.query_failures`
- `storage.d1_bound`
- `storage.d1_written`
- `storage.d1_row_count`
- `storage.d1_error`
- `storage.backend`
- `storage_status`

`GET /api/storage/status` independently checks whether D1 is bound, whether the
`tweets` table is queryable, and the current D1 row count.

After any synchronization run, the Worker performs a repository read-back before reporting success.
The browser independently reads `/api/tweets`; page load is not a source-sync trigger.
The `fresh` path bypasses the Worker isolate's in-memory tweet cache.

The Worker performs read-back **inside the shared sync service**. If the X head IDs and
the repository head IDs disagree, the run records `READBACK_MISMATCH` instead of a false success.
For Cron runs, the scheduled handler then raises so Cloudflare Observability records a failed event.

`/api/tweets` is intentionally returned with `Cache-Control: no-store`.
Private bookmark state must not use public CDN stale-while-revalidate caching.

## 7. X-side unbookmark reconciliation invariant

X bookmarks are a set with both positive and negative changes.

- **Positive event:** an ID appears on X that is not in the repository → UPSERT/add.
- **Negative event:** an ID exists in the repository but no longer exists in X Bookmarks → remove locally.

A partial incremental fetch is never sufficient evidence for a negative event.

Deletion is allowed only after a full scan reaches the natural end of the X Bookmarks timeline:

```text
full_scan = true
AND scan_complete = true
        ↓
remote_ids = authoritative set
        ↓
removed_ids = local_ids - remote_ids
        ↓
delete removed_ids
```

If `max_sync_pages` truncates the scan, `scan_complete=false` and **no missing ID is deleted**.

Cloud Profile performs a full reconciliation periodically (default every 6 hours) while keeping normal Cron runs incremental. Manual **立即同步** forces a full reconciliation.

The direct UI “移出 X 收藏” path remains separate and immediate:

```text
DeleteBookmark on X succeeds
        ↓
delete the same ID from the selected local/cloud repository
```

## 8. D1 upsert invariant

Full X sync is idempotent.

On an existing tweet ID:

- refresh source facts: text, author, username, metrics, media, URL, timestamps;
- preserve existing `category`, `sub_category`, and `classify_status`;
- only fill semantic fields when the existing value is absent / unclassified.

This prevents every full sync from degrading previously AI-classified items back
to `projected`.

## 9. First-deploy / recovery checklist

```bash
pnpm run d1:init:remote
npx wrangler secret put X_AUTH_TOKEN
npx wrangler secret put X_CT0
pnpm run deploy
```

Then inspect:

```text
GET  /api/auth/status
GET  /api/storage/status
GET  /api/sync/status
GET  /api/tweets?fresh=1
```

Personal Cloud should normally synchronize from the configured Cloudflare Cron.
`POST /api/bookmarks/sync` remains available as a force-sync / diagnostic control.

Expected invariants:

- `auth/status.configured == true`
- `storage/status.d1_bound == true`
- `storage/status.d1_ready == true`
- successful production sync normally reports `storage.backend == "d1"`
- `d1_row_count` is non-null and agrees with persisted data
- repeated sync does not erase settled classifications

## 10. Failure codes

### `X_CREDENTIALS_MISSING`

Production Worker Secrets are absent. The browser form cannot fix this.

### `STORAGE_PRECHECK_FAILED`

The selected cloud storage backend could not be read before X synchronization began.
This is a D1/KV configuration or health problem, not an X protocol problem.

### `X_SYNC_FAILED`

The upstream X operation failed. Inspect the returned message and
`fetch.query_failures` where available. Common classes are expired session
cookies, CSRF mismatch, rotated GraphQL query IDs, or an upstream schema change.

### `PERSISTENCE_FAILED`

X retrieval completed but D1/KV persistence did not. Inspect
`storage.d1_error` and `GET /api/storage/status`.

A missing-table/schema error generally means the remote D1 schema has not yet
been initialized with `pnpm run d1:init:remote`.

## 11. Smoke gate

Before deployment:

```bash
pnpm run check
pnpm run check:cloud-schedule
```

The check validates, among other project assets:

- generated config projection parity;
- multiline TOML arrays;
- non-empty Bookmarks queryId fallback;
- seed data validity.
