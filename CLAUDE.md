# kimbo

An endless browser Tetris game with a shared leaderboard. The frontend is static ES modules with
no build step and no JS dependencies. `server.py` is a stdlib-only Python server that serves the
frontend and a JSON API (`/api/leaderboard`, `/api/scores`, `/api/replay/<id>`) backed by SQLite.

## Running and testing

- Run `python server.py` and open http://localhost:8000. The game must be served, because ES
  modules fail from `file://` with a CORS error. Flags: `--port`, `--db`, `--host`, `--origin`,
  `--trust-proxy`.
- Railway runs `python server.py --host 0.0.0.0 --trust-proxy` (`railway.json`, `Procfile` and
  `nixpacks.toml` all say the same; change them together).
- Tests: `python3 -m unittest tests.test_validate tests.test_static_deny`. The second one boots
  the handler on an ephemeral loopback port.

## Rules

- Static serving is an allowlist in `server.py`: the root files named in `STATIC_ROOT_FILES`,
  plus files under `src/` with a suffix in `STATIC_ALLOWED_SUFFIXES`. A new root-level asset
  returns 404 until it is added to `STATIC_ROOT_FILES`, and `tests/test_static_deny.py` covers
  the boundary.
- The SQLite schema changes through the `PRAGMA user_version` migration ladder in `server.py`.
  Add a step there; do not edit an earlier step.
- Piece rotations are data, not computed from a matrix rotation. If a rotation looks wrong,
  edit the offset array in `src/pieces.js`.
- The render layer (`src/render.js`) is the only place that touches the canvas or the HUD DOM.
  Game logic mutates `state` and render reads it.
- The board mutates in place inside `clearLines` in `src/board.js` and inside `lock()` in
  `src/game.js`. Replay (`src/replay.js`, `src/replay-viewer.js`) records timed operations,
  not board snapshots.
- Canvas dimensions are hardcoded in `index.html` to match `CELL × COLS` and `CELL × ROWS` in
  `src/config.js`. If you change `CELL`, `COLS` or `ROWS`, update the canvas `width` and
  `height` too.
- Tuning constants (scoring, gravity, key repeat, storage keys) live in `src/config.js`.
