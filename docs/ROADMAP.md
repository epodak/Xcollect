# Xcollect Roadmap

> **X = Exploration.**
>
> Xcollect is not intended to be only an X / Twitter bookmark manager.
> X / Twitter is the first acquisition adapter and the first complete vertical slice of a broader exploration system.

## 1. Product thesis

People continuously encounter things that feel valuable:

- a tweet worth revisiting;
- a GitHub repository that may solve a future problem;
- a browser page saved for later;
- a Reddit discussion;
- a YouTube video;
- an RSS article;
- a place to visit;
- a product to evaluate.

The platforms provide different verbs — **Bookmark, Star, Save, Favorite, Watch Later, Wishlist** — but these actions are structurally similar.

They all express a weak future intent:

```text
encounter(item)
    ↓
interesting(item) = True
    ↓
save(item)
    ↓
"maybe useful later"
```

Most systems preserve the item and timestamp, but lose the context:

- Why did I save this?
- What was I exploring at the time?
- Which project or problem was it related to?
- What did it resemble?
- What should happen next?
- Is there now a better alternative?

Xcollect exists to preserve, enrich and resurface that exploration state.

## 2. Core invariant

The invariant across sources is not "bookmark" and not even "knowledge".

It is:

> **A human generated a weak future intent while exploring.**

A normalized exploration object should therefore converge toward:

```text
ExplorationItem
├── source
├── source_id
├── url
├── title
├── author
├── content
├── media
├── saved_at
├── captured_at
├── context
├── intent
├── project
├── category
├── sub_category
├── relations
├── status
└── source_metadata
```

Source-specific fields belong in adapters or `source_metadata`; the core model should remain source-neutral.

## 3. Canonical flow

```text
Encounter
   ↓
Collect
   ↓
Normalize
   ↓
Enrich
   ├── summary
   ├── category / sub-category
   ├── intent
   ├── context
   └── relations
   ↓
Organize
   ↓
Resurface
   ↓
Act
```

The product goal is not "help me save more".

The product goal is:

> **Make things I once considered valuable findable, understandable and actionable again.**

## 4. Architecture direction

Xcollect should evolve from a Twitter-shaped application into an adapter-driven exploration platform.

```text
                         Xcollect Core
                              ▲
                              │
                    Acquisition Adapters
          ┌───────────────────┼───────────────────┐
          │                   │                   │
       Twitter/X           GitHub              Browser
          │                   │                   │
       Reddit             YouTube               RSS
          │                   │                   │
       future...           future...           future...
          └───────────────────┼───────────────────┘
                              │
                         Normalization
                              │
                           Enrichment
                  ┌───────────┼───────────┐
                  │           │           │
                Summary     Intent     Context
                  │           │           │
                  └───────────┼───────────┘
                              │
                     Knowledge Topology
                              │
                         Resurfacing
```

Acquisition must remain replaceable. For a given source, several collectors may coexist:

- direct API / GraphQL;
- browser extension;
- userscript;
- passive network interception;
- import/export file;
- webhook or bot interaction.

The collector is an adapter, not the product.

## 5. Roadmap

### Phase 0 — Twitter/X vertical slice — Current

Status: **implemented / evolving**

Current capabilities establish the first complete source adapter:

- X / Twitter bookmark synchronization;
- local-first operation;
- Cloudflare D1 / KV / local storage cascade;
- pluggable AI classification;
- category + `sub_category`;
- topology renormalization;
- searchable visual dashboard;
- reversible interaction with X bookmarks where supported.

The immediate goal of this phase is to make the current adapter reliable while removing Twitter-specific assumptions from the core data model.

### Phase 1 — Source-neutral core

Status: **next architectural milestone**

Refactor toward:

```text
CollectorAdapter
      ↓
ExplorationItem
      ↓
Normalizer
      ↓
Enricher
      ↓
Repository
      ↓
Topology / Search / Resurfacing
```

Key work:

- introduce a source-neutral `ExplorationItem` schema;
- isolate Twitter-specific parsing and credentials behind an adapter boundary;
- define adapter capability flags such as `read`, `write_back`, `delete`, `incremental_sync`;
- preserve raw source payload for forward compatibility;
- add source-aware deduplication and canonical URLs;
- keep UI filtering source-neutral.

### Phase 2 — GitHub Stars adapter

Status: **highest-priority next source**

GitHub Stars have almost the same semantics as X bookmarks:

> "This looks useful; I may need it later."

But GitHub adds richer lifecycle signals:

- repository activity;
- latest release;
- archived / maintained state;
- language / topics;
- forks and alternatives;
- relation to the user's own projects.

Desired enrichment:

```text
GitHub Star
   ↓
Why did I star it?
   ↓
Which exploration theme / project?
   ↓
Is it still maintained?
   ↓
Did a better alternative appear?
   ↓
Should I revisit, adopt, archive or forget it?
```

This adapter should become the reference implementation proving that Xcollect is no longer Twitter-specific.

### Phase 3 — Browser capture

Target forms:

- Chrome / Chromium extension;
- Firefox extension where practical;
- lightweight userscript for selected sites;
- "Save to Xcollect" context-menu action.

The browser adapter should capture more than a URL when possible:

- page title;
- selected text;
- surrounding context;
- current search query / referrer when safe;
- user note;
- open tab group / project context.

A key design question is how much context can be captured without becoming intrusive. Context capture should be explicit, inspectable and configurable.

### Phase 4 — High-value knowledge sources

Candidate adapters:

| Source | Native action | Normalized meaning |
| --- | --- | --- |
| Reddit | Save | revisit this discussion |
| YouTube | Watch Later / playlist | watch or learn later |
| RSS | Star / save | retain this article |
| Hacker News | Favorite | retain this technical discussion |
| Read-it-later services | Save | defer reading |
| Podcasts | Save episode / timestamp | revisit this idea |
| Email | Star / label | revisit or act later |

Priority should be determined by adapter reliability and information value, not adapter count.

### Phase 5 — Exploration beyond "knowledge"

Once the core model is stable, Xcollect may extend to weak intent outside traditional knowledge management.

Examples:

| Domain | Native action | Weak intent |
| --- | --- | --- |
| Maps | Save place | maybe visit later |
| E-commerce | Wishlist / cart | maybe buy later |
| Travel | Save hotel / flight | maybe use later |
| Media | Watchlist | maybe consume later |

These sources test whether `ExplorationItem` is genuinely general or still biased toward documents.

## 6. Context Envelope

A major long-term differentiator should be preserving **why** something was collected.

At collection time, Xcollect should be able to attach an optional Context Envelope:

```text
ExplorationEvent
├── item
├── source
├── timestamp
├── active_project
├── search/query context
├── nearby items
├── explicit note
├── inferred intent
└── confidence
```

Inference must remain distinguishable from user-provided facts.

The important transition is:

```text
save(item)
```

to:

```text
save(item, context, intent)
```

## 7. Topology renormalization

Xcollect should avoid turning AI tagging into a constantly changing taxonomy.

The working hypothesis remains:

1. new items project into existing stable categories;
2. free-form secondary labels absorb local novelty;
3. local accumulation creates pressure for structural change;
4. only when density / novelty passes a threshold does global re-clustering occur;
5. stable categories become long-lived coarse-grained representations of the user's exploration.

```text
new item
   ↓
project to existing category
   ↓
local sub_category
   ↓
accumulation / density change
   ↓
renormalization event
   ↓
split / merge / settle
```

The invariant is not any specific taxonomy. The invariant is continuity of the user's exploration history while the representation evolves.

## 8. Resurfacing is a first-class subsystem

Collection without resurfacing recreates the same graveyard in a better database.

Future resurfacing mechanisms may include:

- "you saved this one year ago";
- unresolved clusters with many saved items but no action;
- GitHub repositories whose maintenance status changed;
- items connected to the user's current project;
- old items made newly relevant by a recent save;
- duplicate or superseded tools;
- exploration timelines by theme.

The system should eventually answer:

> **What have I been exploring, how has that exploration changed, and what is worth revisiting now?**

## 9. Non-goals / design constraints

Xcollect should not become:

- another infinite read-later inbox;
- a forced cloud SaaS;
- a source-specific scraping monolith;
- an AI auto-tagging demo with no lifecycle;
- a taxonomy that reorganizes itself on every new item.

Design constraints:

- local-first where practical;
- self-hostable;
- adapters are replaceable;
- raw data remains exportable;
- source credentials remain isolated;
- AI providers remain replaceable;
- inferred metadata remains auditable;
- graceful degradation when a source changes or blocks an adapter.

## 10. Fixed-point hypothesis

At small scale, Xcollect looks like a bookmark manager.

At medium scale, it becomes a personal knowledge topology.

At large scale, the fixed point is closer to:

> **a personal exploration memory layer across the internet.**

The system should gradually compress thousands of individual saved items into a smaller number of durable exploration themes without destroying the ability to recover the original evidence.

## 11. External reference landscape

The roadmap should be evaluated against adjacent products and open-source projects rather than in isolation.

See:

- [Exploration Tools Landscape](./research/EXPLORATION_TOOLS_LANDSCAPE.md) — X/Twitter bookmark tools, GitHub Stars managers, self-hosted bookmark systems, multi-source collection systems, agent-memory projects, and build-vs-borrow references.

This research is maintained separately from the roadmap so market observations can change without rewriting the product thesis.

---

Current implementation starts with X / Twitter because it provides a concrete, high-frequency test bed.

The roadmap deliberately treats it as **Adapter 01**, not as the definition of Xcollect.
