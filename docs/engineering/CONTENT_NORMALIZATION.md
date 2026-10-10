# Content Normalization & Canonical Reader

## Product contract

Xcollect has two complementary presentation surfaces. Users should be able to read an ordinary X post *without opening a modal*:

```text
Feed Card
= readable canonical projection
= metadata + body_raw + media
= short/ordinary post displayed completely
= very long document initially height-collapsed, expandable in place

Optional Modal / Reader
= structured canonical document
= focused reading, evidence, copy/export, media and source context
```

Never stretch a 140-character `snippet` into a large fixed-height box. Feed cards use `body_raw` when available and show a visible incomplete-source warning when only `snippet` remains. A modal that only enlarges an incomplete 140-character snippet is not a substitute for ingestion normalization.

## Canonical source precedence

For an X bookmark, the ingestion adapter must prefer the richest source representation available:

```text
X Article
article.article_results.result.content_state.blocks
        ↓
Note Tweet
note_tweet.note_tweet_results.result.text
        ↓
legacy Tweet
legacy.full_text
```

`legacy.full_text` is not a reliable full-text source for Note Tweets. It may be only the legacy preview/truncated representation.

X Article content uses a Draft.js-like block structure. Xcollect normalizes those blocks into portable Markdown so the repository does not depend on X's rendering runtime.

## Why normalization happens during ingestion

The reader should not need to scrape X every time a user opens a modal.

```text
X GraphQL
   ↓
source-specific parse
   ↓
canonical Markdown / media
   ↓
body_raw + structured media
   ↓
JSON / D1 / KV
   ↓
Reader
```

This gives Xcollect a durable source snapshot and keeps the UI deterministic.

## Refreshing old records

Parser improvements must be able to upgrade already-known bookmarks.

Normal incremental sync avoids rewriting existing IDs.

Full reconciliation deliberately refreshes source-owned fields for existing IDs so an old record such as:

```text
legacy 280-char preview
```

can become:

```text
full Note Tweet / Article canonical body
```

without losing Xcollect-owned semantic fields such as `category`, `sub_category`, and `classify_status`.

## Reader rendering

The reader:

- renders the canonical title separately from the body;
- avoids repeating the title when it is also the first body line;
- renders headings, lists, blockquotes, code and links;
- renders stored images and videos;
- supports the `{url, poster, type}` video object used by the adapter;
- escapes source text before applying limited Markdown semantics;
- warns when an old record still looks like a truncated legacy `t.co` preview.

## Media

Regular tweet media comes from `legacy.extended_entities`.

X Article inline images are extracted from `content_state` atomic media entities when available and normalized into Markdown image blocks plus stored media references.

## Quoted tweets

The Cloud adapter currently folds one quoted tweet level into the canonical document as a blockquote so the local reader does not lose obvious source context.

## What is NOT yet equivalent to a canonical document

### Multi-tweet threads

A bookmark points to one status. A self-thread is a conversation graph, not a property of one bookmark timeline entry.

Xcollect does not yet claim to reconstruct the author's entire self-thread.

A future Thread Enrichment stage should:

```text
bookmarked status
   ↓
TweetDetail / conversation graph
   ↓
same-author continuation detection
   ↓
ordered thread document
   ↓
cache as canonical Exploration document
```

This should be an enrichment step, not something silently inferred from missing data.

## Engineering invariant

Do not display `snippet` as the primary Modal body when a richer `body_raw` can be collected.

`snippet` exists for cards/search previews. `body_raw` is the canonical reader source.


## Feed card reading contract (2026-10-10)

- Normal short/medium X posts: render all of `body_raw` in place, preserving paragraphs, Markdown structure and safe URLs.
- Very long posts: source is still complete in the DOM; the initial visual region is height-limited and `展开全文` expands in the same card, without navigating or replacing the feed state.
- If a generated title is only the leading prefix of the body, hide that duplicate title instead of rendering the first sentence twice.
- CSS must not force `min-height: 420px`, equal-height stretching, or mobile three-line snippet clipping on canonical card content.
- Only a user-chosen reading-mode action opens the detail reader; opening the original uses X without assuming a bookmark.
- Explicit inline expansion is an `open_detail` reading signal with `surface=feed_inline`, never a terminal bookmark event.
- A `body_raw` gap is a source-quality issue; no front-end treatment may claim to reconstruct missing tweet/thread text.
- Regression check: `node scripts/check_feed_card_reading.mjs` (part of `pnpm run check`).
