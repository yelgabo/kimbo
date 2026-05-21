# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`kimbo` is an endless browser Tetris game. Static files, no build step, no dependencies. The game uses ES modules, so it **must be served** — open `file://` will fail with a module CORS error. Use any static server, e.g. `python -m http.server`, then visit `http://localhost:8000`.

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
```

- [src/config.js](src/config.js) — every tuning constant: board dimensions, cell sizes, colors, scoring table (`LINE_POINTS`), gravity timings, key-repeat timings, localStorage key, restart delay. Change game feel here.
- [src/pieces.js](src/pieces.js) — `PIECES` table (color + four hardcoded rotation arrays per tetromino), `KICKS` wall-kick offsets, `cellsOf(piece)`, and `createBag()` which returns a stateful 7-bag `nextType()` function.
- [src/board.js](src/board.js) — pure board helpers: `emptyBoard()`, `collides(piece, board)`, `clearLines(board)` (mutates the board in place, returns count cleared). No scoring here — that lives in [src/game.js](src/game.js).
- [src/render.js](src/render.js) — `createRenderer(refs)` returns a `render(state)` function. Owns the two 2D contexts, draws grid → locked cells → ghost → active piece → next preview → HUD, then reconciles the overlay (paused / game-over / hidden) using a key-based dedupe so DOM only updates on transitions.
- [src/input.js](src/input.js) — `installInput(game)` attaches `keydown`/`keyup`/`blur` to `window`. Calls `game.move/rotate/hardDrop/setSoftDrop/togglePause/canPlay`. Implements DAS-style horizontal auto-repeat itself (130ms initial, 40ms rate) by ignoring the browser's native `e.repeat` and managing its own timers.
- [src/game.js](src/game.js) — `createGame()` returns `{ state, step(dt), move, rotate, hardDrop, setSoftDrop, togglePause, canPlay }`. Owns the mutable `state` object and all game actions: spawn, lock, line scoring, level progression, top-out (saves best to localStorage), restart, gravity vs. soft-drop tick.
- [src/main.js](src/main.js) — wiring only: grabs DOM refs, builds game + renderer + input, runs the `requestAnimationFrame` loop calling `game.step(dt)` then `render(game.state)`.

### Endless behavior

On top-out, `topOut()` (in [src/game.js](src/game.js)) saves the score to `localStorage` under `BEST_KEY` if it beats the current best, marks `state.gameOver = true`, and sets `state.restartAt = performance.now() + RESTART_DELAY_MS`. The next `step()` call after that timestamp calls `restart()` which zeroes the board and resumes. The game truly never ends; there is no manual restart.

### Scoring & levels

- Line clears use `LINE_POINTS = [0, 40, 100, 300, 1200]` × current level.
- Soft drop adds +1 per cell descended; hard drop adds +2 per cell.
- Level increments every 10 lines cleared. No cap, but gravity floors at `GRAVITY_MIN_MS`.

### Best score persistence

Plain number string in `localStorage` under `kimbo-tetris-best`. Reset by clearing the key in DevTools — no in-game button.

## Running it

- `python -m http.server` (or any static server) and open `http://localhost:8000`.
- No build, no install, no test suite. Edits to any module take effect on next page reload.

## Conventions worth keeping

- Piece rotations are **data**, not computed from a matrix rotation. If a rotation looks wrong, edit the offset array in [src/pieces.js](src/pieces.js).
- The render layer is the **only** place that touches the canvas or the HUD DOM. Game logic mutates `state`; render reads it.
- The board mutates in place inside [src/board.js](src/board.js#L17) `clearLines` and inside `lock()` in [src/game.js](src/game.js). If you ever need undo / replay, that's the first thing to change.
- Canvas dimensions are hardcoded in [index.html](index.html) to match `CELL × COLS` and `CELL × ROWS` in [src/config.js](src/config.js). If you change `CELL`, `COLS`, or `ROWS`, update the canvas `width`/`height` too.
