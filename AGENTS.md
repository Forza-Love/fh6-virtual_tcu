# AGENTS.md

## Cursor Cloud specific instructions

### Platform constraint

Virtual TCU **production runtime is Windows-only** (`python -m virtual_tcu` exits on non-`win32`). On Linux cloud VMs, validate the repo with **CI-parity checks** (lint, typecheck, builds) plus **`pnpm test:py`** (TCU logic with fake telemetry). Do not expect keyboard injection, FH6 UDP, or Electron packaged installers to work on Linux.

### Node.js version

The monorepo requires **Node ≥ 24** (`package.json` `engines`, `.node-version`). The VM default Node may be 22 (`/exec-daemon/node`). The startup update script already installs/selects Node 24 via `nvm` and activates `pnpm@10.33.0`. In a fresh shell that did not inherit that selection, re-select it before any pnpm script (do not hardcode the patch version, which changes — `nvm install 24` currently resolves to v24.18.0):

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"
nvm use 24   # or `nvm install 24` if missing
corepack enable && corepack prepare pnpm@10.33.0 --activate
```

### Python tools on PATH

`pip install --user` puts `pytest` and `ruff` under `~/.local/bin`. Include it when running Python tooling:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Standard commands (repo root)

See `CLAUDE.md` and root `package.json`. Typical Linux validation loop:

| Step | Command |
|------|---------|
| Install JS | `pnpm install --frozen-lockfile` |
| Install Python | `pip install -r requirements.txt -r requirements-dev.txt` |
| Typecheck | `pnpm typecheck` |
| Lint | `pnpm lint` (or CI split: `pnpm exec eslint .` + `ruff check virtual_tcu virtual_tcu.py`) |
| Unit tests | `pnpm test:py` |
| Build UI | `pnpm build:dashboard` → `virtual_tcu/web/dist/` |
| Build Electron | `pnpm build:electron` (compile only; no Windows installer on Linux) |

GitHub Actions (`.github/workflows/ci.yml`) runs typecheck, ESLint, Ruff, `build:dashboard`, and `build:electron` on Ubuntu — **not** pytest.

### Optional: Web UI smoke on Linux

After `pnpm build:dashboard`, you can serve the dashboard with aiohttp by running `WebServer` from a small inline/async script with `TCULogic` + `FakeOutput` (see `tests/conftest.py`). The real app entrypoint `main()` will not start on Linux. Vite dev (`pnpm dev:dashboard`, port 5173) proxies `/ws` to `127.0.0.1:8765` and needs a backend on that port.

To make such a smoke feed the dashboard with live data (instead of the default `OFFLINE` / `N` placeholders), the simulated telemetry frames must set `is_race_on = 1` (the UI renders gear `N` whenever `is_race_on` is falsy — see `formatGearLabel` in `packages/shared/src/utils/format.ts`), and the loop must keep `receiver.last_recv_time = time.time()` fresh each frame (the receiver's `is_live` is a 2.5s freshness window). The dashboard's `broadcast_loop` only reads `receiver.latest()` and calls `tcu.snapshot()`; drive `tcu.process(td)` yourself to exercise shift logic.

### Git hooks

`.husky/pre-commit` runs `pnpm exec lint-staged` (ESLint/Prettier/Ruff on staged files). `.husky/commit-msg` uses commitlint.

### Services (Windows full stack)

For end-to-end desktop + game testing on Windows: Electron (`pnpm dev:electron`) spawns `python -m virtual_tcu --backend-only`; dashboard at `http://127.0.0.1:8765`; FH6 UDP on port 5555. See `CLAUDE.md` for ports, hotkeys, and Administrator notes.
