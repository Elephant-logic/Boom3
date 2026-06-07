"""
Specialized Agent Implementations
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
        raw = response.choices[0].message.content
        self.last_raw_response = raw
        return raw

    def _parse_deliverable(self, ai_response: str) -> AgentDeliverable:
        data = self._extract_json(ai_response)
        if data is None:
            data = self._repair_json(ai_response)
        if data is None:
            raise ValueError(
                f"Agent {self.agent_id} returned unparseable JSON.\n"
                f"Preview: {ai_response[:500]}"
            )
        outputs = [
            CodeOutput(
                code=o['code'], filepath=o['filepath'], language=o['language'],
                dependencies=o.get('dependencies', []), exports=o.get('exports', []),
                imports_from=o.get('imports_from', {})
            )
            for o in data['outputs']
        ]
        wiring = [
            WiringContract(
                from_component=w['from_component'], from_symbol=w['from_symbol'],
                to_component=w['to_component'], to_symbol=w['to_symbol'],
                connection_type=w['connection_type'], parameters=w.get('parameters')
            )
            for w in data.get('wiring', [])
        ]
        return AgentDeliverable(
            agent_role=self.agent_role, outputs=outputs, wiring=wiring,
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
            "The following text was supposed to be valid JSON but failed to parse. "
            "Return ONLY the corrected JSON object, no markdown, no explanation.\n\n"
            f"Broken output:\n{bad_response[:3000]}"
        )
        try:
            repaired = self._call_ai(repair_prompt, temperature=0.0)
            return self._extract_json(repaired)
        except Exception:
            return None


class DatabaseManagerAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a Database Manager agent. Build a complete SQLite database layer for:

APPLICATION: {description}

REQUIRED EXPORTS — implement ALL FIVE exactly as specified:

1. connect() -> bool
   Open and immediately close a connection to verify it works. Return True/False.

2. execute_query(query: str, params: tuple = ()) -> Any
   - For SELECT queries: return list of dicts (column name -> value)
   - For INSERT/UPDATE/DELETE: commit and return lastrowid (for INSERT) or rowcount

3. save(table: str, data: dict) -> int
   INSERT a row. Return the new row id (integer >= 1), or -1 on error.

4. load(table: str, id: int) -> dict
   - If id == 0: return ALL rows as {{"records": [{{col: val, ...}}, ...]}}
   - If id > 0: return single row as {{col: val, ...}} or {{}} if not found

5. delete(table: str, id: int) -> bool
   DELETE row by id. Return True if deleted, False otherwise.

CRITICAL RULES:
- Use sqlite3 only. DATABASE_NAME = 'app.db'
- execute_query for SELECT must use cur.description to get column names and return list of dicts
- load(table, 0) MUST return {{"records": [...]}} — this is how the GUI loads all data
- No placeholders, no pass statements — full working code

Context: {context[:400]}

Return ONLY this JSON (no other text):
{{
    "outputs": [{{
        "code": "FULL_PYTHON_CODE_HERE",
        "filepath": "database.py",
        "language": "python",
        "dependencies": ["sqlite3"],
        "exports": ["connect", "execute_query", "save", "load", "delete"],
        "imports_from": {{}}
    }}],
    "wiring": [],
    "tests_generated": [],
    "documentation": "SQLite database layer"
}}
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Database agent deliverable failed validation")
        return deliverable


class BackendLogicAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a Backend Logic agent. Build complete business logic for:

APPLICATION: {description}

REQUIRED EXPORTS — implement ALL FOUR:

1. initialize_app() -> bool
   - Call connect() to verify database works
   - Call execute_query() to CREATE TABLE IF NOT EXISTS with columns appropriate for this app
   - Return True on success, False on any exception
   Example for expense tracker:
     execute_query("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL NOT NULL, category TEXT NOT NULL, date TEXT NOT NULL, notes TEXT)", ())

2. save_data(data: dict) -> bool
   - First call validate_input(data) — if invalid, print error and return False
   - Then call save("expenses", data) — if result > 0 return True, else False
   - Wrap in try/except, return False on exception

3. load_data() -> dict
   - Call load("expenses", 0) which returns {{"records": [...]}}
   - Return that dict directly
   - On exception return {{"records": []}}

4. validate_input(data: dict) -> tuple[bool, str]
   - If data is None or not a dict: return (False, "Input must be a dictionary")
   - If data is empty: return (False, "Input cannot be empty")
   - Check all required fields exist and have correct types for this app
   - Return (True, "") if valid, (False, "error message") if not

CRITICAL RULES:
- Import: from database import connect, execute_query, save, load, delete
- load_data() must call load("expenses", 0) with TWO arguments — not one
- save_data() must call save("expenses", data) with the table name
- No placeholders — full working code

Context: {context[:400]}

Return ONLY this JSON:
{{
    "outputs": [{{
        "code": "FULL_PYTHON_CODE_HERE",
        "filepath": "logic.py",
        "language": "python",
        "dependencies": [],
        "exports": ["initialize_app", "save_data", "load_data", "validate_input"],
        "imports_from": {{"database": ["connect", "execute_query", "save", "load", "delete"]}}
    }}],
    "wiring": [{{
        "from_component": "logic", "from_symbol": "save_data",
        "to_component": "database", "to_symbol": "save", "connection_type": "function_call"
    }}],
    "tests_generated": [],
    "documentation": "Backend logic layer"
}}
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Backend logic agent deliverable failed validation")
        return deliverable


class GUIBuilderAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a GUI Builder agent. Build a COMPLETE, FULLY FUNCTIONAL tkinter GUI for:

APPLICATION: {description}

REQUIRED EXPORTS:
- initialize_ui() -> tk.Tk  (creates window, does NOT call mainloop)
- run_ui() -> None           (calls initialize_ui() then window.mainloop())
- get_main_window() -> tk.Tk (returns _main_window global)

REQUIRED IMPORTS FROM logic:
  from logic import initialize_app, save_data, load_data, validate_input

BUILD THE ACTUAL APP UI — not a generic placeholder. Include:
- Input fields for every data field the app needs
- An "Add" / "Save" button that calls save_data() with a dict of the field values
- A ttk.Treeview table showing all records, loaded by calling load_data()
- A refresh function that clears and repopulates the Treeview
- Error popups using messagebox.showerror() for validation failures

CRITICAL RULES — these are the most common bugs, avoid them:
1. load_data() returns {{"records": [{{...}}, ...]}} — a DICT with key "records"
   To iterate records: data = load_data(); for item in data["records"]: ...
   WRONG: for item in load_data(): ...  ← this crashes
   CORRECT: for item in load_data()["records"]: ...

2. save_data() expects a dict where values match the database column types:
   - amount must be float(amount_entry.get()) not a string
   - Call float() / int() on numeric fields before putting them in the dict

3. validate_input() is already called inside save_data() — don't call it twice
   Just call save_data(data) and check the bool return

4. initialize_ui() must call initialize_app() at the start to create the DB table

5. No placeholders, no '...', no 'pass' — complete working code

Context: {context[:400]}

Return ONLY this JSON:
{{
    "outputs": [{{
        "code": "FULL_PYTHON_CODE_HERE",
        "filepath": "gui.py",
        "language": "python",
        "dependencies": ["tkinter"],
        "exports": ["initialize_ui", "run_ui", "get_main_window"],
        "imports_from": {{"logic": ["initialize_app", "save_data", "load_data", "validate_input"]}}
    }}],
    "wiring": [
        {{"from_component": "gui", "from_symbol": "save_button", "to_component": "logic", "to_symbol": "save_data", "connection_type": "function_call"}},
        {{"from_component": "gui", "from_symbol": "refresh_table", "to_component": "logic", "to_symbol": "load_data", "connection_type": "function_call"}}
    ],
    "tests_generated": [],
    "documentation": "Full GUI for {description}"
}}
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("GUI agent deliverable failed validation")
        return deliverable


class APIIntegratorAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are an API Integrator agent. Build API integration for:

APPLICATION: {description}

REQUIRED EXPORTS:
- authenticate() -> bool
- make_request(endpoint: str, method: str, data: dict) -> dict
- handle_rate_limit() -> None  (exponential backoff using time.sleep)
- get_health_status() -> bool

Use the requests library. Implement retry logic (max 3 attempts) in make_request().
All functions must have full implementations — no placeholders.

Context: {context[:400]}

Return ONLY this JSON:
{{
    "outputs": [{{
        "code": "FULL_PYTHON_CODE_HERE",
        "filepath": "api_integration.py",
        "language": "python",
        "dependencies": ["requests"],
        "exports": ["authenticate", "make_request", "handle_rate_limit", "get_health_status"],
        "imports_from": {{}}
    }}],
    "wiring": [],
    "tests_generated": [],
    "documentation": "API integration layer"
}}
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("API agent deliverable failed validation")
        return deliverable


class TestEngineerAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a Test Engineer agent. Write pytest tests for:

APPLICATION: {description}

CRITICAL IMPORT RULES — follow exactly:
- CORRECT:  from logic import initialize_app, save_data, load_data, validate_input
- WRONG:    from backend_logic.logic import ...
- WRONG:    from myapp.logic import ...
All files are in the SAME flat directory. Never use package paths.

WHAT TO TEST in test_logic.py:

1. test_initialize_app()
   Mock database.connect and database.execute_query to return success.
   Assert initialize_app() returns True.

2. test_save_data_valid()
   Mock database.save to return 1.
   Pass valid data dict (with all required fields for this app).
   Assert save_data(valid_data) is True.

3. test_save_data_invalid_none()
   Assert save_data(None) is False (no mock needed, validate_input catches it).

4. test_save_data_empty_dict()
   Assert save_data({{}}) is False.

5. test_load_data()
   Mock database.load to return {{"records": [{{"id": 1, "amount": 10.0}}]}}.
   Assert "records" in load_data().

6. test_validate_input_valid()
   Pass a complete valid dict. Assert returns (True, "").

7. test_validate_input_none()
   Assert validate_input(None) returns (False, <non-empty string>).

8. test_validate_input_empty()
   Assert validate_input({{}}) returns (False, <non-empty string>).

9. test_validate_input_missing_field()
   Pass dict missing one required field. Assert returns (False, <non-empty string>).

HOW TO MOCK — CRITICAL RULE:
  When logic.py uses `from database import connect, save, load` (star imports),
  those names are NOT attributes of the logic module. You MUST patch them on the
  database module instead:
  @patch('database.connect')
  @patch('database.save')
  @patch('database.load')
  @patch('database.execute_query')

  NEVER use @patch('logic.connect') or @patch('logic.save') — these will always
  fail with AttributeError because logic.py imports from database, it doesn't
  define these functions itself.

Context: {context[:400]}

Return ONLY this JSON:
{{
    "outputs": [{{
        "code": "FULL_PYTHON_CODE_HERE",
        "filepath": "test_logic.py",
        "language": "python",
        "dependencies": ["pytest"],
        "exports": [],
        "imports_from": {{"logic": ["initialize_app", "save_data", "load_data", "validate_input"]}}
    }}],
    "wiring": [],
    "tests_generated": ["test_logic.py"],
    "documentation": "Test suite"
}}
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Test agent deliverable failed validation")
        return deliverable


class WiringEngineerAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        description = task.get('description', '')
        prompt = f"""
You are a Wiring Engineer. Create the entry point for:

APPLICATION: {description}

Create two files:

1. main.py — must contain:
   from gui import initialize_ui, run_ui, get_main_window
   from logic import initialize_app
   from database import connect

   def main() -> None:
       if not initialize_app():
           print("Failed to initialize")
           return
       run_ui()

   if __name__ == "__main__":
       main()

   NOTE: initialize_app() already calls connect() internally, so no need to call connect() separately.
   run_ui() calls initialize_ui() then mainloop() — so just call run_ui().

2. __init__.py — just a comment: # Package initialization

Context: {context[:400]}

Return ONLY this JSON:
{{
    "outputs": [
        {{
            "code": "FULL_MAIN_PY_CODE",
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
        {{"from_component": "main", "from_symbol": "main", "to_component": "gui", "to_symbol": "run_ui", "connection_type": "function_call"}},
        {{"from_component": "main", "from_symbol": "main", "to_component": "logic", "to_symbol": "initialize_app", "connection_type": "function_call"}}
    ],
    "tests_generated": [],
    "documentation": "Entry point"
}}
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError("Wiring agent deliverable failed validation")
        return deliverable


def create_agent(agent_role: AgentRole, ai_client: OpenAI) -> BaseAgent:
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
