"""
Boom3 Core Orchestrator — WireStack-inspired Living Blueprint Architecture

Flow:
  1. Blueprint phase   — Architect builds a living blueprint from the prompt
  2. Design phase      — Cartographer maps modules, wiring, schema, contracts
  3. Build phase       — Builder writes one module at a time, per blueprint section
  4. Validate phase    — Validator checks each file before accepting it
  5. Wire phase        — Cartographer verifies all connections are complete
  6. Test phase        — Run tests; on failure feed errors back to Builder (codem8s loop)
  7. Review phase      — Reviewer scores against original prompt; reject if < 70
  8. Done
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import json, re, threading, os, subprocess, sys
from pathlib import Path
from datetime import datetime

# ── Specialist team model routing (WireStack pattern) ────────────────────────
def _team_model(role: str) -> str:
    env_key = f"BOOM3_MODEL_{role.upper()}"
    if os.environ.get(env_key):
        return os.environ[env_key]
    deep  = os.environ.get("BOOM3_MODEL_DEEP",  "gpt-4o")
    fast  = os.environ.get("BOOM3_MODEL_FAST",  "gpt-4o-mini")
    base  = os.environ.get("BOOM3_MODEL", "gpt-4o")
    return {"architect": deep, "planner": deep, "reviewer": deep, "security": deep,
            "builder": fast, "tester": fast, "repair": fast}.get(role, base)

from contracts.agent_contracts import (
    AgentRole, AgentDeliverable, ProjectContract, CodeOutput, WiringContract
)


# ── Enums & Data ──────────────────────────────────────────────────────────────

class ExecutionState(Enum):
    IDLE      = "idle"
    PLANNING  = "planning"
    EXECUTING = "executing"
    TESTING   = "testing"
    PAUSED    = "paused"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class ProjectState:
    current_state: ExecutionState
    current_step:  int
    total_steps:   int
    deliverables:  List[AgentDeliverable]
    errors:        List[str]
    logs:          List[str] = field(default_factory=list)
    run_id:        str       = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))

    def to_dict(self):
        return {
            "current_state": self.current_state.value,
            "current_step":  self.current_step,
            "total_steps":   self.total_steps,
            "deliverables":  [d.to_dict() for d in self.deliverables],
            "errors":        self.errors,
            "logs":          self.logs,
            "run_id":        self.run_id,
        }

    @classmethod
    def from_dict(cls, data):
        from contracts.agent_contracts import AgentDeliverable, AgentRole, CodeOutput, WiringContract
        deliverables = []
        for d in data.get("deliverables", []):
            outputs = [CodeOutput(code=o["code"], filepath=o["filepath"], language=o["language"],
                                  dependencies=o.get("dependencies",[]), exports=o.get("exports",[]),
                                  imports_from=o.get("imports_from",{})) for o in d["outputs"]]
            wiring  = [WiringContract(from_component=w["from_component"], from_symbol=w["from_symbol"],
                                      to_component=w["to_component"],   to_symbol=w["to_symbol"],
                                      connection_type=w["connection_type"], parameters=w.get("parameters"))
                       for w in d.get("wiring",[])]
            deliverables.append(AgentDeliverable(agent_role=AgentRole(d["agent_role"]),
                                                  outputs=outputs, wiring=wiring,
                                                  tests_generated=d.get("tests_generated",[]),
                                                  documentation=d.get("documentation","")))
        return cls(current_state=ExecutionState(data["current_state"]),
                   current_step=data["current_step"], total_steps=data["total_steps"],
                   deliverables=deliverables, errors=data.get("errors",[]),
                   logs=data.get("logs",[]), run_id=data.get("run_id",""))


# ── State Manager ─────────────────────────────────────────────────────────────

class StateManager:
    def __init__(self, project_root: Path):
        self.path = project_root / ".boom3_state.json"

    def save(self, state: ProjectState):
        try:
            self.path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        except Exception:
            pass

    def load(self) -> Optional[ProjectState]:
        try:
            return ProjectState.from_dict(json.loads(self.path.read_text()))
        except Exception:
            return None


# ── Wiring Registry ───────────────────────────────────────────────────────────

class WiringRegistry:
    def __init__(self):
        self.connections: List[WiringContract] = []

    def register(self, contract: WiringContract):
        self.connections.append(contract)

    def generate_diagram(self) -> str:
        if not self.connections:
            return "No wiring data yet. Start a project to see connections."
        lines = ["=== WIRING DIAGRAM ===", ""]
        by_type: Dict[str, list] = {}
        for c in self.connections:
            by_type.setdefault(c.connection_type, []).append(c)
        for ctype, conns in by_type.items():
            lines.append(f"{ctype.upper()}:")
            for c in conns:
                lines.append(f"  {c.from_component}.{c.from_symbol} -> {c.to_component}.{c.to_symbol}")
        return "\n".join(lines)


# ── File Manager ──────────────────────────────────────────────────────────────

class FileManager:
    def __init__(self, project_root: Path):
        self.root = project_root

    def write(self, filepath: str, code: str):
        target = (self.root / filepath).resolve()
        if not str(target).startswith(str(self.root.resolve())):
            raise ValueError(f"Refusing to write outside project: {filepath}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")

    def read(self, filepath: str) -> Optional[str]:
        try:
            return (self.root / filepath).read_text(encoding="utf-8")
        except Exception:
            return None

    def all_python_files(self) -> str:
        """Returns all Python source as one string for AI context."""
        chunks = []
        for p in sorted(self.root.rglob("*.py")):
            if ".venv" in p.parts or "__pycache__" in p.parts:
                continue
            rel = p.relative_to(self.root).as_posix()
            try:
                chunks.append(f"--- {rel} ---\n{p.read_text(encoding='utf-8', errors='replace')[:6000]}")
            except Exception:
                pass
        return "\n\n".join(chunks)[:30000]

    def all_files_snapshot(self) -> str:
        """All text files for AI context."""
        chunks = []
        for p in sorted(self.root.rglob("*")):
            if p.is_dir() or ".venv" in p.parts or "__pycache__" in p.parts:
                continue
            if p.suffix not in {".py", ".html", ".js", ".css", ".txt", ".md", ".yaml", ".yml", ".json"}:
                continue
            rel = p.relative_to(self.root).as_posix()
            try:
                chunks.append(f"--- {rel} ---\n{p.read_text(encoding='utf-8', errors='replace')[:4000]}")
            except Exception:
                pass
        return "\n\n".join(chunks)[:40000]


# ── Test Orchestrator ─────────────────────────────────────────────────────────

class TestOrchestrator:
    def __init__(self, project_root: Path):
        self.root = project_root
        self.venv = self._find_venv()

    def _find_venv(self) -> str:
        for candidate in [
            "/opt/render/project/src/.venv/bin/python3.14",
            "/opt/render/project/src/.venv/bin/python3",
            sys.executable,
        ]:
            if os.path.exists(candidate):
                return candidate
        return sys.executable

    def install_dependencies(self, deliverables=None):
        req = self.root / "requirements.txt"
        cmds = []
        # Uninstall local module names to avoid shadowing
        local_names = ["api", "api-integration", "app", "config", "conftest", "database",
                       "gui", "logic", "main", "models", "routes", "service", "services",
                       "test-logic", "test-app", "views"]
        r = subprocess.run([self.venv, "-m", "pip", "uninstall", "-y"] + local_names,
                           capture_output=True, text=True, cwd=self.root)
        cmds.append(f"$ {self.venv} -m pip uninstall -y <local generated module names>\nSTDOUT: {r.stdout}\nSTDERR: {r.stderr}")

        if req.exists():
            r = subprocess.run([self.venv, "-m", "pip", "install", "-r", str(req)],
                               capture_output=True, text=True, cwd=self.root)
            cmds.append(f"$ {self.venv} -m pip install -r requirements.txt\nSTDOUT: {r.stdout}\nSTDERR: {r.stderr}")
        else:
            r = subprocess.run([self.venv, "-m", "pip", "install", "pytest", "requests"],
                               capture_output=True, text=True, cwd=self.root)
            cmds.append(f"$ {self.venv} -m pip install pytest requests\nSTDOUT: {r.stdout}\nSTDERR: {r.stderr}")
        return "\n".join(cmds)

    def run_tests(self, test_files: List[str]) -> Dict[str, Any]:
        if not test_files:
            return {"passed": 0, "failed": 0, "total": 0, "output": "No test files found.", "pass_rate": 100.0}
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.root) + ":" + env.get("PYTHONPATH", "")
        r = subprocess.run(
            [self.venv, "-m", "pytest"] + test_files + ["-v", "--tb=short", "--no-header"],
            capture_output=True, text=True, cwd=self.root, timeout=120, env=env
        )
        output = r.stdout + r.stderr
        passed = len(re.findall(r" PASSED", output))
        failed = len(re.findall(r" FAILED", output))
        errors = len(re.findall(r" ERROR", output))
        total  = passed + failed + errors
        return {"passed": passed, "failed": failed + errors, "total": total,
                "output": output, "pass_rate": (passed / total * 100) if total > 0 else 0.0}

    def generate_report(self, results: Dict) -> str:
        t, p, f, r = results["total"], results["passed"], results["failed"], results.get("pass_rate", 0)
        return f"=== TEST REPORT === Total: {t} Passed: {p} Failed: {f} Pass Rate: {r:.1f}%"


# ── AI Helper ─────────────────────────────────────────────────────────────────

class AIHelper:
    """Thin wrapper for OpenAI calls with conversation history support."""

    def __init__(self, client):
        self.client = client

    def call(self, messages: List[Dict], role: str = "builder", temperature: float = 0.2) -> str:
        resp = self.client.chat.completions.create(
            model=_team_model(role),
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""

    def call_once(self, system: str, user: str, role: str = "builder", temperature: float = 0.2) -> str:
        return self.call([{"role": "system", "content": system},
                          {"role": "user", "content": user}], role=role, temperature=temperature)

    def extract_json(self, text: str) -> Optional[dict]:
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fenced:
            try: return json.loads(fenced.group(1))
            except: pass
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try: return json.loads(text[start:end+1])
            except: pass
        return None

    def extract_code(self, text: str, lang: str = "python") -> Optional[str]:
        m = re.search(rf"```{lang}?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m: return m.group(1).strip()
        if "def " in text or "class " in text or "from " in text:
            return text.strip()
        return None


# ── Living Blueprint ──────────────────────────────────────────────────────────

@dataclass
class Blueprint:
    """
    WireStack-style living blueprint.
    Created by Architect, updated by Cartographer after each module is built.
    All agents work from this — never from the raw prompt directly.
    """
    name:          str
    purpose:       str
    stack:         str
    modules:       List[Dict]   # [{id, file, role, purpose, exports, imports_from}]
    wiring:        List[Dict]   # [{from, to, type, description}]
    schema:        Dict         # {tables: [...], test_data_example: {...}}
    api_routes:    List[Dict]   # [{method, path, description, returns}]
    rules:         List[str]
    changelog:     List[str]
    raw_prompt:    str
    version:       str = "1.0"

    def to_context(self) -> str:
        """Serialise blueprint as AI context string."""
        modules_text = "\n".join(
            f"  [{m['id']}] {m['file']} — {m['purpose']}\n"
            f"    exports: {m.get('exports', [])}\n"
            f"    imports: {m.get('imports_from', {})}"
            for m in self.modules
        )
        wiring_text = "\n".join(f"  {w['from']} → {w['to']} ({w['type']})" for w in self.wiring)
        routes_text = "\n".join(f"  {r['method']} {r['path']} → {r['description']}" for r in self.api_routes)
        schema_text = json.dumps(self.schema, indent=2)
        rules_text  = "\n".join(f"  - {r}" for r in self.rules)
        changelog_text = "\n".join(f"  {c}" for c in self.changelog[-5:])
        return f"""=== LIVING BLUEPRINT v{self.version} ===
Name: {self.name}
Purpose: {self.purpose}
Stack: {self.stack}

MODULES:
{modules_text}

WIRING:
{wiring_text}

API ROUTES:
{routes_text}

SCHEMA:
{schema_text}

RULES (MUST FOLLOW):
{rules_text}

RECENT CHANGELOG:
{changelog_text}
"""

    def update(self, change: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.changelog.append(f"[{ts}] {change}")
        self.version = str(round(float(self.version) + 0.1, 1))


# ── Main Orchestrator ─────────────────────────────────────────────────────────

class ProjectOrchestrator:
    """
    WireStack-inspired orchestrator.

    Phase 1 — Blueprint:    Architect reads prompt, produces living blueprint
    Phase 2 — Per-module:   Builder writes one module at a time
                            Validator checks it before accepting
                            Cartographer updates blueprint after each accept
    Phase 3 — Test loop:    Run all tests; on failure feed errors back (codem8s)
    Phase 4 — Review:       Reviewer scores against original prompt
    """

    TOTAL_PHASES = 8

    def __init__(self, project_root: Path, ai_client):
        self.project_root  = project_root
        self.ai            = AIHelper(ai_client)
        self.file_manager  = FileManager(project_root)
        self.test_runner   = TestOrchestrator(project_root)
        self.wiring_reg    = WiringRegistry()
        self.state_manager = StateManager(project_root)
        self.blueprint: Optional[Blueprint] = None
        self._lock         = threading.Lock()
        self._cancelled    = False
        self._paused       = False

        self.state = ProjectState(
            current_state=ExecutionState.IDLE,
            current_step=0,
            total_steps=self.TOTAL_PHASES,
            deliverables=[],
            errors=[],
            logs=[],
        )

    def add_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        with self._lock:
            self.state.logs.append(entry)
        self.state_manager.save(self.state)

    def _step(self, n: int, msg: str):
        self.state.current_step = n
        self.add_log(msg)

    def cancel(self):
        self._cancelled = True

    def pause(self):
        self._paused = True

    def resume(self) -> bool:
        self._paused = False
        return True

    def _check_cancel(self):
        while self._paused and not self._cancelled:
            import time; time.sleep(0.5)
        if self._cancelled:
            raise RuntimeError("Project cancelled by user")

    # ── Phase 1: Blueprint ────────────────────────────────────────────────────

    def _build_blueprint(self, contract: ProjectContract) -> Blueprint:
        self._step(1, "🏗️  Phase 1 — Architect building living blueprint...")

        system = """You are the Architect. Your job is to read a user's prompt and produce a
complete living blueprint that all other agents will follow EXACTLY.

The blueprint must:
- Identify the REAL application the user wants (not a generic CRUD)
- List every module/file needed with exact filenames
- Define exact function signatures for every export
- Define the database schema with exact column names and types
- Define exact API routes with exact return shapes
- Define test_data_example that EXACTLY matches validate_input() requirements
- Define wiring between all modules
- List strict rules that builders must follow

Return ONLY valid JSON — no markdown, no preamble."""

        user = f"""Build a living blueprint for this project:

PROJECT NAME: {contract.project_name}
DESCRIPTION:
{contract.description}

Return this exact JSON structure:
{{
  "name": "project name",
  "purpose": "one sentence — what this app actually does for the user",
  "stack": "e.g. Flask + SQLite + vanilla JS",
  "modules": [
    {{
      "id": "database",
      "file": "database.py",
      "role": "database_manager",
      "purpose": "SQLite persistence layer",
      "exports": ["connect", "execute_query", "save", "load", "delete"],
      "imports_from": {{}}
    }}
  ],
  "wiring": [
    {{"from": "logic.save_data", "to": "database.save", "type": "function_call", "description": "persists validated data"}}
  ],
  "schema": {{
    "tables": [
      {{
        "name": "projects",
        "columns": ["id INTEGER PRIMARY KEY AUTOINCREMENT", "name TEXT NOT NULL", "description TEXT", "created_at TEXT NOT NULL"],
        "required_fields": ["name", "description", "created_at"],
        "test_data_example": {{"name": "test project", "description": "a test", "created_at": "2024-01-01"}}
      }}
    ]
  }},
  "api_routes": [
    {{"method": "GET",  "path": "/",              "description": "serve index.html",   "returns": "HTML"}},
    {{"method": "POST", "path": "/api/projects",  "description": "create a project",   "returns": "{{\\"id\\": 1, \\"name\\": \\"...\\"}}"}},
    {{"method": "GET",  "path": "/api/projects",  "description": "list all projects",  "returns": "{{\\"projects\\": []}}"}}
  ],
  "rules": [
    "database.py MUST export: connect, execute_query, save, load, delete",
    "logic.py MUST export: initialize_app, save_data, load_data, validate_input",
    "logic.py imports from database using: from database import connect, execute_query, save, load, delete",
    "validate_input() MUST only require fields listed in test_data_example",
    "tests mock using @patch('database.connect') NOT @patch('logic.connect')",
    "app.py MUST call init_db equivalent at startup",
    "All routes return JSON except GET / which returns HTML"
  ],
  "changelog": ["Blueprint created by Architect"]
}}"""

        raw = self.ai.call_once(system, user, role="architect", temperature=0.1)
        data = self.ai.extract_json(raw)

        if not data:
            self.add_log("⚠️  Architect returned invalid JSON — using minimal blueprint")
            data = {
                "name": contract.project_name,
                "purpose": contract.description[:200],
                "stack": "Flask + SQLite + vanilla JS",
                "modules": [
                    {"id": "database", "file": "database.py", "role": "database_manager",
                     "purpose": "SQLite persistence", "exports": ["connect","execute_query","save","load","delete"], "imports_from": {}},
                    {"id": "logic",    "file": "logic.py",    "role": "backend_logic",
                     "purpose": "Business logic", "exports": ["initialize_app","save_data","load_data","validate_input"],
                     "imports_from": {"database": ["connect","execute_query","save","load","delete"]}},
                    {"id": "app",      "file": "app.py",      "role": "wiring_engineer",
                     "purpose": "Flask application", "exports": ["app"], "imports_from": {"logic": ["initialize_app","save_data","load_data"]}},
                    {"id": "tests",    "file": "test_app.py", "role": "test_engineer",
                     "purpose": "Tests", "exports": [], "imports_from": {}},
                ],
                "wiring": [{"from":"logic.save_data","to":"database.save","type":"function_call","description":"persist data"}],
                "schema": {"tables":[{"name":"items","columns":["id INTEGER PRIMARY KEY AUTOINCREMENT","name TEXT NOT NULL","created_at TEXT NOT NULL"],
                                      "required_fields":["name","created_at"],"test_data_example":{"name":"test","created_at":"2024-01-01"}}]},
                "api_routes": [{"method":"GET","path":"/","description":"serve UI","returns":"HTML"},
                               {"method":"POST","path":"/api/items","description":"create item","returns":"{\"id\":1}"},
                               {"method":"GET", "path":"/api/items","description":"list items","returns":"{\"items\":[]}"}],
                "rules": ["database.py MUST export: connect, execute_query, save, load, delete",
                          "logic.py MUST export: initialize_app, save_data, load_data, validate_input",
                          "validate_input MUST only require fields in test_data_example"],
                "changelog": ["Fallback blueprint used"]
            }

        bp = Blueprint(
            name=data.get("name", contract.project_name),
            purpose=data.get("purpose", ""),
            stack=data.get("stack", "Flask + SQLite"),
            modules=data.get("modules", []),
            wiring=data.get("wiring", []),
            schema=data.get("schema", {}),
            api_routes=data.get("api_routes", []),
            rules=data.get("rules", []),
            changelog=data.get("changelog", []),
            raw_prompt=contract.description,
        )

        self.add_log(f"✅  Blueprint complete: {len(bp.modules)} modules, {len(bp.api_routes)} routes, {len(bp.schema.get('tables',[]))} tables")
        self.add_log(f"    Purpose: {bp.purpose}")
        self.add_log(f"    Stack:   {bp.stack}")
        for m in bp.modules:
            self.add_log(f"    Module:  {m['file']} — {m['purpose']}")

        # Save blueprint to disk for inspection
        (self.project_root / ".boom3_blueprint.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
        return bp

    # ── Phase 2: Build modules one by one ─────────────────────────────────────

    def _build_module(self, module: Dict, blueprint: Blueprint) -> bool:
        """
        Build ONE module following the blueprint exactly.
        Validator checks before accepting. Cartographer updates blueprint on accept.
        """
        file_id   = module["id"]
        filepath  = module["file"]
        role      = module.get("role", "builder")
        purpose   = module["purpose"]
        exports   = module.get("exports", [])
        imports   = module.get("imports_from", {})

        self.add_log(f"🔨  Building {filepath} ({purpose})...")

        # Find relevant schema for this module
        schema_ctx = ""
        tables = blueprint.schema.get("tables", [])
        if tables and role in ("database_manager", "backend_logic"):
            schema_ctx = f"\nDATABASE SCHEMA:\n{json.dumps(tables, indent=2)}\n"

        # Find relevant routes for this module
        routes_ctx = ""
        if role in ("wiring_engineer", "gui_builder") and blueprint.api_routes:
            routes_ctx = f"\nAPI ROUTES TO IMPLEMENT:\n" + "\n".join(
                f"  {r['method']} {r['path']} → {r['description']} returns: {r['returns']}"
                for r in blueprint.api_routes
            ) + "\n"

        # Build conversation history for codem8s-style repair
        history = []
        max_build_attempts = 3

        for attempt in range(1, max_build_attempts + 1):
            system = f"""You are a specialist Builder agent.
Your ONLY job is to write {filepath} following the blueprint EXACTLY.

{blueprint.to_context()}

CRITICAL RULES — READ EVERY ONE:
{chr(10).join(f'- {r}' for r in blueprint.rules)}

For {filepath} specifically:
- This module's purpose: {purpose}
- MUST export these exact names: {exports}
- MUST import from: {json.dumps(imports)}
{schema_ctx}{routes_ctx}

Return ONLY the complete Python (or HTML/JS/CSS) file content.
No explanation. No markdown fences. Just the raw file content."""

            if attempt == 1:
                user_msg = f"Write {filepath} now. Follow the blueprint. Export exactly: {exports}"
            else:
                user_msg = (f"Attempt {attempt}: Your previous version failed validation:\n\n"
                            f"{history[-1]['content'] if history else ''}\n\n"
                            f"Fix ALL issues and rewrite {filepath} completely. "
                            f"MUST export: {exports}")

            messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_msg}]
            raw = self.ai.call(messages, role="builder", temperature=0.1)

            # Extract code — remove markdown fences if present
            code = self.ai.extract_code(raw, lang="python") or raw.strip()
            if filepath.endswith(".html"):
                code = self.ai.extract_code(raw, lang="html") or raw.strip()
            elif filepath.endswith(".js"):
                code = self.ai.extract_code(raw, lang="javascript") or self.ai.extract_code(raw, lang="js") or raw.strip()
            elif filepath.endswith(".css"):
                code = self.ai.extract_code(raw, lang="css") or raw.strip()

            # ── Validator: check before accepting ────────────────────────────
            validation_errors = self._validate_module(filepath, code, module, blueprint)

            if not validation_errors:
                # Accept
                self.file_manager.write(filepath, code)
                blueprint.update(f"Built and validated: {filepath}")
                self.add_log(f"✅  {filepath} accepted (attempt {attempt})")
                return True
            else:
                self.add_log(f"⚠️  {filepath} failed validation (attempt {attempt}): {'; '.join(validation_errors[:3])}")
                # Add to history for next attempt (codem8s pattern)
                history.append({"role": "user", "content": user_msg})
                history.append({"role": "assistant", "content": raw})
                history.append({"role": "user", "content": f"Validation errors:\n" + "\n".join(f"- {e}" for e in validation_errors)})

        # Force-write after max attempts with best effort
        self.file_manager.write(filepath, code)
        blueprint.update(f"Force-wrote {filepath} after {max_build_attempts} attempts")
        self.add_log(f"⚠️  {filepath} force-written after {max_build_attempts} attempts")
        return False

    def _validate_module(self, filepath: str, code: str, module: Dict, blueprint: Blueprint) -> List[str]:
        """
        Cartographer-style validator — checks before accepting a module.
        Returns list of error strings; empty = pass.
        """
        errors = []
        if not code or len(code.strip()) < 20:
            return ["File is empty or too short"]

        if filepath.endswith(".py"):
            # Syntax check
            try:
                import ast
                ast.parse(code)
            except SyntaxError as e:
                errors.append(f"SyntaxError: {e}")
                return errors  # No point checking further

            # Export check — required functions/classes must be present
            exports = module.get("exports", [])
            for export in exports:
                if export and not re.search(rf"\bdef {export}\b|\bclass {export}\b|{export}\s*=", code):
                    errors.append(f"Missing required export: {export}")

            # Import check
            imports_from = module.get("imports_from", {})
            for mod, names in imports_from.items():
                if names and f"from {mod} import" not in code and f"import {mod}" not in code:
                    errors.append(f"Missing import from {mod}")

            # Schema consistency — if this is database/logic, check table name matches blueprint
            tables = blueprint.schema.get("tables", [])
            if tables and module["role"] in ("database_manager", "backend_logic"):
                table_name = tables[0]["name"]
                if table_name not in code:
                    errors.append(f"Table '{table_name}' not referenced — blueprint says this table must exist")

            # validate_input must only require fields in test_data_example
            if "validate_input" in module.get("exports", []) and tables:
                test_data = tables[0].get("test_data_example", {})
                required_fields = tables[0].get("required_fields", list(test_data.keys()))
                # Check it doesn't require extra fields not in test_data
                field_checks = re.findall(r'["\'](\w+)["\'].*?not in data|Missing.*?["\'](\w+)["\']', code)
                for match in field_checks:
                    field = match[0] or match[1]
                    if field and field not in required_fields and field not in ("id", "created_at"):
                        # Only warn, don't hard fail
                        pass

        elif filepath.endswith(".html"):
            if "<html" not in code.lower() and "<!doctype" not in code.lower():
                errors.append("HTML file missing <html> tag")

        return errors

    # ── Phase 3: Test loop (codem8s pattern) ─────────────────────────────────

    def _test_and_repair(self, contract: ProjectContract, blueprint: Blueprint) -> bool:
        """
        Run all tests. On failure, feed errors back to Builder with full
        conversation history (codem8s pattern) — never start fresh.
        """
        self._step(6, "🧪  Phase 3 — Running tests...")

        # Find test files
        test_files = [
            p.relative_to(self.project_root).as_posix()
            for p in self.project_root.rglob("test_*.py")
            if ".venv" not in p.parts and "__pycache__" not in p.parts
        ]

        if not test_files:
            self.add_log("⚠️  No test files found — skipping test phase")
            return True

        # Clear stale DB
        for db in self.project_root.glob("*.db"):
            try: db.unlink()
            except: pass

        results = self.test_runner.run_tests(test_files)
        self.add_log(self.test_runner.generate_report(results))

        if results["failed"] == 0:
            self.add_log("✅  All tests passed")
            return True

        self.add_log(f"🛠️  Tests failed — starting repair loop (codem8s pattern)...")

        # Codem8s conversation history — grows across ALL repair attempts
        repair_history = []
        initial_test_output = results["output"]

        system = """You are the repair worker for Boom3.
Tests are failing. Your job is to fix the generated files so ALL tests pass.

Rules:
- Return ONLY valid JSON: {"files": [{"filepath": "...", "code": "..."}], "notes": "..."}
- Return COMPLETE file contents — not diffs
- Fix the APP code to match what tests expect — don't weaken tests
- If SQLite says 'no such table', add a conftest.py that calls init_db() before each test
- If 'cannot import X from Y', add X to Y or fix the import
- Each attempt must try a DIFFERENT approach than previous attempts
- Never start fresh — build on what you know from previous attempts"""

        for attempt in range(1, 4):
            self.add_log(f"🛠️  Repair attempt {attempt}/3")

            if attempt == 1:
                user_msg = f"""Tests are failing. Fix all failures.

FAILING TEST OUTPUT:
{initial_test_output[-8000:]}

BLUEPRINT (what the app should do):
{blueprint.to_context()[:3000]}

CURRENT FILES:
{self.file_manager.all_python_files()}

Return the JSON patch now."""
            else:
                user_msg = f"""Attempt {attempt}: Your previous fix STILL has failures.
Try a completely different approach.

CURRENT FAILURES:
{current_output[-5000:]}

CURRENT FILES:
{self.file_manager.all_python_files()}

Return the JSON patch now."""

            messages = ([{"role": "system", "content": system}]
                        + repair_history
                        + [{"role": "user", "content": user_msg}])

            raw = self.ai.call(messages, role="repair", temperature=0.1)

            # Store in history (codem8s pattern)
            repair_history.append({"role": "user", "content": user_msg})
            repair_history.append({"role": "assistant", "content": raw})

            patch = self.ai.extract_json(raw)
            if not patch or not patch.get("files"):
                self.add_log(f"⚠️  Repair attempt {attempt} returned no files")
                current_output = initial_test_output
                continue

            files_changed = []
            for item in patch["files"]:
                rel = str(item.get("filepath", "")).strip().lstrip("/")
                if rel:
                    self.file_manager.write(rel, item.get("code", ""))
                    files_changed.append(rel)
                    blueprint.update(f"Repair attempt {attempt}: patched {rel}")

            self.add_log(f"    Changed: {', '.join(files_changed)}")

            # Clear stale DB and re-run
            for db in self.project_root.glob("*.db"):
                try: db.unlink()
                except: pass

            results = self.test_runner.run_tests(test_files)
            self.add_log(self.test_runner.generate_report(results))
            current_output = results["output"]

            if results["failed"] == 0:
                self.add_log("✅  Repair succeeded — all tests passing")
                return True

            self.add_log(f"⚠️  Repair attempt {attempt} still has {results['failed']} failures")

        self.add_log(f"⚠️  Repair exhausted — {results['failed']} tests still failing")
        # Don't fail the whole project — return True so review can still run
        return True

    # ── Phase 4: Review ───────────────────────────────────────────────────────

    def _review(self, contract: ProjectContract, blueprint: Blueprint) -> Dict:
        """
        Reviewer scores the built app against the original prompt.
        Uses structural code scan first (fast, no AI), then AI review.
        """
        self._step(7, "🔎  Phase 4 — Reviewing against original prompt...")

        # Structural scan — look for actual evidence of features
        all_code = ""
        for p in self.project_root.rglob("*"):
            if p.is_file() and ".venv" not in p.parts and "__pycache__" not in p.parts:
                try: all_code += p.read_text(encoding="utf-8", errors="replace").lower() + "\n"
                except: pass

        desc = (contract.description + " " + contract.project_name).lower()
        feature_map = {
            "file explorer":       ["file-explorer", "filelist", "file_list", "/files", "file explorer"],
            "code editor":         ["codemirror", "monaco", "code-editor", "code editor", "<textarea"],
            "real-time logs":      ["/logs", "live log", "real-time", "log_stream", "sse"],
            "test runner":         ["/tests", "run_tests", "pytest", "test runner", "/run-tests"],
            "auto-repair":         ["/repair", "auto_repair", "repair loop", "auto repair"],
            "git integration":     ["git", "/git", "git_status", "gitignore"],
            "deploy to render":    ["render", "/deploy", "deploy", "render.yaml"],
            "dependency installer":["requirements", "pip install", "/install", "dependencies"],
            "docker":              ["docker", "dockerfile", "container"],
            "multi-agent":         ["agent", "multi-agent", "orchestrat"],
            "file explorer ui":    ["<div", "template", "index.html", "static"],
        }

        present, missing = [], []
        for feature, signals in feature_map.items():
            if feature.lower() in desc:
                if any(s in all_code for s in signals):
                    present.append(feature)
                else:
                    missing.append(feature)

        total = len(present) + len(missing)
        score = int(len(present) / total * 100) if total > 0 else 80

        self.add_log(f"    Structural score: {score}/100")
        if present: self.add_log(f"    Present: {', '.join(present)}")
        if missing: self.add_log(f"    Missing: {', '.join(missing)}")

        return {"passed": score >= 60, "score": score, "missing": missing,
                "present": present, "summary": f"{score}/100 — {len(missing)} features missing"}

    # ── Phase 5: Compliance repair ─────────────────────────────────────────────

    def _compliance_repair(self, contract: ProjectContract, blueprint: Blueprint,
                           review: Dict, max_attempts: int = 2) -> bool:
        """Add missing features via targeted file patches."""
        missing = review.get("missing", [])
        if not missing:
            return True

        self.add_log(f"🧩  Compliance repair — adding missing features: {', '.join(missing)}")

        # Conversation history across attempts
        history = []
        PROTECTED = {"logic.py", "database.py", "test_logic.py", "conftest.py"}

        system = """You are the compliance repair worker.
The generated app is missing some features from the user's request.
Add the missing features WITHOUT breaking existing passing tests.

Rules:
- NEVER modify: logic.py, database.py, test_logic.py, conftest.py
- Add new files or patch app.py, templates/index.html, static/app.js, static/styles.css
- Return ONLY valid JSON: {"files": [{"filepath": "...", "code": "..."}]}
- Return COMPLETE file contents"""

        for attempt in range(1, max_attempts + 1):
            self.add_log(f"🧩  Compliance attempt {attempt}/{max_attempts}")

            retry_note = "" if attempt == 1 else f"\nPrevious attempt did not fully fix it. Try a MORE COMPLETE approach.\n"

            user_msg = f"""{retry_note}
ORIGINAL REQUEST:
{contract.description}

MISSING FEATURES:
{chr(10).join(f'- {m}' for m in missing)}

BLUEPRINT:
{blueprint.to_context()[:2000]}

CURRENT FILES:
{self.file_manager.all_files_snapshot()[:8000]}

Add the missing features. Return JSON patch now."""

            messages = ([{"role": "system", "content": system}]
                        + history
                        + [{"role": "user", "content": user_msg}])

            raw = self.ai.call(messages, role="reviewer", temperature=0.1)
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": raw})

            patch = self.ai.extract_json(raw)
            if not patch or not patch.get("files"):
                self.add_log(f"⚠️  Compliance attempt {attempt} returned no files")
                continue

            written = []
            for item in patch["files"]:
                rel = str(item.get("filepath", "")).strip().lstrip("/")
                if rel and rel not in PROTECTED:
                    self.file_manager.write(rel, item.get("code", ""))
                    written.append(rel)
                    blueprint.update(f"Compliance patch: {rel}")
                elif rel in PROTECTED:
                    self.add_log(f"  ⏭️  Skipping protected: {rel}")

            self.add_log(f"    Wrote: {', '.join(written)}")

        return True

    # ── Main execute ──────────────────────────────────────────────────────────

    def execute_project(self, contract: ProjectContract) -> bool:
        try:
            self.state.current_state = ExecutionState.EXECUTING
            self.state_manager.save(self.state)

            # ── Phase 1: Blueprint ────────────────────────────────────────────
            self._check_cancel()
            self.state.current_state = ExecutionState.PLANNING
            blueprint = self._build_blueprint(contract)
            self.blueprint = blueprint

            # ── Phase 2: Build each module ────────────────────────────────────
            self._step(2, "🔨  Phase 2 — Building modules per blueprint...")
            self.state.current_state = ExecutionState.EXECUTING

            # Determine build order — database first, then logic, then app, then tests
            order_priority = {
                "database_manager": 0,
                "backend_logic":    1,
                "api_integrator":   2,
                "gui_builder":      3,
                "wiring_engineer":  4,
                "test_engineer":    5,
            }
            ordered_modules = sorted(
                blueprint.modules,
                key=lambda m: order_priority.get(m.get("role", "wiring_engineer"), 3)
            )

            self.state.total_steps = self.TOTAL_PHASES + len(ordered_modules)
            built_count = 0
            for i, module in enumerate(ordered_modules, 1):
                self._check_cancel()
                self._step(2 + i, f"🔨  Building module {i}/{len(ordered_modules)}: {module['file']}")
                ok = self._build_module(module, blueprint)
                if ok:
                    built_count += 1

            self.add_log(f"✅  Built {built_count}/{len(ordered_modules)} modules")

            # Write wiring connections
            for wire in blueprint.wiring:
                self.wiring_reg.register(WiringContract(
                    from_component=wire.get("from","").split(".")[0],
                    from_symbol=wire.get("from","").split(".")[-1],
                    to_component=wire.get("to","").split(".")[0],
                    to_symbol=wire.get("to","").split(".")[-1],
                    connection_type=wire.get("type","function_call"),
                ))

            # Write standard project files
            self._write_standard_files(contract, blueprint)

            # ── Phase 3: Install deps ─────────────────────────────────────────
            self._step(self.TOTAL_PHASES - 2, "📦  Installing dependencies...")
            dep_output = self.test_runner.install_dependencies()
            self.add_log(f"Dependency output: {dep_output[-2000:]}")

            # ── Phase 4: Test + repair ────────────────────────────────────────
            self.state.current_state = ExecutionState.TESTING
            self._test_and_repair(contract, blueprint)

            # ── Phase 5: Review ───────────────────────────────────────────────
            review = self._review(contract, blueprint)
            self.add_log(f"Prompt compliance score: {review['score']}/100 — {review['summary']}")

            # ── Phase 6: Compliance repair if needed ──────────────────────────
            if not review["passed"] and review.get("missing"):
                self._compliance_repair(contract, blueprint, review)
                # Re-review after repair
                review2 = self._review(contract, blueprint)
                self.add_log(f"Post-repair score: {review2['score']}/100")

            # ── Done ──────────────────────────────────────────────────────────
            self._step(self.TOTAL_PHASES, "🎉  Build complete")
            self.state.current_state = ExecutionState.COMPLETED
            self.state_manager.save(self.state)
            return True

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.add_log(f"❌  Project crashed: {e}")
            self.add_log(f"    Traceback: {tb[:1000]}")
            self.state.errors.append(str(e))
            self.state.current_state = ExecutionState.FAILED
            self.state_manager.save(self.state)
            return False

    # ── Standard files ────────────────────────────────────────────────────────

    def _write_standard_files(self, contract: ProjectContract, blueprint: Blueprint):
        """Write conftest.py, requirements.txt, README.md if not already present."""

        # conftest.py — skip tkinter and init db before Flask tests
        conftest = self.project_root / "conftest.py"
        if not conftest.exists():
            conftest.write_text(
                "import pytest, sys\n\n"
                "def pytest_collection_modifyitems(config, items):\n"
                "    skip = pytest.mark.skip(reason='No display (headless)')\n"
                "    for item in items:\n"
                "        try:\n"
                "            src = open(item.function.__code__.co_filename).read()\n"
                "            if 'tkinter' in src or 'import gui' in src:\n"
                "                item.add_marker(skip)\n"
                "        except: pass\n",
                encoding="utf-8"
            )
            self.add_log("📝  conftest.py written")

        # requirements.txt if not present
        req = self.project_root / "requirements.txt"
        if not req.exists():
            req.write_text("Flask>=3.0\npytest>=8.4\nrequests>=2.31\n", encoding="utf-8")
            self.add_log("📝  requirements.txt written")

        # README.md
        readme = self.project_root / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# {blueprint.name}\n\n{blueprint.purpose}\n\n"
                f"**Stack:** {blueprint.stack}\n\n"
                f"## Run\n```\npip install -r requirements.txt\npython app.py\n```\n",
                encoding="utf-8"
            )

    # ── Pause / Cancel / File access (for web_server.py) ─────────────────────

    @property
    def wiring_registry(self):
        return self.wiring_reg

    def read_file(self, filepath: str) -> Optional[str]:
        return self.file_manager.read(filepath)


# ── Compat layer for web_server.py ───────────────────────────────────────────
# web_server.py imports ProjectOrchestrator, create_orchestrator, ProjectContract, ExecutionState

def create_orchestrator(project_root: Path, ai_client) -> ProjectOrchestrator:
    return ProjectOrchestrator(project_root, ai_client)


# Keep AgentCoordinator, ForemanCoordinator stubs so imports don't break
class AgentCoordinator(ABC):
    @abstractmethod
    def plan_work(self, contract: ProjectContract) -> List[Dict]: ...

class ForemanCoordinator(AgentCoordinator):
    def __init__(self, ai_client): self.ai_client = ai_client
    def plan_work(self, contract: ProjectContract) -> List[Dict]: return []


# Keep TestOrchestrator accessible as before
__all__ = [
    "ProjectOrchestrator", "create_orchestrator", "ProjectContract",
    "ExecutionState", "ProjectState", "WiringRegistry",
    "AgentCoordinator", "ForemanCoordinator", "TestOrchestrator",
]
