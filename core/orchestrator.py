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
    run_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    
    def to_dict(self) -> dict:
        """Full serialization including deliverables"""
        return {
            "current_state": self.current_state.value,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "deliverables": [d.to_dict() for d in self.deliverables],
            "errors": self.errors,
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
            errors=data["errors"],
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
You are a project foreman. Break down this project into tasks.

Project: {project_contract.project_name}
Description: {project_contract.description}
Required Agents: {[a.value for a in project_contract.required_agents]}

For each agent, create a task specifying:
1. What files they should create
2. What they need from other agents
3. Order of execution

Return ONLY a JSON array (no markdown, no preamble):
[
    {{
        "agent_role": "gui_builder",
        "description": "Create main GUI",
        "files_to_create": ["gui.py"],
        "dependencies": []
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
        
        # Convert agent_role strings to enum
        for task in tasks:
            task['agent_role'] = AgentRole(task['agent_role'])
        
        return tasks
    
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
    
    def run_tests(self, test_files: List[str]) -> Dict[str, Any]:
        """
        Run all tests using pytest.
        
        Improvements:
        - Run entire suite once (not file-by-file)
        - Capture both stdout and stderr
        - Better error reporting
        """
        import subprocess
        
        if not test_files:
            return {"passed": 0, "failed": 0, "errors": [], "output": ""}
        
        results = {
            "passed": 0,
            "failed": 0,
            "errors": [],
            "output": ""
        }
        
        try:
            # Run all tests in one pytest invocation
            # PYTHONPATH must include the project root so generated modules can be imported
            import os as _os
            env = _os.environ.copy()
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(self.project_root) + (":" + existing if existing else "")

            result = subprocess.run(
                ["pytest"] + test_files + ["-v", "--tb=short"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=60,
                env=env
            )
            
            # Store full output (stdout + stderr for debugging)
            results["output"] = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
            
            # Parse pytest output for pass/fail counts
            # pytest returns 0 for success, non-zero for failures
            if result.returncode == 0:
                # All tests passed
                results["passed"] = len(test_files)
            else:
                # Some tests failed - try to parse output
                stdout = result.stdout
                
                # Look for "X passed" and "Y failed" in output
                import re
                passed_match = re.search(r'(\d+) passed', stdout)
                failed_match = re.search(r'(\d+) failed', stdout)
                
                if passed_match:
                    results["passed"] = int(passed_match.group(1))
                if failed_match:
                    results["failed"] = int(failed_match.group(1))
                else:
                    # Couldn't parse, assume all failed
                    results["failed"] = len(test_files)
                
                results["errors"].append(result.stderr or result.stdout)
        
        except subprocess.TimeoutExpired:
            results["failed"] = len(test_files)
            results["errors"].append("Tests timed out after 60 seconds")
        
        except Exception as e:
            results["failed"] = len(test_files)
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
            errors=[]
        )

        # Control events: set to signal the execution loop
        # _pause_event: cleared = paused, set = running
        # _cancel_event: set = cancel requested
        self._pause_event = threading.Event()
        self._pause_event.set()   # starts unpaused
        self._cancel_event = threading.Event()
    
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
            self.state.current_state = ExecutionState.PLANNING
            tasks = self.coordinator.plan_work(project_contract)
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

                self.state.current_step = i
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
                self.state.deliverables.append(deliverable)
                
                # Write files
                for output in deliverable.outputs:
                    self.file_manager.write_file(output)
                
                # Register wiring
                for wire in deliverable.wiring:
                    self.wiring_registry.register(wire)
            
            # Wiring verification phase
            from core.validation import WiringLinker
            linker = WiringLinker()
            link_result = linker.link_and_verify(self.state.deliverables)
            
            if not link_result.valid:
                self.state.errors.extend(link_result.errors)
                self.state.current_state = ExecutionState.FAILED
                self.state_manager.save(self.state)
                return False
            
            # Commit files (if SafeFileManager)
            if hasattr(self.file_manager, 'commit_all'):
                if not self.file_manager.commit_all():
                    self.state.errors.append("Failed to commit files")
                    self.state.current_state = ExecutionState.FAILED
                    self.state_manager.save(self.state)
                    return False
            
            # Testing phase
            self.state.current_state = ExecutionState.TESTING
            test_files = [
                tf for d in self.state.deliverables 
                for tf in d.tests_generated
            ]
            test_results = self.test_orchestrator.run_tests(test_files)
            
            if test_results["failed"] > 0:
                self.state.errors.append("Tests failed")
                # But continue anyway
            
            # Complete
            self.state.current_state = ExecutionState.COMPLETED
            self.state_manager.save(self.state)
            
            return True
        
        except Exception as e:
            self.state.current_state = ExecutionState.FAILED
            self.state.errors.append(str(e))
            self.state_manager.save(self.state)
            if hasattr(self.file_manager, 'rollback_all'):
                self.file_manager.rollback_all()
            else:
                self.file_manager.rollback()
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
        """Build context for agent execution"""
        context = f"""
Project: {task.get('project_name', 'Unknown')}
Description: {task.get('description', '')}

Other agents' outputs:
"""
        
        # Add info about what other agents created
        for deliverable in self.state.deliverables:
            context += f"\n{deliverable.agent_role.value}:"
            for output in deliverable.outputs:
                context += f"\n  - {output.filepath}: exports {output.exports}"
        
        return context
    
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
