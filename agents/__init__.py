"""
Specialized Agents Package

Each agent has strict contracts and file ownership rules.
"""

from agents.specialized_agents import (
    BaseAgent,
    GUIBuilderAgent,
    BackendLogicAgent,
    DatabaseManagerAgent,
    APIIntegratorAgent,
    TestEngineerAgent,
    WiringEngineerAgent,
    create_agent
)

__all__ = [
    'BaseAgent',
    'GUIBuilderAgent',
    'BackendLogicAgent',
    'DatabaseManagerAgent',
    'APIIntegratorAgent',
    'TestEngineerAgent',
    'WiringEngineerAgent',
    'create_agent',
]
