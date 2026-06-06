"""
Specialized Agent Implementations

Each agent follows strict contracts and implements the BaseAgent interface.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from openai import OpenAI
import json
import os
import re

from contracts.agent_contracts import (
    AgentRole, CodeOutput, WiringContract, 
    AgentDeliverable, generate_agent_contract
)


class BaseAgent(ABC):
    """Base class all agents must inherit from"""
    
    def __init__(self, agent_id: str, agent_role: AgentRole, ai_client: OpenAI):
        self.agent_id = agent_id
        self.agent_role = agent_role
        self.ai_client = ai_client
        self.last_raw_response = None  # Store last raw response for logging
    
    @abstractmethod
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        """Execute a task and return validated deliverable"""
        pass
    
    def _call_ai(self, prompt: str, temperature: float = 0.3) -> str:
        """Make AI call with contract enforcement"""
        contract = generate_agent_contract(self.agent_role)
        
        # Model is env-configurable; per-agent override supported via BOOM3_MODEL_<ROLE>
        default_model = os.environ.get("BOOM3_MODEL", "gpt-4o")
        role_env_key = f"BOOM3_MODEL_{self.agent_role.value.upper()}"
        model = os.environ.get(role_env_key, default_model)

        response = self.ai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": contract},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature
        )
        
        # Capture raw response for logging
        raw_response = response.choices[0].message.content
        self.last_raw_response = raw_response
        
        return raw_response
    
    def _parse_deliverable(self, ai_response: str) -> AgentDeliverable:
        """Parse AI response into deliverable with robust fallback repair"""
        data = self._extract_json(ai_response)
        if data is None:
            # Repair strategy: ask the model to fix its own output
            data = self._repair_json(ai_response)
        if data is None:
            raise ValueError(
                f"Agent {self.agent_id} returned unparseable JSON after repair attempt.\n"
                f"Raw response (first 500 chars): {ai_response[:500]}"
            )
        
        # Build deliverable
        outputs = [
            CodeOutput(
                code=o['code'],
                filepath=o['filepath'],
                language=o['language'],
                dependencies=o.get('dependencies', []),
                exports=o.get('exports', []),
                imports_from=o.get('imports_from', {})
            )
            for o in data['outputs']
        ]
        
        wiring = [
            WiringContract(
                from_component=w['from_component'],
                from_symbol=w['from_symbol'],
                to_component=w['to_component'],
                to_symbol=w['to_symbol'],
                connection_type=w['connection_type'],
                parameters=w.get('parameters')
            )
            for w in data.get('wiring', [])
        ]
        
        return AgentDeliverable(
            agent_role=self.agent_role,
            outputs=outputs,
            wiring=wiring,
            tests_generated=data.get('tests_generated', []),
            documentation=data.get('documentation', '')
        )

    # ------------------------------------------------------------------
    # JSON extraction helpers
    # ------------------------------------------------------------------

    def _extract_json(self, text: str) -> Optional[dict]:
        """
        Try to extract a JSON object from raw AI text.
        Handles fenced json blocks, bare JSON, and trailing prose.
        Returns None on any parse failure.
        """
        # 1. Fenced block
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass

        # 2. Find outermost { ... }
        start = text.find('{')
        if start != -1:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break

        return None

    def _repair_json(self, bad_response: str) -> Optional[dict]:
        """
        Ask the model to repair its own malformed JSON output.
        Makes one additional API call; returns None if still unparseable.
        """
        repair_prompt = (
            "The following text was supposed to be valid JSON matching a specific schema, "
            "but it failed to parse. Please return ONLY the corrected JSON object with no "
            "additional text, markdown, or explanation.\n\n"
            f"Broken output:\n{bad_response[:3000]}"
        )
        try:
            repaired = self._call_ai(repair_prompt, temperature=0.0)
            return self._extract_json(repaired)
        except Exception:
            return None


class GUIBuilderAgent(BaseAgent):
    """Builds user interfaces following strict GUI contracts"""
    
    DELIVERABLE_SPEC = {
        "required_files": ["gui.py"],
        "required_exports": ["initialize_ui", "run_ui", "get_main_window"],
        "required_imports": {
            "logic": ["initialize_app", "save_data", "load_data"]
        },
        "done_means": [
            "gui.py created with valid Python syntax",
            "All three exports present and callable",
            "All imports from logic documented in imports_from",
            "Wiring to backend documented in wiring array",
            "Uses tkinter or ttkbootstrap for UI"
        ]
    }
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = f"""
You are a GUI Builder agent with STRICT REQUIREMENTS.

DELIVERABLE SPECIFICATION (NON-NEGOTIABLE):
Files you MUST create:
  - gui.py (and ONLY gui.py)

Functions you MUST export:
  - initialize_ui() -> tk.Tk
  - run_ui() -> None  
  - get_main_window() -> tk.Tk

Functions you MUST import from logic:
  - initialize_app() -> bool
  - save_data(data: dict) -> bool
  - load_data() -> dict

DONE MEANS:
✓ gui.py exists
✓ All 3 exports implemented
✓ All 3 imports documented
✓ Wiring documented (button → logic.save_data, etc.)
✓ Uses tkinter/ttkbootstrap
✓ No syntax errors

Requirements:
{task.get('description', '')}

Context:
{context[:1000]}

OUTPUT SCHEMA (MUST MATCH EXACTLY):
{{
    "outputs": [
        {{
            "code": "import tkinter as tk\\nfrom logic import initialize_app, save_data, load_data\\n\\ndef initialize_ui():\\n    ...",
            "filepath": "gui.py",
            "language": "python",
            "dependencies": ["tkinter"],
            "exports": ["initialize_ui", "run_ui", "get_main_window"],
            "imports_from": {{"logic": ["initialize_app", "save_data", "load_data"]}}
        }}
    ],
    "wiring": [
        {{
            "from_component": "gui",
            "from_symbol": "save_button",
            "to_component": "logic",
            "to_symbol": "save_data",
            "connection_type": "function_call"
        }}
    ],
    "tests_generated": [],
    "documentation": "Created GUI with main window, initialize, and run functions"
}}

If your output doesn't match this EXACTLY, it will be REJECTED.
Generate the GUI code now.
"""
        
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        
        # Validate deliverable meets contract
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        
        return deliverable


class BackendLogicAgent(BaseAgent):
    """Builds backend logic following strict contracts"""
    
    DELIVERABLE_SPEC = {
        "required_files": ["logic.py"],
        "required_exports": ["initialize_app", "save_data", "load_data", "validate_input"],
        "required_imports": {
            "database": ["connect", "save", "load"]
        },
        "done_means": [
            "logic.py created with valid Python syntax",
            "All four exports implemented",
            "Database imports documented",
            "Error handling in all functions",
            "Type hints on all functions"
        ]
    }
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = f"""
You are a Backend Logic agent with STRICT REQUIREMENTS.

DELIVERABLE SPECIFICATION (NON-NEGOTIABLE):
Files you MUST create:
  - logic.py (and ONLY logic.py)

Functions you MUST export:
  - initialize_app() -> bool
  - save_data(data: dict) -> bool
  - load_data() -> dict
  - validate_input(data: dict) -> tuple[bool, str]

Functions you MUST import from database:
  - connect() -> bool
  - save(table: str, data: dict) -> int
  - load(table: str, id: int) -> dict

DONE MEANS:
✓ logic.py exists
✓ All 4 exports implemented with type hints
✓ Database imports documented
✓ Comprehensive error handling (try/except)
✓ Input validation logic
✓ No syntax errors

Requirements:
{task.get('description', '')}

Context:
{context[:1000]}

OUTPUT SCHEMA (MUST MATCH EXACTLY):
{{
    "outputs": [
        {{
            "code": "from database import connect, save, load\\n\\ndef initialize_app() -> bool:\\n    ...",
            "filepath": "logic.py",
            "language": "python",
            "dependencies": [],
            "exports": ["initialize_app", "save_data", "load_data", "validate_input"],
            "imports_from": {{"database": ["connect", "save", "load"]}}
        }}
    ],
    "wiring": [
        {{
            "from_component": "logic",
            "from_symbol": "save_data",
            "to_component": "database",
            "to_symbol": "save",
            "connection_type": "function_call"
        }}
    ],
    "tests_generated": [],
    "documentation": "Created backend logic with data operations and validation"
}}

If your output doesn't match this EXACTLY, it will be REJECTED.
Generate the backend code now.
"""
        
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        
        return deliverable


class DatabaseManagerAgent(BaseAgent):
    """Manages data persistence following strict contracts"""
    
    DELIVERABLE_SPEC = {
        "required_files": ["database.py"],
        "required_exports": ["connect", "execute_query", "save", "load", "delete"],
        "done_means": [
            "database.py created",
            "All 5 exports implemented",
            "Uses SQLite as default",
            "Connection pooling/management",
            "Error handling for all operations"
        ]
    }
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = f"""
You are a Database Manager agent with STRICT REQUIREMENTS.

DELIVERABLE SPECIFICATION (NON-NEGOTIABLE):
Files you MUST create:
  - database.py (and ONLY database.py)

Functions you MUST export:
  - connect() -> bool
  - execute_query(query: str, params: tuple) -> Any
  - save(table: str, data: dict) -> int
  - load(table: str, id: int) -> dict
  - delete(table: str, id: int) -> bool

DONE MEANS:
✓ database.py exists
✓ All 5 exports implemented
✓ Uses SQLite (import sqlite3)
✓ Connection management (open/close properly)
✓ Parameterized queries (no SQL injection)
✓ Error handling
✓ No syntax errors

Requirements:
{task.get('description', '')}

Context:
{context[:1000]}

OUTPUT SCHEMA (MUST MATCH EXACTLY):
{{
    "outputs": [
        {{
            "code": "import sqlite3\\nfrom typing import Any\\n\\ndef connect() -> bool:\\n    ...",
            "filepath": "database.py",
            "language": "python",
            "dependencies": ["sqlite3"],
            "exports": ["connect", "execute_query", "save", "load", "delete"],
            "imports_from": {{}}
        }}
    ],
    "wiring": [],
    "tests_generated": [],
    "documentation": "Created SQLite database layer with CRUD operations"
}}

If your output doesn't match this EXACTLY, it will be REJECTED.
Generate the database code now.
"""
        
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        
        return deliverable


class APIIntegratorAgent(BaseAgent):
    """Integrates external APIs following strict contracts"""
    
    DELIVERABLE_SPEC = {
        "required_files": ["api_integration.py"],
        "required_exports": ["authenticate", "make_request", "handle_rate_limit", "get_health_status"],
        "done_means": [
            "api_integration.py created",
            "All exports implemented",
            "Retry logic included",
            "Rate limiting handled",
            "Error handling for network issues"
        ]
    }
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = f"""
You are an API Integrator agent with STRICT REQUIREMENTS.

DELIVERABLE SPECIFICATION (NON-NEGOTIABLE):
Files you MUST create:
  - api_integration.py (and ONLY this file)

Functions you MUST export:
  - authenticate() -> bool
  - make_request(endpoint: str, method: str, data: dict) -> dict
  - handle_rate_limit() -> None
  - get_health_status() -> bool

DONE MEANS:
✓ api_integration.py exists
✓ All 4 exports implemented
✓ Uses requests library
✓ Retry logic (max 3 attempts)
✓ Rate limiting (exponential backoff)
✓ Error handling for network issues
✓ No syntax errors

Requirements:
{task.get('description', '')}

Context:
{context[:1000]}

OUTPUT SCHEMA (MUST MATCH EXACTLY):
{{
    "outputs": [
        {{
            "code": "import requests\\nimport time\\n\\ndef authenticate() -> bool:\\n    ...",
            "filepath": "api_integration.py",
            "language": "python",
            "dependencies": ["requests"],
            "exports": ["authenticate", "make_request", "handle_rate_limit", "get_health_status"],
            "imports_from": {{}}
        }}
    ],
    "wiring": [],
    "tests_generated": [],
    "documentation": "Created API integration layer with retry and rate limiting"
}}

If your output doesn't match this EXACTLY, it will be REJECTED.
Generate the API integration code now.
"""
        
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        
        return deliverable


class TestEngineerAgent(BaseAgent):
    """Generates comprehensive tests following strict contracts"""
    
    DELIVERABLE_SPEC = {
        "required_files": ["test_*.py"],
        "required_exports": [],  # Tests don't export
        "done_means": [
            "Test files created for each component",
            "Uses pytest framework",
            "Tests happy paths",
            "Tests error cases",
            "Tests edge cases",
            "Fixtures and mocks as needed"
        ]
    }
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = f"""
You are a Test Engineer agent with STRICT REQUIREMENTS.

DELIVERABLE SPECIFICATION (NON-NEGOTIABLE):
Files you MUST create:
  - test_*.py files (one per component being tested)
  - conftest.py (if fixtures needed)

Test Requirements:
  - Use pytest framework
  - Test happy paths (normal operation)
  - Test error cases (invalid input)
  - Test edge cases (empty, None, large values)
  - Use fixtures for setup/teardown
  - Use mocks for external dependencies

DONE MEANS:
✓ All test files created
✓ Uses pytest syntax
✓ Comprehensive coverage
✓ Tests are runnable
✓ No syntax errors

Requirements:
{task.get('description', '')}

Files to test:
{task.get('files_to_test', [])}

Context:
{context[:1000]}

OUTPUT SCHEMA (MUST MATCH EXACTLY):
{{
    "outputs": [
        {{
            "code": "import pytest\\n\\ndef test_happy_path():\\n    assert True\\n\\ndef test_error_case():\\n    ...",
            "filepath": "test_component.py",
            "language": "python",
            "dependencies": ["pytest"],
            "exports": [],
            "imports_from": {{"component": ["function_to_test"]}}
        }}
    ],
    "wiring": [],
    "tests_generated": ["test_component.py"],
    "documentation": "Created comprehensive test suite"
}}

If your output doesn't match this EXACTLY, it will be REJECTED.
Generate the tests now.
"""
        
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        
        return deliverable


class WiringEngineerAgent(BaseAgent):
    """Connects all components following strict contracts"""
    
    DELIVERABLE_SPEC = {
        "required_files": ["main.py", "__init__.py"],
        "required_exports": ["main"],
        "done_means": [
            "main.py created",
            "__init__.py created",
            "All imports correct",
            "Initialization order correct",
            "Entry point defined",
            "Complete wiring documented"
        ]
    }
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = f"""
You are a Wiring Engineer agent with STRICT REQUIREMENTS.

DELIVERABLE SPECIFICATION (NON-NEGOTIABLE):
Files you MUST create:
  - main.py (application entry point)
  - __init__.py (package initialization)

Functions you MUST export:
  - main() -> None

DONE MEANS:
✓ main.py exists with main() function
✓ __init__.py exists
✓ All components imported
✓ Correct initialization order
✓ All wiring connections documented
✓ if __name__ == "__main__": main() at bottom
✓ No syntax errors

Requirements:
{task.get('description', '')}

Components to wire:
{task.get('components', [])}

Context:
{context[:1000]}

OUTPUT SCHEMA (MUST MATCH EXACTLY):
{{
    "outputs": [
        {{
            "code": "from gui import initialize_ui, run_ui\\nfrom logic import initialize_app\\n\\ndef main():\\n    ...",
            "filepath": "main.py",
            "language": "python",
            "dependencies": [],
            "exports": ["main"],
            "imports_from": {{"gui": ["initialize_ui", "run_ui"], "logic": ["initialize_app"]}}
        }},
        {{
            "code": "# Package initialization\\n",
            "filepath": "__init__.py",
            "language": "python",
            "dependencies": [],
            "exports": [],
            "imports_from": {{}}
        }}
    ],
    "wiring": [
        {{
            "from_component": "main",
            "from_symbol": "main",
            "to_component": "gui",
            "to_symbol": "initialize_ui",
            "connection_type": "function_call"
        }}
    ],
    "tests_generated": [],
    "documentation": "Created main entry point and wired all components together"
}}

CRITICAL: Document ALL connections in the wiring array!
If your output doesn't match this EXACTLY, it will be REJECTED.
Generate the wiring code now.
"""
        
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        
        return deliverable


# Agent factory
def create_agent(agent_role: AgentRole, ai_client: OpenAI) -> BaseAgent:
    """Factory to create appropriate agent"""
    agents = {
        AgentRole.GUI_BUILDER: GUIBuilderAgent,
        AgentRole.BACKEND_LOGIC: BackendLogicAgent,
        AgentRole.DATABASE_MANAGER: DatabaseManagerAgent,
        AgentRole.API_INTEGRATOR: APIIntegratorAgent,
        AgentRole.TEST_ENGINEER: TestEngineerAgent,
        AgentRole.WIRING_ENGINEER: WiringEngineerAgent,
    }
    
    agent_class = agents.get(agent_role)
    if not agent_class:
        raise ValueError(f"Unknown agent role: {agent_role}")
    
    agent_id = f"{agent_role.value}_{id(agent_class)}"
    return agent_class(agent_id, agent_role, ai_client)


if __name__ == "__main__":
    # Example usage
    from openai import OpenAI
    
    client = OpenAI()
    
    # Create a GUI agent
    gui_agent = create_agent(AgentRole.GUI_BUILDER, client)
    
    # Example task
    task = {
        "description": "Create a simple calculator GUI with buttons for +, -, *, /"
    }
    
    # Execute (would need real API key)
    # deliverable = gui_agent.execute_task(task, "Building a calculator app")
    # print(f"Generated {len(deliverable.outputs)} files")
