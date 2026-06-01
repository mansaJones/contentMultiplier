"""Content Multiplier — Flask web app.

POST /generate runs the full pipeline (transcript synthesis + 3 transforms).
GET / serves the single-page form + results UI.

Auth: HTTP Basic. If WEB_PASSWORD is unset (local dev), auth is disabled.
When deployed, set WEB_PASSWORD (and optionally WEB_USERNAME, default 'admin').
"""

from __future__ import annotations

import logging
import os
import secrets
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

# Load .env BEFORE importing config (config reads at import time)
load_dotenv()

from content_multiplier import web_pipeline  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("content_multiplier.web")

app = Flask(__name__)

WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")


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


@app.route("/")
@requires_auth
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
@requires_auth
def generate():
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "topic is required"}), 400

    tone = (data.get("tone") or "professional thought-leader").strip()
    audience = (data.get("audience") or "B2B marketing leaders").strip()
    length = (data.get("length") or "5 minute monologue").strip()

    log.info("Generating: topic=%r tone=%r length=%r", topic[:60], tone, length)
    try:
        result = web_pipeline.generate_all(
            topic=topic, tone=tone, audience=audience, length=length
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Generation failed")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    log.info(
        "Done: %d-word transcript -> drafts (errors=%s)",
        result.get("word_count", 0),
        bool(result.get("errors")),
    )
    return jsonify(result)


@app.route("/healthz")
def healthz():
    """Unauthenticated health check for deploy targets."""
    return "ok", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="127.0.0.1", port=port, debug=debug)
