# Engineering Documentation Map

This directory contains the durable engineering rationale and contracts for Xcollect.

Use the layers below deliberately:

| Layer | Purpose | Put here |
| --- | --- | --- |
| `AGENTS.md` | Non-negotiable project invariants | Rules future agents must not violate |
| `docs/engineering/*.md` | Architecture, rationale, state models, failure semantics | Why the system is designed this way |
| `.agents/skills/*/SKILL.md` | Repeatable agent execution playbooks | How to safely change a subsystem |
| `scripts/check_*.py` | Executable contracts | Machine-checkable acceptance criteria |
| Code | Implementation | The current mechanism, not the only source of rationale |

## Canonical engineering documents

- `DEPLOYMENT_PROFILES.md` — Local vs Cloud capability profiles.
- `BACKGROUND_SYNC.md` — Cron/background synchronization contract.
- `SYNC_AND_D1.md` — storage and synchronization mechanics.
- `CONTENT_NORMALIZATION.md` — canonical source-content normalization.
- `DISCOVERY_ENGINE.md` — Discovery Plane, ranking, feedback semantics, candidate lifecycle and bookmark promotion.

## Discovery maintenance

Any change touching discovery/feed/recommendation/bookmark-promotion semantics must read:

1. `AGENTS.md` Invariant 9.
2. `docs/engineering/DISCOVERY_ENGINE.md`.
3. `.agents/skills/discovery-plane/SKILL.md`.

The corresponding executable contracts are:

- `scripts/check_discovery.py`
- `scripts/check_feed_contract.py`
- `scripts/check_related_hot.py`

The intended pattern is:

```text
Invariant
   ↓
Engineering rationale
   ↓
Agent skill / procedure
   ↓
Implementation
   ↓
Executable acceptance check
```

If a design decision changes semantics, update all affected layers rather than leaving the reasoning only in a commit message or chat history.
