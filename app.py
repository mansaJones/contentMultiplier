"""Content Multiplier — Flask web app.

POST /generate runs the full pipeline (transcript synthesis + 3 transforms).
GET /        serves the single-page form + results UI.
GET /stats   returns current rate-limit + daily-budget state (auth-gated).
GET /healthz unauthenticated health check.

Auth: HTTP Basic. If WEB_PASSWORD is unset (local dev), auth is disabled.
When deployed, set WEB_PASSWORD (and optionally WEB_USERNAME, default 'admin').

Rate limiting (per-IP) and daily cost ceiling (global) both gate /generate.
Both are in-memory; on Render free tier they reset whenever the container
spins back up. Acceptable for v1 since the auth gate blocks most abuse;
swap to a persistent backend (Redis, SQLite) for hardened production.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

# Load .env BEFORE importing config (config reads at import time)
load_dotenv()

from content_multiplier import web_pipeline  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("content_multiplier.web")

app = Flask(__name__)

# Trust ONE layer of proxy (Render's load balancer) so that request.remote_addr
# and Flask-Limiter's get_remote_address see the real client IP from
# X-Forwarded-For instead of the proxy's internal IP.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")

RATE_LIMIT_HOURLY = os.getenv("RATE_LIMIT_HOURLY", "5 per hour")
RATE_LIMIT_DAILY = os.getenv("RATE_LIMIT_DAILY", "20 per day")

DAILY_MAX_GENERATIONS = int(os.getenv("DAILY_MAX_GENERATIONS", "50"))
DAILY_MAX_USD = float(os.getenv("DAILY_MAX_USD", "5.00"))
COST_PER_GENERATION_USD = float(os.getenv("COST_PER_GENERATION_USD", "0.08"))

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
    headers_enabled=True,  # adds X-RateLimit-* headers to responses
)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def requires_auth(f):
    """HTTP Basic gate. Bypassed when WEB_PASSWORD is unset (local dev only)."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not WEB_PASSWORD:
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not (
            secrets.compare_digest(auth.username or "", WEB_USERNAME)
            and secrets.compare_digest(auth.password or "", WEB_PASSWORD)
        ):
            return Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Content Multiplier"'},
            )
        return f(*args, **kwargs)

    return decorated


# --------------------------------------------------------------------------- #
# Daily budget (global across all users)
# --------------------------------------------------------------------------- #
class DailyBudget:
    """In-memory daily budget tracker.

    Resets at UTC midnight. State is in-memory only; on Render free-tier
    spin-down this resets when the container restarts. For persistent
    accounting across restarts, swap the storage to SQLite or Redis.
    """

    def __init__(self, max_generations: int, max_usd: float, cost_per_gen: float):
        self.max_generations = max_generations
        self.max_usd = max_usd
        self.cost_per_gen = cost_per_gen
        self._date = None
        self._count = 0
        self._cost = 0.0

    def _maybe_reset(self) -> None:
        today = datetime.now(timezone.utc).date()
        if self._date != today:
            self._date = today
            self._count = 0
            self._cost = 0.0

    def check(self) -> str | None:
        """None if budget allows another generation, else a reason string."""
        self._maybe_reset()
        if self._count >= self.max_generations:
            return f"Daily generation cap reached ({self.max_generations}/day)."
        if self._cost + self.cost_per_gen > self.max_usd:
            return f"Daily spend cap reached (~${self.max_usd:.2f}/day estimated)."
        return None

    def record(self) -> None:
        self._maybe_reset()
        self._count += 1
        self._cost += self.cost_per_gen

    def status(self) -> dict:
        self._maybe_reset()
        return {
            "date_utc": str(self._date),
            "generations_used": self._count,
            "generations_max": self.max_generations,
            "cost_used_usd": round(self._cost, 4),
            "cost_max_usd": self.max_usd,
            "cost_per_generation_estimate_usd": self.cost_per_gen,
        }


budget = DailyBudget(
    max_generations=DAILY_MAX_GENERATIONS,
    max_usd=DAILY_MAX_USD,
    cost_per_gen=COST_PER_GENERATION_USD,
)


# --------------------------------------------------------------------------- #
# Per-IP usage tracker (mirrors Flask-Limiter counts, exposed via /quota)
# --------------------------------------------------------------------------- #
def _parse_amount(rate_str: str) -> int:
    """Extract the leading integer from a 'N per ...' Flask-Limiter string."""
    m = re.match(r"\s*(\d+)", rate_str)
    return int(m.group(1)) if m else 0


class IPUsageTracker:
    """Sliding-window counter mirroring the rate limiter, exposed for /quota.

    In-memory only; same persistence caveats as the rate limiter and the
    DailyBudget. Doesn't enforce limits — Flask-Limiter does that — this
    just tells the UI what's left so the user can see it.
    """

    HOUR = 3600
    DAY = 86400

    def __init__(self, hourly_max: int, daily_max: int):
        self.hourly_max = hourly_max
        self.daily_max = daily_max
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, ip: str) -> None:
        now = time.time()
        q = self._events[ip]
        while q and now - q[0] > self.DAY:
            q.popleft()

    def record(self, ip: str) -> None:
        self._prune(ip)
        self._events[ip].append(time.time())

    def stats(self, ip: str) -> dict:
        self._prune(ip)
        now = time.time()
        q = self._events[ip]
        hourly_used = sum(1 for t in q if now - t < self.HOUR)
        daily_used = len(q)
        hourly_reset = 0
        daily_reset = 0
        if hourly_used >= self.hourly_max and q:
            oldest_hr = next((t for t in q if now - t < self.HOUR), None)
            if oldest_hr is not None:
                hourly_reset = max(0, int(self.HOUR - (now - oldest_hr)))
        if daily_used >= self.daily_max and q:
            daily_reset = max(0, int(self.DAY - (now - q[0])))
        return {
            "hourly_used": hourly_used,
            "hourly_remaining": max(0, self.hourly_max - hourly_used),
            "hourly_max": self.hourly_max,
            "hourly_reset_in_seconds": hourly_reset,
            "daily_used": daily_used,
            "daily_remaining": max(0, self.daily_max - daily_used),
            "daily_max": self.daily_max,
            "daily_reset_in_seconds": daily_reset,
        }


ip_tracker = IPUsageTracker(
    hourly_max=_parse_amount(RATE_LIMIT_HOURLY),
    daily_max=_parse_amount(RATE_LIMIT_DAILY),
)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
@requires_auth
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
@requires_auth
@limiter.limit(RATE_LIMIT_HOURLY)
@limiter.limit(RATE_LIMIT_DAILY)
def generate():
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "topic is required"}), 400

    tone = (data.get("tone") or "professional thought-leader").strip()
    audience = (data.get("audience") or "B2B marketing leaders").strip()
    length = (data.get("length") or "5 minute monologue").strip()
    fmt = (data.get("format") or "monologue").strip().lower()
    if fmt not in ("monologue", "interview"):
        fmt = "monologue"

    # Budget gate — refuse BEFORE making any Anthropic calls.
    reason = budget.check()
    if reason:
        log.warning("Budget refused request: %s", reason)
        return jsonify({"error": reason, "status": budget.status()}), 429

    log.info(
        "Generating: format=%s topic=%r tone=%r length=%r",
        fmt, topic[:60], tone, length,
    )
    try:
        result = web_pipeline.generate_all(
            topic=topic, tone=tone, audience=audience, length=length, format=fmt
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Generation failed")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    # Only debit budget + IP counter on success — failed runs shouldn't burn the cap.
    budget.record()
    ip_tracker.record(get_remote_address())
    log.info(
        "Done: %d-word transcript -> drafts (errors=%s)",
        result.get("word_count", 0),
        bool(result.get("errors")),
    )
    return jsonify(result)


@app.route("/quota")
@requires_auth
def quota():
    """Current caller's remaining attempts + budget headroom (for the UI counter)."""
    ip_stats = ip_tracker.stats(get_remote_address())
    bud = budget.status()
    budget_remaining = max(0, bud["generations_max"] - bud["generations_used"])
    return jsonify({
        "ip": ip_stats,
        "budget_remaining": budget_remaining,
        "budget_max": bud["generations_max"],
    })


@app.route("/stats")
@requires_auth
def stats():
    """Current rate-limit config + daily budget state. Useful for monitoring."""
    return jsonify({
        "budget": budget.status(),
        "rate_limits": {
            "per_ip_hourly": RATE_LIMIT_HOURLY,
            "per_ip_daily": RATE_LIMIT_DAILY,
        },
        "auth_enabled": bool(WEB_PASSWORD),
    })


@app.route("/healthz")
def healthz():
    """Unauthenticated health check for deploy targets."""
    return "ok", 200


@app.errorhandler(429)
def handle_429(e):
    """Return clean JSON for rate-limit hits instead of Flask-Limiter's HTML."""
    detail = getattr(e, "description", "Too many requests.")
    return jsonify({"error": "Rate limit exceeded.", "detail": str(detail)}), 429


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="127.0.0.1", port=port, debug=debug)
