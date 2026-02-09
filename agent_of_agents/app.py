"""
Agent of Agents - Web Application
Flask server with SSE streaming for real-time agent pipeline visualization.
"""

import json
import os
import time
from flask import Flask, render_template, request, Response, jsonify, send_from_directory

from orchestrator import Orchestrator

app = Flask(__name__)

# Store active sessions
sessions = {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/run", methods=["POST"])
def run_pipeline():
    """Start the agent pipeline. Returns a session ID for SSE streaming."""
    data = request.json
    user_request = data.get("request", "")
    api_key = data.get("api_key", "")
    model = data.get("model", "claude-sonnet-4-20250514")
    max_attempts = data.get("max_attempts", 5)

    if not user_request.strip():
        return jsonify({"error": "Request cannot be empty"}), 400

    session_id = f"session_{int(time.time() * 1000)}"
    sessions[session_id] = {
        "request": user_request,
        "api_key": api_key,
        "model": model,
        "max_attempts": max_attempts,
        "status": "pending",
    }

    return jsonify({"session_id": session_id})


@app.route("/api/stream/<session_id>")
def stream(session_id):
    """SSE endpoint for streaming pipeline events."""
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    def generate():
        orchestrator = Orchestrator(
            api_key=session["api_key"] or None,
            model=session["model"],
            max_fix_attempts=session["max_attempts"],
        )
        sessions[session_id]["status"] = "running"

        for event in orchestrator.run(session["request"], session_id):
            yield event

        sessions[session_id]["status"] = "complete"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/files/<session_id>")
def get_files(session_id):
    """Get files from a workspace."""
    workspace = os.path.join("/tmp/agent_workspaces", session_id)
    if not os.path.exists(workspace):
        return jsonify({"error": "Workspace not found"}), 404

    files = {}
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fname in filenames:
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, workspace)
            try:
                with open(fpath, "r") as f:
                    files[relpath] = f.read()
            except (UnicodeDecodeError, PermissionError):
                files[relpath] = "[binary or unreadable file]"

    return jsonify({"files": files})


@app.route("/api/sessions")
def list_sessions():
    """List all sessions."""
    return jsonify({
        sid: {"request": s["request"][:100], "status": s["status"]}
        for sid, s in sessions.items()
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*60}")
    print(f"  Agent of Agents - GUI")
    print(f"  Running on http://localhost:{port}")
    print(f"{'='*60}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
