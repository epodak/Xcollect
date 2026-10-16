# Xcollect Reading Experience — Stitch + Impeccable Workflow

Status: baseline audit / implementation backlog. Updated 2026-10-16.
Product truth: [PRODUCT.md](../../PRODUCT.md). Target design: [DESIGN.md](../../DESIGN.md).

## The diagnosis

The success criterion is **“Would I voluntarily read Xcollect instead of opening X?”**, not “Does the dashboard show all the available filters?”

Repository audit (code inspection, not live screenshot review):
- `public/index.html`: prominent brand, search, stats, sync, discover, classify, theme, auth, export; sidebar navigation and filters; four scope tabs; seven sorting options; three view modes. The information architecture gives management tools too much permanent presence.
- `public/css/cards.css`: text-rich cards render an additional tinted/left-bordered inner box. Some text representations are clamped to 2 or 6 lines. Canonical reader paths may exist, but the surface still visually encourages scanning rather than sustained reading.
- `public/css/theme.css`, `layout.css`: neon-indigo brand accents, bright hover shadows and decorative glow/backdrop surfaces; these raise visual noise for a text-heavy product.
- `public/css/watch.css`: distinct research workspace uses the shared tokens but has another set of card/rail controls; needs cohesive hierarchy.

Do not interpret these observations as a tested live visual audit. Cloudflare Access may restrict production. Real authenticated desktop/mobile screenshots and manual interaction testing remain required.

## Separation of responsibilities

| Artifact/tool | Responsibility | When used |
| --- | --- | --- |
| `PRODUCT.md` | Durable facts: audience, jobs, constraints, evidence, success | Before any redesign |
| `DESIGN.md` | Shared target visual language, semantic tokens, component style and rationale | Before creating/editing UI |
| Google Stitch | Explore candidate layouts with the DESIGN.md vocabulary | Before major surface redesign; compare variants |
| Impeccable | `critique`, `shape`, `audit`, `polish` and responsive hardening | Before and after each UI change |
| `AGENTS.md` | Invariants, implementation/test/deploy requirements | Always |
| Screenshots & manual tests | Truth about actual readability, interaction and regressions | Before declaring success |

Stitch DESIGN.md is an open-format design description, not a requirement to add Stitch as a runtime dependency. Impeccable is an agent development skill, not a frontend JavaScript dependency.

## Install the design skill for development

From the repository root (the repo requires **pnpm only**, not npm/yarn):

```bash
pnpm dlx impeccable install --providers=codex,claude --scope=project
```

This is the pnpm invocation of the upstream installer; confirm the CLI options against the installed version. Run once in an authorized development workspace, review any generated provider hook before granting permissions, and commit intentional shared agent files, not ephemeral screenshots or local cache. Codex uses `$impeccable` or its skills menu instead of a literal slash command.

Upstream: https://github.com/pbakaus/impeccable
Stitch spec: https://github.com/google-labs-code/design.md
Stitch skills: https://github.com/google-labs-code/stitch-skills

The installer has **not been run as part of this docs-only branch**. A later implementation PR must either commit the scoped skill installation or include verifiable installation evidence. Do not pretend these Markdown files install the third-party tool.

## The first three design increments

### 1. Feed-as-reader (P0)

- Move secondary management buttons from the permanent header to a compact menu; leave search and current reading mode obvious.
- Create a true comfortable reading column; re-evaluate grid/list defaults using screenshot comparison rather than a blind global switch.
- Remove unnecessary tinted inset content boxes and heavy card glow; prioritize normal body text and media.
- Display all ordinary text without silent truncation. For genuinely long sources, inline expansion must be discoverable and preserve context.
- Preserve canonical `body_raw`, attributed quote structure, and existing feed actions/contracts.

**Acceptance:** screenshots at 375px and 1440px, both themes; ordinary/long/media/quote cards; clicking Copy/Original/Not Interested/× unchanged; no false X bookmark operation.

### 2. Discovery decision rhythm (P1)

- Clarify the distinction between discovered, watched and bookmarked items without repetitive badges.
- Make positive signals and rejection easy to find without permanent button overload.
- Separate “false positive” from “not interested in this topic” in both copy and interactions.

**Acceptance:** no ambiguity in a 5-minute reading walkthrough; feedback event/schema and 24h Discovery TTL remain intact.

### 3. Active Research convergence (P1)

- Give the user question and supporting evidence priority over task-creation/admin affordances.
- Reuse feed reading components and styles; avoid special-case styles that diverge from DESIGN.md.
- Test empty, loading, failed, paused and multiple-topic states.

**Acceptance:** desktop/mobile captures and regression checks for topic management, data freshness, and reader continuity.

## Every design iteration (repeat every ~3 days)

1. Read AGENTS.md, PRODUCT.md and DESIGN.md, then inspect existing Issues/PRs, tests and latest code.
2. Capture real baseline in local and (when authorized) cloud browser: desktop and mobile, light and dark.
3. Run Impeccable critique/audit (or document why the runtime is unavailable); identify three prioritized problems with screenshots.
4. Pick **one** meaningful reading task, shape alternatives in Stitch where useful, implement one scoped change.
5. Run `pnpm run check` and applicable a11y/interaction checks. Do **not** claim passed checks without execution.
6. Compare before/after; document visible benefit, known trade-offs, deployment URL/status and next issue.
7. Update the roadmap or an issue with an owner, acceptance criteria and evidence. A reminder is **not** a background developer or automatic deployment.

## User-centered measurement

Primary: proportion of intentional X/Xcollect browsing sessions begun in Xcollect (self-recorded until instrumentation exists). Secondary: reads in-feed without opening an extra modal; time to find relevant content; successful Copy/Original/feedback outcomes; return sessions; complaint count for cramped typography/quotations. Separate measured numbers from hypotheses. Never imply usage telemetry exists merely because the metric is defined.
