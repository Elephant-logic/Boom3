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
        self.last_raw_response = None
    
    @abstractmethod
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        pass
    
    def _call_ai(self, prompt: str, temperature: float = 0.3) -> str:
        contract = generate_agent_contract(self.agent_role)
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
        raw_response = response.choices[0].message.content
        self.last_raw_response = raw_response
        return raw_response
    
    def _parse_deliverable(self, ai_response: str) -> AgentDeliverable:
        data = self._extract_json(ai_response)
        if data is None:
            data = self._repair_json(ai_response)
        if data is None:
            raise ValueError(
                f"Agent {self.agent_id} returned unparseable JSON after repair attempt.\n"
                f"Raw response (first 500 chars): {ai_response[:500]}"
            )
        
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

    def _extract_json(self, text: str) -> Optional[dict]:
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass

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
    """Builds user interfaces following strict contracts"""
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a GUI Builder agent. Your job is to build a COMPLETE, FULLY FUNCTIONAL tkinter GUI
for the specific application described below. Do NOT produce a generic placeholder UI.

APPLICATION DESCRIPTION:
{description}

CRITICAL REQUIREMENTS — READ CAREFULLY:
1. Build the ACTUAL UI for this specific app. If it's an expense tracker, build expense tracker
   UI with input fields for amount, category, date, a table/listbox showing all expenses,
   totals, etc. If it's a todo app, build todo UI. Match the description exactly.
2. Every button must call a real function from logic.py (save_data, load_data, etc.)
3. Show data in a ttk.Treeview table so the user can see their records
4. Include proper labels, entry fields, dropdowns for every data field needed
5. The UI must be complete enough that a user could actually use the app

REQUIRED EXPORTS (implement ALL THREE):
  - initialize_ui() -> tk.Tk   — creates and returns the main window (do NOT call mainloop)
  - run_ui() -> None           — calls initialize_ui() then mainloop()
  - get_main_window() -> tk.Tk — returns the existing window

REQUIRED IMPORTS FROM logic:
  - initialize_app, save_data, load_data, validate_input

DATABASE SETUP NOTE:
At the top of initialize_ui(), call initialize_app() which sets up the database.
Also call load_data() to populate the table on startup.

Context from other agents:
{context[:800]}

OUTPUT SCHEMA — return ONLY this JSON, no other text:
{{
    "outputs": [
        {{
            "code": "import tkinter as tk\\nfrom tkinter import ttk, messagebox\\nfrom logic import initialize_app, save_data, load_data, validate_input\\n\\n_main_window = None\\n\\ndef initialize_ui() -> tk.Tk:\\n    # FULL IMPLEMENTATION HERE - not a placeholder\\n    ...",
            "filepath": "gui.py",
            "language": "python",
            "dependencies": ["tkinter"],
            "exports": ["initialize_ui", "run_ui", "get_main_window"],
            "imports_from": {{"logic": ["initialize_app", "save_data", "load_data", "validate_input"]}}
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
    "documentation": "Full GUI implementation for {description}"
}}

Write COMPLETE, WORKING Python code. No placeholders, no '...', no 'pass'.
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        return deliverable


class BackendLogicAgent(BaseAgent):
    """Builds backend logic following strict contracts"""
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a Backend Logic agent. Build COMPLETE, APP-SPECIFIC business logic for:

APPLICATION DESCRIPTION:
{description}

REQUIRED EXPORTS (implement ALL FOUR with full logic for this specific app):
  - initialize_app() -> bool
      Must call connect() AND create any needed database tables using execute_query().
      For example for an expense tracker, create the expenses table with columns:
      id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, date TEXT, description TEXT
  - save_data(data: dict) -> bool
      Validate input first using validate_input(). Then call save() to persist.
  - load_data() -> dict
      Load ALL records from the database. Return as dict with key "records" containing a list.
  - validate_input(data: dict) -> tuple[bool, str]
      Validate all required fields for THIS specific app. Return (True, "") or (False, "error message").

REQUIRED IMPORTS FROM database:
  - connect, execute_query, save, load, delete

IMPORTANT — initialize_app() MUST create the table:
  execute_query(
      "CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, date TEXT, notes TEXT)",
      ()
  )
  (adjust table/columns to match the app description)

Context:
{context[:800]}

OUTPUT SCHEMA — return ONLY this JSON:
{{
    "outputs": [
        {{
            "code": "from database import connect, execute_query, save, load, delete\\n\\ndef initialize_app() -> bool:\\n    # FULL IMPLEMENTATION\\n    ...",
            "filepath": "logic.py",
            "language": "python",
            "dependencies": [],
            "exports": ["initialize_app", "save_data", "load_data", "validate_input"],
            "imports_from": {{"database": ["connect", "execute_query", "save", "load", "delete"]}}
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
    "documentation": "Backend logic for {description}"
}}

Write COMPLETE code. No placeholders.
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        return deliverable


class DatabaseManagerAgent(BaseAgent):
    """Manages data persistence following strict contracts"""
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a Database Manager agent. Build a complete SQLite database layer for:

APPLICATION DESCRIPTION:
{description}

REQUIRED EXPORTS (implement ALL FIVE):
  - connect() -> bool
  - execute_query(query: str, params: tuple) -> Any
      Must handle both SELECT (return rows) and INSERT/UPDATE/DELETE (commit and return rowcount/lastrowid)
  - save(table: str, data: dict) -> int
      Insert a record, return the new row ID (or -1 on error)
  - load(table: str, id: int) -> dict
      Load one record by ID. Also support load(table, 0) to return ALL records as a list under key "records"
  - delete(table: str, id: int) -> bool

IMPORTANT for load(): when id == 0, return ALL rows:
  if id == 0:
      cur.execute(f"SELECT * FROM {{table}}")
      rows = cur.fetchall()
      columns = [col[0] for col in cur.description]
      return {{"records": [dict(zip(columns, row)) for row in rows]}}

Context:
{context[:800]}

OUTPUT SCHEMA — return ONLY this JSON:
{{
    "outputs": [
        {{
            "code": "import sqlite3\\nfrom typing import Any\\n\\nDATABASE_NAME = 'app.db'\\n\\ndef connect() -> bool:\\n    ...",
            "filepath": "database.py",
            "language": "python",
            "dependencies": ["sqlite3"],
            "exports": ["connect", "execute_query", "save", "load", "delete"],
            "imports_from": {{}}
        }}
    ],
    "wiring": [],
    "tests_generated": [],
    "documentation": "SQLite database layer for {description}"
}}

Write COMPLETE code. No placeholders.
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        return deliverable


class APIIntegratorAgent(BaseAgent):
    """Integrates external APIs following strict contracts"""
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are an API Integrator agent. Build API integration code for:

APPLICATION DESCRIPTION:
{description}

REQUIRED EXPORTS:
  - authenticate() -> bool
  - make_request(endpoint: str, method: str, data: dict) -> dict
  - handle_rate_limit() -> None
  - get_health_status() -> bool

All functions must have real implementations with retry logic and error handling.
Use the requests library. Implement exponential backoff in handle_rate_limit().

Context:
{context[:800]}

OUTPUT SCHEMA — return ONLY this JSON:
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
    "documentation": "API integration for {description}"
}}

Write COMPLETE code. No placeholders.
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        return deliverable


class TestEngineerAgent(BaseAgent):
    """Generates comprehensive tests"""
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a Test Engineer agent. Write pytest tests for:

APPLICATION DESCRIPTION:
{description}

CRITICAL IMPORT RULE:
Import directly from the module files — NOT from packages.
CORRECT:   from logic import initialize_app, save_data, load_data, validate_input
WRONG:     from backend_logic.logic import ...
WRONG:     from myapp.logic import ...

The files logic.py, database.py, gui.py are all in the same flat directory.
Always use: from logic import ...  from database import ...  etc.

Write tests for logic.py covering:
- initialize_app() — should return True
- save_data() — happy path, invalid data, edge cases
- load_data() — should return dict with "records" key
- validate_input() — valid data, missing fields, wrong types, empty dict, None

Use pytest fixtures. Mock database calls where needed using unittest.mock.

OUTPUT SCHEMA — return ONLY this JSON:
{{
    "outputs": [
        {{
            "code": "import pytest\\nfrom unittest.mock import patch, MagicMock\\nfrom logic import initialize_app, save_data, load_data, validate_input\\n\\n# FULL TEST IMPLEMENTATIONS\\n...",
            "filepath": "test_logic.py",
            "language": "python",
            "dependencies": ["pytest"],
            "exports": [],
            "imports_from": {{"logic": ["initialize_app", "save_data", "load_data", "validate_input"]}}
        }}
    ],
    "wiring": [],
    "tests_generated": ["test_logic.py"],
    "documentation": "Test suite for {description}"
}}

Write COMPLETE tests. No placeholders.
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        return deliverable


class WiringEngineerAgent(BaseAgent):
    """Connects all components"""
    
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a Wiring Engineer agent. Create the entry point for:

APPLICATION DESCRIPTION:
{description}

REQUIRED FILES:
  - main.py — application entry point with main() function
  - __init__.py — empty package init

main() must:
1. Call initialize_app() — sets up DB and creates tables
2. Call connect() — connects to database  
3. Call run_ui() — starts the GUI (this blocks until window closes)

REQUIRED EXPORTS: main()

Context:
{context[:800]}

OUTPUT SCHEMA — return ONLY this JSON:
{{
    "outputs": [
        {{
            "code": "from gui import initialize_ui, run_ui, get_main_window\\nfrom logic import initialize_app\\nfrom database import connect\\n\\ndef main() -> None:\\n    if not initialize_app():\\n        print('Failed to initialize')\\n        return\\n    run_ui()\\n\\nif __name__ == '__main__':\\n    main()\\n",
            "filepath": "main.py",
            "language": "python",
            "dependencies": [],
            "exports": ["main"],
            "imports_from": {{"gui": ["initialize_ui", "run_ui", "get_main_window"], "logic": ["initialize_app"], "database": ["connect"]}}
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
            "to_symbol": "run_ui",
            "connection_type": "function_call"
        }}
    ],
    "tests_generated": [],
    "documentation": "Entry point wiring for {description}"
}}

Write COMPLETE code.
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Agent deliverable failed contract validation")
        return deliverable


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
