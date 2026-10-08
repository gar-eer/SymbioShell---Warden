from enum import Enum
from typing import List, Tuple
from .parser import ParsedCommand

class CommandState(Enum):
    READ_ONLY = "READ_ONLY"
    WRITE = "WRITE"
    UNKNOWN = "UNKNOWN"
#making a comment
class CommandClassifier:
    """
    Classifies bash commands into READ_ONLY vs WRITE (state-modifying).
    Inspects binaries, flags, and output redirections.
    """

    READ_ONLY_BINARIES = {
        "ls", "cat", "grep", "egrep", "fgrep", "rg", "find", "pwd", "whoami", "id",
        "stat", "head", "tail", "less", "more", "wc", "diff", "du", "df", "env",
        "printenv", "file", "readlink", "ps", "top", "htop", "uptime", "uname",
        "which", "whereis", "date", "hostname", "history", "tree", "jq"
    }

    WRITE_BINARIES = {
        "rm", "cp", "mv", "touch", "mkdir", "rmdir", "chmod", "chown", "chgrp",
        "ln", "truncate", "dd", "tar", "zip", "unzip", "gzip", "gunzip", "bzip2",
        "sed", "awk", "tee", "git", "npm", "yarn", "pip", "pip3", "apt", "apt-get",
        "yum", "dnf", "pacman", "systemctl", "service", "useradd", "usermod", "userdel"
    }

    @classmethod
    def classify(cls, parsed_commands: List[ParsedCommand]) -> Tuple[CommandState, str]:
        """
        Classifies list of commands. Returns (CommandState, summary_description).
        If any single command in a chain/pipeline writes or modifies state,
        the entire command is classified as WRITE.
        """
        if not parsed_commands:
            return CommandState.READ_ONLY, "Empty command"

        reasons = []
        is_write = False

        for cmd in parsed_commands:
            binary = cmd.binary.lower()

            # 1. Output redirection implies WRITE
            if cmd.output_redirections:
                is_write = True
                targets = ", ".join(cmd.output_redirections)
                reasons.append(f"Output redirection writing to target(s): [{targets}]")

            # 2. Known write binary
            if binary in cls.WRITE_BINARIES:
                # Sub-check git read-only subcommands
                if binary == "git":
                    git_sub = cmd.args[0] if cmd.args else ""
                    if git_sub in ("status", "log", "diff", "show", "branch", "remote"):
                        continue
                    else:
                        is_write = True
                        reasons.append(f"Git command 'git {git_sub}' mutates repository state.")
                # Sub-check sed in-place flag (-i)
                elif binary == "sed":
                    if any('i' in arg for arg in cmd.args if arg.startswith('-')):
                        is_write = True
                        reasons.append("sed in-place editing flag (-i) detected.")
                else:
                    is_write = True
                    reasons.append(f"State-modifying command '{binary}' executed.")

            # 3. Echo/Printf with redirection vs without
            elif binary in ("echo", "printf"):
                if cmd.output_redirections:
                    is_write = True
                    reasons.append(f"'{binary}' redirected to file.")

            # 4. Unknown binary without write binary flag
            elif binary not in cls.READ_ONLY_BINARIES and binary != "":
                # If unknown binary, flag as WRITE for safety or UNKNOWN
                is_write = True
                reasons.append(f"Executable '{binary}' may modify system state.")

        if is_write:
            return CommandState.WRITE, "; ".join(reasons)
        else:
            return CommandState.READ_ONLY, "Command performs read-only operations without side effects."
