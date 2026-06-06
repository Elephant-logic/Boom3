#!/usr/bin/env python3
"""
Example: Generate a Simple Calculator App

This demonstrates the complete Boom3 Refactored system.
"""

import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import create_complete_orchestrator
from contracts.agent_contracts import ProjectContract, AgentRole


def generate_calculator():
    """Generate a complete calculator application"""
    
    print("=" * 60)
    print("Boom3 Refactored - Calculator Example")
    print("=" * 60)
    print()
    
    # Check API key
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Please set OPENAI_API_KEY environment variable")
        print("   export OPENAI_API_KEY='your-key-here'")
        return 1
    
    # Create project directory
    project_root = Path("./example_calculator")
    project_root.mkdir(exist_ok=True)
    
    print(f"📁 Project directory: {project_root.absolute()}")
    print()
    
    # Create orchestrator
    print("🔧 Creating orchestrator...")
    orchestrator = create_complete_orchestrator(project_root)
    print("✅ Orchestrator ready")
    print()
    
    # Define project
    print("📋 Defining project contract...")
    contract = ProjectContract(
        project_name="Calculator",
        description="""
A simple desktop calculator application with:
- Basic operations: +, -, *, /
- Clear and equals buttons
- Display showing current calculation
- Modern UI with ttkbootstrap
- Error handling for division by zero
        """.strip(),
        required_agents=[
            AgentRole.GUI_BUILDER,
            AgentRole.BACKEND_LOGIC,
            AgentRole.WIRING_ENGINEER,
            AgentRole.TEST_ENGINEER
        ],
        expected_files={},
        integration_points=[]
    )
    print("✅ Contract defined")
    print()
    
    # Execute
    print("🚀 Starting generation...")
    print("   This will:")
    print("   1. AI plans the work")
    print("   2. Agents generate code following strict contracts")
    print("   3. Files are validated and saved")
    print("   4. Tests are generated and run")
    print("   5. Wiring diagram is created")
    print()
    
    success = orchestrator.execute_project(contract)
    
    print()
    print("=" * 60)
    
    if success:
        print("✅ SUCCESS! Calculator generated")
        print("=" * 60)
        print()
        
        print("📁 Generated files:")
        for deliverable in orchestrator.state.deliverables:
            print(f"\n   {deliverable.agent_role.value}:")
            for output in deliverable.outputs:
                filepath = project_root / output.filepath
                size = filepath.stat().st_size if filepath.exists() else 0
                print(f"     ✓ {output.filepath} ({size} bytes)")
        
        print()
        print("🔌 Wiring diagram:")
        print()
        diagram = orchestrator.wiring_registry.generate_diagram()
        for line in diagram.split('\n'):
            print(f"   {line}")
        
        print()
        print("🧪 Test results:")
        test_files = []
        for deliverable in orchestrator.state.deliverables:
            test_files.extend(deliverable.tests_generated)
        
        if test_files:
            results = orchestrator.test_orchestrator.run_tests(test_files)
            print(f"   Passed: {results['passed']}")
            print(f"   Failed: {results['failed']}")
        else:
            print("   No tests generated")
        
        print()
        print("🎉 To run your calculator:")
        print(f"   cd {project_root}")
        print("   python backend/main.py")
        print()
        
        return 0
    
    else:
        print("❌ FAILED")
        print("=" * 60)
        print()
        print("Errors:")
        for error in orchestrator.state.errors:
            print(f"  - {error}")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(generate_calculator())
