#!/usr/bin/env python3
"""kimbo leaderboard server. Stdlib-only HTTP + sqlite3.

Serves the static repo at / and a JSON API at /api/*. Backed by SQLite
in WAL mode. Designed to bind to loopback in production and sit behind
a reverse proxy (Caddy/nginx) that terminates TLS.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import OrderedDict, deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlparse, parse_qs

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
DISPLAY_NAME_RE = re.compile(r"^anon-[0-9a-f]{4}$")

MAX_BODY_BYTES = 65536          # large enough for a ~5-min replay log
MAX_REPLAY_LOG_BYTES = 60_000   # base64-ish JSON array of [t,op] pairs
RATE_LIMIT_WINDOW_SEC = 60
RATE_LIMIT_MAX_HITS = 6
RATE_LIMIT_BUCKET_CAP = 10_000

EXPECTED_BODY_KEYS = frozenset(
    ("playerId", "displayName", "score", "lines", "level", "durationMs", "seed", "replayLog")
)

DENIED_STATIC_SUFFIXES = (
    ".db", ".db-journal", ".db-wal", ".db-shm",
    ".sqlite", ".sqlite-journal", ".sqlite-wal", ".sqlite-shm", ".sqlite3",
)

# Mirror of LINE_POINTS in src/config.js. Verified at startup; if config.js drifts,
# the server refuses to boot rather than silently mis-validate.
LINE_POINTS = [0, 40, 100, 300, 1200]
LINES_PER_LEVEL = 10

# Derived ceilings. All from LINE_POINTS + sustained-human limits.
MAX_LINES_PER_SEC = 6              # pro Tetris sustained pace
MIN_MS_PER_LINE = 100              # reciprocal of MAX_LINES_PER_SEC
MAX_SCORE_PER_SEC_PER_LEVEL = 2500 # 1200 * L * (6/4) lines/sec + slack
HARD_DROP_BONUS_PER_SEC = 114      # 19 cells * 2pts * 3 pieces/sec


def min_score_for_lines(lines):
    """Cheapest possible score for N lines: every clear is a single (40 * level).
    Level increments every LINES_PER_LEVEL lines per game.js.

    This is the LOWER bound that catches forged payloads like
    `{score: 9_500_000, lines: 8000, level: 801, ...}` — 8000 lines of all
    singles is already 128M, so 9.5M is mathematically impossible.
    """
    full = lines // LINES_PER_LEVEL
    remainder = lines % LINES_PER_LEVEL
    return (
        LINE_POINTS[1] * LINES_PER_LEVEL * full * (full + 1) // 2
        + LINE_POINTS[1] * (full + 1) * remainder
    )


def _verify_config_coupling():
    """Assert src/config.js's LINE_POINTS still matches the server mirror.
    Run at startup; fail loudly rather than silently mis-validate after a config edit.
    """
    config_js = os.path.join(REPO_ROOT, "src", "config.js")
    with open(config_js) as f:
        m = re.search(r"LINE_POINTS\s*=\s*\[([^\]]+)\]", f.read())
    if not m:
        raise RuntimeError("could not find LINE_POINTS in src/config.js")
    actual = [int(x.strip()) for x in m.group(1).split(",")]
    if actual != LINE_POINTS:
        raise RuntimeError(
            f"LINE_POINTS drift: server expects {LINE_POINTS}, "
            f"config.js has {actual}. Update server.py constants and re-derive ceilings."
        )


# ─── DB ───────────────────────────────────────────────────────────────

def db_connect(path):
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def db_init(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    conn = db_connect(path)
    try:
        conn.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous  = NORMAL;
            CREATE TABLE IF NOT EXISTS scores (
              id           INTEGER PRIMARY KEY AUTOINCREMENT,
              player_id    TEXT    NOT NULL,
              display_name TEXT    NOT NULL,
              score        INTEGER NOT NULL,
              lines        INTEGER NOT NULL,
              level        INTEGER NOT NULL,
              duration_ms  INTEGER NOT NULL,
              created_at   INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_scores_top
              ON scores(score DESC, created_at ASC);
            """
        )
        # Migrations are idempotent: each ALTER is wrapped to tolerate
        # "duplicate column" if a racing process won the migration first.
        _migrate(conn)
    finally:
        conn.close()


def _migrate(conn):
    """Migration ladder, gated by PRAGMA user_version.

    Wrapped in a serialized transaction to prevent concurrent server starts
    from both running the same ALTER and crashing. ALTER TABLE ADD COLUMN
    in SQLite is atomic (no rewrite), and we tolerate idempotent re-runs.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur_version = conn.execute("PRAGMA user_version").fetchone()[0]

        if cur_version < 1:
            conn.execute("PRAGMA user_version = 1")
            cur_version = 1

        if cur_version < 2:
            for stmt in (
                "ALTER TABLE scores ADD COLUMN seed INTEGER",
                "ALTER TABLE scores ADD COLUMN replay_log TEXT",
            ):
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            conn.execute("PRAGMA user_version = 2")

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ─── Rate limiter ─────────────────────────────────────────────────────

class RateLimiter:
    """Two LRU-capped OrderedDicts: by playerId and by client IP.

    Bucket caps prevent unbounded growth from UUID/IP rotation DoS.
    """

    def __init__(self):
        self._by_player = OrderedDict()
        self._by_ip = OrderedDict()
        self._lock = Lock()

    def _hit(self, bucket, key, now):
        if key in bucket:
            bucket.move_to_end(key)
            dq = bucket[key]
        else:
            if len(bucket) >= RATE_LIMIT_BUCKET_CAP:
                bucket.popitem(last=False)
            dq = deque()
            bucket[key] = dq
        while dq and now - dq[0] > RATE_LIMIT_WINDOW_SEC:
            dq.popleft()
        if len(dq) >= RATE_LIMIT_MAX_HITS:
            return False
        dq.append(now)
        return True

    def allow(self, player_id, ip):
        now = time.monotonic()
        with self._lock:
            return self._hit(self._by_player, player_id, now) and self._hit(
                self._by_ip, ip, now
            )


# ─── Handler ──────────────────────────────────────────────────────────

class KimboHandler(SimpleHTTPRequestHandler):
    server_version = "kimbo/1.0"

    # Class-level config injected by main()
    db_path = None
    expected_origin = None  # None = accept same-origin / missing Origin
    trust_proxy = False
    limiter = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=REPO_ROOT, **kwargs)

    # ── logging ──

    def log_message(self, format, *args):  # noqa: A002 (signature locked by base)
        # Suppress default per-request log; we emit our own JSON line.
        pass

    def _log_request(self, status, started_monotonic):
        ms = int((time.monotonic() - started_monotonic) * 1000)
        rec = {
            "ts": int(time.time() * 1000),
            "method": self.command,
            "path": self.path,
            "status": status,
            "ms": ms,
            "ip": self._real_ip(),
        }
        sys.stdout.write(json.dumps(rec, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    def _real_ip(self):
        if self.trust_proxy:
            fwd = self.headers.get("X-Forwarded-For")
            if fwd:
                return fwd.split(",")[0].strip()
        return self.client_address[0]

    # ── safety overrides ──

    def list_directory(self, path):
        # Directory listings leak layout. Deny.
        self.send_error(404, "Not Found")
        return None

    def send_head(self):
        # Block direct fetch of DB files even if they ever land in the served tree.
        if self.path:
            lowered = self.path.lower().split("?", 1)[0]
            for suf in DENIED_STATIC_SUFFIXES:
                if lowered.endswith(suf):
                    self.send_error(404, "Not Found")
                    return None
        return super().send_head()

    # ── routing ──

    def do_GET(self):
        started = time.monotonic()
        status = 200
        try:
            if self.path.startswith("/api/"):
                status = self._handle_api_get()
            else:
                super().do_GET()
                status = getattr(self, "_last_static_status", 200)
        except Exception:
            status = 500
            self._send_json(500, {"error": "internal"})
        finally:
            self._log_request(status, started)

    def do_POST(self):
        started = time.monotonic()
        status = 500
        try:
            if self.path.startswith("/api/"):
                status = self._handle_api_post()
            else:
                self._send_json(404, {"error": "not found"})
                status = 404
        except Exception:
            self._send_json(500, {"error": "internal"})
            status = 500
        finally:
            self._log_request(status, started)

    # Track static status for logging
    def send_response(self, code, message=None):
        self._last_static_status = code
        super().send_response(code, message)

    # ── API: GET ──

    def _handle_api_get(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/leaderboard":
            return self._get_leaderboard(parsed)
        m = re.match(r"^/api/replay/(\d+)$", parsed.path)
        if m:
            return self._get_replay(int(m.group(1)))
        self._send_json(404, {"error": "not found"})
        return 404

    def _get_replay(self, score_id):
        if score_id <= 0 or score_id > 2**31:
            self._send_json(400, {"error": "bad id"})
            return 400
        conn = db_connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT display_name, score, lines, level, duration_ms, seed, replay_log
                  FROM scores WHERE id = ?
                """,
                (score_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None or row["seed"] is None or row["replay_log"] is None:
            self._send_json(404, {"error": "not found"})
            return 404
        self._send_json(200, {
            "displayName": row["display_name"],
            "score": row["score"],
            "lines": row["lines"],
            "level": row["level"],
            "durationMs": row["duration_ms"],
            "seed": row["seed"],
            "log": row["replay_log"],
        })
        return 200

    def _get_leaderboard(self, parsed):
        q = parse_qs(parsed.query)
        try:
            n = int((q.get("limit") or ["10"])[0])
        except (TypeError, ValueError):
            self._send_json(400, {"error": "bad limit"})
            return 400
        n = max(1, min(100, n))
        conn = db_connect(self.db_path)
        try:
            rows = conn.execute(
                # safe: n is a clamped int; LIMIT cannot be bound as a parameter
                f"""
                SELECT id, display_name, score, lines, level, created_at,
                       ROW_NUMBER() OVER (ORDER BY score DESC, created_at ASC) AS rank,
                       (seed IS NOT NULL AND replay_log IS NOT NULL) AS has_replay
                  FROM scores
                 ORDER BY score DESC, created_at ASC
                 LIMIT {n}
                """
            ).fetchall()
        finally:
            conn.close()
        entries = [
            {
                "id": r["id"],
                "rank": r["rank"],
                "displayName": r["display_name"],
                "score": r["score"],
                "lines": r["lines"],
                "level": r["level"],
                "createdAt": r["created_at"],
                "hasReplay": bool(r["has_replay"]),
            }
            for r in rows
        ]
        self._send_json(200, {"entries": entries})
        return 200

    # ── API: POST ──

    def _handle_api_post(self):
        if self.path != "/api/scores":
            self._send_json(404, {"error": "not found"})
            return 404

        if self.headers.get("Content-Type", "") != "application/json":
            self._send_json(400, {"error": "content-type must be application/json"})
            return 400

        if self.expected_origin is not None:
            origin = self.headers.get("Origin")
            if origin != self.expected_origin:
                self._send_json(403, {"error": "origin not allowed"})
                return 403
        else:
            origin = self.headers.get("Origin")
            if origin is not None:
                host = self.headers.get("Host", "")
                if host and origin not in (f"http://{host}", f"https://{host}"):
                    self._send_json(403, {"error": "origin mismatch"})
                    return 403

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "bad content-length"})
            return 400
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(400, {"error": "body too large or empty"})
            return 400

        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "bad json"})
            return 400

        ok, err = validate_score_body(body)
        if not ok:
            self._send_json(400, {"error": err})
            return 400

        if not self.limiter.allow(body["playerId"], self._real_ip()):
            self._send_json(429, {"error": "rate limited"})
            return 429

        now_ms = int(time.time() * 1000)
        conn = db_connect(self.db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO scores
                  (player_id, display_name, score, lines, level, duration_ms, created_at, seed, replay_log)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    body["playerId"],
                    body["displayName"],
                    body["score"],
                    body["lines"],
                    body["level"],
                    body["durationMs"],
                    now_ms,
                    body["seed"],
                    body["replayLog"],
                ),
            )
            new_id = cur.lastrowid
            conn.commit()
            rank_row = conn.execute(
                """
                SELECT COUNT(*) + 1 AS rank
                  FROM scores
                 WHERE score > ?
                    OR (score = ? AND created_at < ?)
                """,
                (body["score"], body["score"], now_ms),
            ).fetchone()
            total = conn.execute("SELECT COUNT(*) AS c FROM scores").fetchone()["c"]
        finally:
            conn.close()

        self._send_json(200, {"id": new_id, "rank": rank_row["rank"], "total": total})
        return 200

    # ── helpers ──

    def _send_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


# ─── Validation ───────────────────────────────────────────────────────

def _is_int(x):
    # `isinstance(True, int)` is True in Python — reject bools explicitly.
    return type(x) is int


def validate_score_body(body):
    if not isinstance(body, dict):
        return False, "body must be object"
    keys = set(body.keys())
    if keys != EXPECTED_BODY_KEYS:
        return False, "unexpected or missing keys"

    pid = body["playerId"]
    name = body["displayName"]
    if not isinstance(pid, str) or not UUID_V4_RE.match(pid):
        return False, "invalid playerId"
    if not isinstance(name, str) or not DISPLAY_NAME_RE.match(name):
        return False, "invalid displayName"
    if name != "anon-" + pid[:4]:
        return False, "displayName must derive from playerId"

    for field in ("score", "lines", "level", "durationMs", "seed"):
        if not _is_int(body[field]):
            return False, f"{field} must be int"

    if not isinstance(body["replayLog"], str):
        return False, "replayLog must be string"
    if len(body["replayLog"]) > MAX_REPLAY_LOG_BYTES:
        return False, "replayLog too large"

    score = body["score"]
    lines = body["lines"]
    level = body["level"]
    dur = body["durationMs"]
    seed = body["seed"]

    # Per-field bounds.
    if not (0 <= score <= 10_000_000):
        return False, "score out of range"
    if not (0 <= lines <= 100_000):
        return False, "lines out of range"
    if not (1 <= level <= 1000):
        return False, "level out of range"
    if not (1000 <= dur <= 86_400_000):
        return False, "durationMs out of range"
    if not (0 <= seed <= 0xFFFFFFFF):
        return False, "seed out of range"

    # Exact invariant from game.js:51 — level == floor(lines/10) + 1.
    if level != lines // LINES_PER_LEVEL + 1:
        return False, "level does not match lines"

    # No lines → only drop bonuses contribute to score.
    if lines == 0 and score > HARD_DROP_BONUS_PER_SEC * (dur // 1000 + 1):
        return False, "score with no lines exceeds drop bonus ceiling"

    # Time floor relative to lines: at most 10 lines/sec ever.
    if dur < max(1000, lines * MIN_MS_PER_LINE):
        return False, "durationMs too short for lines cleared"

    # Lines-per-second ceiling.
    if lines > MAX_LINES_PER_SEC * (dur // 1000):
        return False, "lines exceed human rate"

    # Score-per-second ceiling, scaled by level.
    if score > MAX_SCORE_PER_SEC_PER_LEVEL * level * (dur // 1000 + 1):
        return False, "score exceeds per-second ceiling"

    # Upper cross-field: every clear at max level is a Tetris (1200 * level),
    # plus drop bonus tied to duration. Above this is impossible.
    if score > LINE_POINTS[4] * level * lines + HARD_DROP_BONUS_PER_SEC * (dur // 1000 + 1):
        return False, "score exceeds max possible for lines/level/duration"

    # LOWER bound: even all-singles at the actual level progression has a
    # minimum. Catches the 9.5M / 8000-lines forgery.
    if score < min_score_for_lines(lines):
        return False, "score below minimum possible for lines"

    return True, None


# ─── Entry point ──────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description="kimbo leaderboard server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=os.path.join(REPO_ROOT, "data", "kimbo.db"))
    parser.add_argument("--origin", default=None)
    parser.add_argument("--trust-proxy", action="store_true")
    args = parser.parse_args(argv)

    _verify_config_coupling()
    db_init(args.db)

    KimboHandler.db_path = args.db
    KimboHandler.expected_origin = args.origin
    KimboHandler.trust_proxy = args.trust_proxy
    KimboHandler.limiter = RateLimiter()

    try:
        httpd = ThreadingHTTPServer((args.host, args.port), KimboHandler)
    except OSError as e:
        if getattr(e, "errno", None) in (48, 98):  # EADDRINUSE on mac/linux
            print(
                f"port {args.port} is in use — try: python server.py --port {args.port + 1}",
                file=sys.stderr,
            )
            return 1
        raise

    print(
        f"kimbo serving http://{args.host}:{args.port}  "
        f"(db: {args.db}, origin: {args.origin or '*'})",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
