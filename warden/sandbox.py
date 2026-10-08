from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from .telemetry import TelemetryCollector, TelemetryData
from .parser import BashParser, ParsedCommand
from .blocklist import BlocklistChecker
from .classifier import CommandClassifier, CommandState
from .permissions import PermissionChecker

class SandboxDecision(Enum):
    ALLOW = "ALLOW"
    WARN = "WARN"    # Not too dangerous, but requires verification
    BLOCK = "BLOCK"  # Blocked by blocklist (dangerous)
    DENY = "DENY"    # Denied by permissions check

@dataclass
class SandboxResult:
    command: str
    allowed: bool
    decision: SandboxDecision
    state: CommandState
    state_explanation: str
    reason: str
    errors: List[str] = field(default_factory=list)
    telemetry: Optional[TelemetryData] = None
    target_paths: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "allowed": self.allowed,
            "decision": self.decision.value,
            "state": self.state.value,
            "state_explanation": self.state_explanation,
            "reason": self.reason,
            "errors": self.errors,
            "telemetry": self.telemetry.to_prompt_string() if self.telemetry else None,
            "target_paths": self.target_paths
        }


class SemanticSandbox:
    """
    Dev B: Semantic Sandbox Engine.
    Combines Telemetry, Bash Parsing, Blocklist Checking, State Modification Classification,
    and Target File Permission verification.
    """
    #collect and create telemetry result here
    def __init__(self, target_shell: str = "/bin/bash"):
        self.telemetry_collector = TelemetryCollector(target_shell=target_shell)

    #put it in an object
    def get_telemetry_context(self, custom_cwd: Optional[str] = None) -> TelemetryData:
        """
        Returns active environment telemetry object.
        """
        return self.telemetry_collector.collect(custom_cwd=custom_cwd)

    #convert into a string and return it to llm
    def get_telemetry_prompt_string(self, custom_cwd: Optional[str] = None) -> str:
        """
        Returns telemetry prompt string for LLM injection:
        USER: root, CWD: /var/log, OS: Ubuntu 22.04
        """
        telemetry = self.get_telemetry_context(custom_cwd=custom_cwd)
        return telemetry.to_prompt_string()

    
    def evaluate(self, command_str: str, custom_cwd: Optional[str] = None) -> SandboxResult:
        """
        Evaluates a bash command string against the Semantic Sandbox rules.
        """
        telemetry = self.get_telemetry_context(custom_cwd=custom_cwd)
        parsed_cmds = BashParser.parse_full_command(command_str)

        if not parsed_cmds:
            return SandboxResult(
                command=command_str,
                allowed=True,
                decision=SandboxDecision.ALLOW,
                state=CommandState.READ_ONLY,
                state_explanation="Empty command line",
                reason="No operation specified.",
                telemetry=telemetry
            )

        # 1. Blocklist Inspection
        is_blocked, block_reason = BlocklistChecker.check(parsed_cmds, command_str)
        if is_blocked:
            return SandboxResult(
                command=command_str,
                allowed=False,
                decision=SandboxDecision.BLOCK,
                state=CommandState.WRITE,
                state_explanation="Command violates dangerous operation blocklist.",
                reason=block_reason or "Dangerous command prohibited by security policy.",
                errors=[block_reason] if block_reason else [],
                telemetry=telemetry
            )

        # 2. State Modification Classification (Read-Only vs Write)
        state, state_explanation = CommandClassifier.classify(parsed_cmds)

        # 3. Permissions Verification
        target_paths = PermissionChecker.extract_target_paths(parsed_cmds, telemetry.cwd)
        has_perm, perm_errors = PermissionChecker.verify_permissions(
            parsed_cmds,
            cwd=telemetry.cwd,
            is_root=telemetry.is_root
        )

        if not has_perm:
            return SandboxResult(
                command=command_str,
                allowed=False,
                decision=SandboxDecision.DENY,
                state=state,
                state_explanation=state_explanation,
                reason="Permission denied for target files or directories.",
                errors=perm_errors,
                telemetry=telemetry,
                target_paths=target_paths
            )

        # Passed all security layers
        return SandboxResult(
            command=command_str,
            allowed=True,
            decision=SandboxDecision.ALLOW,
            state=state,
            state_explanation=state_explanation,
            reason=f"Command allowed ({state.value}).",
            errors=[],
            telemetry=telemetry,
            target_paths=target_paths
        )
