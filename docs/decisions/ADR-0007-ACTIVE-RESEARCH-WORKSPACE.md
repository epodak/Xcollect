# ADR-0007 — Active Research is a first-class workspace, not a toolbar panel

Date: 2026-10-10
Status: Accepted in feature/watch-research-workspace

## Context

The first Topic Watch UI placed a watch list, a new-topic form, run-state
text and bespoke simplified result cards *inside the main Feed sorting bar*.
It made deliberate research intent look like a temporary filter, left the
main tweet feed visible underneath, and abandoned the full canonical reader.

The product actually has three orthogonal concepts:
1. System-curated, short-lived Discovery observations.
2. User-owned, durable research **intent** (Topic Watch policy).
3. User-owned, durable **knowledge** confirmed from real X bookmarks.

## Decision

- Add a peer-level `主动探寻` / Active Research scope alongside Discovery,
  Bookmarks and All. This is a workspace view, not a new feed or bookmark owner.
- While viewing research, hide the global taxonomy sidebar and generic Feed
  sort/view controls. Instead use the full content width for a research workbench.
- The left rail lists durable user research tasks, while the right pane presents
  the selected task's explicit question, emphasis directions, latest
  scheduler observations, and ephemeral source evidence.
- A task's `intent` is visible as a research question, not confused with a
  raw SearchTimeline query. A collapsed `检索命中依据` details element shows
  the actual query as verifiable provenance; keyword-match is **not**
  misrepresented as AI semantic relevance.
- Use the existing tweet card renderer, media and canonical document reader.
  Preserve copy/dislike/original interactions; never reintroduce an X
  CreateBookmark proxy button.
- Empty results are distinct from an unavailable source, paused tracking,
  active local filtering, a task not yet selected in round-robin polling, and
  source candidates filtered out under the 24h/quality constraints.
- On mobile, the task rail becomes a horizontal selector and results remain
  single-column. All new surfaces respect shared light/dark design tokens.
- Watch result items remain out of the primary Feed's `tweets` ownership
  collection. A small lookup fallback in copy, reader and feedback logic
  allows using existing interactions without double-counting them in global
  Feed totals or saving raw Watch items to the bookmarks database.

## Non-goals

No server-side LLM generated research report, semantic judgment by the watch
intent, permanent Watch result archive, X bookmark write path, or inferred
"research conclusion" is shipped in this UI change. Topic Watch v1's backend
still uses explicit keyword query expansion and shared global Discovery quality.
Future topic-specific semantic relevance and hypothesis/contradiction clustering
should be an independent, measurable backend phase.

## Regression contracts

`scripts/check_watch_workspace.py` verifies independent workspace hierarchy,
single canonical reader, query provenance, and responsive behavior. CI
checks JS syntax and the existing Discovery/Bookmark consistency contracts.
