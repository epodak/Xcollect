# Xcollect — Product Truth

> Status: product context for the Impeccable design workflow. This is a factual/product contract, **not** a record that the proposed visual redesign has shipped.
> Canonical engineering invariants: [AGENTS.md](AGENTS.md). Architecture/roadmap: [docs/ROADMAP.md](docs/ROADMAP.md).

## Platform and audience

Local-first personal exploration memory, available through a Python local web app and optional Cloudflare Personal Cloud. The immediate high-frequency interface is an X/Twitter-derived discovery and bookmarked-content feed. The primary user is someone who repeatedly explores technical, product and research topics and wants a faster, more useful reading flow than manually browsing X.

## User jobs and outcomes

1. **Read:** comfortably scroll new, relevant discoveries, with full source text, images, videos and attributed quoted posts; do not force entry to a detail screen for ordinary reading.
2. **Decide:** quickly identify what matters and distinguish ephemeral discoveries from durable bookmarks.
3. **Act:** copy, inspect the original, signal a false positive, indicate semantic disinterest or save through an explicitly verified X flow. Actions must preserve the source/provenance contract.
4. **Research:** specify a lasting topic/question in the Active Research workspace, examine evidence and return later.
5. **Recover:** find durable information again, in original context, rather than merely accumulating saves.

## The product problem to solve first

The user still habitually browses X even though Xcollect already includes relevant personalized discovery and saved information. Their reported blocker is **low desire to spend time reading the existing interface**: it looks cramped and unattractive, emphasizes controls/chrome over content, and sometimes interrupts the reading flow with truncated cards or fragmented quotations.

**North-star hypothesis:** When the feed feels like an editorial reading surface rather than an administrative dashboard, the user will choose Xcollect as their everyday entry point. This hypothesis requires actual usage and screenshot review; it is not yet validated.

## Positioning and product personality

Personal exploration reader and research workspace — not a generic analytics dashboard, productivity landing page or second X clone. Editorial, calm, content-first, dense enough for serious reading, with predictable controls. Features do not justify extra permanent chrome unless they improve a frequent task.

## Current capabilities versus constraints

- Current repository has Discovery (24h ephemeral), Bookmarks (durable), Active Research/Topic Watch (durable intent), and an All view.
- The cloud is optional; Local Profile must stay first-class. Visual improvements may not introduce Cloudflare, D1, AI or authentication as basic reading requirements.
- Canonical feed text uses `body_raw`; `snippet` is fallback, not the normal truncated substitute. Quote attribution must stay intact. Preserve explicit source/author identity and link to original.
- A Discovery card is **not** a saved bookmark. Discovery may expose Copy, Not Interested, Original and false-positive ×, but cannot silently create a bookmark or claim it succeeded.
- Keep keyboard access, visible focus, mobile adaptation, reduced-motion support, performant image loading, and light/dark legibility.

## Evidence versus assumptions

Observed in repository (2026-10-16): `public/index.html` has many header actions, a sidebar, four feed scopes, seven sort modes and three view toggles. Styles live in `public/css/theme.css`, `layout.css`, `cards.css`, `modal.css` and `watch.css`. The CSS has small card-body text, clamped snippets and decorative surfaces/glows. These are **code observations**, not proof of the live page's appearance or conversion rates.

User-reported evidence: they prefer visiting X because this interface feels ugly and unrewarding to scroll. No measured retention, completion, session-time or before/after usability benchmark has been established.

## Product principles

1. **Content over chrome.** Make the first viewport about the next interesting item; move maintenance/synchronization actions to progressive disclosure.
2. **Reading before drilling.** Normal posts are readable in-feed. Long documents expand inline with obvious continuity; an optional reader is still available.
3. **Semantic honesty.** Clear provenance (Discovery vs Bookmark) and clear feedback meanings; no fake success states.
4. **One visual language.** Shared tokens, type, spacing and states across feed, research and reader.
5. **Evidence before adjectives.** Prefer a testable screenshot difference, accessibility check and observed usage to the claim that a page looks “more premium”.
6. **Regression-safe redesign.** Preserve API, events, source-data semantics, Local/Cloud parity and existing acceptance checks.

## Measurable acceptance candidates

- In a normal session, the user can read ordinary text posts and attributed quotes in the feed without mandatory modal navigation.
- At mobile widths (~375px), no horizontal overflow or hidden primary actions; at desktop (~1440px), a readable column does not stretch text to an exhausting measure.
- Keyboard controls and focus are visible; color/contrast evaluated against WCAG 2.1 AA where applicable.
- A visual baseline captures Discovery, Bookmarks, Watch and reader in both themes, at mobile and desktop widths.
- Every design PR states before/after visual evidence, explicit interaction checks, `pnpm run check` status and whether production deployment was performed.

## Non-goals for the first redesign

A brand-new framework, decorative motion for its own sake, full X feature parity, forced redesign of backend discovery ranking, new database schema or replacing readable text with AI summaries.
