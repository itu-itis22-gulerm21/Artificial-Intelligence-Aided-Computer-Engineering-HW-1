"""
Brightwave Crawler - Flask API
"""

import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

import crawler as crawler_engine
import search_service

app = Flask(__name__, static_folder="demo", static_url_path="/demo")
CORS(app)

DEMO_DIR = os.path.join(os.path.dirname(__file__), "demo")


# ---- Static pages ----

@app.route("/")
def index():
    return send_from_directory(DEMO_DIR, "crawler.html")


@app.route("/crawler")
@app.route("/crawler.html")
def crawler_page():
    return send_from_directory(DEMO_DIR, "crawler.html")


@app.route("/search")
@app.route("/search.html")
def search_page():
    return send_from_directory(DEMO_DIR, "search.html")


@app.route("/status")
@app.route("/status.html")
def status_page():
    return send_from_directory(DEMO_DIR, "status.html")


# ---- API: Crawlers ----

@app.route("/api/crawl", methods=["POST"])
def start_crawl():
    data = request.get_json(force=True) or {}
    origin = data.get("origin", "").strip()
    if not origin:
        return jsonify({"error": "origin URL is required"}), 400
    if not origin.startswith(("http://", "https://")):
        origin = "https://" + origin

    try:
        max_depth = int(data.get("max_depth", 3))
        hit_rate = float(data.get("hit_rate", 1.0))
        queue_capacity = int(data.get("queue_capacity", 10000))
        max_urls = int(data.get("max_urls", 100))
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid parameter: {e}"}), 400

    crawler_id = crawler_engine.start_crawler(
        origin=origin,
        max_depth=max_depth,
        hit_rate=hit_rate,
        queue_capacity=queue_capacity,
        max_urls=max_urls,
    )

    return jsonify({
        "crawler_id": crawler_id,
        "status": "active",
        "origin": origin,
    })


@app.route("/api/crawlers", methods=["GET"])
def list_crawlers():
    crawlers = crawler_engine.list_all_crawlers()
    return jsonify({"crawlers": crawlers})


@app.route("/api/crawlers/<crawler_id>", methods=["GET"])
def get_crawler_status(crawler_id):
    state = crawler_engine.load_crawler_state(crawler_id)
    if not state:
        return jsonify({"error": "Crawler not found"}), 404
    return jsonify(state)


@app.route("/api/crawlers/<crawler_id>/pause", methods=["POST"])
def pause_crawler(crawler_id):
    job = crawler_engine.get_crawler(crawler_id)
    if not job:
        # Try to update file state for persistence
        state = crawler_engine.load_crawler_state(crawler_id)
        if state:
            state["status"] = "paused"
            crawler_engine._save_crawler_state(state)
            return jsonify({"ok": True, "status": "paused"})
        return jsonify({"error": "Crawler not found"}), 404
    job.pause()
    return jsonify({"ok": True, "status": job.status})


@app.route("/api/crawlers/<crawler_id>/resume", methods=["POST"])
def resume_crawler(crawler_id):
    job = crawler_engine.get_crawler(crawler_id)
    if job:
        job.resume()
        return jsonify({"ok": True, "status": job.status})
    # Job not in memory — restore it from its saved state file
    restored_id = crawler_engine.resume_crawler(crawler_id)
    if not restored_id:
        return jsonify({"error": "Crawler not found or already finished"}), 404
    return jsonify({"ok": True, "status": "active", "resumed_from_disk": True})


@app.route("/api/crawlers/<crawler_id>/stop", methods=["POST"])
def stop_crawler(crawler_id):
    job = crawler_engine.get_crawler(crawler_id)
    if not job:
        state = crawler_engine.load_crawler_state(crawler_id)
        if state:
            state["status"] = "stopped"
            crawler_engine._save_crawler_state(state)
            return jsonify({"ok": True, "status": "stopped"})
        return jsonify({"error": "Crawler not found"}), 404
    job.stop()
    return jsonify({"ok": True, "status": "stopping"})


# ---- API: Stats ----

@app.route("/api/stats", methods=["GET"])
def stats():
    return jsonify(crawler_engine.get_stats())


@app.route("/api/clear", methods=["POST"])
def clear():
    crawler_engine.clear_all_data()
    return jsonify({"ok": True})


# ---- API: Search ----

@app.route("/api/search", methods=["GET"])
def search():
    query = request.args.get("q", "").strip()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    lucky = request.args.get("lucky", "false").lower() == "true"

    if not query:
        return jsonify({"error": "query is required"}), 400

    if lucky:
        result = search_service.feeling_lucky(query)
        return jsonify({"result": result})

    results = search_service.search(query, page=page, per_page=per_page)
    return jsonify(results)


import time as _time

# ---- API: Long Polling for crawler state ----
#
# How it works:
#   The client sends ?last_log=N where N is the number of log lines it already
#   has.  The server holds the connection open for up to LONG_POLL_TIMEOUT
#   seconds, checking every LONG_POLL_INTERVAL seconds whether new log lines
#   have appeared.  As soon as there is new data (or the crawler finishes) the
#   response is flushed immediately.  If nothing new arrives within the timeout
#   window the server returns the current state anyway so the client can
#   re-connect without an infinite wait.
#
LONG_POLL_TIMEOUT  = 25   # seconds – safely below browser/proxy 30 s timeouts
LONG_POLL_INTERVAL = 0.5  # polling granularity inside the held connection

@app.route("/api/crawlers/<crawler_id>/poll", methods=["GET"])
def long_poll_crawler(crawler_id):
    try:
        last_log = int(request.args.get("last_log", 0))
    except (ValueError, TypeError):
        last_log = 0

    deadline = _time.monotonic() + LONG_POLL_TIMEOUT

    while _time.monotonic() < deadline:
        state = crawler_engine.load_crawler_state(crawler_id)
        if not state:
            return jsonify({"error": "Crawler not found"}), 404

        current_logs = state.get("logs", [])
        is_terminal  = state.get("status") in ("finished", "stopped")

        # Return as soon as there are new log lines, or the job is done.
        if len(current_logs) > last_log or is_terminal:
            return jsonify({
                **state,
                "new_logs": current_logs[last_log:],
                "log_cursor": len(current_logs),
            })

        _time.sleep(LONG_POLL_INTERVAL)

    # Timeout – return current state so the client re-connects immediately.
    state = crawler_engine.load_crawler_state(crawler_id) or {}
    current_logs = state.get("logs", [])
    return jsonify({
        **state,
        "new_logs": current_logs[last_log:],
        "log_cursor": len(current_logs),
    })


def _auto_resume_on_startup():
    """Re-launch any crawler jobs that were active or paused when the server last stopped."""
    for state in crawler_engine.list_all_crawlers():
        if state.get("status") in ("active", "paused"):
            cid = state["id"]
            restored = crawler_engine.resume_crawler(cid)
            if restored:
                print(f"↩️  Resumed crawler {cid} (origin: {state['origin']})")


if __name__ == "__main__":
    os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)
    _auto_resume_on_startup()
    print("🕷️  Brightwave Crawler running at http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
