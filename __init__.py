"""
Boom3 Refactored - Production-Ready AI App Generator

A modular, contract-based system for generating applications with specialized AI agents.
"""

__version__ = "2.0.0"
__author__ = "Boom3 Team"

from pathlib import Path

# Package root
PACKAGE_ROOT = Path(__file__).parent

# Make key classes available at package level
from core.orchestrator import (
    ProjectOrchestrator,
    StateManager,
    WiringRegistry,
    TestOrchestrator,
    FileManager
)

from contracts.agent_contracts import (
    AgentRole,
    ProjectContract,
    CodeOutput,
    WiringContract,
    AgentDeliverable
)

from agents.specialized_agents import create_agent

__all__ = [
    'ProjectOrchestrator',
    'StateManager',
    'WiringRegistry',
    'TestOrchestrator',
    'FileManager',
    'AgentRole',
    'ProjectContract',
    'CodeOutput',
    'WiringContract',
    'AgentDeliverable',
    'create_agent',
]
