"""
Contracts Package - Strict Agent Interfaces
"""

from contracts.agent_contracts import (
    AgentRole,
    FILE_OWNERSHIP,
    CodeOutput,
    WiringContract,
    AgentDeliverable,
    CodeStyleContract,
    InterfaceContract,
    ProjectContract,
    generate_agent_contract,
    AGENT_PROMPT_TEMPLATE
)

__all__ = [
    'AgentRole',
    'FILE_OWNERSHIP',
    'CodeOutput',
    'WiringContract',
    'AgentDeliverable',
    'CodeStyleContract',
    'InterfaceContract',
    'ProjectContract',
    'generate_agent_contract',
    'AGENT_PROMPT_TEMPLATE'
]
