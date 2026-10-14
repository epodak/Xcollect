# ADR-0009: Quoted Tweets Are First-Class Nested Content

- Date: 2026-10-14
- Status: Accepted for implementation
- Scope: Local/Cloud X adapters, D1/KV/Local storage, feed, reader, export.

## Problem

A quote-tweet is a relation between two independently authored X statuses. Previous
canonical ingestion concatenated the quoted status into parent Markdown. A linewise
Markdown renderer fragmented the quote into unrelated visual blocks; the grouped
legacy renderer improved readability but could not safely retain quoted author,
media, publication time and source identity.

## Decision

1. Keep primary `body_raw` limited to the parent Tweet source body.
2. Add one nullable `quoted_tweet` object with `id, author, username, avatar,
   url, created_at, body_raw, images, videos`. Do not recursively fetch nested
   quotes or infer missing text.
3. Parse at the X adapter; store JSON object unchanged in Local and KV, serialize
   as JSON TEXT in the D1 `tweets.quoted_tweet` column. Writer upgrades old D1
   schemas idempotently; read path tolerates missing field. Discovery's payload
   already supports the object.
4. Embed one compact Tweet card under the parent in both feed and reader, with
   distinct clickable source link, author identity, paragraph and media support.
   Never enlarge the main card purely to fake a visual quote.
5. Compose portable Markdown from primary body + source metadata + quote
   only **on export**. Do not make portable Markdown the canonical data model.
6. Preserve historical flattened `> 引用` snapshots without parsing them into
   inferred entities. Backfill via authoritative X full reconciliation only.
7. Preserve existing bookmark/discovery semantic and feedback boundaries.

## Invariants

- Parent body != quoted body; parent media != quoted media.
- Exactly one visible embedded quote card per structured quoted status.
- No duplicated quote after backfill. Old records remain readable.
- All user text is escaped, URL handling limited to http/https.
- No X API action or external navigation happens on hover or render.
- Neither Local Profile nor no-quote records require schema management.

## Verification

- `tests/test_quoted_tweet_reader.py`: GraphQL projection, source identity, media.
- `tests/test_structured_quote_storage.py`: D1 legacy upgrade, JSON round-trip,
  reconciling a removed quote.
- `scripts/check_feed_card_reading.mjs`: embedded card, Markdown export,
  media and XSS, plus legacy Markdown blockquote.
- `pnpm run check` acceptance gate before Cloudflare deployment.

## Deferred

Quote graph indexes, multiple quoted source relations, thread expansion, deleted
quote tombstones and UI quote-to-knowledge-graph navigation are separate features.
