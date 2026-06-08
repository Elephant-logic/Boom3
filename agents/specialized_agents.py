"""
Specialized Agent Implementations

Blueprint-driven agents. Each agent receives the same shared_architecture
(blueprint) created by the Foreman and must build only its assigned module(s).
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

    _ROLE_TO_TEAM = {
        "gui_builder": "builder",
        "backend_logic": "builder",
        "api_integrator": "builder",
        "database_manager": "builder",
        "test_engineer": "tester",
        "wiring_engineer": "architect",
    }

    _ROLE_GUIDANCE = {
        AgentRole.DATABASE_MANAGER: "Own persistence/data models only. Build database.py/models.py/schema files exactly from the blueprint. Do not invent a different domain.",
        AgentRole.BACKEND_LOGIC: "Own business logic/services only. Implement the blueprint's domain workflows and exported functions. Do not create UI placeholders.",
        AgentRole.API_INTEGRATOR: "Own web/API routes or external API integration only. Implement real endpoints from the blueprint and wire them to logic/services.",
        AgentRole.GUI_BUILDER: "Own the user interface only. Build the exact screens/components in the blueprint, with real controls calling the planned APIs.",
        AgentRole.TEST_ENGINEER: "Own tests only. Write meaningful pytest tests for the blueprint features and public contracts. Tests must verify requested behaviour, not fake placeholder success.",
        AgentRole.WIRING_ENGINEER: "Own entrypoint/config/docs/deployment only. Create requirements, README, render/Docker/config and wire the actual modules together.",
    }

    def _team_model(self, team_role: str) -> str:
        env_key = f"BOOM3_MODEL_{team_role.upper()}"
        if os.environ.get(env_key):
            return os.environ[env_key]
        defaults = {
            "architect": os.environ.get("BOOM3_MODEL_DEEP", "gpt-4o"),
            "builder": os.environ.get("BOOM3_MODEL_FAST", "gpt-4o-mini"),
            "tester": os.environ.get("BOOM3_MODEL_FAST", "gpt-4o-mini"),
        }
        return defaults.get(team_role, os.environ.get("BOOM3_MODEL", "gpt-4o"))

    def _call_ai(self, prompt: str, temperature: float = 0.25) -> str:
        contract = generate_agent_contract(self.agent_role)
        team_role = self._ROLE_TO_TEAM.get(self.agent_role.value, "builder")
        model = self._team_model(team_role)
        role_env_key = f"BOOM3_MODEL_{self.agent_role.value.upper()}"
        if os.environ.get(role_env_key):
            model = os.environ[role_env_key]
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

    def _execute_blueprint_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        shared = task.get("shared_architecture") or {}
        files_to_create = task.get("files_to_create") or []
        dependencies = task.get("dependencies") or []
        guidance = self._ROLE_GUIDANCE.get(self.agent_role, "Build your assigned module from the blueprint.")

        prompt = f"""
You are Boom3 agent: {self.agent_role.value}.

You MUST build from the FOREMAN BLUEPRINT below. The blueprint is the contract for the whole project. Do not invent a different app, data model, endpoint set, or test standard.

PROJECT NAME:
{task.get('project_name', '')}

ORIGINAL USER PROMPT:
{task.get('description', '')}

FOREMAN BLUEPRINT / SHARED ARCHITECTURE:
{json.dumps(shared, indent=2, ensure_ascii=False)}

ENGINE PLAN / DISCOVERY REQUIREMENTS:
- Use shared_architecture.discovery_pack as the available engine catalogue.
- Use shared_architecture.selected_engines and shared_architecture.engine_plan to decide what capabilities your files must expose.
- If the prompt is an app-builder/platform, implement real runner/log/file/test/repair/deploy behaviour, not fake buttons.
- If the prompt is another app type, use only the engines needed for that app.

YOUR TASK:
{task.get('description', '')}

YOUR ASSIGNED FILES:
{json.dumps(files_to_create, ensure_ascii=False)}

SUGGESTED DEPENDENCIES:
{json.dumps(dependencies, ensure_ascii=False)}

ROLE RULES:
{guidance}

EXISTING PROJECT CONTEXT:
{context[:12000]}

ABSOLUTE RULES:
- Generate complete working code, not placeholders.
- Do not use fake success responses such as "tests executed successfully" unless tests really run.
- Do not write TODO/pass/ellipsis/stub-only implementation.
- Do not leak unrelated domains such as expenses unless the user prompt asks for expenses.
- Use only pip-installable third-party packages in dependencies. Never list stdlib modules like sqlite3, json, os, sys, pathlib, datetime, typing, zipfile, subprocess, shutil, tkinter.
- If you create tests, tests must check the actual requested features from the blueprint and selected engine plan.
- Every route/button/public function you expose must have real supporting logic or a clearly safe local stub only when external credentials are required.
- Do not use placeholder text like "successfully executed" without doing the work described.
- Keep paths relative to the generated project.
- Return only JSON, no markdown.

Return JSON in this exact schema:
{{
  "outputs": [
    {{
      "code": "complete file contents",
      "filepath": "relative/path.ext",
      "language": "python|javascript|html|css|sql|markdown|text|yaml|json",
      "dependencies": [],
      "exports": [],
      "imports_from": {{}}
    }}
  ],
  "wiring": [
    {{
      "from_component": "component_or_file",
      "from_symbol": "symbol_or_route",
      "to_component": "component_or_file",
      "to_symbol": "symbol_or_route",
      "connection_type": "function_call|event_handler|import|data_flow"
    }}
  ],
  "tests_generated": [],
  "documentation": "what you built and how it follows the blueprint"
}}
"""
        response = self._call_ai(prompt)
        deliverable = self._parse_deliverable(response)
        if not deliverable.validate():
            raise ValueError(f"{self.agent_role.value} deliverable failed validation")
        return deliverable

    def _parse_deliverable(self, ai_response: str) -> AgentDeliverable:
        data = self._extract_json(ai_response)
        if data is None:
            data = self._repair_json(ai_response)
        if data is None:
            raise ValueError(
                f"Agent {self.agent_id} returned unparseable JSON. Preview: {ai_response[:500]}"
            )
        outputs = [
            CodeOutput(
                code=o["code"], filepath=o["filepath"], language=o["language"],
                dependencies=o.get("dependencies", []), exports=o.get("exports", []),
                imports_from=o.get("imports_from", {}),
            )
            for o in data.get("outputs", [])
        ]
        wiring = [
            WiringContract(
                from_component=w["from_component"], from_symbol=w["from_symbol"],
                to_component=w["to_component"], to_symbol=w["to_symbol"],
                connection_type=w["connection_type"], parameters=w.get("parameters"),
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
            f"Broken output:\n{bad_response[:4000]}"
        )
        try:
            repaired = self._call_ai(repair_prompt, temperature=0.0)
            return self._extract_json(repaired)
        except Exception:
            return None


class DatabaseManagerAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        return self._execute_blueprint_task(task, context)


class BackendLogicAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        return self._execute_blueprint_task(task, context)


class GUIBuilderAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        return self._execute_blueprint_task(task, context)


class APIIntegratorAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        return self._execute_blueprint_task(task, context)


class TestEngineerAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        return self._execute_blueprint_task(task, context)


class WiringEngineerAgent(BaseAgent):
    def execute_task(self, task: Dict[str, Any], context: str) -> AgentDeliverable:
        return self._execute_blueprint_task(task, context)


def create_agent(agent_role: AgentRole, ai_client: OpenAI) -> BaseAgent:
    agents = {
        AgentRole.GUI_BUILDER: GUIBuilderAgent,
        AgentRole.BACKEND_LOGIC: BackendLogicAgent,
        AgentRole.API_INTEGRATOR: APIIntegratorAgent,
        AgentRole.DATABASE_MANAGER: DatabaseManagerAgent,
        AgentRole.TEST_ENGINEER: TestEngineerAgent,
        AgentRole.WIRING_ENGINEER: WiringEngineerAgent,
    }
    agent_class = agents.get(agent_role)
    if not agent_class:
        raise ValueError(f"Unknown agent role: {agent_role}")
    agent_id = f"{agent_role.value}_{id(agent_class)}"
    return agent_class(agent_id, agent_role, ai_client)
