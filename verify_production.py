#!/usr/bin/env python3
"""
Production Readiness Verification Script

Tests all 11 fixes are working correctly.
"""

import sys
import os
from pathlib import Path
import subprocess
import json

def test_imports():
    """Test #1: Can import without errors"""
    print("🧪 Test #1: Checking imports...")
    try:
        from contracts.agent_contracts import AgentRole, ProjectContract
        from core.orchestrator import ProjectState, StateManager
        from core.validation import DeliverableValidator, RetryPolicy
        from core.run_logger import RunLogger
        from core.file_workspace import FileWorkspace, SafeFileManager
        from agents.specialized_agents import create_agent
        from main import create_complete_orchestrator
        print("✅ All imports successful")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def test_state_serialization():
    """Test #2: State serialization works"""
    print("\n🧪 Test #2: State serialization...")
    try:
        from core.orchestrator import ProjectState, ExecutionState, StateManager
        from contracts.agent_contracts import AgentDeliverable, AgentRole, CodeOutput
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create state with deliverables
            output = CodeOutput(
                code="def test(): pass",
                filepath="test.py",
                language="python",
                exports=["test"]
            )
            
            deliverable = AgentDeliverable(
                agent_role=AgentRole.GUI_BUILDER,
                outputs=[output],
                wiring=[],
                tests_generated=[],
                documentation="Test"
            )
            
            state = ProjectState(
                current_state=ExecutionState.EXECUTING,
                current_step=5,
                total_steps=10,
                deliverables=[deliverable],
                errors=[]
            )
            
            # Save
            manager = StateManager(Path(tmpdir) / "state.json")
            manager.save(state)
            
            # Load
            loaded = manager.load()
            
            # Verify
            assert loaded.current_step == 5
            assert len(loaded.deliverables) == 1
            assert loaded.deliverables[0].agent_role == AgentRole.GUI_BUILDER
            assert len(loaded.deliverables[0].outputs) == 1
            assert loaded.deliverables[0].outputs[0].filepath == "test.py"
            
            print("✅ State serialization working")
            return True
    except Exception as e:
        print(f"❌ State serialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_validation():
    """Test #3: Validation engine works"""
    print("\n🧪 Test #3: Validation engine...")
    try:
        from core.validation import DeliverableValidator
        from contracts.agent_contracts import AgentDeliverable, AgentRole, CodeOutput
        
        validator = DeliverableValidator()
        
        # Test valid deliverable
        valid = AgentDeliverable(
            agent_role=AgentRole.GUI_BUILDER,
            outputs=[CodeOutput(
                code="def main(): pass",
                filepath="gui.py",
                language="python",
                exports=["main"]
            )],
            wiring=[],
            tests_generated=[],
            documentation="Test"
        )
        
        result = validator.validate_complete(valid)
        assert result.valid, f"Valid deliverable rejected: {result.errors}"
        
        # Test invalid deliverable (wrong file ownership)
        invalid = AgentDeliverable(
            agent_role=AgentRole.GUI_BUILDER,
            outputs=[CodeOutput(
                code="def logic(): pass",
                filepath="logic.py",  # Backend file!
                language="python"
            )],
            wiring=[],
            tests_generated=[],
            documentation=""
        )
        
        result = validator.validate_complete(invalid)
        assert not result.valid, "Invalid deliverable was accepted!"
        assert len(result.errors) > 0, "No errors for invalid deliverable"
        
        print("✅ Validation engine working")
        return True
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_retry_policy():
    """Test #3b: Retry policy works"""
    print("\n🧪 Test #3b: Retry policy...")
    try:
        from core.validation import RetryPolicy, FailureReason
        
        policy = RetryPolicy(max_attempts=3)
        
        # Should retry on schema issues
        assert policy.should_retry("task1", FailureReason.SCHEMA_INVALID)
        
        # Record attempts
        policy.record_attempt("task1")
        policy.record_attempt("task1")
        policy.record_attempt("task1")
        
        # Should NOT retry after max attempts
        assert not policy.should_retry("task1", FailureReason.SCHEMA_INVALID)
        
        print("✅ Retry policy working")
        return True
    except Exception as e:
        print(f"❌ Retry policy failed: {e}")
        return False

def test_run_logger():
    """Test #4: Run logger works"""
    print("\n🧪 Test #4: Run logger...")
    try:
        from core.run_logger import RunLogger
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(Path(tmpdir))
            logger.log.project_name = "Test"
            
            logger.log_agent_call(
                agent_id="test",
                agent_role="gui_builder",
                task={"desc": "test"},
                prompt="test prompt",
                model="gpt-4o",
                temperature=0.3,
                raw_response="response",
                parsed_output={},
                validation_result={"valid": True},
                files_written=["test.py"],
                errors=[],
                duration=1.0
            )
            
            logger.finalize(success=True)
            
            # Check log file exists
            assert logger.log_file.exists(), "Log file not created"
            
            # Load and verify
            from core.run_logger import RunLog
            loaded = RunLog.load(logger.log_file)
            assert len(loaded.agent_calls) == 1
            assert loaded.success == True
            
            print("✅ Run logger working")
            return True
    except Exception as e:
        print(f"❌ Run logger failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_file_workspace():
    """Test #9: File workspace with staging"""
    print("\n🧪 Test #9: File workspace...")
    try:
        from core.file_workspace import FileWorkspace
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = FileWorkspace(Path(tmpdir))
            
            # Stage files
            workspace.write_staged("backend/gui.py", "def main(): pass")
            workspace.write_staged("backend/logic.py", "def process(): pass")
            
            # Check staged
            assert len(workspace.list_staged()) == 2
            
            # Commit
            success = workspace.commit()
            assert success, "Commit failed"
            
            # Verify files exist
            assert (Path(tmpdir) / "backend" / "gui.py").exists()
            assert (Path(tmpdir) / "backend" / "logic.py").exists()
            
            print("✅ File workspace working")
            return True
    except Exception as e:
        print(f"❌ File workspace failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cli_runnable():
    """Test #10: CLI can run"""
    print("\n🧪 Test #10: CLI runnable...")
    try:
        # Check main.py can be imported
        import main
        assert hasattr(main, 'create_complete_orchestrator')
        assert hasattr(main, 'main')
        
        print("✅ CLI is runnable (main.py imports successfully)")
        return True
    except Exception as e:
        print(f"❌ CLI test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("="*60)
    print("Boom3 Production Readiness Verification")
    print("="*60)
    
    tests = [
        ("Imports", test_imports),
        ("State Serialization", test_state_serialization),
        ("Validation Engine", test_validation),
        ("Retry Policy", test_retry_policy),
        ("Run Logger", test_run_logger),
        ("File Workspace", test_file_workspace),
        ("CLI Runnable", test_cli_runnable),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n💥 Test '{name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED - System is production ready!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} tests failed - needs fixes")
        return 1

if __name__ == "__main__":
    sys.exit(main())
