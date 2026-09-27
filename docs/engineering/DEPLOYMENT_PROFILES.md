# Deployment Profiles

## Principle

Xcollect follows **progressive capability enhancement**:

> The minimum environment must remain useful. Richer infrastructure unlocks richer capabilities; it must not become the price of entry.

Cloudflare is an optional remote-access deployment profile, not a runtime dependency of Xcollect.

---

## Profile A — Local (default)

Target user:

- one person;
- one machine;
- wants the lowest setup cost;
- does not need public / remote access.

Architecture:

```text
Browser
  ↓
127.0.0.1
  ↓
local_server.py
  ├── X Web credentials (.env)
  └── data/xcollect.json
```

Requirements:

- Python 3.10+
- `X_AUTH_TOKEN`
- `X_CT0`

No Node.js, Cloudflare account, domain, D1, KV or Workers AI is required.

### Storage contract

`data/xcollect.json` is the primary Local Profile database.

It is private runtime data and must not be committed.

Writes use:

```text
xcollect.json
   ↓
xcollect.json.tmp
   ↓ fsync
atomic os.replace()
   ↓
xcollect.json
```

A best-effort `xcollect.json.bak` is kept before replacement.

`scripts/seed_data.json` is a repository asset / bootstrap sample, not the user's live database.
For backward compatibility, the first Local Profile run can initialize the runtime database from the seed file when no local database exists.

---

## Profile B — Personal Cloud (optional)

Target user:

- wants to access Xcollect remotely;
- has a private domain / Cloudflare deployment;
- wants persistent server-side state across devices.

Architecture:

```text
Internet
   ↓
Cloudflare Worker
   ↓
capability probe
   ├── D1 available → D1 primary
   └── KV available → KV fallback
```

D1 is the preferred Cloud Profile backend because it supports structured queries, indexing, lifecycle state and future Exploration / Agent features.

KV is a reduced-capability fallback when configured.

If neither D1 nor KV exists, the user should normally use the Local Profile instead of being forced to provision cloud infrastructure.

---

## Capability matrix

| Capability | Local JSON | Cloudflare KV | Cloudflare D1 |
| --- | ---: | ---: | ---: |
| Basic X bookmark collection | ✓ | ✓ | ✓ |
| Zero cloud account required | ✓ | — | — |
| Remote multi-device access | — | ✓ | ✓ |
| Human-readable portable data | ✓ | △ | △ |
| Structured query / indexes | △ | — | ✓ |
| Topology / lifecycle analytics | △ | △ | ✓ |
| Future agent retrieval | △ | △ | ✓ |
| Operational complexity | Lowest | Medium | Higher |

The table is not a ranking of users. Each profile exists for a different deployment goal.

---

## Source adapters and storage profiles are orthogonal

Do not couple source acquisition to one storage backend.

```text
Twitter/X ─┐
GitHub    ─┤
Browser   ─┼── Exploration Core ──┬── Local JSON
YouTube   ─┤                      ├── KV
RSS       ─┘                      └── D1
```

Adding GitHub Stars must not imply D1.
Adding D1 must not imply Twitter/X.

---

## Engineering invariants

1. Local Profile is a first-class supported product path, not a fallback after Cloudflare fails.
2. Cloudflare is an optional remote-access enhancement.
3. Basic usage must never require D1, KV, Workers AI, Node.js or a domain.
4. Repository demo/seed assets must never double as the user's mutable runtime database.
5. Secrets remain outside the repository.
6. Local persistence must be crash-safe enough that an interrupted write does not destroy the primary JSON file.
7. Cloud storage selection is capability-driven:
   - D1 when bound and healthy;
   - otherwise KV when bound and healthy.
8. AI is optional. Rule-based classification remains a zero-key fallback.
9. Documentation must present Local Profile before Cloud Profile.
10. Future capabilities should raise the ceiling, not the minimum installation floor.

---

## User-facing mental model

```text
Just want to use it?
→ Local Profile

Want to open it from phone / another computer / the Internet?
→ Personal Cloud Profile

Want richer querying, topology, agent memory?
→ Add D1 / AI / future services
```

That is the intended progression.


---

## Known structural debt

Local and Cloud profiles currently have different runtime HTTP stacks:

- `local_server.py` uses Python stdlib HTTP / urllib;
- Cloudflare uses `src/entry.py`, `src/twitter.py`, `src/storage.py`.

Their external contracts are now aligned, but some X parsing / synchronization logic is still duplicated.

The Phase 1 refactor should extract pure, runtime-neutral components:

```text
X protocol model / parser
Incremental-sync policy
ExplorationItem normalization
Semantic merge policy
        ↓
Runtime adapters
├── Local urllib + JSON
└── Cloudflare js_fetch + D1/KV
```

Do not solve this by making Local depend on Cloudflare modules or by making Cloud depend on the local HTTP server.
The shared layer should contain pure domain logic; runtime-specific I/O stays at the edges.
