# 🚀 Boom3 Refactored - Quick Start Guide

## Complete Working System

This is the **full, production-ready** refactored Boom3 system with:
- ✅ Modular architecture (no monolith)
- ✅ Strict agent contracts (no chaos)
- ✅ Modern web UI (no Tkinter ceiling)
- ✅ All agents implemented
- ✅ Complete orchestration
- ✅ CLI and Web interfaces

---

## 📦 Installation

### 1. Install Dependencies

```bash
cd boom3_refactored
pip install -r requirements.txt
```

### 2. Set API Key

```bash
export OPENAI_API_KEY='your-api-key-here'
```

---

## 🎯 Usage Methods

### Method 1: Command Line (Simplest)

```bash
# Basic usage
python main.py ./my_project \
  --name "Password Manager" \
  --description "Encrypted password storage with cloud sync" \
  --agents gui_builder backend_logic database_manager

# Output:
# 🚀 Boom3 Refactored - Starting
# 📁 Project: Password Manager
# ⚙️  Planning work...
# 🤖 gui_builder working...
# 🤖 backend_logic working...
# 🤖 database_manager working...
# ✅ Project completed successfully!
```

### Method 2: Web UI (Best Experience)

```bash
# Start web server
python ui/web_server.py

# Open browser
# http://localhost:5000

# Use beautiful web interface:
# - Enter project details
# - Select agents
# - Click Start
# - Watch real-time progress
# - View generated files
# - See wiring diagram
```

### Method 3: Python API (Programmatic)

```python
from pathlib import Path
from main import create_complete_orchestrator
from contracts.agent_contracts import ProjectContract, AgentRole

# Create orchestrator
orchestrator = create_complete_orchestrator(Path("./my_project"))

# Define project
contract = ProjectContract(
    project_name="Todo App",
    description="Task manager with categories and due dates",
    required_agents=[
        AgentRole.GUI_BUILDER,
        AgentRole.BACKEND_LOGIC,
        AgentRole.DATABASE_MANAGER,
        AgentRole.WIRING_ENGINEER
    ],
    expected_files={},
    integration_points=[]
)

# Execute
success = orchestrator.execute_project(contract)

# Check results
if success:
    print("✅ Done!")
    print(orchestrator.wiring_registry.generate_diagram())
```

---

## 📁 What Gets Generated

```
my_project/
├── backend/
│   ├── gui.py                  # GUI Builder creates this
│   ├── logic.py                # Backend Logic creates this
│   ├── database.py             # Database Manager creates this
│   └── main.py                 # Wiring Engineer creates this
│
├── tests/
│   ├── test_gui.py             # Test Engineer creates this
│   ├── test_logic.py
│   └── conftest.py
│
├── .boom3_state.json           # State for pause/resume
└── wiring_hub.json             # Connection documentation
```

---

## 🎓 Examples

### Example 1: Simple Calculator

```bash
python main.py ./calculator \
  --name "Calculator" \
  --description "Basic calculator with +, -, *, /" \
  --agents gui_builder backend_logic

# Generates:
# - gui.py (calculator UI)
# - logic.py (math operations)
# - main.py (wiring)
```

### Example 2: Password Manager

```bash
python main.py ./password_manager \
  --name "Password Manager" \
  --description "Encrypted password storage with categories" \
  --agents gui_builder backend_logic database_manager wiring_engineer

# Generates:
# - gui.py (password UI)
# - logic.py (encryption logic)
# - database.py (SQLite storage)
# - main.py (complete wiring)
```

### Example 3: API Dashboard

```bash
python main.py ./api_dashboard \
  --name "API Dashboard" \
  --description "Dashboard for monitoring API health and metrics" \
  --agents gui_builder backend_logic api_integrator

# Generates:
# - gui.py (dashboard UI)
# - logic.py (data processing)
# - api_integration.py (API calls)
```

---

## 🔧 Advanced Features

### Pause and Resume

```python
# During execution
orchestrator.pause()

# Later
orchestrator.resume()

# State is automatically saved to .boom3_state.json
```

### View Wiring Diagram

```python
diagram = orchestrator.wiring_registry.generate_diagram()
print(diagram)

# Output:
# === WIRING DIAGRAM ===
# 
# FUNCTION_CALL:
#   gui.save_button -> logic.save_data
#   logic.save_data -> database.save
# 
# IMPORT:
#   gui.py -> logic.py
#   logic.py -> database.py
```

### Run Tests

```python
# Tests are auto-generated and run
results = orchestrator.test_orchestrator.run_tests(test_files)
print(f"Passed: {results['passed']}")
print(f"Failed: {results['failed']}")
```

### Access Generated Files

```python
# Read generated code
code = orchestrator.file_manager.read_file("backend/gui.py")
print(code)

# List all files
for deliverable in orchestrator.state.deliverables:
    print(f"Agent: {deliverable.agent_role.value}")
    for output in deliverable.outputs:
        print(f"  File: {output.filepath}")
        print(f"  Exports: {output.exports}")
```

---

## 🧪 Testing the System

### Test Individual Modules

```bash
# Test contracts
cd contracts
python agent_contracts.py

# Test orchestrator
cd core
python orchestrator.py

# Test agents
cd agents
python specialized_agents.py
```

### Run Full Test

```bash
# Create a test project
python main.py ./test_app \
  --name "Test App" \
  --description "Simple test application" \
  --agents gui_builder backend_logic

# Check generated files
ls -la test_app/backend/
cat test_app/backend/gui.py
```

---

## 📊 Project Structure

```
boom3_refactored/
│
├── contracts/
│   └── agent_contracts.py       # Strict interfaces (250 lines)
│
├── core/
│   └── orchestrator.py          # Modular core (350 lines)
│
├── agents/
│   └── specialized_agents.py    # All agent implementations (500 lines)
│
├── ui/
│   ├── web_server.py            # Flask API (200 lines)
│   └── templates/
│       └── index.html           # Web UI (350 lines)
│
├── main.py                      # CLI interface (200 lines)
├── requirements.txt             # Dependencies
├── README.md                    # Full documentation
├── ARCHITECTURE.md              # Architecture explanation
└── QUICKSTART.md                # This file
```

**Total: ~1850 lines** (vs 2000+ monolithic)
**But:** Much more maintainable, testable, and extensible!

---

## 🐛 Troubleshooting

### "OPENAI_API_KEY not set"

```bash
export OPENAI_API_KEY='sk-...'
# Or add to ~/.bashrc
```

### "Module not found"

```bash
pip install -r requirements.txt
```

### "Agent deliverable failed validation"

The agent tried to create a file it doesn't own. This is good - the contracts are working!

Check the error message to see which contract was violated.

### "Web UI won't start"

```bash
# Make sure Flask is installed
pip install flask flask-sock

# Check port isn't in use
lsof -i :5000

# Try different port
python ui/web_server.py --port 5001
```

---

## 🎯 Next Steps

### Customize Agents

Edit `agents/specialized_agents.py` to change agent behavior:

```python
class GUIBuilderAgent(BaseAgent):
    def execute_task(self, task, context):
        # Your custom logic
        prompt = f"Create GUI with my special requirements..."
        # ...
```

### Add New Agent Type

```python
# 1. Add to contracts/agent_contracts.py
class AgentRole(Enum):
    MY_NEW_AGENT = "my_new_agent"

# 2. Add file ownership
FILE_OWNERSHIP[AgentRole.MY_NEW_AGENT] = ["my_files_*.py"]

# 3. Implement in agents/specialized_agents.py
class MyNewAgent(BaseAgent):
    def execute_task(self, task, context):
        # Implementation
        pass
```

### Integrate with Existing Code

```python
# Import the orchestrator
from main import create_complete_orchestrator

# Use in your own application
orchestrator = create_complete_orchestrator(your_project_path)
orchestrator.execute_project(your_contract)
```

---

## 📚 Documentation

- **README.md** - Complete system documentation
- **ARCHITECTURE.md** - Architecture details and problem solutions
- **QUICKSTART.md** - This file
- **contracts/agent_contracts.py** - Contract system documentation (in code)
- **core/orchestrator.py** - Core modules documentation (in code)

---

## 💡 Tips

1. **Start simple** - Use 2-3 agents first, then add more
2. **Check wiring** - Always review the wiring diagram
3. **Review contracts** - If agents misbehave, tighten the contracts
4. **Use web UI** - Better experience than CLI
5. **Save state** - Use pause/resume for long-running projects

---

## 🎉 You're Ready!

```bash
# Try it now:
python main.py ./my_first_app \
  --name "My First App" \
  --description "A simple hello world application" \
  --agents gui_builder backend_logic wiring_engineer

# Then open the generated files and see the magic!
```

**Happy building!** 🚀
