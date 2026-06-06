#!/usr/bin/env python3
"""
Boom3 Production CLI

Thin wrapper around the core orchestrator.
All business logic lives in core/orchestrator.py

Run from repo root:
    python main.py ./project --name "App" --description "..." --agents gui_builder backend_logic
"""

import sys
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("Error: Install OpenAI SDK: pip install openai>=1.3.5")
    sys.exit(1)

from core.orchestrator import create_orchestrator
from contracts.agent_contracts import AgentRole, ProjectContract


def main():
    """Command line interface"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Boom3 Production - AI App Generator")
    parser.add_argument("project_dir", help="Project directory")
    parser.add_argument("--name", required=True, help="Project name")
    parser.add_argument("--description", required=True, help="Project description")
    parser.add_argument("--agents", nargs="+", required=True,
                       help="Required agents (gui_builder backend_logic database_manager etc)")
    
    args = parser.parse_args()
    
    # Create project directory
    project_root = Path(args.project_dir)
    project_root.mkdir(parents=True, exist_ok=True)
    
    # Get API key
    import os
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set")
        return 1
    
    ai_client = OpenAI(api_key=api_key)
    
    # Create orchestrator (now returns working ProductionOrchestrator)
    print("🚀 Boom3 Production - Starting")
    print(f"📁 Project: {args.name}")
    print(f"📝 Description: {args.description}")
    print(f"🤖 Agents: {', '.join(args.agents)}")
    print()
    
    orchestrator = create_orchestrator(project_root, ai_client)
    
    # Create project contract
    contract = ProjectContract(
        project_name=args.name,
        description=args.description,
        required_agents=[AgentRole(a) for a in args.agents],
        expected_files={},  # Will be determined by foreman
        integration_points=[]
    )
    
    # Execute project
    try:
        print("📋 Planning work...")
        success = orchestrator.execute_project(contract)
        
        if success:
            print()
            print("✅ Project completed successfully!")
            print()
            print("📊 Generated files:")
            for deliverable in orchestrator.state.deliverables:
                print(f"   {deliverable.agent_role.value}:")
                for output in deliverable.outputs:
                    print(f"     - {output.filepath}")
            
            print()
            print("🔌 Wiring diagram:")
            print(orchestrator.wiring_registry.generate_diagram())
            
            return 0
        else:
            print()
            print("❌ Project failed:")
            for error in orchestrator.state.errors:
                print(f"   - {error}")
            
            return 1
    
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
