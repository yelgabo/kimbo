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

# Static serving is scoped to the game's actual assets, not just "any file
# with an asset extension anywhere under the repo". Reachable set:
#   - the site root  ("/" -> index.html)
#   - an explicit root-file allowlist (index.html, styles.css, favicon)
#   - anything under src/ with an allowlisted asset extension
# Everything else (server.py, tests/, docs/, *.md, config, dotfiles) is denied.
STATIC_ROOT_FILES = frozenset(("index.html", "styles.css", "favicon.ico"))
STATIC_ASSET_DIR = "src"
STATIC_ALLOWED_SUFFIXES = (
    ".html", ".css", ".js", ".mjs", ".map",
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".otf",
)

# Sent on every response. CSP allows same-origin assets plus the Google Fonts
# stylesheet (fonts.googleapis.com) and font files (fonts.gstatic.com) the
# page links; nothing inline (no inline <script>/<style>/style= is used).
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    (
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'",
    ),
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
        # When behind a trusted proxy, take the RIGHT-most X-Forwarded-For hop:
        # each proxy appends the address it saw, so the last entry is the client
        # as observed by our closest trusted proxy. Trusting the left-most entry
        # would let a directly-reachable origin be handed a spoofed client IP
        # (defeating the per-IP rate-limit arm).
        if self.trust_proxy:
            fwd = self.headers.get("X-Forwarded-For")
            if fwd:
                parts = [p.strip() for p in fwd.split(",") if p.strip()]
                if parts:
                    return parts[-1]
        return self.client_address[0]

    # ── safety overrides ──

    def list_directory(self, path):
        # Directory listings leak layout. Deny.
        self.send_error(404, "Not Found")
        return None

    def _static_rel_allowed(self, rel):
        """Decide on the REPO_ROOT-relative path (POSIX '/'-joined) that will
        actually be opened. Denies any dotfile/dot-dir segment, then scopes to
        the game's assets: an explicit root-file allowlist, or a file under
        src/ with an allowlisted extension. Everything else is refused.
        """
        parts = rel.split("/")
        if any(p.startswith(".") for p in parts):
            return False
        if len(parts) == 1:
            return parts[0] in STATIC_ROOT_FILES
        if parts[0] == STATIC_ASSET_DIR:
            return parts[-1].lower().endswith(STATIC_ALLOWED_SUFFIXES)
        return False

    def send_head(self):
        # Run the allow-decision on the SAME filesystem path the base handler
        # will open (translate_path already unquotes, normalizes, strips
        # query/fragment, and confines the result under REPO_ROOT). This avoids
        # any urlparse/translate_path divergence (e.g. '//server.py'). A bad
        # byte (embedded NUL) surfaces as ValueError from isdir/relpath/open;
        # treat it as 404 rather than letting it bubble to a 500.
        try:
            fs_path = self.translate_path(self.path)
            if os.path.isdir(fs_path):
                # Only the site root serves its index.html; every other
                # directory (src/, docs/, ...) 404s. Keeps "/" working.
                if os.path.abspath(fs_path) != REPO_ROOT:
                    self.send_error(404, "Not Found")
                    return None
                return super().send_head()

            rel = os.path.relpath(fs_path, REPO_ROOT).replace(os.sep, "/")
            if rel.startswith("..") or not self._static_rel_allowed(rel):
                self.send_error(404, "Not Found")
                return None
            # Defense in depth: never serve DB artifacts even if scoping widens.
            lowered = rel.lower()
            for suf in DENIED_STATIC_SUFFIXES:
                if lowered.endswith(suf):
                    self.send_error(404, "Not Found")
                    return None
            return super().send_head()
        except ValueError:
            self.send_error(404, "Not Found")
            return None

    # ── routing ──

    def do_GET(self):
        started = time.monotonic()
        status = 200
        self._headers_started = False
        try:
            if self.path.startswith("/api/"):
                status = self._handle_api_get()
            else:
                super().do_GET()
                status = getattr(self, "_last_static_status", 200)
        except Exception:
            status = 500
            self._fail_500()
        finally:
            self._log_request(status, started)

    def do_POST(self):
        started = time.monotonic()
        status = 500
        self._headers_started = False
        try:
            if self.path.startswith("/api/"):
                status = self._handle_api_post()
            else:
                self._send_json(404, {"error": "not found"})
                status = 404
        except Exception:
            status = 500
            self._fail_500()
        finally:
            self._log_request(status, started)

    def _fail_500(self):
        """Best-effort 500. If a (possibly partial) response is already on the
        wire — e.g. a static file that failed mid-copy — don't write a second
        status line into the stream; just drop the connection so the client sees
        a truncated response rather than a corrupt double-send.
        """
        if getattr(self, "_headers_started", False):
            self.close_connection = True
            return
        try:
            self._send_json(500, {"error": "internal"})
        except Exception:
            self.close_connection = True

    # Track static status for logging; note that a response has begun so the
    # error path can avoid double-sending; and reset the per-response
    # security-header guard (handler instances are reused on keep-alive).
    def send_response(self, code, message=None):
        self._last_static_status = code
        self._headers_started = True
        self._security_headers_sent = False
        super().send_response(code, message)

    def end_headers(self):
        if not getattr(self, "_security_headers_sent", False):
            self._security_headers_sent = True
            for name, value in SECURITY_HEADERS:
                self.send_header(name, value)
        super().end_headers()

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
    # Env-var fallbacks support PaaS like Railway/Fly that inject $PORT.
    # CLI flags still override; local `python server.py` is unchanged.
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument(
        "--db",
        default=os.environ.get("DB_PATH", os.path.join(REPO_ROOT, "data", "kimbo.db")),
    )
    parser.add_argument("--origin", default=os.environ.get("KIMBO_ORIGIN") or None)
    parser.add_argument(
        "--trust-proxy",
        action="store_true",
        default=os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes"),
    )
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
