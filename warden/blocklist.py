import re
from typing import List, Tuple, Optional
from .parser import ParsedCommand

class BlocklistChecker:
    """
    Strict blocklist detector for dangerous and destructive bash commands.
    Applies pattern matching, regex analysis, and system target inspection.
    """

    # Highly dangerous binaries
    BLOCKED_BINARIES = {
        "mkfs", "mkfs.ext2", "mkfs.ext3", "mkfs.ext4", "mkfs.vfat", "mkfs.ntfs", "mkfs.xfs",
        "fdisk", "gdisk", "parted", "sfdisk",
        "shutdown", "reboot", "init", "poweroff", "halt"
    }

    # Dangerous patterns (regex)
    DANGEROUS_PATTERNS: List[Tuple[str, str]] = [
        # Fork bombs
        (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', "Fork bomb detected"),
        # Recursive root removal
        (r'rm\s+-[a-zA-Z]*r[a-zA-Z]*f\s+/(?:\*|\s*$)', "Recursive root filesystem removal (rm -rf /)"),
        (r'rm\s+-[a-zA-Z]*f[a-zA-Z]*r\s+/(?:\*|\s*$)', "Recursive root filesystem removal (rm -rf /)"),
        (r'rm\s+-[a-zA-Z]*r\s+--no-preserve-root', "Root removal without preservation flag"),
        (r'rm\s+-[a-zA-Z]*r[a-zA-Z]*f\s+~(?:\*|\s*|\/.*)', "Home directory recursive removal"),
        # Raw disk writing (dd of=/dev/...)
        (r'dd\s+.*of=/dev/(?:sd[a-z]|hd[a-z]|nvme\d+n\d+|disk\d+)', "Raw block device write via dd"),
        (r'>\s*/dev/(?:sd[a-z]|hd[a-z]|nvme\d+n\d+|disk\d+)', "Direct redirection to raw block device"),
        # Dangerous remote code execution via pipes
        (r'(?:curl|wget|fetch)\s+.*\|\s*(?:bash|sh|zsh|python|perl|ruby)', "Unsafe remote script execution piped to shell"),
        # Dangerous root permissions modifications
        (r'chmod\s+-[a-zA-Z]*R\s+777\s+/(?:\*|\s*$)', "Recursive world-writable permission on root directory"),
        (r'chown\s+-[a-zA-Z]*R\s+.*\s+/(?:\*|\s*$)', "Recursive ownership modification on root directory")
    ]

    # Critical system files/dirs that must not be deleted or overwritten
    CRITICAL_SYSTEM_PATHS = {
        "/etc/passwd", "/etc/shadow", "/etc/sudoers", "/etc/fstab",
        "/boot", "/sys", "/proc", "/dev"
    }

    @classmethod
    def check(cls, parsed_commands: List[ParsedCommand], raw_command: str) -> Tuple[bool, Optional[str]]:
        """
        Evaluates command against blocklist rules.
        Returns (is_blocked: bool, reason: Optional[str]).
        """
        # 1. Regex check on raw command
        for pattern, reason in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, raw_command, re.IGNORECASE):
                return True, f"BLOCKED: {reason}"

        # 2. Per-command analysis
        for cmd in parsed_commands:
            binary = cmd.binary.lower()

            # Check blocked binaries
            if binary in cls.BLOCKED_BINARIES:
                return True, f"BLOCKED: Binary '{binary}' is prohibited for security reasons."

            # Check rm targeting root or system dirs
            if binary == "rm":
                has_recursive = any('r' in arg or 'R' in arg for arg in cmd.args if arg.startswith('-'))
                for arg in cmd.args:
                    if not arg.startswith('-'):
                        clean_path = arg.rstrip('/')
                        if clean_path in ("", "/"):
                            return True, "BLOCKED: Attempted deletion of root directory '/'."
                        if clean_path in cls.CRITICAL_SYSTEM_PATHS or any(clean_path.startswith(cp) for cp in cls.CRITICAL_SYSTEM_PATHS):
                            return True, f"BLOCKED: Attempted deletion of critical system path '{clean_path}'."

            # Check redirection to critical system files
            for out_path in cmd.output_redirections:
                clean_out = out_path.rstrip('/')
                if clean_out in cls.CRITICAL_SYSTEM_PATHS:
                    return True, f"BLOCKED: Attempted overwrite of critical system file '{clean_out}'."

        return False, None
