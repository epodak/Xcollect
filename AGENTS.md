# AGENTS.md - Project Operating Rules & Invariants

> Single Source of Truth: All cross-agent collaborative guidelines follow C:\Users\root\AGENTS.md.

## Non-negotiable rules

1. **Invariants outrank aesthetic or creative freedom.**
   Backward compatibility, API contracts, zero-breaking-change guarantees, and architectural invariants strictly outrank "looks cleaner".

2. **Configuration hygiene (Agent Relay Hygiene).**
   - Sensitive credentials belong strictly in local private `.env` only (never committed).
   - `.env.example` is the 100% desensitized shadow mirror of `.env` (1:1 key parity).
   - Non-sensitive decoupling configs belong in `config.toml` (committed to repo).

3. **Node.js package manager invariant (pnpm only).**
   - Strictly use `pnpm` for all package management and script execution (`pnpm install`, `pnpm run dev`, `pnpm build`, `pnpm test`).
   - Using `npm` or `yarn` is strictly prohibited. Never commit `package-lock.json` or `yarn.lock`.

4. **Evaluation closes the loop.**
   A task recipe without an objective evaluation criterion (test assertion, exit code, typecheck) is incomplete. Execution stops only when acceptance gates pass (`python local_server.py --check`).


5. **Deployment profile invariant (progressive capability enhancement).**
   - Local Profile is first-class and is the default onboarding path: Python + local JSON + X credentials.
   - Cloudflare is optional remote-access infrastructure, never a prerequisite for basic use.
   - D1/KV/Workers AI may enhance capability but must not raise the minimum installation floor.
   - `scripts/seed_data.json` is a repository seed/demo asset; mutable user data belongs under ignored runtime storage such as `data/xcollect.json`.
   - Documentation must explain Local Profile before Cloud Profile.
   - See `docs/engineering/DEPLOYMENT_PROFILES.md`.
