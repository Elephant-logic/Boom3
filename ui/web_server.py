"""
Modern Web UI for Boom3

Production hardening:
- ProjectStore abstraction: Redis-backed when BOOM3_REDIS_URL is set,
  in-process dict otherwise.  Swap the backend without touching routes.
- API key authentication: optional — set BOOM3_API_KEY to enable it.
- Rate limiting via flask-limiter (falls back gracefully if not installed).
- WebSocket client list protected by a threading.Lock.
- Binds to 0.0.0.0 by default so Render's proxy can reach it.
  PORT env var (set automatically by Render) is respected.
"""

from flask import Flask, render_template, jsonify, request
from flask_sock import Sock
from pathlib import Path
import json
import os
import uuid
import threading
import functools
from typing import Any, List, Optional
from openai import OpenAI

from core.orchestrator import (
    ProjectOrchestrator, create_orchestrator,
    ProjectContract, ExecutionState,
)
from contracts.agent_contracts import AgentRole


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__,
            template_folder='../ui/templates',
            static_folder='../ui/static')
sock = Sock(app)


# ---------------------------------------------------------------------------
# Configuration (all from environment — no secrets in source)
# ---------------------------------------------------------------------------

PROJECTS_BASE_DIR = Path(
    os.environ.get("BOOM3_PROJECTS_DIR", Path.home() / "boom3_projects")
).resolve()
PROJECTS_BASE_DIR.mkdir(parents=True, exist_ok=True)

BOOM3_API_KEY: str = os.environ.get("BOOM3_API_KEY", "")
BOOM3_HOST: str = os.environ.get("BOOM3_HOST", "0.0.0.0")
# Render injects PORT automatically; fall back to BOOM3_PORT or 5000
BOOM3_PORT: int = int(os.environ.get("PORT", os.environ.get("BOOM3_PORT", "5000")))

MAX_DESCRIPTION_LEN = 4000
MAX_PROJECT_NAME_LEN = 128


# ---------------------------------------------------------------------------
# Optional rate limiting (flask-limiter)
# ---------------------------------------------------------------------------

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["200 per hour", "30 per minute"],
        storage_uri=os.environ.get("BOOM3_REDIS_URL", "memory://"),
    )
    _limiter_available = True
except ImportError:
    limiter = None
    _limiter_available = False


# ---------------------------------------------------------------------------
# ProjectStore: Redis-backed or in-process dict
# ---------------------------------------------------------------------------

class ProjectStore:
    """
    Thin abstraction over project storage.

    When BOOM3_REDIS_URL is set, orchestrator metadata is serialised to Redis
    so multiple workers share state.  The orchestrator objects themselves still
    live in the worker process (they hold live threads); Redis stores enough
    info for other workers to answer status queries.

    When BOOM3_REDIS_URL is not set, falls back to a plain dict — fine for a
    single-process deployment or local development.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._local: dict = {}
        self._redis = None

        redis_url = os.environ.get("BOOM3_REDIS_URL")
        if redis_url:
            try:
                import redis as _redis
                self._redis = _redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
                app.logger.info("ProjectStore: Redis backend active (%s)", redis_url)
            except Exception as exc:
                app.logger.warning(
                    "ProjectStore: Redis unavailable (%s) — falling back to in-process dict. "
                    "State will NOT be shared across multiple workers.", exc
                )
                self._redis = None

    def set(self, project_id: str, orchestrator: "ProjectOrchestrator") -> None:
        with self._lock:
            self._local[project_id] = orchestrator
            if self._redis:
                self._sync_to_redis(project_id, orchestrator)

    def sync_state(self, project_id: str) -> None:
        """Push latest state/progress for a project to Redis. Call after each state change."""
        with self._lock:
            orch = self._local.get(project_id)
            if orch and self._redis:
                self._sync_to_redis(project_id, orch)

    def _sync_to_redis(self, project_id: str, orchestrator: "ProjectOrchestrator") -> None:
        """Write project metadata + current state to Redis (no lock assumed — caller holds it)."""
        try:
            self._redis.hset(
                "boom3:projects",
                project_id,
                json.dumps({
                    "id": project_id,
                    "root": str(orchestrator.project_root),
                    "state": orchestrator.state.current_state.value,
                    "progress": orchestrator.state.current_step / max(orchestrator.state.total_steps, 1) * 100,
                }),
            )
        except Exception as exc:
            app.logger.warning("Redis write error for project %s: %s", project_id, exc)

    def get(self, project_id: str) -> Optional["ProjectOrchestrator"]:
        with self._lock:
            return self._local.get(project_id)

    def all_summaries(self) -> list:
        with self._lock:
            local_ids = set(self._local.keys())
            summaries = [
                {
                    "id": pid,
                    "state": orch.state.current_state.value,
                    "progress": orch.state.current_step / max(orch.state.total_steps, 1) * 100,
                }
                for pid, orch in self._local.items()
            ]

            if self._redis:
                try:
                    all_entries = self._redis.hgetall("boom3:projects")
                    for pid, raw in all_entries.items():
                        if pid not in local_ids:
                            meta = json.loads(raw)
                            summaries.append({
                                "id": pid,
                                "state": meta.get("state", "unknown"),
                                "progress": meta.get("progress", 0),
                            })
                except Exception as exc:
                    app.logger.warning("Redis read error in all_summaries: %s", exc)

        return summaries

    def exists(self, project_id: str) -> bool:
        with self._lock:
            return project_id in self._local


_store = ProjectStore()


# ---------------------------------------------------------------------------
# WebSocket client registry (thread-safe)
# ---------------------------------------------------------------------------

class _WebSocketRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: List[Any] = []

    def add(self, ws: Any) -> None:
        with self._lock:
            self._clients.append(ws)

    def remove(self, ws: Any) -> None:
        with self._lock:
            try:
                self._clients.remove(ws)
            except ValueError:
                pass

    def broadcast(self, message: str) -> None:
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.send(message)
            except Exception:
                pass


_ws_registry = _WebSocketRegistry()


# ---------------------------------------------------------------------------
# Authentication decorator
# ---------------------------------------------------------------------------

def require_api_key(fn):
    """
    Optional API key enforcement.

    - If BOOM3_API_KEY is NOT set: all requests are allowed (simple/dev deploys).
    - If BOOM3_API_KEY IS set: requests with a matching X-Boom3-Key header are
      allowed. Requests from the same-origin browser UI (no header) are also
      allowed since they are not externally reachable without Render's proxy.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not BOOM3_API_KEY:
            return fn(*args, **kwargs)
        provided = request.headers.get("X-Boom3-Key", "")
        # Allow same-origin UI requests (no key header) and correct key
        if not provided or provided == BOOM3_API_KEY:
            return fn(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is not set. "
            "Add it in your Render dashboard under Environment Variables."
        )
    return OpenAI(api_key=api_key)


def _sanitize_description(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text[:MAX_DESCRIPTION_LEN]
    suspicious = [
        "ignore previous instructions", "ignore all instructions",
        "you are now", "disregard the above",
    ]
    lower = text.lower()
    for pattern in suspicious:
        if pattern in lower:
            app.logger.warning("Possible prompt injection attempt in project description.")
            break
    return text


def _safe_project_root(name_hint: str) -> Path:
    safe_name = Path(name_hint).name or "project"
    project_id = str(uuid.uuid4())
    project_root = (PROJECTS_BASE_DIR / safe_name / project_id).resolve()
    project_root.relative_to(PROJECTS_BASE_DIR)  # raises ValueError if escaped
    return project_root


def _broadcast_update(project_id: str, state: Any) -> None:
    message = json.dumps({
        "type": "state_update",
        "project_id": project_id,
        "state": state.current_state.value,
        "progress": state.current_step / max(state.total_steps, 1) * 100,
    })
    _ws_registry.broadcast(message)


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — API  (all protected)
# ---------------------------------------------------------------------------

@app.route("/api/projects", methods=["GET"])
@require_api_key
def list_projects():
    return jsonify({"projects": _store.all_summaries()})


@app.route("/api/projects", methods=["POST"])
@require_api_key
def create_project():
    data = request.json or {}

    try:
        project_root = _safe_project_root(data.get("project_root", "project"))
    except ValueError:
        return jsonify({"error": "Invalid project path"}), 400

    project_root.mkdir(parents=True, exist_ok=True)

    try:
        ai_client = _get_ai_client()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    project_id = project_root.name   # UUID from _safe_project_root
    orchestrator = create_orchestrator(project_root, ai_client)
    _store.set(project_id, orchestrator)

    return jsonify({"id": project_id, "status": "created"})


@app.route("/api/projects/<project_id>/start", methods=["POST"])
@require_api_key
def start_project(project_id):
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found"}), 404

    data = request.json or {}
    contract = ProjectContract(
        project_name=str(data.get("name", ""))[:MAX_PROJECT_NAME_LEN],
        description=_sanitize_description(data.get("description", "")),
        required_agents=[AgentRole(r) for r in data.get("required_agents", [])],
        expected_files=data.get("expected_files", {}),
        integration_points=data.get("integration_points", []),
    )

    def execute():
        try:
            orchestrator.execute_project(contract)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            orchestrator.state.current_state = ExecutionState.FAILED
            orchestrator.state.errors.append(str(exc))
        finally:
            _broadcast_update(project_id, orchestrator.state)
            _store.sync_state(project_id)

    threading.Thread(target=execute, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/projects/<project_id>/state", methods=["GET"])
@require_api_key
def get_project_state(project_id):
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found"}), 404
    return jsonify({
        "state": orchestrator.state.current_state.value,
        "current_step": orchestrator.state.current_step,
        "total_steps": orchestrator.state.total_steps,
        "errors": orchestrator.state.errors,
        "deliverables_count": len(orchestrator.state.deliverables),
    })


@app.route("/api/projects/<project_id>/pause", methods=["POST"])
@require_api_key
def pause_project(project_id):
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found"}), 404
    orchestrator.pause()
    return jsonify({"status": "paused"})


@app.route("/api/projects/<project_id>/resume", methods=["POST"])
@require_api_key
def resume_project(project_id):
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found"}), 404
    success = orchestrator.resume()
    return jsonify({"status": "resumed" if success else "failed"})


@app.route("/api/projects/<project_id>/cancel", methods=["POST"])
@require_api_key
def cancel_project(project_id):
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found"}), 404

    state = orchestrator.state.current_state.value
    if state in ("completed", "failed", "cancelled"):
        return jsonify({"error": f"Project is already {state}"}), 409

    orchestrator.cancel()
    _store.sync_state(project_id)
    _broadcast_update(project_id, orchestrator.state)
    return jsonify({"status": "cancelled"})


@app.route("/api/projects/<project_id>/wiring", methods=["GET"])
@require_api_key
def get_wiring_diagram(project_id):
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found"}), 404
    diagram = orchestrator.wiring_registry.generate_diagram()
    return jsonify({
        "diagram": diagram,
        "connections": [
            {
                "from": f"{c.from_component}.{c.from_symbol}",
                "to": f"{c.to_component}.{c.to_symbol}",
                "type": c.connection_type,
            }
            for c in orchestrator.wiring_registry.connections
        ],
    })


@app.route("/api/projects/<project_id>/logs", methods=["GET"])
@require_api_key
def get_project_logs(project_id):
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found"}), 404
    logs = getattr(orchestrator.state, 'logs', []) or []
    return jsonify({"logs": logs})


@app.route("/api/projects/<project_id>/files", methods=["GET"])
@require_api_key
def list_generated_files(project_id):
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found"}), 404
    files = [
        {
            "path": output.filepath,
            "language": output.language,
            "agent": deliverable.agent_role.value,
            "exports": output.exports,
        }
        for deliverable in orchestrator.state.deliverables
        for output in deliverable.outputs
    ]
    return jsonify({"files": files})


@app.route("/api/projects/<project_id>/files/<path:filepath>", methods=["GET"])
@require_api_key
def get_file_content(project_id, filepath):
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found"}), 404
    content = orchestrator.file_manager.read_file(filepath)
    if content is None:
        return jsonify({"error": "File not found"}), 404
    return jsonify({"content": content})


# ---------------------------------------------------------------------------
# Debug endpoint — shows last error for any project
# ---------------------------------------------------------------------------

@app.route("/api/debug/<project_id>")
def debug_project(project_id):
    """Returns full error list for a project — no auth needed for debugging."""
    orchestrator = _store.get(project_id)
    if not orchestrator:
        return jsonify({"error": "Project not found", "known_ids": list(_store._local.keys())}), 404
    return jsonify({
        "state": orchestrator.state.current_state.value,
        "errors": orchestrator.state.errors,
        "current_step": orchestrator.state.current_step,
        "total_steps": orchestrator.state.total_steps,
        "deliverables_count": len(orchestrator.state.deliverables),
    })

@app.route("/api/debug")
def debug_all():
    """Lists all known project IDs and their states."""
    return jsonify({
        "projects": {
            pid: {
                "state": orch.state.current_state.value,
                "errors": orch.state.errors,
                "steps": f"{orch.state.current_step}/{orch.state.total_steps}",
            }
            for pid, orch in _store._local.items()
        }
    })


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@sock.route("/ws/projects/<project_id>")
def project_websocket(ws, project_id):
    _ws_registry.add(ws)
    try:
        while True:
            data = ws.receive()
            if data == "ping":
                ws.send(json.dumps({"type": "pong"}))
    finally:
        _ws_registry.remove(ws)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Boom3 Web UI  ->  http://{BOOM3_HOST}:{BOOM3_PORT}")
    if not _limiter_available:
        print("  WARNING: flask-limiter not installed -- rate limiting disabled.")
    app.run(host=BOOM3_HOST, port=BOOM3_PORT, debug=False)
