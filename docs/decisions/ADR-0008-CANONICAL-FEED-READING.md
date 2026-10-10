# ADR-0008: Canonical-first Feed Cards and Inline Reading

- Date: 2026-10-10
- Status: Proposed (feature branch, pending CI and visual acceptance)
- Scope: Feed presentation in both Bookmark and Discovery planes; no storage or recommendation schema change.

## Problem

The mobile feed showed a generated large title and the first 140 characters of `snippet` inside an oversized equal-height panel. CSS capped the text to 3 lines on mobile / 6 lines elsewhere and `min-height: 420px` plus flex stretching manufactured empty space. The user had to enter a separate reader to read an ordinary tweet even though canonical `body_raw` was already ingested and persisted.

## Decision

1. Card is a **readable canonical projection**, not a teaser. Source of truth: `body_raw`; `snippet` only as an explicitly flagged fallback.
2. Ordinary posts render directly in the card, with paragraph/Markdown structure and any video or image below the text.
3. Long documents (currently >1600 characters) include all canonical text but start with a height limit of 26rem; users can expand/collapse in place, without a modal. Threshold is a UX tuning value, **not** a data truncation limit.
4. If the generated title duplicates the first sentence/prefix of the body, suppress the duplicate visual title.
5. Remove artificial equal card heights; keep the canonical reader as optional focused mode and for complex source content.
6. Preserve security: render normalized Markdown with the existing escaped safe renderer; sanitize URLs. Preserve feedback and bookmark separation. A deliberate inline expand may record `open_detail` with `surface=feed_inline` but **never** `bookmark`.

## Alternatives

- Merely reduce title font size: rejected; does not resolve missing text or giant white panels.
- Increase snippet to 500 characters: rejected; still arbitrarily truncates and duplicates already available canonical data.
- Open modal on every card interaction: rejected for routine reading; interrupts discovery workflow.
- Show full multi-thousand-character articles in every feed card by default: rejected; ruins scan efficiency; inline expansion retains full access.

## Acceptance

- A short post with `body_raw` longer than 140 characters shows the tail content without opening a modal.
- Generated first-line titles do not appear duplicated.
- 2000-character posts show an inline `展开全文` control and preserve the terminal source text.
- No unnecessary empty 420px card panel, or mobile 3-line clipping of canonical content.
- User content is HTML escaped; media and reader still work.
- `pnpm run check` includes the new deterministic `scripts/check_feed_card_reading.mjs` regression suite.
- Manual iPhone viewport review remains required before merging/deploying.

## Follow-up

Measure preference for short-complete vs long-collapsed reading, viewport and content length distributions, and expand-to-original rates before retuning threshold. No schema changes or unverified AI-generated summaries are introduced.
