"""
Specialized Agent Implementations

This version removes the old hard-coded toy tkinter/expense-tracker prompts.
Agents now generate prompt-specific web/SaaS application files and the later
compliance gate decides whether the generated project actually satisfies the
original user request.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
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

    def _call_ai(self, prompt: str, temperature: float = 0.25) -> str:
        contract = generate_agent_contract(self.agent_role)
        default_model = os.environ.get("BOOM3_MODEL", "gpt-4o")
        role_env_key = f"BOOM3_MODEL_{self.agent_role.value.upper()}"
        model = os.environ.get(role_env_key, default_model)
        response = self.ai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": contract},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
        raw = response.choices[0].message.content or ""
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
                code=o["code"],
                filepath=o["filepath"],
                language=o["language"],
                dependencies=o.get("dependencies", []),
                exports=o.get("exports", []),
                imports_from=o.get("imports_from", {}),
            )
            for o in data["outputs"]
        ]
        wiring = [
            WiringContract(
                from_component=w["from_component"],
                from_symbol=w["from_symbol"],
                to_component=w["to_component"],
                to_symbol=w["to_symbol"],
                connection_type=w["connection_type"],
                parameters=w.get("parameters"),
            )
            for w in data.get("wiring", [])
        ]
        return AgentDeliverable(
            agent_role=self.agent_role,
            outputs=outputs,
            wiring=wiring,
            tests_generated=data.get("tests_generated", []),
            documentation=data.get("documentation", ""),
        )

    def _extract_json(self, text: str) -> Optional[dict]:
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass
        start = text.find("{")
        if start != -1:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
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
            f"Broken output:\n{bad_response[:6000]}"
        )
        try:
            repaired = self._call_ai(repair_prompt, temperature=0.0)
            return self._extract_json(repaired)
        except Exception:
            return None

    def _prompt_contract(self, purpose: str, task: Dict[str, Any], context: str, examples: str) -> str:
        description = task.get("description", "")
        return f"""
You are the {self.agent_role.value} agent for Boom3.

PURPOSE: {purpose}

PROJECT/TASK DESCRIPTION:
{description}

FULL PROJECT CONTEXT:
{context[:9000]}

IMPORTANT QUALITY BAR:
- Build the actual requested app, not a toy placeholder.
- If the user asked for a Lovable/Bolt/Replit-style app builder, generate an app-builder product with file explorer, code editor UI, live logs, project API, test runner/repair UI, and download/deploy affordances.
- Use Flask + SQLite + vanilla HTML/CSS/JS unless the prompt clearly asks for something else.
- Keep files runnable on Render/free Linux: simple dependencies, no Docker requirement for generated app runtime.
- Include realistic behaviour and validations. Avoid pass, TODO, placeholder-only features, fake buttons that do nothing, or tests that merely test mocks.
- Return multiple useful files when needed.

Return ONLY JSON, no markdown, in this exact shape:
{{
  "outputs": [
    {{
      "filepath": "relative/path.ext",
      "language": "python|javascript|html|css|sql|markdown|text|yaml|json",
      "code": "complete file contents",
      "dependencies": [],
      "exports": [],
      "imports_from": {{}}
    }}
  ],
  "wiring": [
    {{"from_component":"name","from_symbol":"symbol","to_component":"name","to_symbol":"symbol","connection_type":"function_call"}}
  ],
  "tests_generated": [],
  "documentation": "what this agent built"
}}

FILE EXAMPLES/EXPECTATIONS FOR THIS AGENT:
{examples}
"""


class GUIBuilderAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = self._prompt_contract(
            "Create the user-facing web UI.",
            task,
            context,
            """
Create at least:
- templates/index.html with real screens/components matching the requested app
- static/styles.css with responsive layout
- static/app.js with API calls, live log rendering, form handling, and change-request/download actions where relevant
Optional compatibility file gui.py may be included if useful.
For an app-builder prompt, the UI must include: prompt input, project list, file explorer, code editor area, live logs, tests panel, repair/change box, download button, deploy instructions panel.
""",
        )
        deliverable = self._parse_deliverable(self._call_ai(prompt))
        if not deliverable.validate():
            raise ValueError("GUI agent deliverable failed validation")
        return deliverable


class BackendLogicAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = self._prompt_contract(
            "Create application business logic/services.",
            task,
            context,
            """
Create at least logic.py and/or services.py containing real domain functions used by the app.
For an app-builder prompt, include functions for project creation, file generation state, test status, repair requests, file listing, and zip creation helpers.
Expose useful functions with type hints. Avoid generic save_data/load_data-only toy logic unless the requested app is actually that simple.
""",
        )
        deliverable = self._parse_deliverable(self._call_ai(prompt))
        if not deliverable.validate():
            raise ValueError("Backend logic agent deliverable failed validation")
        return deliverable


class APIIntegratorAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = self._prompt_contract(
            "Create web/API server integration.",
            task,
            context,
            """
Create app.py or routes.py implementing Flask routes for the requested app.
Routes should serve templates/static files, expose JSON APIs, validate input, return clear errors, and call the business/database layers.
For an app-builder prompt, include endpoints for projects, files, logs, test runs, repair/change requests, and download zip.
""",
        )
        deliverable = self._parse_deliverable(self._call_ai(prompt))
        if not deliverable.validate():
            raise ValueError("API agent deliverable failed validation")
        return deliverable


class DatabaseManagerAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = self._prompt_contract(
            "Create persistence/database layer.",
            task,
            context,
            """
Create database.py and optionally schema.sql/models.py.
Use SQLite. Provide init_db(), get_connection(), and CRUD helpers that match the app domain.
For an app-builder prompt, persist projects, files, logs, test results, and change requests.
""",
        )
        deliverable = self._parse_deliverable(self._call_ai(prompt))
        if not deliverable.validate():
            raise ValueError("Database agent deliverable failed validation")
        return deliverable


class TestEngineerAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = self._prompt_contract(
            "Create meaningful pytest tests for the actual requested app.",
            task,
            context,
            """
Create test_*.py files that verify the requested requirements, not just trivial mocks.
For a Flask app, use Flask's test client. Test required endpoints, database operations, validation, file listing/download, test/repair workflow, and prompt-specific features.
Tests should fail if the app is only a placeholder or missing key requested features.
""",
        )
        deliverable = self._parse_deliverable(self._call_ai(prompt))
        # Ensure tests_generated is populated for pytest discovery.
        if not deliverable.tests_generated:
            deliverable.tests_generated = [o.filepath for o in deliverable.outputs if o.filepath.startswith("test_") or "/test_" in o.filepath]
        if not deliverable.validate():
            raise ValueError("Test agent deliverable failed validation")
        return deliverable


class WiringEngineerAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        prompt = self._prompt_contract(
            "Create entrypoint, requirements, README, and deployment/run docs.",
            task,
            context,
            """
Create:
- main.py that starts the app or imports app from app.py
- requirements.txt with all generated dependencies
- README.md with run/test/deploy instructions
- optional render.yaml if appropriate
For Flask apps, main.py should run app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000))).
""",
        )
        deliverable = self._parse_deliverable(self._call_ai(prompt))
        if not deliverable.validate():
            raise ValueError("Wiring agent deliverable failed validation")
        return deliverable


# Backwards-compatible alias name used elsewhere.
DatabaseManagerAgent = DatabaseManagerAgent
BackendLogicAgent = BackendLogicAgent
APIIntegratorAgent = APIIntegratorAgent
TestEngineerAgent = TestEngineerAgent
WiringEngineerAgent = WiringEngineerAgent


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
