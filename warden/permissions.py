import os
from typing import List, Tuple, Dict, Any, Optional
from .parser import ParsedCommand
from .classifier import CommandState, CommandClassifier

class PermissionChecker:
    """
    Checks if the active OS user has actual filesystem permissions
    (Read, Write, Execute) for target paths specified in the bash command.
    """

    @classmethod
    def extract_target_paths(cls, parsed_commands: List[ParsedCommand], cwd: str) -> Dict[str, List[str]]:
        """
        Extracts read_targets and write_targets from parsed commands.
        """
        read_targets = set()
        write_targets = set()

        for cmd in parsed_commands:
            binary = cmd.binary.lower()

            # Output redirections are write targets
            for out in cmd.output_redirections:
                abs_p = os.path.abspath(os.path.join(cwd, out))
                write_targets.add(abs_p)

            # Input redirections are read targets
            for inp in cmd.input_redirections:
                abs_p = os.path.abspath(os.path.join(cwd, inp))
                read_targets.add(abs_p)

            # Positional arguments analysis
            if binary in ("cat", "grep", "head", "tail", "stat", "less", "more", "wc", "file"):
                for arg in cmd.args:
                    if not arg.startswith('-'):
                        abs_p = os.path.abspath(os.path.join(cwd, arg))
                        read_targets.add(abs_p)

            elif binary in ("rm", "mv", "cp", "touch", "mkdir", "chmod", "chown"):
                for arg in cmd.args:
                    if not arg.startswith('-'):
                        abs_p = os.path.abspath(os.path.join(cwd, arg))
                        write_targets.add(abs_p)

            elif binary.startswith("./") or binary.endswith(".sh"):
                abs_p = os.path.abspath(os.path.join(cwd, binary))
                read_targets.add(abs_p)

        return {
            "read": list(read_targets),
            "write": list(write_targets)
        }

    @classmethod
    def verify_permissions(cls, parsed_commands: List[ParsedCommand], cwd: str, is_root: bool = False) -> Tuple[bool, List[str]]:
        """
        Verifies actual OS read and write permissions on target paths.
        Returns (has_permissions: bool, list_of_permission_errors: List[str]).
        """
        if is_root:
            # Root generally bypasses normal mode bit permission checks (except mount flags)
            return True, []

        targets = cls.extract_target_paths(parsed_commands, cwd)
        errors = []

        # Check Read Targets
        for path in targets["read"]:
            if os.path.exists(path):
                if not os.access(path, os.R_OK):
                    errors.append(f"READ PERMISSION DENIED: Cannot read file '{path}'.")
            else:
                # If file doesn't exist, check if parent directory is readable
                parent = os.path.dirname(path)
                if os.path.exists(parent) and not os.access(parent, os.R_OK):
                    errors.append(f"READ PERMISSION DENIED: Cannot access directory '{parent}'.")

        # Check Write Targets
        for path in targets["write"]:
            if os.path.exists(path):
                if not os.access(path, os.W_OK):
                    errors.append(f"WRITE PERMISSION DENIED: Cannot write to existing target '{path}'.")
            else:
                # File doesn't exist yet -> check if parent directory is writable
                parent = os.path.dirname(path)
                if not parent:
                    parent = cwd
                if os.path.exists(parent):
                    if not os.access(parent, os.W_OK):
                        errors.append(f"WRITE PERMISSION DENIED: Cannot create file in non-writable directory '{parent}'.")
                else:
                    errors.append(f"TARGET DIRECTORY MISSING: Parent directory '{parent}' does not exist.")

        has_permissions = len(errors) == 0
        return has_permissions, errors
