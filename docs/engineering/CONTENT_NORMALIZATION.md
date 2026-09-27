# Content Normalization & Canonical Reader

## Product contract

Xcollect has two different presentation surfaces and they must not collapse into the same thing:

```text
Card
= Preview / Projection
= title + short snippet + media preview

Modal / Reader
= Canonical Document View
= source content normalized at ingestion time + local structured rendering
```

A modal that only enlarges the same 140-character snippet has no product value and violates this contract.

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
