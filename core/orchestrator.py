"""
Core System - Modular Architecture

This breaks apart the monolith into clean, testable modules.
Each module has ONE responsibility.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import json
import re
import threading
from pathlib import Path
from datetime import datetime

from contracts.agent_contracts import (
    AgentRole, AgentDeliverable, ProjectContract,
    CodeOutput, WiringContract
)


class ExecutionState(Enum):
    """Clear state management"""
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    TESTING = "testing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ProjectState:
    """Immutable state snapshot - FULLY SERIALIZABLE"""
    current_state: ExecutionState
    current_step: int
    total_steps: int
    deliverables: List[AgentDeliverable]
    errors: List[str]
    logs: List[str] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    
    def to_dict(self) -> dict:
        """Full serialization including deliverables"""
        return {
            "current_state": self.current_state.value,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "deliverables": [d.to_dict() for d in self.deliverables],
            "errors": self.errors,
            "logs": self.logs,
            "run_id": self.run_id
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ProjectState':
        """Full deserialization including deliverables"""
        from contracts.agent_contracts import AgentDeliverable, AgentRole, CodeOutput, WiringContract
        
        # Reconstruct deliverables
        deliverables = []
        for d_data in data.get("deliverables", []):
            # Reconstruct outputs
            outputs = [
                CodeOutput(
                    code=o["code"],
                    filepath=o["filepath"],
                    language=o["language"],
                    dependencies=o.get("dependencies", []),
                    exports=o.get("exports", []),
                    imports_from=o.get("imports_from", {})
                )
                for o in d_data["outputs"]
            ]
            
            # Reconstruct wiring
            wiring = [
                WiringContract(
                    from_component=w["from_component"],
                    from_symbol=w["from_symbol"],
                    to_component=w["to_component"],
                    to_symbol=w["to_symbol"],
                    connection_type=w["connection_type"],
                    parameters=w.get("parameters")
                )
                for w in d_data.get("wiring", [])
            ]
            
            deliverables.append(AgentDeliverable(
                agent_role=AgentRole(d_data["agent_role"]),
                outputs=outputs,
                wiring=wiring,
                tests_generated=d_data.get("tests_generated", []),
                documentation=d_data.get("documentation", "")
            ))
        
        return cls(
            current_state=ExecutionState(data["current_state"]),
            current_step=data["current_step"],
            total_steps=data["total_steps"],
            deliverables=deliverables,
            errors=data.get("errors", []),
            logs=data.get("logs", []),
            run_id=data.get("run_id", "unknown")
        )


class StateManager:
    """
    Handles ONLY state persistence
    Single Responsibility: Save/Load state
    """
    
    def __init__(self, state_file: Path):
        self.state_file = state_file
    
    def save(self, state: ProjectState) -> bool:
        """Save state to disk"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state.to_dict(), f, indent=2)
            return True
        except Exception as e:
            print(f"Failed to save state: {e}")
            return False
    
    def load(self) -> Optional[ProjectState]:
        """Load state from disk"""
        if not self.state_file.exists():
            return None
        
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            return ProjectState.from_dict(data)
        except Exception as e:
            print(f"Failed to load state: {e}")
            return None


class WiringRegistry:
    """
    Handles ONLY wiring tracking
    Single Responsibility: Track connections
    """
    
    def __init__(self):
        self.connections: List[WiringContract] = []
    
    def register(self, connection: WiringContract) -> bool:
        """Register a new connection"""
        if not connection.validate():
            return False
        
        self.connections.append(connection)
        return True
    
    def get_connections_for(self, component: str) -> List[WiringContract]:
        """Get all connections involving a component"""
        return [
            c for c in self.connections 
            if c.from_component == component or c.to_component == component
        ]
    
    def validate_all(self) -> tuple[bool, List[str]]:
        """
        Validate all connections for:
        - Circular dependencies
        - Missing components
        - Duplicate connections
        """
        issues = []
        
        # Build component graph
        components = set()
        edges = {}  # component -> list of dependencies
        
        for conn in self.connections:
            components.add(conn.from_component)
            components.add(conn.to_component)
            
            if conn.from_component not in edges:
                edges[conn.from_component] = []
            edges[conn.from_component].append(conn.to_component)
        
        # Check for circular dependencies using DFS
        def has_cycle(node, visited, rec_stack):
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in edges.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor, visited, rec_stack):
                        return True
                elif neighbor in rec_stack:
                    return True
            
            rec_stack.remove(node)
            return False
        
        visited = set()
        for component in components:
            if component not in visited:
                if has_cycle(component, visited, set()):
                    issues.append(f"Circular dependency detected involving: {component}")
        
        # Check for duplicate connections
        seen = set()
        for conn in self.connections:
            key = (conn.from_component, conn.from_symbol, conn.to_component, conn.to_symbol)
            if key in seen:
                issues.append(
                    f"Duplicate connection: {conn.from_component}.{conn.from_symbol} "
                    f"-> {conn.to_component}.{conn.to_symbol}"
                )
            seen.add(key)
        
        return len(issues) == 0, issues
    
    def generate_diagram(self) -> str:
        """Generate wiring diagram"""
        lines = ["=== WIRING DIAGRAM ===\n"]
        
        by_type = {}
        for conn in self.connections:
            by_type.setdefault(conn.connection_type, []).append(conn)
        
        for conn_type, conns in by_type.items():
            lines.append(f"\n{conn_type.upper()}:")
            for c in conns:
                lines.append(f"  {c.from_component}.{c.from_symbol} -> {c.to_component}.{c.to_symbol}")
        
        return "\n".join(lines)


class AgentCoordinator(ABC):
    """
    Abstract coordinator - defines interface for different coordination strategies
    """
    
    @abstractmethod
    def plan_work(self, project_contract: ProjectContract) -> List[Dict[str, Any]]:
        """Create execution plan"""
        pass
    
    @abstractmethod
    def assign_task(self, task: Dict[str, Any]) -> AgentRole:
        """Determine which agent handles a task"""
        pass
    
    @abstractmethod
    def validate_deliverable(self, deliverable: AgentDeliverable) -> tuple[bool, List[str]]:
        """Check if deliverable meets standards"""
        pass


class ForemanCoordinator(AgentCoordinator):
    """
    Foreman-based coordination with robust JSON parsing
    Single Responsibility: Coordinate agent work
    """
    
    def __init__(self, ai_client):
        self.ai_client = ai_client
    
    def plan_work(self, project_contract: ProjectContract) -> List[Dict[str, Any]]:
        """
        Break project into tasks with robust JSON parsing.
        
        Handles:
        1. JSON in markdown code blocks
        2. Raw JSON
        3. Fallback extraction of first JSON array
        """
        # AI-powered planning prompt
        prompt = f"""
You are a strict project foreman. Break down this project into tasks that build the ACTUAL requested app, not a toy demo.

Project: {project_contract.project_name}
Description: {project_contract.description}
Required Agents: {[a.value for a in project_contract.required_agents]}

Planning rules:
- Preserve the user's requested product scope. If they ask for a Lovable/Bolt/Replit-style app builder, plan a real web app builder with file explorer/code viewer, editor area, live logs, project APIs, dependency install/test runner, auto-repair/change workflow, zip download, and deploy instructions.
- First design ONE shared architecture, then give every agent the same filenames, module names, route names, data model, and public function names.
- Do not let each agent invent its own storage or API shape. If the app uses SQLite, all logic must use the database helpers; do not mix JSON-file storage with SQLite unless explicitly requested.
- Include concrete expected files in each task. Prefer Flask + SQLite + vanilla HTML/CSS/JS unless the user specifies another stack.
- Requirements must contain only pip-installable third-party packages. Never include Python stdlib modules like sqlite3, json, os, sys, pathlib, typing, datetime, unittest, tkinter, zipfile, shutil, subprocess.
- Tests must verify prompt requirements, not just trivial functions.
- Do not plan generic placeholder files.

For each agent, create a task specifying:
1. What files they should create
2. What exact prompt requirements they cover
3. What they need from other agents
4. Order of execution
5. The SAME shared_architecture object on every task

The shared_architecture object must include:
- stack
- file_map
- routes
- database_tables
- public_functions_by_file
- dependency_policy
- acceptance_criteria

Return ONLY a JSON array (no markdown, no preamble):
[
    {{
        "agent_role": "gui_builder",
        "description": "Create app-builder UI matching shared architecture",
        "files_to_create": ["templates/index.html", "static/styles.css", "static/app.js"],
        "dependencies": [],
        "shared_architecture": {{
            "stack": "Flask + SQLite + vanilla JS",
            "file_map": {{"app.py":"Flask routes/API", "database.py":"SQLite helpers", "logic.py":"business functions"}},
            "routes": ["GET /", "POST /api/projects", "GET /api/projects/<id>/files"],
            "database_tables": ["projects", "files", "logs", "test_runs"],
            "public_functions_by_file": {{"database.py":["init_db", "create_project", "list_files"], "logic.py":["create_project", "build_zip"]}},
            "dependency_policy": "requirements.txt contains only pip packages, never stdlib modules",
            "acceptance_criteria": ["real UI", "working APIs", "tests pass", "download zip"]
        }}
    }},
    ...
]
"""
        
        response = self.ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        
        content = response.choices[0].message.content
        
        # Parse with robust fallback
        tasks = self._parse_json_robust(content)
        
        # Convert agent_role strings to enum and inject shared architecture into every task.
        # This keeps agents coordinated instead of each inventing its own app shape.
        shared_architecture = None
        for task in tasks:
            if task.get("shared_architecture") and not shared_architecture:
                shared_architecture = task.get("shared_architecture")
        if not shared_architecture:
            shared_architecture = self._fallback_shared_architecture(project_contract)

        for task in tasks:
            task['agent_role'] = AgentRole(task['agent_role'])
            task['project_name'] = project_contract.project_name
            task['description'] = project_contract.description
            task['shared_architecture'] = shared_architecture
        
        return tasks

    def _fallback_shared_architecture(self, project_contract: ProjectContract) -> Dict[str, Any]:
        desc = (project_contract.description or '').lower()
        app_builder = any(term in desc for term in ['lovable', 'bolt', 'replit', 'app builder', 'code editor'])
        if app_builder:
            return {
                "stack": "Flask + SQLite + vanilla HTML/CSS/JS",
                "file_map": {
                    "app.py": "Flask app, pages, JSON APIs, download zip",
                    "database.py": "SQLite schema and CRUD for projects/files/logs/test_runs",
                    "logic.py": "project/file/test/repair service functions using database.py",
                    "services.py": "dependency install, pytest runner, zip packaging helpers",
                    "templates/index.html": "single-page app-builder UI",
                    "static/styles.css": "responsive UI",
                    "static/app.js": "API client, editor/file/log interactions",
                    "test_app.py": "Flask endpoint and workflow tests",
                    "main.py": "entrypoint",
                    "requirements.txt": "Flask pytest requests only; never stdlib modules",
                    "README.md": "run, test, deploy docs",
                    "render.yaml": "Render deployment example",
                },
                "routes": ["GET /", "POST /api/projects", "GET /api/projects/<id>/files", "GET /api/projects/<id>/logs", "POST /api/projects/<id>/tests", "POST /api/projects/<id>/repair", "GET /api/projects/<id>/download"],
                "database_tables": ["projects", "files", "logs", "test_runs", "change_requests"],
                "public_functions_by_file": {
                    "database.py": ["init_db", "create_project", "get_project", "save_file", "list_files", "append_log", "list_logs", "save_test_run"],
                    "logic.py": ["create_project", "generate_initial_files", "list_project_files", "get_project_logs", "record_test_result", "build_project_zip"],
                    "services.py": ["install_dependencies", "run_tests", "repair_project", "make_zip"],
                },
                "dependency_policy": "Only pip packages in requirements.txt. Exclude sqlite3/json/os/sys/pathlib/typing/datetime/unittest/zipfile/shutil/subprocess.",
                "acceptance_criteria": ["real web UI", "file explorer", "code editor area", "live logs", "test runner", "repair/change workflow", "zip download", "Render deployment docs", "meaningful pytest suite"],
            }
        return {
            "stack": "Flask + SQLite + vanilla HTML/CSS/JS",
            "file_map": {"app.py":"Flask app/API", "database.py":"SQLite persistence", "logic.py":"business logic", "templates/index.html":"UI", "static/app.js":"frontend behaviour", "test_app.py":"tests", "requirements.txt":"pip dependencies"},
            "routes": ["GET /"],
            "database_tables": [],
            "public_functions_by_file": {},
            "dependency_policy": "Only pip-installable third-party packages; never stdlib modules like sqlite3.",
            "acceptance_criteria": ["matches prompt", "runs", "tests pass"],
        }
    
    def _parse_json_robust(self, content: str) -> List[Dict[str, Any]]:
        """
        Parse JSON with multiple fallback strategies.
        
        Tries in order:
        1. Extract from ```json blocks
        2. Parse entire content as JSON
        3. Extract first JSON array found
        """
        # Strategy 1: Extract from markdown code blocks
        json_match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Strategy 2: Try parsing entire content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # Strategy 3: Find first JSON array in text
        # Look for [ ... ] pattern
        array_match = re.search(r'\[.*\]', content, re.DOTALL)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass
        
        # If all fails, raise descriptive error
        raise ValueError(
            f"Could not parse JSON from response. "
            f"Content preview: {content[:200]}..."
        )
    
    def assign_task(self, task: Dict[str, Any]) -> AgentRole:
        """Assign task to appropriate agent"""
        return task["agent_role"]
    
    def validate_deliverable(self, deliverable: AgentDeliverable) -> tuple[bool, List[str]]:
        """Validate deliverable meets contract"""
        return deliverable.validate(), []


class TestOrchestrator:
    """
    Handles ONLY test execution
    Single Responsibility: Run tests and report results
    """
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
    
    def install_dependencies(self, deliverables: List[AgentDeliverable]) -> Dict[str, Any]:
        """Install generated app dependencies before running tests.

        Installs dependencies declared by agent outputs plus requirements.txt if present.
        Built-in stdlib modules are skipped.
        """
        import subprocess
        import sys

        stdlib = {"sqlite3", "json", "os", "sys", "datetime", "math", "re", "pathlib", "typing", "tkinter", "unittest", "zipfile", "shutil", "subprocess", "threading", "dataclasses", "enum", "functools", "itertools", "collections", "logging", "tempfile", "uuid", "time", "base64", "hashlib", "secrets", "argparse"}

        def clean_requirement_line(line: str) -> str:
            raw = line.strip()
            if not raw or raw.startswith('#'):
                return raw
            pkg = raw.split(';', 1)[0].strip()
            pkg = re.split(r'[<>=!~\[ ]', pkg, maxsplit=1)[0].strip().lower().replace('_', '-')
            if pkg.replace('-', '_') in stdlib or pkg in stdlib:
                return ''
            if pkg in local_modules:
                return ''
            # Avoid ancient pins that break in Render's Python 3.14 environment.
            # Generated apps should use current compatible versions unless the user
            # explicitly asks for legacy versions.
            if pkg == 'flask':
                return 'Flask>=3.0'
            if pkg == 'pytest':
                return 'pytest>=8.4'
            if pkg == 'requests':
                return 'requests>=2.31'
            if pkg == 'sqlalchemy':
                return 'SQLAlchemy>=2.0'
            return raw

        def package_name(spec: str) -> str:
            raw = str(spec).strip()
            if not raw or raw.startswith('#'):
                return ''
            raw = raw.split(';', 1)[0].strip()
            return re.split(r'[<>=!~\[ ]', raw, maxsplit=1)[0].strip().lower().replace('_', '-')

        # Anything generated as a .py file is a LOCAL MODULE, not a pip package.
        # Earlier builds tried to run: pip install app database logic pytest
        # because agents placed local imports into the dependencies list.
        # That is wrong; only third-party packages should be installed.
        local_modules = set()
        for py in self.project_root.rglob('*.py'):
            if py.name == '__init__.py':
                continue
            local_modules.add(py.stem.lower().replace('_', '-'))
        for child in self.project_root.iterdir():
            if child.is_dir() and (child / '__init__.py').exists():
                local_modules.add(child.name.lower().replace('_', '-'))

        deps = set()
        skipped_local = []
        for d in deliverables:
            for output in d.outputs:
                for dep in getattr(output, "dependencies", []) or []:
                    dep = str(dep).strip()
                    name = package_name(dep)
                    if not name:
                        continue
                    if name.replace('-', '_') in stdlib or name in stdlib:
                        continue
                    if name in local_modules:
                        skipped_local.append(dep)
                        continue
                    deps.add(dep)

        req = self.project_root / "requirements.txt"
        removed_req_lines = []
        if req.exists():
            original_lines = req.read_text(encoding="utf-8", errors="replace").splitlines()
            cleaned_lines = []
            for line in original_lines:
                cleaned = clean_requirement_line(line)
                if cleaned:
                    cleaned_lines.append(cleaned)
                elif line.strip() and not line.strip().startswith('#'):
                    removed_req_lines.append(line.strip())
            if cleaned_lines != original_lines:
                req.write_text("\n".join(cleaned_lines).strip() + ("\n" if cleaned_lines else ""), encoding="utf-8")

        results = {"ok": True, "installed": sorted(deps), "output": ""}
        if skipped_local:
            results["output"] += "Skipped local generated modules from pip install: " + ", ".join(sorted(set(skipped_local))) + "\n"
        if removed_req_lines:
            results["output"] += "Sanitized requirements.txt; removed non-pip/stdlib/local entries: " + ", ".join(removed_req_lines) + "\n"
        # Do not separately install dependencies already present in requirements.txt.
        req_names = set()
        if req.exists():
            for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
                name = package_name(line)
                if name:
                    req_names.add(name)
        deps = {d for d in deps if package_name(d) not in req_names}

        commands = []
        if req.exists() and req.read_text(encoding="utf-8", errors="replace").strip():
            commands.append([sys.executable, "-m", "pip", "install", "-r", str(req)])
        if deps:
            commands.append([sys.executable, "-m", "pip", "install", *sorted(deps)])

        for cmd in commands:
            try:
                proc = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True, timeout=120)
                results["output"] += f"$ {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\n"
                if proc.returncode != 0:
                    # If pip reports a non-existent distribution from requirements.txt,
                    # remove that line and retry once. This catches common AI mistakes
                    # like adding sqlite3/unittest/json to requirements.txt.
                    missing = re.findall(r"No matching distribution found for ([A-Za-z0-9_.-]+)", proc.stderr + proc.stdout)
                    if missing and req.exists() and "-r" in cmd:
                        bad = {m.lower().replace('_', '-') for m in missing}
                        lines = req.read_text(encoding="utf-8", errors="replace").splitlines()
                        kept = []
                        removed = []
                        for line in lines:
                            name = re.split(r'[<>=!~\[ ;]', line.strip(), maxsplit=1)[0].lower().replace('_', '-')
                            if name in bad:
                                removed.append(line.strip())
                            else:
                                kept.append(line)
                        if removed:
                            req.write_text("\n".join(kept).strip() + ("\n" if kept else ""), encoding="utf-8")
                            results["output"] += "Removed invalid requirements after pip failure: " + ", ".join(removed) + "\n"
                            proc2 = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True, timeout=120)
                            results["output"] += f"$ {' '.join(cmd)} # retry\nSTDOUT:\n{proc2.stdout}\nSTDERR:\n{proc2.stderr}\n"
                            if proc2.returncode == 0:
                                continue
                    results["ok"] = False
                    break
            except Exception as e:
                results["ok"] = False
                results["output"] += f"Dependency install failed: {e}\n"
                break

        return results

    def _discover_test_files(self, hinted_tests: Optional[List[str]] = None) -> List[str]:
        """Discover pytest files that actually exist.

        Earlier Boom3 builds trusted agent metadata such as test_app.py. When
        the agent generated test_logic.py/test_services.py instead, pytest was
        called with a nonexistent file and the whole project failed. This
        function treats agent metadata as a hint only and falls back to real
        filesystem discovery.
        """
        from pathlib import Path

        root = Path(self.project_root)
        discovered = []

        # Keep valid hinted tests first, but ignore stale/nonexistent names.
        for name in hinted_tests or []:
            if not name:
                continue
            p = root / name
            if p.is_file() and p.name.startswith("test") and p.suffix == ".py":
                discovered.append(p.relative_to(root).as_posix())

        # Then discover any pytest-style files anywhere under the project.
        for pattern in ("test_*.py", "*_test.py"):
            for p in root.rglob(pattern):
                if not p.is_file():
                    continue
                if any(part in {".venv", "venv", "__pycache__", ".pytest_cache"} for part in p.parts):
                    continue
                rel = p.relative_to(root).as_posix()
                if rel not in discovered:
                    discovered.append(rel)

        return discovered

    def run_tests(self, test_files: List[str]) -> Dict[str, Any]:
        """Run generated tests using pytest discovery, not hardcoded filenames."""
        import subprocess
        import sys
        import os as _os
        import re

        test_files = self._discover_test_files(test_files)

        if not test_files:
            # No pytest files were generated. Still do a basic health check so
            # Boom3 does not mark broken Python code as completed.
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "compileall", "-q", str(self.project_root)],
                    capture_output=True,
                    text=True,
                    cwd=self.project_root,
                    timeout=60,
                )
                output = f"No pytest files found; ran compileall health check.\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
                if result.returncode == 0:
                    return {"passed": 1, "failed": 0, "errors": [], "output": output}
                return {"passed": 0, "failed": 1, "errors": [result.stderr or result.stdout], "output": output}
            except Exception as e:
                return {"passed": 0, "failed": 1, "errors": [str(e)], "output": str(e)}

        results = {"passed": 0, "failed": 0, "errors": [], "output": ""}

        try:
            env = _os.environ.copy()
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(self.project_root) + (":" + existing if existing else "")

            # Run only files that exist. Never force test_app.py unless it exists.
            result = subprocess.run(
                ["pytest", *test_files, "-v", "--tb=short"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=90,
                env=env,
            )

            results["output"] = (
                f"Discovered tests: {', '.join(test_files)}\n"
                f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
            )

            stdout = result.stdout or ""
            passed_match = re.search(r'(\d+) passed', stdout)
            failed_match = re.search(r'(\d+) failed', stdout)
            error_match = re.search(r'(\d+) error', stdout)

            results["passed"] = int(passed_match.group(1)) if passed_match else (len(test_files) if result.returncode == 0 else 0)
            fail_count = int(failed_match.group(1)) if failed_match else 0
            err_count = int(error_match.group(1)) if error_match else 0
            results["failed"] = fail_count + err_count

            if result.returncode != 0 and results["failed"] == 0:
                # Collection/import failure or another pytest failure mode.
                results["failed"] = 1

            if results["failed"] > 0:
                results["errors"].append(result.stderr or result.stdout)

        except subprocess.TimeoutExpired:
            results["failed"] = max(1, len(test_files))
            results["errors"].append("Tests timed out after 90 seconds")

        except Exception as e:
            results["failed"] = max(1, len(test_files))
            results["errors"].append(str(e))

        return results
    
    def generate_test_report(self, results: Dict[str, Any]) -> str:
        """Generate human-readable test report"""
        total = results["passed"] + results["failed"]
        pass_rate = (results["passed"] / total * 100) if total > 0 else 0
        
        report = [
            "=== TEST REPORT ===",
            f"Total: {total}",
            f"Passed: {results['passed']}",
            f"Failed: {results['failed']}",
            f"Pass Rate: {pass_rate:.1f}%",
        ]
        
        if results["errors"]:
            report.append("\nErrors:")
            for error in results["errors"]:
                report.append(f"  - {error[:100]}")
        
        return "\n".join(report)


class FileManager:
    """
    Handles ONLY file operations
    Single Responsibility: Read/write files safely
    """
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.created_files: List[Path] = []
    
    def write_file(self, output: CodeOutput) -> bool:
        """Write code output to file"""
        try:
            file_path = self.project_root / output.filepath
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(output.code)
            
            self.created_files.append(file_path)
            return True
        
        except Exception as e:
            print(f"Failed to write {output.filepath}: {e}")
            return False
    
    def read_file(self, filepath: str) -> Optional[str]:
        """Read file contents"""
        try:
            with open(self.project_root / filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except:
            return None
    
    def rollback(self):
        """Delete all created files (for error recovery)"""
        for file_path in reversed(self.created_files):
            try:
                file_path.unlink()
            except:
                pass
        self.created_files.clear()


# ==============================================================================
# ABSTRACT BASE CLASS
# ==============================================================================
# ProjectOrchestrator below is ABSTRACT - it cannot be instantiated directly.
# Use ProductionOrchestrator (concrete implementation) or create your own subclass.
# ==============================================================================


class ProjectOrchestrator(ABC):
    """
    ABSTRACT BASE CLASS - Main orchestrator that composes all modules.
    
    Single Responsibility: Coordinate the modules (not do their work)
    
    This class provides the complete production pipeline but leaves _execute_task()
    as abstract. Subclasses MUST implement _execute_task() with their specific
    validation/retry logic.
    
    Do NOT instantiate this directly - use ProductionOrchestrator instead.
    """
    
    def __init__(
        self,
        project_root: Path,
        coordinator: AgentCoordinator,
        state_manager: StateManager,
        wiring_registry: WiringRegistry,
        test_orchestrator: TestOrchestrator,
        file_manager: FileManager
    ):
        self.project_root = project_root
        self.coordinator = coordinator
        self.state_manager = state_manager
        self.wiring_registry = wiring_registry
        self.test_orchestrator = test_orchestrator
        self.file_manager = file_manager
        
        self.state = ProjectState(
            current_state=ExecutionState.IDLE,
            current_step=0,
            total_steps=0,
            deliverables=[],
            errors=[],
            logs=[]
        )

        # Control events: set to signal the execution loop
        # _pause_event: cleared = paused, set = running
        # _cancel_event: set = cancel requested
        self._pause_event = threading.Event()
        self._pause_event.set()   # starts unpaused
        self._cancel_event = threading.Event()

    def add_log(self, message: str) -> None:
        """Add a UI-visible log line and persist it best-effort."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        if not hasattr(self.state, "logs") or self.state.logs is None:
            self.state.logs = []
        self.state.logs.append(line)
        # Keep state JSON small enough for Render/free instances.
        self.state.logs = self.state.logs[-500:]
        try:
            self.state_manager.save(self.state)
        except Exception:
            pass
    
    def execute_project(self, project_contract: ProjectContract) -> bool:
        """
        Execute complete project with full production pipeline:
        - Planning
        - Execution with validation/retry
        - Wiring verification
        - Testing
        - File commitment
        """
        try:
            # Planning phase
            self.add_log("🧠 Planning project with AI foreman...")
            self.state.current_state = ExecutionState.PLANNING
            tasks = self.coordinator.plan_work(project_contract)
            self.add_log(f"✅ Planning complete: {len(tasks)} task(s) created")
            self.state.total_steps = len(tasks)
            self.state_manager.save(self.state)
            
            # Execution phase
            self.state.current_state = ExecutionState.EXECUTING
            
            for i, task in enumerate(tasks):
                # Check for pause/cancel between tasks
                if not self._check_control():
                    # Cancelled — rollback any uncommitted staged files and exit
                    if hasattr(self.file_manager, 'rollback'):
                        self.file_manager.rollback()
                    return False

                self.state.current_step = i + 1
                role = task.get("agent_role")
                role_name = getattr(role, "value", str(role))
                self.add_log(f"🤖 Running agent {i + 1}/{len(tasks)}: {role_name}")
                self.state_manager.save(self.state)
                
                # Execute task (subclass implements validation/retry)
                deliverable = self._execute_task(task)
                
                # Validate deliverable
                valid, issues = self.coordinator.validate_deliverable(deliverable)
                if not valid:
                    self.state.errors.extend(issues)
                    self.state.current_state = ExecutionState.FAILED
                    self.state_manager.save(self.state)
                    return False
                
                # Save deliverable
                self.add_log(f"✅ Agent finished: {role_name}; generated {len(deliverable.outputs)} file(s)")
                self.state.deliverables.append(deliverable)
                
                # Write files
                for output in deliverable.outputs:
                    self.file_manager.write_file(output)
                
                # Register wiring
                for wire in deliverable.wiring:
                    self.wiring_registry.register(wire)
            
            # Wiring verification phase
            self.add_log("🔌 Verifying wiring between generated files...")
            from core.validation import WiringLinker
            linker = WiringLinker()
            link_result = linker.link_and_verify(self.state.deliverables)
            
            if not link_result.valid:
                self.state.errors.extend(link_result.errors)
                self.state.current_state = ExecutionState.FAILED
                self.state_manager.save(self.state)
                return False
            
            self.add_log("✅ Wiring verified")
            # Commit files (if SafeFileManager)
            if hasattr(self.file_manager, 'commit_all'):
                if not self.file_manager.commit_all():
                    self.state.errors.append("Failed to commit files")
                    self.state.current_state = ExecutionState.FAILED
                    self.state_manager.save(self.state)
                    return False
            
            # Testing phase
            self.add_log("📦 Committing generated files and starting test pipeline...")
            self.state.current_state = ExecutionState.TESTING
            self.state_manager.save(self.state)

            self.add_log("📦 Installing generated app dependencies...")
            dep_results = self.test_orchestrator.install_dependencies(self.state.deliverables)
            if dep_results.get("output"):
                self.add_log("Dependency output:\n" + dep_results.get("output", "")[-4000:])
            if not dep_results.get("ok", False):
                self.add_log("❌ Dependency install failed")
                self.state.errors.append("Dependency install failed")
                self.state.errors.append(dep_results.get("output", ""))
                self.state.current_state = ExecutionState.FAILED
                self.state_manager.save(self.state)
                return False

            test_files = [
                tf for d in self.state.deliverables
                for tf in d.tests_generated
            ]
            self.add_log(f"🧪 Running tests ({len(test_files)} test file(s))...")
            test_results = self.test_orchestrator.run_tests(test_files)
            self.add_log(self.test_orchestrator.generate_test_report(test_results))
            if test_results.get("output"):
                self.add_log("Test output:\n" + test_results.get("output", "")[-6000:])

            if test_results["failed"] > 0:
                self.add_log("🛠️ Tests failed; attempting automatic repair")
                self.state.errors.append("Tests failed; attempting automatic repair")
                self.state.errors.append(test_results.get("output", ""))
                self.state_manager.save(self.state)

                repaired = self._repair_until_tests_pass(test_files, test_results, max_attempts=3)
                if not repaired:
                    self.state.current_state = ExecutionState.FAILED
                    self.add_log("❌ Automatic repair failed; tests are still failing")
                    self.state.errors.append("Automatic repair failed; tests are still failing")
                    self.state_manager.save(self.state)
                    return False

            # Prompt compliance phase: tests passing is not enough. The generated
            # app must also satisfy the user's requested app shape. This prevents
            # toy apps from passing trivial tests.
            self.add_log("🔎 Checking generated app against original prompt...")
            compliance = self._check_prompt_compliance(project_contract)
            if not compliance.get("passed", False):
                missing = compliance.get("missing", []) or [compliance.get("summary", "Prompt compliance failed")]
                self.add_log("⚠️ Prompt compliance failed; missing: " + "; ".join(map(str, missing[:8])))
                self.state.errors.append("Prompt compliance failed: " + "; ".join(map(str, missing[:8])))
                self.state_manager.save(self.state)
                fixed = self._repair_prompt_compliance(project_contract, compliance, test_files, max_attempts=3)
                if not fixed:
                    self.state.current_state = ExecutionState.FAILED
                    self.add_log("❌ Prompt compliance repair failed; project does not match the request")
                    self.state.errors.append("Prompt compliance repair failed")
                    self.state_manager.save(self.state)
                    return False
            else:
                self.add_log("✅ Prompt compliance passed")

            # Complete only after dependencies, tests, and prompt compliance pass
            self.add_log("🎉 Build verified: dependencies installed, tests passed, and prompt requirements satisfied")
            self.state.current_state = ExecutionState.COMPLETED
            self.state_manager.save(self.state)

            return True
        
        except Exception as e:
            self.state.current_state = ExecutionState.FAILED
            self.add_log(f"❌ Project crashed: {e}")
            self.state.errors.append(str(e))
            self.state_manager.save(self.state)
            if hasattr(self.file_manager, 'rollback_all'):
                self.file_manager.rollback_all()
            else:
                self.file_manager.rollback()
            return False
    
    def _read_generated_project_files(self, max_chars: int = 60000) -> str:
        """Read generated app files for AI review/repair."""
        chunks = []
        allowed = {".py", ".txt", ".md", ".json", ".html", ".css", ".js", ".sql", ".yaml", ".yml"}
        for path in sorted(self.project_root.rglob("*")):
            if not path.is_file() or ".venv" in path.parts or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
                continue
            if path.suffix.lower() not in allowed and path.name not in {"Dockerfile", "requirements.txt", ".dockerignore", ".gitignore", ".env.example", ".flaskenv"}:
                continue
            rel = path.relative_to(self.project_root).as_posix()
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            chunks.append(f"--- {rel} ---\n{content[:8000]}")
        return "\n\n".join(chunks)[:max_chars]

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        import json
        import re
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("AI response did not contain a JSON object")
        return json.loads(text[start:end + 1])

    def _check_prompt_compliance(self, project_contract: ProjectContract) -> Dict[str, Any]:
        """Ask AI to compare the built files against the original user prompt.

        Passing tests alone allowed tiny placeholder apps to be marked complete.
        This gate fails projects that do not resemble the requested application.
        """
        import os
        ai_client = getattr(self, "ai_client", None)
        if ai_client is None:
            return {"passed": False, "score": 0, "missing": ["No AI client available for prompt compliance review"], "summary": "No AI client"}

        prompt = f"""
You are Boom3's strict acceptance reviewer.

Original project name: {project_contract.project_name}
Original user request:
{project_contract.description}

Generated files:
{self._read_generated_project_files(70000)}

Decide whether this generated app genuinely satisfies the user's request.
Do NOT pass toy/placeholder apps just because tests pass.
Do NOT pass if the prompt asked for an app-builder/Lovable/Bolt/Replit-style tool and the project lacks a real web UI, file explorer/code viewer, live logs, test runner/repair workflow, project APIs, and download/deploy support.

Return ONLY JSON:
{{
  "passed": true_or_false,
  "score": 0_to_100,
  "summary": "one sentence",
  "missing": ["specific missing requirement"],
  "required_files_or_features": ["specific files/features that should exist"]
}}
"""
        response = ai_client.chat.completions.create(
            model=os.environ.get("BOOM3_MODEL", "gpt-4o"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        review = self._extract_json_object(response.choices[0].message.content or "")
        # Require both explicit pass and a reasonable score.
        review["passed"] = bool(review.get("passed")) and int(review.get("score", 0)) >= 75
        self.add_log(f"Prompt compliance score: {review.get('score', 0)}/100 — {review.get('summary', '')}")
        return review

    def _repair_prompt_compliance(self, project_contract: ProjectContract, compliance: Dict[str, Any], test_files: List[str], max_attempts: int = 3) -> bool:
        """Repair/regenerate the generated app until it matches the prompt and tests pass."""
        import os
        ai_client = getattr(self, "ai_client", None)
        if ai_client is None:
            return False

        last_test_output = ""
        for attempt in range(1, max_attempts + 1):
            self.add_log(f"🧩 Prompt compliance repair attempt {attempt}/{max_attempts}")
            prompt = f"""
You are Boom3's prompt-compliance repair worker.

The generated app passed code tests but FAILED acceptance review because it does not match the original user request.

Original project name: {project_contract.project_name}
Original user request:
{project_contract.description}

Acceptance review:
{compliance}

Previous test output:
{last_test_output[-12000:]}

Current files:
{self._read_generated_project_files(80000)}

Patch/create the project so it genuinely matches the original request.
For app-builder/Lovable/Bolt/Replit-style prompts, create a real Flask web app with:
- templates/index.html
- static/styles.css
- static/app.js
- app.py with JSON APIs
- database.py and/or logic.py
- test_app.py with meaningful Flask/client tests
- requirements.txt
- README.md
- ZIP/download endpoint and visible logs/test/repair/change UI

Return ONLY JSON:
{{
  "files": [
    {{"filepath": "relative/path.ext", "code": "complete replacement file contents"}}
  ],
  "notes": "brief explanation"
}}
Rules:
- Return complete contents for every file you change.
- You may add new files.
- Keep paths inside the generated project.
- Include or update tests so they fail on placeholder implementations.
- Do not include markdown outside JSON.
"""
            try:
                response = ai_client.chat.completions.create(
                    model=os.environ.get("BOOM3_MODEL", "gpt-4o"),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                )
                patch = self._extract_json_object(response.choices[0].message.content or "")
                files = patch.get("files", [])
                if not files:
                    raise ValueError("prompt compliance repair returned no files")
                self.add_log("AI compliance repair returned: " + ", ".join(str(f.get("filepath", "?")) for f in files))
                for item in files:
                    rel = str(item["filepath"]).strip().lstrip("/")
                    target = (self.project_root / rel).resolve()
                    if not str(target).startswith(str(self.project_root.resolve())):
                        raise ValueError(f"refusing to write outside project: {rel}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(item["code"], encoding="utf-8")

                # Discover new tests created during compliance repair.
                discovered_tests = sorted(p.relative_to(self.project_root).as_posix() for p in self.project_root.rglob("test_*.py") if ".venv" not in p.parts)
                if discovered_tests:
                    test_files = discovered_tests

                dep_results = self.test_orchestrator.install_dependencies(self.state.deliverables)
                if dep_results.get("output"):
                    self.add_log("Dependency output:\n" + dep_results.get("output", "")[-4000:])
                if not dep_results.get("ok", False):
                    last_test_output = dep_results.get("output", "")
                    self.add_log("❌ Dependencies failed after compliance repair")
                    continue

                self.add_log(f"🧪 Running tests ({len(test_files)} test file(s)) after compliance repair...")
                test_results = self.test_orchestrator.run_tests(test_files)
                last_test_output = test_results.get("output", "")
                self.add_log(self.test_orchestrator.generate_test_report(test_results))
                if last_test_output:
                    self.add_log("Compliance repair test output:\n" + last_test_output[-6000:])
                if test_results.get("failed", 0) > 0:
                    self.add_log(f"⚠️ Compliance repair attempt {attempt} still has failing tests")
                    self.add_log("🛠️ Running normal test auto-repair after compliance patch...")
                    # Compliance repair often adds required features but leaves one
                    # or two tests out of sync with the changed API shape. Do not
                    # throw the whole compliance attempt away immediately; first use
                    # the normal test repair loop, then re-check prompt compliance.
                    if not self._repair_until_tests_pass(test_files, test_results, max_attempts=2):
                        self.add_log(f"⚠️ Compliance repair attempt {attempt} could not be test-repaired")
                        continue

                compliance = self._check_prompt_compliance(project_contract)
                if compliance.get("passed", False):
                    self.add_log("✅ Prompt compliance repair succeeded")
                    return True
                self.add_log("⚠️ Compliance repair still missing: " + "; ".join(map(str, compliance.get("missing", [])[:8])))

            except Exception as e:
                last_test_output = str(e)
                self.add_log(f"❌ Prompt compliance repair attempt {attempt} crashed: {e}")

        return False

    def _repair_until_tests_pass(self, test_files: List[str], test_results: Dict[str, Any], max_attempts: int = 3) -> bool:
        """Use the AI client to patch generated files, then rerun tests.

        This is the missing build/test/fix loop: Boom3 should not mark a project
        complete just because files were generated. It must install deps, run tests,
        ask the model to repair failures, and only complete when tests pass.
        """
        import json
        import re

        ai_client = getattr(self, "ai_client", None)
        if ai_client is None:
            self.state.errors.append("No AI client available for automatic repair")
            return False

        def extract_json(text: str):
            fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
            if fenced:
                text = fenced.group(1)
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError("repair response did not contain JSON")
            return json.loads(text[start:end + 1])

        def read_project_files() -> str:
            chunks = []
            for path in sorted(self.project_root.rglob("*.py")):
                if ".venv" in path.parts or "__pycache__" in path.parts:
                    continue
                rel = path.relative_to(self.project_root).as_posix()
                try:
                    content = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                chunks.append(f"--- {rel} ---\n{content[:6000]}")
            return "\n\n".join(chunks)[:30000]

        model = __import__("os").environ.get("BOOM3_MODEL", "gpt-4o")

        for attempt in range(1, max_attempts + 1):
            self.add_log(f"🛠️ Automatic repair attempt {attempt}/{max_attempts}")
            self.state.errors.append(f"Automatic repair attempt {attempt}/{max_attempts}")
            self.state_manager.save(self.state)

            prompt = f"""
You are Boom3's automatic repair worker. The generated app failed its tests.
Patch the generated files so all tests pass and the app still matches the user's requested app.

Return ONLY JSON in this exact format:
{{
  "files": [
    {{"filepath": "logic.py", "code": "complete replacement file contents"}}
  ],
  "notes": "brief explanation"
}}

Rules:
- Return complete replacement contents for every file you change.
- Only patch files inside the generated project.
- Prefer fixing application code over weakening tests. Only edit tests when their expectations are objectively wrong or inconsistent with the requested product.
- You MUST inspect the failing assertion and patch the file that controls that behavior. Do not keep changing the same unrelated helper file if the failing route/API response is implemented elsewhere.
- If a Flask endpoint returns raw [] but tests expect a JSON object containing a files key, fix the endpoint to return {{"files": [...]}} rather than repeatedly changing unrelated logic helpers.
- If create_project has a signature mismatch, make app.py, logic.py, database.py and tests agree on one contract.
- If a test parses response text manually, prefer returning proper JSON and update the test to use response.get_json() when appropriate.
- After each patch, the generated app must still match the original user request, not just satisfy trivial tests.
- Do not include markdown.

Previous pytest output:
{test_results.get('output', '')[-14000:]}

Project files:
{read_project_files()}
"""
            try:
                response = ai_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                )
                raw = response.choices[0].message.content or ""
                patch = extract_json(raw)
                files = patch.get("files", [])
                if not files:
                    raise ValueError("repair response contained no files")

                self.add_log(f"AI repair returned {len(files)} file change(s): " + ", ".join(str(f.get("filepath", "?")) for f in files))
                for item in files:
                    rel = str(item["filepath"]).strip().lstrip("/")
                    target = (self.project_root / rel).resolve()
                    if not str(target).startswith(str(self.project_root.resolve())):
                        raise ValueError(f"refusing to write outside project: {rel}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(item["code"], encoding="utf-8")

                self.add_log(f"🧪 Running tests ({len(test_files)} test file(s))...")
                test_results = self.test_orchestrator.run_tests(test_files)
                self.add_log(self.test_orchestrator.generate_test_report(test_results))
                if test_results.get("output"):
                    self.add_log("Repair test output:\n" + test_results.get("output", "")[-6000:])
                if test_results["failed"] == 0:
                    self.add_log("✅ Automatic repair succeeded; tests passed")
                    self.state.errors.append("Automatic repair succeeded; tests passed")
                    self.state_manager.save(self.state)
                    return True

                self.add_log(f"⚠️ Repair attempt {attempt} still failed")
                self.state.errors.append(f"Repair attempt {attempt} still failed")
                self.state.errors.append(test_results.get("output", ""))
                self.state_manager.save(self.state)

            except Exception as e:
                self.add_log(f"❌ Repair attempt {attempt} crashed: {e}")
                self.state.errors.append(f"Repair attempt {attempt} crashed: {e}")
                self.state_manager.save(self.state)

        return False

    def apply_change_request(self, change_request: str, max_attempts: int = 3) -> bool:
        """Apply a user-requested change to the generated project, then rerun tests.

        This powers the UI "Request changes" button. It edits existing files, runs
        tests, and leaves the project FAILED if the requested change cannot be
        verified.
        """
        import json
        import re
        import os

        ai_client = getattr(self, "ai_client", None)
        if ai_client is None:
            self.add_log("❌ No AI client available for requested changes")
            self.state.current_state = ExecutionState.FAILED
            self.state.errors.append("No AI client available for requested changes")
            self.state_manager.save(self.state)
            return False

        def extract_json(text: str):
            fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
            if fenced:
                text = fenced.group(1)
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError("change response did not contain JSON")
            return json.loads(text[start:end + 1])

        def read_project_files() -> str:
            chunks = []
            for path in sorted(self.project_root.rglob("*")):
                if not path.is_file() or ".venv" in path.parts or "__pycache__" in path.parts:
                    continue
                if path.suffix.lower() not in {".py", ".txt", ".md", ".json", ".html", ".css", ".js"}:
                    continue
                rel = path.relative_to(self.project_root).as_posix()
                try:
                    content = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                chunks.append(f"--- {rel} ---\n{content[:6000]}")
            return "\n\n".join(chunks)[:40000]

        self.state.current_state = ExecutionState.TESTING
        self.add_log("✏️ Applying requested change: " + change_request[:500])
        model = os.environ.get("BOOM3_MODEL", "gpt-4o")

        test_files = [tf for d in self.state.deliverables for tf in d.tests_generated]
        last_output = ""
        for attempt in range(1, max_attempts + 1):
            self.add_log(f"✏️ Change attempt {attempt}/{max_attempts}")
            prompt = f"""
You are Boom3's change worker. Update the generated app to satisfy this user request:
{change_request}

Return ONLY JSON in this exact format:
{{
  "files": [
    {{"filepath": "relative/path.py", "code": "complete replacement file contents"}}
  ],
  "notes": "brief explanation"
}}

Rules:
- Return complete replacement contents for every file you change.
- Only edit files inside the generated project.
- Preserve existing working behaviour unless the user requested otherwise.
- If tests need updating because requirements changed, include the updated tests.
- Do not include markdown.

Previous test output:
{last_output[-12000:]}

Project files:
{read_project_files()}
"""
            try:
                response = ai_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                )
                raw = response.choices[0].message.content or ""
                patch = extract_json(raw)
                files = patch.get("files", [])
                if not files:
                    raise ValueError("change response contained no files")
                self.add_log("AI change returned: " + ", ".join(str(f.get("filepath", "?")) for f in files))
                for item in files:
                    rel = str(item["filepath"]).strip().lstrip("/")
                    target = (self.project_root / rel).resolve()
                    if not str(target).startswith(str(self.project_root.resolve())):
                        raise ValueError(f"refusing to write outside project: {rel}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(item["code"], encoding="utf-8")

                dep_results = self.test_orchestrator.install_dependencies(self.state.deliverables)
                if dep_results.get("output"):
                    self.add_log("Dependency output:\n" + dep_results.get("output", "")[-4000:])
                if not dep_results.get("ok", False):
                    last_output = dep_results.get("output", "")
                    self.add_log("❌ Dependencies failed after requested change")
                    continue

                test_results = self.test_orchestrator.run_tests(test_files)
                last_output = test_results.get("output", "")
                self.add_log(self.test_orchestrator.generate_test_report(test_results))
                if last_output:
                    self.add_log("Change test output:\n" + last_output[-6000:])
                if test_results.get("failed", 0) == 0:
                    self.state.current_state = ExecutionState.COMPLETED
                    self.add_log("✅ Requested change applied and tests passed")
                    self.state_manager.save(self.state)
                    return True
                self.add_log(f"⚠️ Requested change attempt {attempt} still has failing tests")
            except Exception as e:
                last_output = str(e)
                self.add_log(f"❌ Requested change attempt {attempt} crashed: {e}")

        self.state.current_state = ExecutionState.FAILED
        self.state.errors.append("Requested change failed verification")
        self.state_manager.save(self.state)
        return False

    @abstractmethod
    def _execute_task(self, task: Dict[str, Any]) -> AgentDeliverable:
        """
        Execute a single task with full production pipeline:
        - Agent execution
        - Validation with retry
        - Logging
        
        Subclasses MUST implement this method.
        """
        pass
    
    def pause(self):
        """
        Pause execution after the current task completes.
        The execution loop checks _pause_event between tasks.
        """
        self._pause_event.clear()
        self.state.current_state = ExecutionState.PAUSED
        self.state_manager.save(self.state)

    def resume(self) -> bool:
        """
        Resume a paused run.  Unblocks the execution loop so it moves
        to the next task.
        """
        if self.state.current_state == ExecutionState.PAUSED:
            self.state.current_state = ExecutionState.EXECUTING
            self.state_manager.save(self.state)
            self._pause_event.set()
            return True
        # Legacy: also try loading from disk (supports restart after crash)
        saved_state = self.state_manager.load()
        if saved_state and saved_state.current_state == ExecutionState.PAUSED:
            self.state = saved_state
            self.state.current_state = ExecutionState.EXECUTING
            self._pause_event.set()
            return True
        return False

    def cancel(self):
        """
        Request cancellation of the current run.
        The execution loop will stop after the current task finishes
        (we do not kill threads mid-task to avoid leaving corrupt state).
        If paused, also unblocks so the loop can see the cancel signal.
        """
        self._cancel_event.set()
        self._pause_event.set()   # unblock a paused loop so it can exit
        self.state.current_state = ExecutionState.CANCELLED
        self.state_manager.save(self.state)

    def _check_control(self) -> bool:
        """
        Block here if paused; return False if cancelled.
        Call this between tasks in the execution loop.
        """
        # Wait indefinitely while paused (unblocked by resume() or cancel())
        self._pause_event.wait()
        # After unblocking, check for cancellation
        if self._cancel_event.is_set():
            return False
        return True


# ==============================================================================
# CONCRETE IMPLEMENTATION
# ==============================================================================
# ProductionOrchestrator below is the CONCRETE implementation of the abstract
# ProjectOrchestrator. It provides the actual _execute_task() logic.
# ==============================================================================


class ProductionOrchestrator(ProjectOrchestrator):
    """
    CONCRETE IMPLEMENTATION - Production-ready orchestrator.
    
    This is the ACTUAL WORKING orchestrator that implements the abstract
    _execute_task() method with:
    - Agent execution
    - Validation and retry
    - Complete logging with raw responses
    - Error handling
    
    Use create_orchestrator() factory to instantiate this.
    """
    
    def __init__(
        self,
        project_root: Path,
        ai_client,
        coordinator: AgentCoordinator = None,
        state_manager: StateManager = None,
        wiring_registry: WiringRegistry = None,
        test_orchestrator: TestOrchestrator = None,
        file_manager = None,
        run_logger = None
    ):
        # Initialize or create components
        coordinator = coordinator or ForemanCoordinator(ai_client)
        state_manager = state_manager or StateManager(project_root / ".boom3_state.json")
        wiring_registry = wiring_registry or WiringRegistry()
        test_orchestrator = test_orchestrator or TestOrchestrator(project_root)
        
        # Use SafeFileManager by default
        if file_manager is None:
            from core.file_workspace import SafeFileManager
            file_manager = SafeFileManager(project_root, overwrite=False)
        
        # Initialize run logger
        if run_logger is None:
            from core.run_logger import RunLogger
            run_logger = RunLogger(project_root)
        
        # Initialize base
        super().__init__(
            project_root=project_root,
            coordinator=coordinator,
            state_manager=state_manager,
            wiring_registry=wiring_registry,
            test_orchestrator=test_orchestrator,
            file_manager=file_manager
        )
        
        self.ai_client = ai_client
        self.run_logger = run_logger
    
    def _execute_task(self, task: Dict[str, Any]) -> AgentDeliverable:
        """
        Execute task with full production pipeline:
        - Agent execution with raw response capture
        - Validation with retry
        - Complete logging
        """
        import time
        from agents.specialized_agents import create_agent
        from core.validation import DeliverableValidator, RetryPolicy, FailureReason
        
        # Create agent
        # create_agent accepts only (agent_role, ai_client).
        # The previous 3-argument call crashed the worker thread before any agent could run.
        agent = create_agent(
            task['agent_role'],
            self.ai_client
        )
        
        # Setup validation and retry
        validator = DeliverableValidator()
        retry_policy = RetryPolicy(max_attempts=3)
        
        # Build context
        context = self._build_context(task)
        
        # RETRY LOOP
        task_id = task.get('id', task['agent_role'].value)
        
        while True:
            attempt = retry_policy.get_attempt_count(task_id) + 1
            print(f"   Attempt {attempt}/{retry_policy.max_attempts}...")
            
            # Execute task and capture raw response
            start_time = time.time()
            try:
                deliverable = agent.execute_task(task, context)
                raw_response = getattr(agent, 'last_raw_response', None)
            except Exception as e:
                print(f"   Agent execution failed: {e}")
                
                # Check if we should retry
                if retry_policy.should_retry(task_id, FailureReason.COMPILATION_FAILED):
                    retry_policy.record_attempt(task_id)
                    guidance = retry_policy.get_retry_strategy(
                        FailureReason.COMPILATION_FAILED, 
                        attempt
                    )
                    context = f"{context}\n\nPREVIOUS ATTEMPT FAILED:\n{str(e)}\n\n{guidance}"
                    continue
                else:
                    raise
            
            duration = time.time() - start_time
            
            # VALIDATE
            print("   Validating...")
            validation = validator.validate_complete(deliverable)
            
            # Log warnings
            for warning in validation.warnings:
                print(f"   ⚠️  {warning}")
            
            # Check if valid
            if validation.valid:
                print("   ✅ Validation passed")
                
                # LOG with actual raw response
                self.run_logger.log_agent_call(
                    agent_id=agent.agent_id,
                    agent_role=task['agent_role'].value,
                    task=task,
                    prompt=context[:1000],
                    model="gpt-4o",
                    temperature=0.3,
                    raw_response=raw_response or "[Response not captured]",
                    parsed_output=deliverable.to_dict(),
                    validation_result={
                        "valid": validation.valid,
                        "errors": validation.errors,
                        "warnings": validation.warnings
                    },
                    files_written=[o.filepath for o in deliverable.outputs],
                    errors=[],
                    duration=duration
                )
                
                return deliverable
            
            # Validation failed
            print(f"   ❌ Validation failed: {validation.failure_reason.value if validation.failure_reason else 'unknown'}")
            for error in validation.errors:
                print(f"      - {error}")
            
            # Check retry
            if not retry_policy.should_retry(task_id, validation.failure_reason):
                error_msg = f"Validation failed after {attempt} attempts: {validation.errors}"
                print(error_msg)
                
                # Log the failed attempt
                self.run_logger.log_agent_call(
                    agent_id=agent.agent_id,
                    agent_role=task['agent_role'].value,
                    task=task,
                    prompt=context[:1000],
                    model="gpt-4o",
                    temperature=0.3,
                    raw_response=raw_response or "[Response not captured]",
                    parsed_output=deliverable.to_dict() if deliverable else {},
                    validation_result={
                        "valid": False,
                        "errors": validation.errors,
                        "warnings": validation.warnings
                    },
                    files_written=[],
                    errors=validation.errors,
                    duration=duration
                )
                
                raise ValueError(error_msg)
            
            # Retry with guidance
            retry_policy.record_attempt(task_id)
            guidance = retry_policy.get_retry_strategy(validation.failure_reason, attempt)
            print(f"   🔄 Retrying with guidance...")
            
            context = f"""{context}

PREVIOUS ATTEMPT FAILED:
Errors: {validation.errors}

{guidance}

Please fix these issues and try again.
"""
    
    def _build_context(self, task: Dict[str, Any]) -> str:
        """Build context for agent execution with shared architecture and prior code.

        Earlier versions only told agents file names/exports, so every agent
        invented its own architecture. This context is intentionally stronger:
        every agent sees the same architecture contract and snippets of files
        already produced.
        """
        context = f"""
Project: {task.get('project_name', 'Unknown')}
Description: {task.get('description', '')}

THIS AGENT TASK:
{json.dumps({k: (v.value if hasattr(v, 'value') else v) for k, v in task.items()}, indent=2, default=str)[:8000]}

SHARED ARCHITECTURE CONTRACT - FOLLOW THIS EXACTLY:
{json.dumps(task.get('shared_architecture', {}), indent=2, default=str)[:12000]}

COORDINATION RULES:
- Use the filenames, public functions, routes, and storage model from the shared architecture.
- Import only functions that are listed in public_functions_by_file or visible in previous outputs.
- Do not invent alternate storage layers. If database.py exists in the architecture, logic.py must use it instead of independent JSON-file storage.
- requirements.txt must contain only pip-installable third-party packages. Never include sqlite3, json, os, sys, pathlib, typing, datetime, unittest, tkinter, zipfile, shutil, subprocess.
- If this task creates tests, tests must verify the original prompt and shared architecture.

OTHER AGENTS' OUTPUTS SO FAR:
"""
        
        for deliverable in self.state.deliverables:
            context += f"\n\n## {deliverable.agent_role.value}:"
            for output in deliverable.outputs:
                context += f"\n--- {output.filepath} ---\nexports: {output.exports}\nimports_from: {output.imports_from}\n"
                if output.language in {"python", "javascript", "html", "css", "sql", "json", "yaml", "text", "markdown"}:
                    context += output.code[:2500] + "\n"
        
        return context[:30000]
    
    def execute_project(self, project_contract: ProjectContract) -> bool:
        """
        Execute project with logging setup and cleanup.
        Overrides parent to add run logger setup.
        """
        # Set run logger project info
        self.run_logger.log.project_name = project_contract.project_name
        self.run_logger.log.project_description = project_contract.description
        
        try:
            # Execute with parent implementation
            success = super().execute_project(project_contract)
            
            # Finalize logging
            self.run_logger.finalize(success=success)
            
            return success
        except Exception as e:
            # Log error and finalize
            self.run_logger.log_error(str(e))
            self.run_logger.finalize(success=False)
            raise


# Factory for easy setup - NOW RETURNS WORKING ORCHESTRATOR
def create_orchestrator(project_root: Path, ai_client) -> ProductionOrchestrator:
    """
    Create fully configured, production-ready orchestrator.
    
    Returns ProductionOrchestrator which actually works (not abstract base).
    """
    return ProductionOrchestrator(
        project_root=project_root,
        ai_client=ai_client
    )


if __name__ == "__main__":
    # Example usage
    from pathlib import Path
    
    project_root = Path("./test_project")
    project_root.mkdir(exist_ok=True)
    
    orchestrator = create_orchestrator(project_root, None)
    
    contract = ProjectContract(
        project_name="Test App",
        description="A test application",
        required_agents=[AgentRole.GUI_BUILDER, AgentRole.BACKEND_LOGIC],
        expected_files={
            AgentRole.GUI_BUILDER: ["gui.py"],
            AgentRole.BACKEND_LOGIC: ["logic.py"]
        },
        integration_points=[]
    )
    
    # orchestrator.execute_project(contract)
    print("Orchestrator created successfully")
