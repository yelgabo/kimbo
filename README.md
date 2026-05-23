# kimbo

An endless browser Tetris game with a shared leaderboard and per-score replays.
Static frontend, stdlib-only Python backend, SQLite storage. No build step, no JS dependencies.

## Quick start

```bash
python server.py
# open http://localhost:8000
```

That's it. The server serves the static frontend and a small JSON API on the same origin.

Flags:
- `--port 8001` — override default 8000
- `--db path/to.db` — override default `data/kimbo.db`
- `--host 0.0.0.0` — bind beyond loopback (production sits behind a reverse proxy; see [Deployment](#deployment))
- `--origin https://your.domain` — pin the expected `Origin` header for CSRF defense
- `--trust-proxy` — honor `X-Forwarded-For` for per-IP rate limiting (only when behind a real proxy)

## Features

- Endless play: tops out, briefly shows the overlay with your rank, restarts automatically. No manual restart, no game-over screen to dismiss.
- 7-bag piece sequencer with hand-placed rotation data and wall-kicks.
- Shared leaderboard: top 10 ranked by score; your row highlighted as `YOU`.
- Watch any score's replay by clicking the `▶` button next to it on the leaderboard. Replays drive the real game engine from a seed + recorded input log at 4× speed.
- Local best score persists in `localStorage`, so the HUD shows your personal best even when offline.
- Sound effects + chiptune music (toggleable with `M` / `N`).

## Architecture

```
┌─────────────────── browser ──────────────────┐
│  index.html  ──  styles.css                  │
│       │                                      │
│  src/main.js     wiring; no game logic       │
│   ├── createGame({seed, events}) ► game.js   │
│   ├── createRenderer(refs)       ► render.js │
│   ├── installInput(game)         ► input.js  │
│   ├── createLeaderboard()        ► leaderboard.js
│   ├── createReplayLogger()       ► replay.js │
│   ├── installReplayViewer()      ► replay-viewer.js
│   └── createAudio()              ► audio.js  │
│                                              │
│  game.js → board.js, pieces.js, config.js   │
│                                              │
│  localStorage:                               │
│    kimbo-player-id (UUID v4, persistent)     │
│    kimbo-tetris-best (local best)            │
└──────────────────────────────────────────────┘
                  │ │
                  ▼ ▼  same-origin fetch
┌─────────────────── server.py ────────────────┐
│  ThreadingHTTPServer (stdlib only)           │
│                                              │
│  GET  /…           — static frontend         │
│  GET  /api/leaderboard?limit=N               │
│  POST /api/scores                            │
│  GET  /api/replay/<id>                       │
│                                              │
│  validate_score_body — 9 hard checks         │
│  rate limit: 6/min per UUID AND per IP       │
│                                              │
│  data/kimbo.db (SQLite, WAL mode)            │
│    scores(id, player_id, display_name,       │
│           score, lines, level, duration_ms,  │
│           created_at, seed, replay_log)      │
└──────────────────────────────────────────────┘

tests/test_validate.py — 27 unit tests
```

### Module layout in [src/](src/)

- [src/config.js](src/config.js) — every tuning constant (board, scoring, gravity, API base, localStorage keys).
- [src/pieces.js](src/pieces.js) — `PIECES` table, `KICKS`, `cellsOf()`, `createBag(rng)`, and a seedable `mulberry32(seed)` PRNG so games can be replayed deterministically.
- [src/board.js](src/board.js) — pure board helpers: `emptyBoard`, `collides`, `clearLines`.
- [src/game.js](src/game.js) — `createGame({seed, events})` owns the mutable `state` (board, piece, score, level, lines, seed, gameTimeMs, …) and exposes `step(dt)`, `move`, `rotate`, `hardDrop`, `setSoftDrop`, `togglePause`. Fires `events.input(op, t)` after every successful input so a logger can record gameplay.
- [src/render.js](src/render.js) — `createRenderer(refs)` returns `render(state)`. Owns all canvas and HUD DOM. Game logic mutates `state`; render reads it.
- [src/input.js](src/input.js) — keyboard handling with DAS-style horizontal auto-repeat (130 ms initial / 40 ms rate).
- [src/leaderboard.js](src/leaderboard.js) — `createLeaderboard()` returning `{playerId, displayName, submit, fetchTop, fetchReplay}`. All failures are swallowed so the game keeps working offline.
- [src/replay.js](src/replay.js) — `createReplayLogger()` for the live game, `createReplay({seed, log, …})` to drive a fresh game from a recorded log.
- [src/replay-viewer.js](src/replay-viewer.js) — modal-based viewer for any leaderboard row.
- [src/audio.js](src/audio.js) — WebAudio-based SFX + chiptune music.
- [src/main.js](src/main.js) — wiring only.

## Identity & privacy

Each browser profile gets a stable v4 UUID stored in `localStorage[kimbo-player-id]`. The leaderboard shows it as `anon-<first-4-hex>`. Refreshing the page keeps the same identity; clearing localStorage rotates it. Two real people sharing one browser profile share one identity — there are no accounts, no nicknames, no email.

The server never returns raw `player_id` in responses; only the derived display name.

## Anti-cheat

The client is fully trusted JavaScript — anyone with DevTools can call `fetch('/api/scores', …)` directly. Defense is server-side bounds checking, not client trust:

- Strict v4 UUID + derived display name regex
- Per-field bounds and the level==lines//10+1 invariant
- A **lower bound** `score ≥ min_score_for_lines(lines)` derived from the game's own scoring math — for example, 8000 lines is mathematically incapable of producing fewer than 128 M points, so any "8000 lines for 9 M points" forgery is hard-rejected
- Rate ceilings: ≤6 lines/sec, ≤2500×level pts/sec
- Per-UUID and per-IP rate limiter, 6 submissions/min

For social audit: every submitted score includes the recorded input log. Anyone can click `▶` on any row and watch the actual gameplay — cheaters who curl a high score also have to fake a believable 5-minute play log, which is much harder. The full plan and remaining attack surface are in [docs not yet committed].

## Deployment

### Railway (zero-config-ish)

The repo includes [`railway.json`](railway.json), [`nixpacks.toml`](nixpacks.toml), and [`Procfile`](Procfile). Railway will detect Python, install nothing (stdlib only), and start the server with `--host 0.0.0.0 --trust-proxy`. `--port` honors `$PORT`, which Railway injects automatically.

**Required environment variables in the Railway dashboard:**

| Variable | Value | Why |
|---|---|---|
| `DB_PATH` | `/data/kimbo.db` | The default `data/kimbo.db` lives inside the repo, which gets wiped on every deploy. You **must** mount a persistent volume (e.g. at `/data`) and point `DB_PATH` at it, or your leaderboard resets every push. |
| `KIMBO_ORIGIN` | `https://<your-railway-domain>` | Pins the expected `Origin` header. Set this once Railway gives you a public URL. |

`PORT`, `HOST`, and `TRUST_PROXY` are handled automatically by the start command — don't set them manually.

### Self-hosted VPS

Designed for a single VPS behind a reverse proxy. Sketch:

```
/opt/kimbo/                  # the repo, pulled via git
/var/lib/kimbo/kimbo.db      # owned by `kimbo` user, 0640
/etc/systemd/system/kimbo.service
/etc/caddy/Caddyfile         # TLS + reverse_proxy 127.0.0.1:8000
```

Run as:
```
python server.py \
  --host 127.0.0.1 --port 8000 \
  --db /var/lib/kimbo/kimbo.db \
  --origin https://your.domain \
  --trust-proxy
```

Nightly backup is `sqlite3 /var/lib/kimbo/kimbo.db '.backup /var/backups/kimbo/kimbo-$(date +%F).db'`.

## Tests

```bash
python -m unittest tests.test_validate
```

27 unit tests covering every check in `validate_score_body`, plus boundary cases on `min_score_for_lines`.

## Conventions

- Piece rotations are **data**, not computed. If a rotation looks wrong, edit the array in [src/pieces.js](src/pieces.js).
- The render layer is the **only** place that touches canvas or HUD DOM.
- Canvas dimensions are hardcoded in [index.html](index.html) to match `CELL × COLS` and `CELL × ROWS` in [src/config.js](src/config.js).
- The server mirrors `LINE_POINTS` from `src/config.js`. Drift = startup assertion failure (intentional — refuses to silently mis-validate).

## License

See [LICENSE](LICENSE).
