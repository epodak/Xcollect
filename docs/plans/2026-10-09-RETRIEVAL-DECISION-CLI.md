# Xcollect Retrieval + Decision CLI — Execution Plan

Status: E2E research implemented, offline tests passing; production acceptance pending (2026-10-09)
Branch: `feature/retrieval-decision-cli`
Base: `main` at `7cc31e34d893c0e94c97d544870488c618ea1e78`

## Goal

Enable evidence-preserving bookmark research: natural language recall -> automatic Clef/Jev judgment -> generative synthesis -> terminal/Markdown/JSONL delivery. Original lexical-only slicing has been superseded by ADR-0003.

## Non-negotiable boundaries

- Bookmark Plane is durable; Discovery candidates are not exported or indexed as bookmarks. The 24h UTC Discovery expiry remains unchanged.
- `body_raw` is the canonical source; `snippet` is a fallback only, clearly marked.
- Raw source facts, inference annotations, and exports stay separate.
- Local profile requires no Cloudflare, Node, API key or AI.
- No direct D1 management token in CLI. Remote access is through a restricted API.
- No automatic AI on every sync, no silently paid calls, no inference result interpreted as verified evidence.
- Preserve existing feed/browser and X sync contracts.
- Never put API tokens, X sessions, or private bookmark content in Git.

## Milestones and acceptance gates

| Stage | Scope | Verification |
| --- | --- | --- |
| P0 — plan and decisions | This plan + ADR | Decision paths and credentials documented |
| P1 — local retrieval | Pure stdlib lexical/multilingual substring search, aliases, safe bundle export, CLI for local JSON | Unit tests: match, safe path, ID, source fidelity, exports |
| P2 — remote read contract | Authenticated `/api/v1/search` and `/api/v1/items/:id`, no public access when token absent | Auth denial tests, bounded queries, no Discovery leakage |
| P3 — typed decision | Optional `/api/v1/decide`, Clef-flash/Jev allowlist and bounded state | Fake AI binding tests; no billable call when unconfigured |
| P4 — scale-up | FTS5 recall, automatic model filtering, synthesized research report | Implemented with SQLite/D1 FTS5; live D1 migration and model smoke test pending. Vectorize/MCP/offline mirror remain future |
| P5 — deployment | Access policy review, Cloudflare secrets, real data smoke test | Requires owner's production credentials and Cloudflare deployment |

## CLI command contract

```text
python -m xcollect_cli search "Opus 5.5" --source local --json
python -m xcollect_cli search "Grok Bot" --source cloud --limit 20
python -m xcollect_cli read <tweet-id> --source local
python -m xcollect_cli export "JEV" --format bundle --out ./exports/jev
python -m xcollect_cli decide "Grok Bot" --source cloud --model clef-flash
```

Output bundle: `README.md`, `sources.jsonl`, `manifest.json`, `posts/<id>.md`.
Use stable source URLs and structured provenance, not fabricated bookmark timestamps.
Never let source-controlled tweet text escape Markdown code/metadata escaping.

## Security constraints

Cloud API requires `XCOLLECT_API_TOKEN` and `Authorization: Bearer ...`, or explicit Cloudflare Access with verified identity; a missing token must fail closed. Protect legacy `/api/tweets`, `/api/feed`, and all write/sync APIs with Cloudflare Access at the deployment boundary before public launch; adding new private endpoints does not retroactively protect legacy paths. Disable unintended public `workers.dev` routes or protect them equivalently.

## Known follow-ups / open risks

- Cloud D1 currently loads all bookmarks on `/api/tweets`; P2's bounded API must not be confused with indexed FTS performance.
- Ingestion stores X timestamp and timeline position, not necessarily precise bookmark time.
- Python Workers `env.AI.run` must be tested against a live Cloudflare deployment before claiming production-ready AI.
- API's raw token transport should use HTTPS; localhost exception only for local dev.
- New AI Search indexes must be rebuildable projections and propagate deletion events; no permanent Discovery archive.

## Progress ledger

- [x] Inspected repository contracts and Cloudflare model API.
- [x] Created isolated feature branch and draft PR #5.
- [x] P1 lexical local search, read, safe bundle export and CLI with tests.
- [x] P2 cloud token-gated v1 read endpoints; local loopback read API.
- [x] P3 opt-in Clef-flash/Clef/Jev typed decision code with fake-binding unit tests.
- [x] ADR-0003 修正目标偏移：已实现 `ask` / `research` 完整召回→判决→生成→引用链路。
- [x] 本地 SQLite FTS5 + D1 FTS5 重建/增删改迁移、Direct Cloudflare AI 与 Worker 双后端。
- [x] 生成 `report.md`、来源 JSONL、过滤记录；模型虚构引用会被拒绝。
- [x] PR CI: existing contracts + retrieval tests passed (including repair of time-stale Discovery fixture).
- [ ] Vectorize、MCP 和增量镜像（不属于当前已验证实现）。
- [ ] P5 live Worker inference and Cloudflare deployment — gated by owner secrets and Access review.

## Sources

- Cloudflare Clef-flash: https://developers.cloudflare.com/ai/models/%40cf/cloudflare/clef-flash/
- Cloudflare Jev: https://developers.cloudflare.com/ai/models/typesafe/jev/
- D1 FTS5: https://developers.cloudflare.com/d1/sql-api/sql-statements/
