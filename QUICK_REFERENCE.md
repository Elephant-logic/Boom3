# Quick Reference - Production Architecture

## File Locations (What Lives Where)

### Core Business Logic
**`core/orchestrator.py`** - The heart of the system
- `ProjectOrchestrator` - Main production pipeline
- `ForemanCoordinator` - AI-powered planning with robust JSON parsing
- `StateManager` - Persistence
- `WiringRegistry` - Connection tracking
- `TestOrchestrator` - Test execution
- `FileManager` - File operations

**Rule**: If it's core business logic, it goes here.

### CLI Interface
**`main.py`** - Thin wrapper ONLY
- `ProductionOrchestrator` - Implements `_execute_task()` with validation/retry
- `create_production_orchestrator()` - Setup function
- `main()` - CLI argument parsing

**Rule**: Only CLI interface code. No business logic.

### Agents
**`agents/specialized_agents.py`**
- `BaseAgent` - Captures raw responses automatically
- `GUIBuilderAgent`, `BackendLogicAgent`, etc.

**Rule**: Agent implementations. They inherit raw response capture.

### Contracts
**`contracts/agent_contracts.py`**
- Data structures for agents to follow
- Validation rules

**Rule**: Define interfaces, not implementations.

---

## How To: Common Tasks

### Add a New Agent

1. Create class in `agents/specialized_agents.py`:
   ```python
   class MyNewAgent(BaseAgent):
       def execute_task(self, task, context):
           response = self._call_ai(prompt)  # Automatically captures raw
           return self._parse_deliverable(response)
   ```

2. Register in `create_agent()` factory function

3. Done! Raw response logging is automatic.

### Change Orchestration Logic

Edit `core/orchestrator.py`:
- **Planning**: Modify `ForemanCoordinator.plan_work()`
- **Execution**: Modify `ProjectOrchestrator.execute_project()`
- **Validation**: Already delegated to subclass `_execute_task()`

**Don't touch `main.py`** - it's just the CLI.

### Improve JSON Parsing

Edit `ForemanCoordinator._parse_json_robust()` in `core/orchestrator.py`:
```python
def _parse_json_robust(self, content):
    # Add your parsing strategy
    # Current: markdown blocks → direct parse → array extraction
    pass
```

### Debug a Failed Run

1. Find log file: `.boom3_run_YYYYMMDD_HHMMSS.json`

2. Check fields:
   ```json
   {
     "agent_calls": [
       {
         "raw_response": "...actual model output...",
         "parsed_output": {...},
         "validation_result": {...},
         "errors": [...]
       }
     ]
   }
   ```

3. Raw response is now ACTUALLY there (not a placeholder)

### Add a New CLI Option

Edit `main()` in `main.py`:
```python
parser.add_argument("--my-option", help="...")
```

Use in `ProductionOrchestrator` if needed.

---

## Architecture Decision Records

### Why `_execute_task()` is Abstract?

**Decision**: `ProjectOrchestrator._execute_task()` is abstract.

**Reasoning**: 
- Different execution strategies (local vs cloud, different retry policies)
- Keeps base class clean
- Forces explicit implementation in subclasses

**Implementation**: `ProductionOrchestrator` in `main.py` implements it with validation/retry.

### Why Split Orchestrator and CLI?

**Decision**: Business logic in `core/`, CLI in `main.py`.

**Reasoning**:
- Business logic is testable without CLI
- Can add web UI, API, or other interfaces easily
- Single responsibility principle
- Easier to reason about

### Why Capture Raw Response in BaseAgent?

**Decision**: Store `last_raw_response` in `BaseAgent`.

**Reasoning**:
- All agents get this automatically
- Single point of capture
- No need to modify orchestrator or individual agents
- Complete audit trail for debugging

---

## Common Pitfalls

### ❌ DON'T: Put Business Logic in main.py
```python
# BAD - in main.py
def calculate_project_complexity():
    # complex logic here
```

**DO**: Put it in `core/orchestrator.py` or appropriate module.

### ❌ DON'T: Parse JSON Without Fallback
```python
# BAD
data = json.loads(response)  # Can fail
```

**DO**: Use `_parse_json_robust()` or similar multi-strategy approach.

### ❌ DON'T: Log Without Raw Response
```python
# BAD
self.run_logger.log_agent_call(
    ...
    raw_response="[Not captured]"  # Missing critical data
)
```

**DO**: Always pass `agent.last_raw_response`.

### ❌ DON'T: Create Multiple Orchestrators
```python
# BAD
class AnotherOrchestrator:
    def execute_project(self):
        # duplicate pipeline logic
```

**DO**: Subclass `ProjectOrchestrator` and override `_execute_task()`.

---

## Testing Strategy

### Unit Tests
```python
# Test individual components
def test_foreman_parsing():
    coordinator = ForemanCoordinator(mock_client)
    tasks = coordinator._parse_json_robust(sample_json)
    assert len(tasks) > 0
```

### Integration Tests
```python
# Test full pipeline
def test_complete_run():
    orchestrator = create_production_orchestrator(test_dir)
    success = orchestrator.execute_project(contract)
    assert success
    assert orchestrator.run_logger.log.success
```

### Replay Tests
```python
# Use logged runs as test data
def test_replay():
    log = RunLog.load("failed_run.json")
    # Replay and verify fix
```

---

## Performance Tips

1. **Raw response storage**: Large responses inflate log files. Consider truncation for very long responses:
   ```python
   raw_response=raw[:10000] + "...[truncated]" if len(raw) > 10000 else raw
   ```

2. **State saves**: Currently saves after every step. For long runs, this could be optimized:
   ```python
   if i % 5 == 0:  # Save every 5 steps instead
       self.state_manager.save(self.state)
   ```

3. **JSON parsing**: Most expensive is the regex search. Cache if parsing multiple times.

---

## Migration Guide (from old architecture)

If you have existing code using the old `CompleteOrchestrator`:

1. **Import change**:
   ```python
   # Old
   from main import CompleteOrchestrator
   
   # New
   from main import create_production_orchestrator
   orchestrator = create_production_orchestrator(project_root)
   ```

2. **Execution is the same**:
   ```python
   orchestrator.execute_project(contract)  # Unchanged
   ```

3. **Log files are now complete**:
   ```python
   log = RunLog.load(".boom3_run_*.json")
   # log.agent_calls[0].raw_response is now ACTUAL response
   ```

---

## Summary: Three Core Principles

1. **Single Source of Truth**: `core/orchestrator.py` is the system
2. **Complete Logging**: Raw responses are always captured
3. **Robust Parsing**: Multiple fallback strategies for JSON

Everything else follows from these.
