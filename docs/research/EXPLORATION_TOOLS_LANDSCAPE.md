# Exploration Tools Landscape

> Market / adjacent-project reference for Xcollect  
> Snapshot date: **2026-09-26**
>
> This document is intentionally placed under `docs/research/`, not `docs/engineering/`.
> It describes the external landscape that informs product boundaries, architecture decisions,
> and "build vs. borrow" choices. Internal implementation specifications belong in
> `docs/engineering/`.

## 1. Why this research exists

Xcollect started from X / Twitter bookmarks, but **X = Exploration**.

The broader problem is not specific to Twitter:

```text
Encounter something valuable
        ↓
Bookmark / Star / Save / Favorite / Watch Later
        ↓
Weak future intent
        ↓
Platform-specific silo
        ↓
Often never revisited
```

The market already contains many products that solve one or more parts of this chain:

- acquisition / export;
- archiving;
- organization;
- AI tagging;
- semantic retrieval;
- read-later;
- resurfacing;
- review workflows;
- conversion into notes / knowledge;
- agent-accessible personal memory.

Xcollect should not reimplement mature solutions blindly. This landscape is a reference for:

1. identifying structurally similar systems;
2. borrowing proven acquisition and storage patterns;
3. recognizing crowded commodity layers;
4. isolating Xcollect's own hypotheses;
5. tracking projects whose evolution may affect our roadmap.

---

## 2. Market map

A useful coarse-graining is to separate the market by **job**, not by product label.

```text
Source
  ↓
Acquire
  ↓
Archive
  ↓
Normalize
  ↓
Organize / Enrich
  ↓
Review / Resurface
  ↓
Convert
  ↓
Decision Context / Agent Memory
```

Most existing products dominate only a subset of this pipeline.

Xcollect's long-term ambition spans the pipeline, but the individual layers should remain replaceable.

---

# 3. X / Twitter-specific tools

## 3.1 xarchive

**Project:** https://github.com/sytelus/xarchive

Position:

```text
X session
  ↓
internal GraphQL
  ↓
complete bookmark archive
  ↓
IndexedDB / JSON
  ↓
local viewer + search
```

Notable characteristics:

- Chrome Manifest V3 extension;
- captures authentication/query information from normal X browsing;
- uses X's internal GraphQL rather than the official API;
- dynamically discovers rotating GraphQL query IDs;
- exports complete bookmarks and X Premium folders;
- local-first, no server;
- pause/resume, incremental archive semantics, identity checks;
- standalone searchable viewer.

### Reference value for Xcollect

**Do not reinvent blindly:**

- dynamic query-ID discovery;
- authenticated-account identity pinning;
- conservative rate limiting and backoff;
- snapshot vs cumulative archive semantics;
- partial recovery;
- folder coverage verification.

xarchive is currently one of the strongest references for the **X acquisition adapter**.

---

## 3.2 TBD / twitter-bookmarks-downloader

**Project:** https://github.com/0x1b2c/twitter-bookmarks-downloader

Position:

```text
X Web App
  ↓
normal XMLHttpRequest responses
  ↓
Userscript passive interception
  ↓
localhost Go daemon
  ↓
SQLite + media archive
```

Its key architectural idea is **Passive Interception**:

> Do not recreate every private API request if the browser is already receiving the data.

Notable characteristics:

- Tampermonkey/userscript acquisition;
- hooks XHR responses;
- local Go backend;
- SQLite;
- media-first preservation;
- incremental and deep recovery modes.

### Reference value for Xcollect

Xcollect should keep acquisition pluggable:

```text
XAdapter
├── DirectGraphQLCollector
├── BrowserExtensionCollector
└── PassiveUserscriptCollector
```

The userscript path may be more resilient in some failure modes than direct request emulation.

---

## 3.3 BookmarkDeepX

**Project:** https://github.com/KeremDev/BookmarkDeepX

A local-first Chrome extension for managing X bookmarks without depending on the official X API.

### Reference value

Useful as a lightweight reference for:

- browser-native UX;
- local-first bookmark organization;
- extension packaging and distribution.

---

## 3.4 XSaved

**Chrome Web Store:** https://chromewebstore.google.com/detail/xsaved-%E2%80%94-bookmark-manager/nefnhjnjkpimffifpbpdogjoglpjihdn

Position:

- local-first X bookmark manager;
- folders, notes, tags, search and export;
- optional sync;
- paid mobile tier adds semantic search, smart topics and related saves.

### Reference value

Shows that X bookmark management is already a crowded product category.

"Search + tags + AI topics" by itself is not a durable Xcollect differentiation.

---

## 3.5 XBookmark

**Chrome Web Store:** https://chromewebstore.google.com/detail/xbookmark-twitter-bookmar/fmhmeljlbkjibmimlgnijjffmjgbabch

Focus:

- local capture;
- tags;
- search;
- Markdown / JSON export;
- privacy-first browser operation.

### Reference value

Markdown / JSON portability should be treated as baseline functionality rather than a differentiator.

---

## 3.6 Totem

**Chrome Web Store:** https://chromewebstore.google.com/detail/twitter-x-bookmarks-on-ne/acpkgdfhoaalmnhjifhneghcgfnjkglo

Totem attacks a different failure mode:

> the bookmark exists, but the user never sees it again.

It places X bookmarks on the browser new-tab page and creates time-sized reading queues.

### Reference value

Totem is an important reference for **resurfacing**.

Xcollect should not stop at:

```text
collect → classify → search
```

It needs:

```text
collect → classify → resurface → act
```

---

## 3.7 Scrollmark

**Project:** https://github.com/kmccleary3301/scrollmark

A local-first userscript-based X/Twitter research archive and search workbench.

It observes GraphQL/API responses while browsing and builds a portable research archive.

### Reference value

Useful reference for:

- passive observation;
- research-oriented archive UX;
- portable bundle formats;
- local-first capture.

---

## 3.8 x2o

**Project:** https://github.com/kiki123124/x2o

Position:

```text
X bookmarks
  ↓
AI classification
  ↓
summary
  ↓
structured Obsidian vault
```

Supports many AI providers, including local models.

### Reference value

x2o demonstrates the **conversion** layer:

> saved item → durable knowledge artifact.

Xcollect should remain able to export into systems such as Obsidian rather than trying to replace every downstream PKM tool.

---

## 3.9 Dewey

**Product:** https://getdewey.co/

Dewey focuses specifically on organizing X / Twitter bookmarks using:

- browser extension sync;
- search;
- folders / collections;
- AI-assisted tagging.

### Reference value

Dewey confirms that "AI-organized Twitter bookmarks" is already an established product proposition.

Xcollect should differentiate above the source-specific organizer layer.

---

## 3.10 Readwise / Reader

**Twitter import docs:** https://docs.readwise.io/readwise/docs/importing-highlights/twitter

Readwise supports several X save paths, including:

- X bookmark synchronization;
- replying with `@readwise save`;
- sending content toward Reader / Readwise workflows.

### Reference value

Readwise is a strong reference for:

- low-friction capture;
- bot-based acquisition;
- downstream resurfacing;
- integration into reading and highlighting workflows.

The old interaction model — mention a bot under a post and let it capture the object — is still a useful adapter pattern even if source-platform policies can make it fragile.

---

# 4. The closest multi-source references

These projects matter more to Xcollect's long-term architecture than ordinary bookmark managers.

## 4.1 Recall Inbox — closest near-term structural match

**Project:** https://github.com/dynchen/recall-inbox

Recall Inbox describes itself as:

> a self-hosted inbox for X bookmarks, GitHub stars, and other saved items.

Current flow:

```text
X bookmarks ───┐
               ├── sync → inbox → review → tag/note → export
GitHub Stars ──┘
```

Notable characteristics:

- X bookmarks;
- GitHub Stars;
- local mode;
- Cloudflare Workers + D1;
- Vercel + Postgres;
- scheduled sync;
- review states:
  - `inbox`
  - `keep`
  - `action`
  - `dismiss`
- tags and notes;
- Markdown export;
- optional AI summary.

### Why it matters

This is very close to Xcollect's **next architectural step**.

The overlap is substantial:

| Dimension | Recall Inbox | Xcollect direction |
| --- | --- | --- |
| X bookmarks | yes | yes |
| GitHub Stars | yes | planned |
| Cloudflare Workers | yes | yes |
| D1 | yes | yes |
| self-hosted | yes | yes |
| normalized saved-item model | yes | planned |
| review workflow | strong | should add |
| AI classification | optional/light | core |
| topology renormalization | no | core hypothesis |
| context envelope | limited | core hypothesis |
| exploration state model | no | long-term |
| decision-context layer | no | long-term |

### What to borrow

- explicit Source Adapter contract;
- item review states;
- scheduled sync pattern;
- Markdown exit path;
- GitHub Stars integration as a concrete reference implementation.

### What not to copy blindly

Recall Inbox is intentionally an **inbox processing workflow**.

Xcollect's hypothesis is broader:

```text
saved item
  ↓
exploration memory
  ↓
evolving topology
  ↓
resurfacing
  ↓
personal state / decision context
```

---

## 4.2 Trove — closest long-term conceptual match

**Project:** https://github.com/Lowside-Labs/Trove

Trove's thesis is extremely close to the long-term Xcollect discussion:

> your "second brain" is already distributed across X bookmarks, Instagram saves,
> Substack, GitHub stars, Claude conversations and ChatGPT threads.

Supported sources currently include:

- X bookmarks and likes;
- Instagram saved posts;
- Substack saves / likes;
- GitHub Stars;
- Hacker News favorites;
- Claude exports;
- ChatGPT exports.

Trove puts them into a local workspace intended to be consumed directly by AI agents such as Claude Code and Codex.

Representative structure:

```text
~/Trove/
├── CLAUDE.md
├── AGENTS.md
├── INDEX.md
└── content/
```

### Why it matters

Trove is a strong external confirmation of this direction:

```text
scattered personal saves
        ↓
portable local memory
        ↓
AI agent context
```

### Difference to preserve

Trove is currently oriented around making saved content **agent-readable**.

Xcollect can go further in modeling:

- why an item was saved;
- what exploration state produced it;
- how themes evolve through time;
- which old items become newly relevant;
- how evidence should be refreshed before a decision.

This suggests a useful separation:

```text
Trove-like layer:
"What have I saved?"

Xcollect hypothesis:
"What was I exploring, why did I save it,
how did that trajectory evolve,
and what should be resurfaced now?"
```

---

# 5. Generic bookmark / read-later / archive systems

This market is mature and crowded. Xcollect should reuse ideas rather than compete feature-for-feature.

## 5.1 Karakeep

**Docs:** https://docs.karakeep.app/  
**Project:** https://github.com/karakeep-app/karakeep

Karakeep (formerly Hoarder) is an open-source, self-hosted "bookmark everything" system.

Capabilities include:

- links, notes, images and other saved content;
- automatic metadata fetching;
- full-text and semantic search;
- LLM auto-tagging and summarization;
- local Ollama support;
- browser extensions;
- iOS / Android apps;
- agent-friendly CLI and skills;
- rules engine.

### Reference value

Karakeep already covers a large portion of the generic "save anything + AI tag + search" market.

Therefore:

> Xcollect should not define itself as merely "Karakeep but for X".

The differentiator must live in **exploration semantics, time, intent, topology and decision context**.

---

## 5.2 karakeep-sync

**Project:** https://github.com/sidoshi/karakeep-sync

Adapters currently sync:

- Hacker News activity;
- Reddit saved posts;
- GitHub Stars;
- Pinboard;
- with X / Bluesky planned.

### Reference value

This is a clean demonstration that:

```text
many platform-specific Save verbs
          ↓
adapter layer
          ↓
one normalized bookmark backend
```

is already a useful architecture.

---

## 5.3 Linkwarden

**Docs:** https://docs.linkwarden.app/  
**Product:** https://linkwarden.app/

Focus:

- bookmarks;
- article reading;
- annotations;
- webpage preservation;
- screenshots / archives;
- collaboration;
- browser extension;
- self-hosting.

### Reference value

Linkwarden is stronger on **preservation** than Xcollect currently needs.

Important lesson:

```text
metadata URL != preserved evidence
```

For high-value ExplorationItems, Xcollect may eventually need optional snapshot/archive adapters rather than assuming the original source will remain accessible.

---

## 5.4 Raindrop.io

**Product:** https://raindrop.io/

Current Pro functionality includes:

- full-text search;
- web archive;
- AI assistant grounded in saved content;
- natural-language organization;
- tag / collection suggestions;
- retrieval across saved pages, PDFs and YouTube content.

### Reference value

"Ask questions over my saved library" is rapidly becoming commodity functionality.

Xcollect should eventually expose the same ability, but its deeper advantage should be **temporal exploration history and context**, not generic RAG alone.

---

## 5.5 mymind

**Product:** https://mymind.com/

Core thesis:

> Remember everything. Organize nothing.

It saves notes, bookmarks, inspiration, articles, images and other media; AI performs organization and search.

Important features include:

- AI tagging;
- image OCR;
- Smart Spaces;
- summaries;
- private personal memory;
- "Serendipity" resurfacing;
- browser and mobile capture.

### Reference value

Two ideas are especially relevant:

1. **low-friction capture** — asking users to classify every save destroys flow;
2. **serendipitous resurfacing** — memory value comes partly from bringing forgotten objects back.

Xcollect's topology model should preserve these benefits while keeping the AI's inferred organization auditable.

---

## 5.6 Other mature self-hosted systems

The self-hosted bookmark/read-later category includes many established tools:

- ArchiveBox — https://archivebox.io/
- linkding — https://github.com/sissbruecker/linkding
- wallabag — https://wallabag.org/
- Shiori — https://github.com/go-shiori/shiori
- Readeck — https://readeck.org/
- Shaarli — https://github.com/shaarli/Shaarli

These confirm that generic:

```text
save URL → tags → search → read later
```

is a commodity layer.

---

# 6. GitHub Stars ecosystem

GitHub Stars are a high-value next adapter because a Star often represents:

> "This project may solve a future problem."

## 6.1 GitHub native Stars + Lists

**Docs:** https://docs.github.com/en/get-started/exploring-projects-on-github/saving-repositories-with-stars

GitHub itself supports:

- starred repositories;
- search;
- sorting/filtering;
- public Star Lists.

### Limitation relevant to Xcollect

Native organization mostly answers:

> "Where is the repo I starred?"

Xcollect should additionally answer:

> "Why did I star it, which exploration did it belong to, what replaced it,
> is it still maintained, and does it matter to what I am doing now?"

---

## 6.2 GithubStarsManager

**Project:** https://github.com/16km/githubstarsmanager

Capabilities:

- automatic Stars sync;
- AI summaries and categories;
- semantic search;
- release tracking;
- release asset filtering and downloads.

### Reference value

The **lifecycle** dimension is important.

A GitHub ExplorationItem is not static. After saving it:

- releases appear;
- maintenance may stop;
- repository may archive;
- competitors may emerge;
- the user may adopt or reject it.

Xcollect's GitHub adapter should model lifecycle events rather than snapshot-only metadata.

---

## 6.3 starred_repos_organizer

**Project:** https://github.com/uwla/starred_repos_organizer

Capabilities include:

- GitHub, GitLab, Codeberg and Gitea sources;
- local/offline use;
- JSON import/export;
- topic management;
- filtering/grouping;
- self-hosted server option.

### Reference value

Useful reference for provider-neutral repository schemas.

---

## 6.4 CF Star Manager

**Chrome Web Store:** https://chromewebstore.google.com/detail/cf-star-manager/nhliabnkiabbjeldcfgkpdgifbhbokfd

Provides:

- tags;
- private notes;
- search;
- language filters;
- optional private-Gist synchronization.

### Reference value

User annotation ("why I care") is often more durable than automatic categorization.

Xcollect should support explicit user notes alongside inferred intent.

---

## 6.5 Automatically indexed Stars

Example:

**David Wells / stars:** https://github.com/DavidWells/stars

This pattern periodically turns thousands of Stars into a searchable/generated index.

### Reference value

A source adapter does not always need an interactive UI.

Exportable, deterministic, agent-readable materialized views are valuable outputs.

---

# 7. Conversion and agent-oriented systems

## 7.1 Bookmark Maxxing

**Project:** https://github.com/bennewell35/bookmark-maxxing

Thesis:

```text
saved links
   ↓
recurring themes
   ↓
reusable skills / workflows / prompts / artifacts
```

### Reference value

This is an important downstream pattern:

> bookmarks are evidence; the output should sometimes be a reusable artifact.

Xcollect should eventually allow transformation pipelines without making one transformation format mandatory.

---

# 8. Competitive / architectural comparison

## 8.1 What is already commodity

The following should not be treated as unique product claims:

- saving URLs;
- X bookmark export;
- browser extension capture;
- tags and folders;
- AI auto-tagging;
- AI summaries;
- semantic search;
- Markdown / JSON export;
- self-hosted bookmark storage;
- GitHub Star synchronization;
- generic RAG over saved content.

These are useful capabilities, but the market already provides strong implementations.

## 8.2 Xcollect-specific hypotheses

The areas still worth testing as differentiated system behavior are:

### A. Exploration as the canonical object

Not:

```text
Tweet
Repo
WebPage
Video
```

but:

```text
ExplorationItem
```

with source-specific data behind an adapter boundary.

### B. Context Envelope

Capture not only the item, but potentially:

- active project;
- surrounding search/query;
- explicit note;
- nearby saves;
- inferred intent;
- inference confidence.

```text
save(item)
```

becomes:

```text
save(item, context, intent)
```

### C. Topology Renormalization

Do not let AI tags create a permanently unstable taxonomy.

```text
new item
   ↓
project into stable category
   ↓
local novelty / sub-category
   ↓
accumulation
   ↓
phase-change threshold
   ↓
split / merge / settle
```

### D. Resurfacing as a first-class subsystem

Search assumes the user already remembers what to search for.

Resurfacing asks:

> "Which forgotten item has become relevant again?"

### E. Temporal exploration state

The unit of analysis is not only the item, but the trajectory:

```text
RPA
  ↓
Browser Automation
  ↓
Computer Use
  ↓
Agents
  ↓
World Models
```

Different vocabulary may represent one persistent exploration manifold.

### F. Decision Context, not autonomous decision

Xcollect should provide evidence and historical context to an agent.

```text
Decision_t =
f(
  CurrentState_t,
  Goal_t,
  ExplorationHistory_0:t,
  Constraints_t
)
```

Xcollect primarily owns:

```text
ExplorationHistory_0:t
```

Current facts should still be refreshed from live sources before high-impact decisions.

### G. Agent-independent personal memory

The desired boundary is:

```text
                   ┌── ChatGPT
                   ├── Grok
Xcollect Memory ───┼── Muse
                   ├── Claude
                   └── Local Agents
```

Possible interfaces:

- MCP;
- REST API;
- SQL;
- vector retrieval;
- graph queries;
- Markdown / filesystem materializations;
- event stream.

Xcollect should not need to become the agent itself.

---

# 9. Build vs borrow reference table

| Capability | Strong external reference | Xcollect approach |
| --- | --- | --- |
| X GraphQL acquisition | xarchive | borrow patterns / isolate adapter |
| Passive X capture | TBD, Scrollmark | optional acquisition adapter |
| X bookmark UI | XSaved, BookmarkDeepX | avoid over-investing in commodity UI |
| Resurfacing | Totem, mymind | make first-class |
| X → PKM conversion | x2o, Readwise | export/integrate rather than replace |
| Multi-source saved-item inbox | Recall Inbox | study closely; extend semantics |
| Multi-source local AI memory | Trove | closest long-term architectural reference |
| Generic save-everything | Karakeep | integrate/borrow concepts, do not clone |
| Web preservation | Linkwarden / ArchiveBox | optional preservation service |
| Generic AI retrieval | Raindrop / Karakeep | baseline, not differentiator |
| GitHub Star lifecycle | GithubStarsManager | incorporate live repo state |
| Explicit notes/tags | CF Star Manager | preserve user-authored intent |
| Saved-items → artifacts | Bookmark Maxxing | downstream transformation pipeline |

---

# 10. Recommended Xcollect sequence after this research

## Step 1 — Stabilize the core boundary

Introduce:

```text
SourceAdapter
ExplorationItem
ExplorationEvent
ContextEnvelope
```

Do this before adding many new sources.

## Step 2 — Build GitHub Stars as Adapter 02

Use Recall Inbox and GithubStarsManager as references.

Do not stop at importing repo metadata.

Capture lifecycle state:

- starred_at;
- last push;
- release state;
- archived status;
- topics/language;
- adopted / evaluated / dismissed;
- relation to user's projects.

## Step 3 — Add review state

Borrow the useful idea from Recall Inbox:

```text
inbox
keep
action
dismiss
```

but keep this orthogonal to taxonomy.

An item's **workflow state** is not its **semantic category**.

## Step 4 — Make resurfacing measurable

Define metrics such as:

- resurfaced-item open rate;
- resurfaced-item action rate;
- time from save to first revisit;
- percentage of saved items never revisited;
- percentage of resurfaced items linked to a current project.

## Step 5 — Expose an agent interface

Before building a full autonomous agent, expose queries like:

```text
What have I previously explored about X?
Why did I save these?
Which items became obsolete?
Which old exploration is relevant to this current project?
```

Trove is a useful reference for the local-agent consumption surface.

## Step 6 — Add Browser Capture only after the schema stabilizes

Otherwise browser capture will push source-specific assumptions into the core.

---

# 11. Fixed-point view of the landscape

The market can be coarse-grained into four increasingly abstract layers:

```text
L0 — Bookmark / Archive
     xarchive, TBD, Linkwarden

L1 — Organizer / Retrieval
     Dewey, XSaved, Karakeep, Raindrop, mymind

L2 — Review / Conversion
     Recall Inbox, x2o, Readwise, Bookmark Maxxing

L3 — Agent Memory / Decision Context
     Trove
     Xcollect long-term hypothesis
```

The strategic question for Xcollect is therefore not:

> "Can we build a better bookmark manager?"

It is:

> **Can we preserve the user's exploration trajectory well enough that any future personal agent can recover useful context from it?**

That is the hypothesis this project should test.

---

# 12. Watch list

Projects worth periodically revisiting:

- https://github.com/sytelus/xarchive
- https://github.com/0x1b2c/twitter-bookmarks-downloader
- https://github.com/dynchen/recall-inbox
- https://github.com/Lowside-Labs/Trove
- https://github.com/karakeep-app/karakeep
- https://github.com/sidoshi/karakeep-sync
- https://github.com/kiki123124/x2o
- https://github.com/16km/githubstarsmanager
- https://github.com/bennewell35/bookmark-maxxing
- https://getdewey.co/
- https://readwise.io/
- https://raindrop.io/
- https://mymind.com/
- https://linkwarden.app/

This list is not exhaustive. Add a project when it introduces a materially different acquisition, normalization, resurfacing, conversion, or agent-memory pattern.
