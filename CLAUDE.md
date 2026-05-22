# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`kimbo` is an endless browser Tetris game with a shared leaderboard. The frontend is static files, no build step, no JS dependencies. The backend is a stdlib-only Python server (`server.py`) that serves the static frontend AND a small JSON API backed by SQLite. The game uses ES modules, so it **must be served** — open `file://` will fail with a module CORS error.

## Architecture

Single-page canvas game. The DOM shell and stylesheet sit at the repo root; the JS is split into focused ES modules under [src/](src/).

- [index.html](index.html) — DOM shell: `<canvas id="board">` (300×600 = 10×20 cells of 30px), `<canvas id="next">` for the preview, an `#overlay` for paused/game-over text, and HUD `<div>`s. Loads [src/main.js](src/main.js) as a module.
- [styles.css](styles.css) — dark theme via CSS variables, flex layout (board + HUD side-by-side, stacked on narrow viewports).

### Module layout in [src/](src/)

The dependency graph is shallow and one-directional:

```
main.js → game.js → board.js → pieces.js → config.js
       → render.js → board.js, pieces.js, config.js
       → input.js → config.js
       → audio.js
       → leaderboard.js → config.js
```

- [src/config.js](src/config.js) — every tuning constant: board dimensions, cell sizes, colors, scoring table (`LINE_POINTS`), gravity timings, key-repeat timings, localStorage key, restart delay. Change game feel here.
- [src/pieces.js](src/pieces.js) — `PIECES` table (color + four hardcoded rotation arrays per tetromino), `KICKS` wall-kick offsets, `cellsOf(piece)`, and `createBag()` which returns a stateful 7-bag `nextType()` function.
- [src/board.js](src/board.js) — pure board helpers: `emptyBoard()`, `collides(piece, board)`, `clearLines(board)` (mutates the board in place, returns count cleared). No scoring here — that lives in [src/game.js](src/game.js).
- [src/render.js](src/render.js) — `createRenderer(refs)` returns a `render(state)` function. Owns the two 2D contexts, draws grid → locked cells → ghost → active piece → next preview → HUD, then reconciles the overlay (paused / game-over / hidden) using a key-based dedupe so DOM only updates on transitions.
- [src/input.js](src/input.js) — `installInput(game)` attaches `keydown`/`keyup`/`blur` to `window`. Calls `game.move/rotate/hardDrop/setSoftDrop/togglePause/canPlay`. Implements DAS-style horizontal auto-repeat itself (130ms initial, 40ms rate) by ignoring the browser's native `e.repeat` and managing its own timers.
- [src/game.js](src/game.js) — `createGame()` returns `{ state, step(dt), move, rotate, hardDrop, setSoftDrop, togglePause, canPlay }`. Owns the mutable `state` object and all game actions: spawn, lock, line scoring, level progression, top-out (saves best to localStorage), restart, gravity vs. soft-drop tick.
- [src/leaderboard.js](src/leaderboard.js) — `createLeaderboard()` returns `{ playerId, displayName, submit, fetchTop }`. Lazy-generates a v4 UUID into `localStorage[PLAYER_ID_KEY]`; display name is `'anon-' + uuid.slice(0, 4)`. `submit()` POSTs to `/api/scores` (fire-and-forget, never throws); `fetchTop()` GETs `/api/leaderboard`. All network failures swallowed with `console.warn` so the game stays playable offline.
- [src/main.js](src/main.js) — wiring only: grabs DOM refs, builds game + renderer + input + leaderboard, wires `topOut` to both audio and `leaderboard.submit()`, runs the `requestAnimationFrame` loop calling `game.step(dt)` then `render(game.state)`.

### Endless behavior

On top-out, `topOut()` (in [src/game.js](src/game.js)) saves the score to `localStorage` under `BEST_KEY` if it beats the current best, marks `state.gameOver = true`, and sets `state.restartAt = performance.now() + RESTART_DELAY_MS`. The next `step()` call after that timestamp calls `restart()` which zeroes the board and resumes. The game truly never ends; there is no manual restart.

### Scoring & levels

- Line clears use `LINE_POINTS = [0, 40, 100, 300, 1200]` × current level.
- Soft drop adds +1 per cell descended; hard drop adds +2 per cell.
- Level increments every 10 lines cleared. No cap, but gravity floors at `GRAVITY_MIN_MS`.

### Best score persistence

Plain number string in `localStorage` under `kimbo-tetris-best`. Reset by clearing the key in DevTools — no in-game button. This is the **local** best and remains the source of truth for the HUD's "BEST" tile even when the server is unreachable.

### Server & data

[server.py](server.py) is a stdlib-only HTTP server (`http.server.ThreadingHTTPServer` + `sqlite3`) that serves the static repo at `/` and a JSON API at `/api/*`. The DB lives at `data/kimbo.db` by default (WAL mode, single table `scores`, schema `user_version = 1`).

Endpoints:
- `GET /api/leaderboard?limit=N` — top-N scores by `score DESC, created_at ASC`. Default 10, max 100.
- `POST /api/scores` — submit a run. Strict validation: v4 UUID `playerId`, `displayName` derived as `anon-<first4>`, integer bounds, cross-field plausibility check. Rate-limited 6/min per playerId AND per IP.

Static-file safety: `*.db*` / `*.sqlite*` are hard-denied at the handler, directory listings return 404, and the DB lives outside any path the static handler would serve. The `data/` directory is gitignored (see [.gitignore](.gitignore)).

Identity: anonymous v4 UUIDs in `localStorage[kimbo-player-id]`, displayed as `anon-<4hex>`. To rotate identity, clear that key in DevTools (no in-game button).

Production runs the same `server.py` behind a reverse proxy (Caddy/nginx) that terminates TLS. Use `--host 127.0.0.1 --db /var/lib/kimbo/kimbo.db --origin https://your.domain --trust-proxy`. Nightly `sqlite3 .backup` is the backup story; SQLite WAL means the file is online-safe to snapshot via the backup API.

## Running it

- **Local dev**: `python server.py` and open `http://localhost:8000`. Flags: `--port 8001`, `--db path/to.db`. Defaults bind to loopback only.
- No JS build, no JS install. Edits to any module take effect on next page reload; `server.py` restart picks up server changes.

## Conventions worth keeping

- Piece rotations are **data**, not computed from a matrix rotation. If a rotation looks wrong, edit the offset array in [src/pieces.js](src/pieces.js).
- The render layer is the **only** place that touches the canvas or the HUD DOM. Game logic mutates `state`; render reads it.
- The board mutates in place inside [src/board.js](src/board.js#L17) `clearLines` and inside `lock()` in [src/game.js](src/game.js). If you ever need undo / replay, that's the first thing to change.
- Canvas dimensions are hardcoded in [index.html](index.html) to match `CELL × COLS` and `CELL × ROWS` in [src/config.js](src/config.js). If you change `CELL`, `COLS`, or `ROWS`, update the canvas `width`/`height` too.
