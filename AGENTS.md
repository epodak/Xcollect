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
