"""
Run Logging System

Every agent call, validation, file write logged for:
- Debugging
- Replay
- Audit trail
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum


def _json_safe(value):
    """Recursively convert Enums and dataclasses into JSON-safe values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(_json_safe(k)): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe(value.to_dict())
    return value


@dataclass
class AgentCallLog:
    """Log of single agent execution"""
    timestamp: str
    agent_id: str
    agent_role: str
    task: Dict[str, Any]
    prompt: str
    model: str
    temperature: float
    raw_response: str
    parsed_output: Dict[str, Any]
    validation_result: Dict[str, Any]
    files_written: List[str]
    errors: List[str]
    duration_seconds: float


@dataclass
class RunLog:
    """Complete log of a generation run"""
    run_id: str
    start_time: str
    end_time: str = None
    project_name: str = ""
    project_description: str = ""
    agent_calls: List[AgentCallLog] = field(default_factory=list)
    state_snapshots: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    success: bool = False
    
    def to_dict(self) -> dict:
        """Serialize to dict"""
        return {
            "run_id": self.run_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "project_name": self.project_name,
            "project_description": self.project_description,
            "agent_calls": [_json_safe(asdict(call)) for call in self.agent_calls],
            "state_snapshots": _json_safe(self.state_snapshots),
            "errors": _json_safe(self.errors),
            "success": self.success
        }
    
    def save(self, filepath: Path):
        """Save to JSON"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(_json_safe(self.to_dict()), f, indent=2)
    
    @classmethod
    def load(cls, filepath: Path) -> 'RunLog':
        """Load from JSON"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Reconstruct agent calls
        agent_calls = [
            AgentCallLog(**call_data) 
            for call_data in data.get("agent_calls", [])
        ]
        
        return cls(
            run_id=data["run_id"],
            start_time=data["start_time"],
            end_time=data.get("end_time"),
            project_name=data.get("project_name", ""),
            project_description=data.get("project_description", ""),
            agent_calls=agent_calls,
            state_snapshots=data.get("state_snapshots", []),
            errors=data.get("errors", []),
            success=data.get("success", False)
        )
    
    def add_agent_call(
        self,
        agent_id: str,
        agent_role: str,
        task: Dict[str, Any],
        prompt: str,
        model: str,
        temperature: float,
        raw_response: str,
        parsed_output: Dict[str, Any],
        validation_result: Dict[str, Any],
        files_written: List[str],
        errors: List[str],
        duration: float
    ):
        """Add an agent call to the log"""
        call = AgentCallLog(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            agent_role=agent_role,
            task=task,
            prompt=prompt,
            model=model,
            temperature=temperature,
            raw_response=raw_response,
            parsed_output=parsed_output,
            validation_result=validation_result,
            files_written=files_written,
            errors=errors,
            duration_seconds=duration
        )
        self.agent_calls.append(call)
    
    def add_state_snapshot(self, state: Dict[str, Any]):
        """Add state snapshot"""
        self.state_snapshots.append({
            "timestamp": datetime.now().isoformat(),
            "state": state
        })
    
    def add_error(self, error: str):
        """Add error"""
        self.errors.append({
            "timestamp": datetime.now().isoformat(),
            "error": error
        })
    
    def get_replay_instructions(self) -> str:
        """Get instructions to replay this run"""
        return f"""
To replay this run:

1. Use the same inputs:
   Project: {self.project_name}
   Description: {self.project_description}

2. Agent calls made: {len(self.agent_calls)}
   {chr(10).join(f"   - {call.agent_role} at {call.timestamp}" for call in self.agent_calls)}

3. Files generated:
   {chr(10).join(f"   - {f}" for call in self.agent_calls for f in call.files_written)}

4. To debug, check:
   - Agent call #{len(self.agent_calls)} (last call)
   - Prompt: See agent_calls[-1].prompt
   - Response: See agent_calls[-1].raw_response
   - Validation: See agent_calls[-1].validation_result
"""


class RunLogger:
    """Manages run logging"""
    
    def __init__(self, project_root: Path, run_id: str = None):
        self.project_root = project_root
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log = RunLog(
            run_id=self.run_id,
            start_time=datetime.now().isoformat()
        )
        self.log_file = project_root / f".boom3_run_{self.run_id}.json"
    
    def log_agent_call(
        self,
        agent_id: str,
        agent_role: str,
        task: Dict[str, Any],
        prompt: str,
        model: str,
        temperature: float,
        raw_response: str,
        parsed_output: Dict[str, Any],
        validation_result: Dict[str, Any],
        files_written: List[str],
        errors: List[str],
        duration: float
    ):
        """Log an agent call"""
        self.log.add_agent_call(
            agent_id=agent_id,
            agent_role=agent_role,
            task=task,
            prompt=prompt,
            model=model,
            temperature=temperature,
            raw_response=raw_response,
            parsed_output=parsed_output,
            validation_result=validation_result,
            files_written=files_written,
            errors=errors,
            duration=duration
        )
        self.save()
    
    def log_state(self, state: Dict[str, Any]):
        """Log state snapshot"""
        self.log.add_state_snapshot(state)
        self.save()
    
    def log_error(self, error: str):
        """Log error"""
        self.log.add_error(error)
        self.save()
    
    def finalize(self, success: bool):
        """Finalize run"""
        self.log.end_time = datetime.now().isoformat()
        self.log.success = success
        self.save()
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"Run {self.run_id} {'COMPLETED' if success else 'FAILED'}")
        print(f"{'='*60}")
        print(f"Duration: {self._calculate_duration()}")
        print(f"Agent calls: {len(self.log.agent_calls)}")
        print(f"Errors: {len(self.log.errors)}")
        print(f"\nFull log: {self.log_file}")
        print(f"{'='*60}\n")
    
    def save(self):
        """Save log to disk"""
        self.log.save(self.log_file)
    
    def _calculate_duration(self) -> str:
        """Calculate run duration"""
        if not self.log.end_time:
            return "In progress"
        
        start = datetime.fromisoformat(self.log.start_time)
        end = datetime.fromisoformat(self.log.end_time)
        duration = end - start
        
        minutes = int(duration.total_seconds() / 60)
        seconds = int(duration.total_seconds() % 60)
        
        return f"{minutes}m {seconds}s"


if __name__ == "__main__":
    # Example usage
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(Path(tmpdir))
        logger.log.project_name = "Test App"
        logger.log.project_description = "A test application"
        
        # Simulate agent call
        logger.log_agent_call(
            agent_id="gui_123",
            agent_role="gui_builder",
            task={"description": "Create GUI"},
            prompt="Create a calculator GUI...",
            model="gpt-4o",
            temperature=0.3,
            raw_response="```json\n{...}\n```",
            parsed_output={"code": "def main(): pass"},
            validation_result={"valid": True},
            files_written=["gui.py"],
            errors=[],
            duration=3.5
        )
        
        logger.finalize(success=True)
        
        # Load and replay
        loaded = RunLog.load(logger.log_file)
        print(loaded.get_replay_instructions())
