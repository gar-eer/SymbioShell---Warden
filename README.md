# Symbioshell - Dev B: The Warden (System & Security)

"The Warden" provides **State Telemetry** and a **Semantic Sandbox** for Symbioshell, ensuring that any LLM-generated shell command is evaluated for environment context, state mutation, filesystem permissions, and security blocklists before execution.

---

## Key Capabilities

### 1. State Telemetry (`warden/telemetry.py`)
Ensures the LLM is aware of its execution context prior to generating commands.
- **Captured Telemetry**: User, UID/GID, Privilege Level (`root` vs `non-root`), CWD, OS Name & Version, Shell, Hostname, and Git Repository/Branch.
- **Formatted Prompt String**:
  ```text
  USER: root, CWD: /var/log, OS: Ubuntu 22.04, SHELL: /bin/bash, PRIVILEGE: root
  ```

### 2. Semantic Sandbox (`warden/sandbox.py`)
Combines 3 defensive layers to evaluate bash commands:
1. **Blocklist Enforcement (`warden/blocklist.py`)**:
   - Catches catastrophic operations (e.g. `rm -rf /`, `mkfs`, `dd` to raw disk, fork bombs, piped remote code execution like `curl | bash`, critical system file wipes).
2. **State Modification Classifier (`warden/classifier.py`)**:
   - Classifies commands as `READ_ONLY` vs `WRITE`.
   - Detects state-mutating binaries (`rm`, `mv`, `touch`, `sed -i`, `git commit`, `npm install`) and output redirections (`>`, `>>`, `&>`).
3. **Permissions Inspection (`warden/permissions.py`)**:
   - Verifies active OS user read, write, and execute permissions on target files and parent directories prior to execution.

---

## Package Architecture

```text
Symbioshell/
├── warden/
│   ├── __init__.py         # Package exports
│   ├── telemetry.py        # Environment Telemetry Collector
│   ├── sandbox.py          # Semantic Sandbox Engine
│   ├── blocklist.py        # Dangerous Command Blocklist Checker
│   ├── classifier.py       # State Modification Classifier (Read-Only vs Write)
│   ├── permissions.py      # File & Path Permission Checker
│   └── parser.py           # Bash Tokenizer & Pipeline Parser
├── tests/
│   └── test_warden.py      # Comprehensive Test Suite
├── cli.py                  # CLI Interface & Demonstration
└── README.md
```

---

## Usage Example

### Python API

```python
from warden import SemanticSandbox, SandboxDecision, CommandState

sandbox = SemanticSandbox()

# 1. Inject Telemetry Context into LLM Prompt
telemetry_prompt = sandbox.get_telemetry_prompt_string()
# Output: USER: root, CWD: /var/log, OS: Ubuntu 22.04, SHELL: /bin/bash...

# 2. Evaluate LLM Generated Command
result = sandbox.evaluate("ls -la /var/log")
print(result.allowed)      # True
print(result.decision)     # SandboxDecision.ALLOW
print(result.state)        # CommandState.READ_ONLY

# 3. Evaluate Dangerous Command
bad_result = sandbox.evaluate("rm -rf /")
print(bad_result.allowed)  # False
print(bad_result.decision) # SandboxDecision.BLOCK
print(bad_result.reason)   # "BLOCKED: Recursive root filesystem removal (rm -rf /)"
```

---

## Running Tests & CLI Demo

### Run Unit Tests
```bash
python -m unittest discover tests
```

### CLI Demo
```bash
# Print state telemetry
python cli.py --telemetry

# Evaluate safe command
python cli.py "ls -la /var/log"

# Evaluate dangerous command
python cli.py "rm -rf /"

# Evaluate in JSON format
python cli.py --json "echo 'hello' > test.txt"
```
