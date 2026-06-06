"""
Agent Contracts & Schemas

This module defines STRICT interfaces that agents MUST follow.
No more chaos - every agent has clear responsibilities and output formats.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal
from enum import Enum
import json

class AgentRole(Enum):
    """Strict role definitions - each agent owns specific files"""
    GUI_BUILDER = "gui_builder"
    BACKEND_LOGIC = "backend_logic"
    API_INTEGRATOR = "api_integrator"
    DATABASE_MANAGER = "database_manager"
    TEST_ENGINEER = "test_engineer"
    WIRING_ENGINEER = "wiring_engineer"

# File ownership - prevents agents from stepping on each other
FILE_OWNERSHIP = {
    # Broadened so agents can build real web/SaaS apps instead of being forced
    # into the old toy tkinter/flat-file shape. Validation still prevents empty
    # outputs, but no longer blocks realistic files like templates/index.html,
    # static/app.js, app.py, requirements.txt, README.md, etc.
    AgentRole.GUI_BUILDER: ["gui.py", "ui_*.py", "widgets.py", "index.html", "*.html", "*.css", "*.js"],
    AgentRole.BACKEND_LOGIC: ["logic.py", "core.py", "business.py", "services.py", "auth.py", "*.py"],
    AgentRole.API_INTEGRATOR: ["api_*.py", "integration.py", "app.py", "routes.py", "server.py", "*.py"],
    AgentRole.DATABASE_MANAGER: ["database.py", "models.py", "schema.sql", "migrations.sql", "seed.py"],
    AgentRole.TEST_ENGINEER: ["test_*.py", "conftest.py", "*.py"],
    AgentRole.WIRING_ENGINEER: ["main.py", "__init__.py", "config.py", "requirements.txt", "README.md", "render.yaml", "Dockerfile", "*.md", "*.txt", "*.yaml", "*.yml"]
}

@dataclass
class CodeOutput:
    """Strict schema for code output - every agent MUST use this"""
    code: str
    filepath: str
    language: Literal["python", "javascript", "html", "css", "sql", "markdown", "text", "yaml", "json"]
    dependencies: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)  # Functions/classes this file provides
    imports_from: Dict[str, List[str]] = field(default_factory=dict)  # {module: [symbols]}
    
    def validate(self) -> bool:
        """Ensure output meets contract"""
        if not self.code or not self.filepath:
            return False
        if self.language not in ["python", "javascript", "html", "css", "sql", "markdown", "text", "yaml", "json"]:
            return False
        return True
    
    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "filepath": self.filepath,
            "language": self.language,
            "dependencies": self.dependencies,
            "exports": self.exports,
            "imports_from": self.imports_from
        }

@dataclass
class WiringContract:
    """Strict schema for wiring connections"""
    from_component: str
    from_symbol: str  # function/class/variable name
    to_component: str
    to_symbol: str
    connection_type: Literal["function_call", "event_handler", "import", "data_flow"]
    parameters: Optional[Dict[str, Any]] = None
    
    def validate(self) -> bool:
        if not all([self.from_component, self.from_symbol, self.to_component, self.to_symbol]):
            return False
        if self.connection_type not in ["function_call", "event_handler", "import", "data_flow"]:
            return False
        return True

@dataclass
class AgentDeliverable:
    """What each agent MUST deliver - no exceptions"""
    agent_role: AgentRole
    outputs: List[CodeOutput]
    wiring: List[WiringContract]
    tests_generated: List[str]  # Test file paths
    documentation: str  # Markdown explaining what was built
    
    def validate(self) -> bool:
        """Ensure deliverable meets contract"""
        if not self.outputs:
            return False
        
        # All outputs must validate
        if not all(output.validate() for output in self.outputs):
            return False
        
        # All wiring must validate
        if not all(wire.validate() for wire in self.wiring):
            return False
        
        # Agent must only touch files it owns
        owned_patterns = FILE_OWNERSHIP.get(self.agent_role, [])
        for output in self.outputs:
            filename = output.filepath.split('/')[-1]
            if not any(self._matches_pattern(filename, pattern) for pattern in owned_patterns):
                return False
        
        return True
    
    def _matches_pattern(self, filename: str, pattern: str) -> bool:
        """Simple glob matching"""
        if '*' in pattern:
            prefix = pattern.split('*')[0]
            return filename.startswith(prefix)
        return filename == pattern
    
    def to_dict(self) -> dict:
        return {
            "agent_role": self.agent_role.value,
            "outputs": [o.to_dict() for o in self.outputs],
            "wiring": [w.__dict__ for w in self.wiring],
            "tests_generated": self.tests_generated,
            "documentation": self.documentation
        }

class CodeStyleContract:
    """Enforces consistent code style across all agents"""
    
    PYTHON_STYLE = {
        "indent": 4,
        "max_line_length": 88,
        "quotes": "double",
        "docstring_style": "google",
        "type_hints": True,
        "imports_order": ["stdlib", "third_party", "local"]
    }
    
    NAMING_CONVENTIONS = {
        "classes": "PascalCase",
        "functions": "snake_case",
        "variables": "snake_case",
        "constants": "UPPER_SNAKE_CASE",
        "private": "_prefix"
    }
    
    REQUIRED_DOCSTRING_SECTIONS = [
        "Args",
        "Returns",
        "Raises"
    ]
    
    @staticmethod
    def validate_python_code(code: str) -> tuple[bool, List[str]]:
        """Validate code meets style contract"""
        issues = []
        
        # Check indentation (simplified)
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            if line.startswith('    '):
                continue  # Valid 4-space indent
            if line.startswith('\t'):
                issues.append(f"Line {i}: Uses tabs instead of 4 spaces")
        
        # Check imports at top
        first_code_line = None
        for i, line in enumerate(lines):
            if line.strip() and not line.strip().startswith('#'):
                first_code_line = i
                break
        
        if first_code_line:
            for i in range(first_code_line + 1, len(lines)):
                if lines[i].startswith('import ') or lines[i].startswith('from '):
                    issues.append(f"Line {i+1}: Import not at top of file")
        
        return len(issues) == 0, issues

class InterfaceContract:
    """Defines interfaces between agents - prevents overlap"""
    
    # GUI Builder can ONLY call these backend functions
    GUI_TO_BACKEND_INTERFACE = [
        "initialize_app() -> bool",
        "save_data(data: dict) -> bool",
        "load_data() -> dict",
        "validate_input(data: dict) -> tuple[bool, str]",
        "get_status() -> dict"
    ]
    
    # Backend can ONLY call these database functions
    BACKEND_TO_DATABASE_INTERFACE = [
        "connect() -> bool",
        "execute_query(query: str, params: tuple) -> Any",
        "save(table: str, data: dict) -> int",
        "load(table: str, id: int) -> dict",
        "delete(table: str, id: int) -> bool"
    ]
    
    # API Integrator can ONLY provide these functions
    API_INTERFACE = [
        "authenticate() -> bool",
        "make_request(endpoint: str, method: str, data: dict) -> dict",
        "handle_rate_limit() -> None",
        "get_health_status() -> bool"
    ]
    
    @staticmethod
    def validate_interface_compliance(agent_role: AgentRole, exports: List[str]) -> tuple[bool, List[str]]:
        """Check if agent is only exporting allowed functions"""
        allowed_interfaces = {
            AgentRole.GUI_BUILDER: InterfaceContract.GUI_TO_BACKEND_INTERFACE,
            AgentRole.BACKEND_LOGIC: InterfaceContract.BACKEND_TO_DATABASE_INTERFACE,
            AgentRole.API_INTEGRATOR: InterfaceContract.API_INTERFACE,
        }
        
        allowed = allowed_interfaces.get(agent_role, [])
        allowed_names = [sig.split('(')[0] for sig in allowed]
        
        violations = []
        for export in exports:
            if export not in allowed_names:
                violations.append(f"{export} not in allowed interface for {agent_role.value}")
        
        return len(violations) == 0, violations

@dataclass
class ProjectContract:
    """Overall project contract - defines complete app structure"""
    project_name: str
    description: str
    required_agents: List[AgentRole]
    expected_files: Dict[AgentRole, List[str]]
    integration_points: List[Dict[str, str]]  # Where agents must connect
    
    def validate_completeness(self, deliverables: List[AgentDeliverable]) -> tuple[bool, List[str]]:
        """Check if all required agents delivered"""
        issues = []
        
        delivered_roles = {d.agent_role for d in deliverables}
        missing_roles = set(self.required_agents) - delivered_roles
        
        if missing_roles:
            issues.append(f"Missing agents: {[r.value for r in missing_roles]}")
        
        # Check all expected files were created
        for agent_role, expected in self.expected_files.items():
            agent_deliverable = next((d for d in deliverables if d.agent_role == agent_role), None)
            if not agent_deliverable:
                continue
            
            created_files = {o.filepath.split('/')[-1] for o in agent_deliverable.outputs}
            missing_files = set(expected) - created_files
            
            if missing_files:
                issues.append(f"{agent_role.value} missing files: {list(missing_files)}")
        
        return len(issues) == 0, issues

# Example usage template for agents
AGENT_PROMPT_TEMPLATE = """
You are a {agent_role} agent.

CONTRACT REQUIREMENTS:
1. You MUST output using CodeOutput schema
2. You can ONLY create these files: {allowed_files}
3. You MUST follow this interface: {interface}
4. Code style: {style_contract}

OUTPUT FORMAT (JSON):
{{
    "outputs": [
        {{
            "code": "...",
            "filepath": "...",
            "language": "python",
            "dependencies": [...],
            "exports": [...],
            "imports_from": {{...}}
        }}
    ],
    "wiring": [
        {{
            "from_component": "...",
            "from_symbol": "...",
            "to_component": "...",
            "to_symbol": "...",
            "connection_type": "function_call"
        }}
    ],
    "tests_generated": [...],
    "documentation": "..."
}}

If your output doesn't match this schema, it will be REJECTED.
"""

def generate_agent_contract(agent_role: AgentRole) -> str:
    """Generate specific contract for an agent"""
    return AGENT_PROMPT_TEMPLATE.format(
        agent_role=agent_role.value,
        allowed_files=FILE_OWNERSHIP.get(agent_role, []),
        interface=InterfaceContract.GUI_TO_BACKEND_INTERFACE,  # Would be role-specific
        style_contract=CodeStyleContract.PYTHON_STYLE
    )

if __name__ == "__main__":
    # Test the contracts
    output = CodeOutput(
        code="def hello(): pass",
        filepath="gui.py",
        language="python",
        exports=["hello"]
    )
    
    print("CodeOutput valid:", output.validate())
    print("Contract:", generate_agent_contract(AgentRole.GUI_BUILDER)[:200])
