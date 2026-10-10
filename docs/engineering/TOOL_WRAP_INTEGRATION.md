# Xcollect × Local tool-wrap Skill Integration

Date: 2026-10-09. Status: designed and CLI-prepared; registration must run on the user's machine after cloning.

## Verified local tool-wrap contract

The existing Windows host exposes the root workspace at `D:/`.
Observed launchers:

- `D:/Tool/DIY/tool-wrap`, `tool-wrap.cmd`: aliases to `wrap-tool`.
- `D:/Tool/DIY/wrap-tool`, `wrap-tool.cmd`: invoke `C:/Users/root/.gemini/config/skills/tool-wrap/scripts/wrap_tool.py`.
- Existing `agent-history` wrappers show an independent Git Bash executable (shebang + `exec`) and `.cmd` launcher (preserves exit code).
- An archived tool-wrap naming report requires consistent command/Skill/script naming and automatic `-` / `_` aliases.
- The actual `SKILL.md` lives under `C:/Users/root/.gemini/config/skills/tool-wrap/SKILL.md` outside the current D:/ MCP root; these details were verified from the launchers and the real `--help` output, not by claiming to have opened that file.

Observed `tool-wrap --help` options: `--name`, `--target`, `--type {dual,cli,python,node}`, `--env`, `--subcommands`, `--uri-template`, `--aliases`, `--out-dir`.

## Decision: one global command, many subcommands

Use canonical `xcollect` with optional short alias `xc`, **not** separate `xcollect-search`, `xcollect-export` global wrappers.

```text
xcollect doctor
xcollect search "jev"
xcollect search "Opus 5.5" --json
xcollect read <source-id>
xcollect export "Grok Bot" --out notes/grok
xcollect --source cloud search "grok"
xcollect --source cloud decide <source-id> --model clef-flash
```

`doctor`, `search`, `read`, `export`, `decide` are executable CLI subcommands. Only `decide` calls the AI provider and requires explicit cloud-side opt-in. `ask`, `explore`, `sync`, `mcp` and `serve` are **not yet implemented** and must not appear in a help example as live commands.

## One-time registration on the actual Windows machine

First clone or fetch the feature branch to a **stable** path. The mounted D:/ workspace's `find-repo Xcollect` returned no local checkout at the time of authoring; do not invent one. Example if you choose `D:/Code/Xcollect` (substitute your real path):

```bash
cd /d/Code/Xcollect
git fetch origin
git switch --track origin/feature/retrieval-decision-cli
python -m xcollect_cli doctor

# From Git Bash. Replace the target with the actual absolute Windows path.
tool-wrap --name xcollect \
  --target "D:/Code/Xcollect/xcollect_cli.py" \
  --type python \
  --env AI \
  --aliases xc
```

`--type python` invokes the repo's Python script in the selected Conda environment, while generated files are written to `D:/Tool/DIY`. The selected environment must include Python 3.10+. It is not necessary to run `pip install -e .` in this mode.

Check wrapper discoverability in a **new** shell (requires `D:/Tool/DIY` on both Windows PATH and Git Bash PATH):

```bash
command -v xcollect
xcollect --help
xcollect doctor --json
xc search "jev"
```

PowerShell/CMD:

```powershell
where.exe xcollect
xcollect doctor
xcollect search "Opus 5.5"
```

If you prefer editable-installed entry points, `pip install -e .` already creates `xcollect`; avoid simultaneously putting a separate same-name executable earlier in PATH unless intentionally choosing which one wins. The tool-wrap Python wrapper above is simpler on this host.

## Working directory, data and secret invariants

- Default local data path is now resolved from `xcollect_cli.py`'s **physical checkout**: `<repo>/data/xcollect.json`. It no longer depends on shell CWD.
- `XCOLLECT_DATA` or explicit global `--data` overrides it, e.g. `xcollect --data "D:/private/xcollect.json" search "JEV"`. A missing local file is an error; there is no silent seed fallback.
- The `--out` export path intentionally remains relative to the invoking directory. `cd ~/Documents; xcollect export "jev" --out notes/jev` writes under Documents, not into the repo.
- Never put `XCOLLECT_API_TOKEN` or X login cookies into `D:/Tool/DIY/xcollect.cmd`, Git, or the `tool-wrap` arguments. Cloud read mode reads `XCOLLECT_API_BASE` and `XCOLLECT_API_TOKEN` from process environment.
- A public hostname needs Cloudflare Access covering **all** legacy and new APIs; a new bearer-protected v1 route does not protect legacy routes.
- `xcollect doctor` reports only whether the cloud parameters exist; it does **not** print secret values or make a network request.

## Re-registration and tests

Re-run `tool-wrap --name xcollect ...` only when the checkout path or selected Python environment changes. Do not rewrite the wrappers on every `git pull`; the wrappers are expected to call the live Python file and pick up pulled code automatically. Determine tool-wrap's overwrite semantics before invoking it on an existing alias with local customization.

```bash
python scripts/check_retrieval.py
pnpm run check
```

Follow-up: record an alias collision check (`where.exe xc`, `command -v xc`), a Windows runtime smoke test, and a direct inspection of the canonical Skill file when available via an in-scope mount.
