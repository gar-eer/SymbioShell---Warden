import os
import platform
import getpass
import subprocess
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional

@dataclass
class TelemetryData:
    user: str
    uid: int
    gid: int
    is_root: bool
    cwd: str
    os_name: str
    os_version: str
    shell: str
    hostname: str
    git_branch: Optional[str] = None
    git_repo: Optional[str] = None

    def to_prompt_string(self) -> str:
        """
        Formats telemetry into the required format for prompt injection:
        USER: root, CWD: /var/log, OS: Ubuntu 22.04
        """
        parts = [
            f"USER: {self.user}",
            f"CWD: {self.cwd}",
            f"OS: {self.os_name} {self.os_version}".strip(),
            f"SHELL: {self.shell}",
            f"PRIVILEGE: {'root' if self.is_root else 'non-root'}"
        ]
        if self.git_branch:
            parts.append(f"GIT_BRANCH: {self.git_branch}")
        return ", ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TelemetryCollector:
    """
    State Telemetry Collector for Symbioshell (Dev B).
    Gathers active system environment details prior to LLM command generation.
    """

    def __init__(self, target_shell: str = "/bin/bash"):
        self.target_shell = target_shell

    def _get_os_info(self) -> tuple[str, str]:
        """Detect OS name and distribution/version."""
        system = platform.system()
        if system == "Linux":
            # Attempt to read /etc/os-release for distro info (e.g. Ubuntu 22.04)
            if os.path.exists("/etc/os-release"):
                try:
                    info = {}
                    with open("/etc/os-release", "r") as f:
                        for line in f:
                            if "=" in line:
                                k, v = line.strip().split("=", 1)
                                info[k] = v.strip('"')
                    name = info.get("NAME", "Linux")
                    version = info.get("VERSION_ID", info.get("VERSION", platform.release()))
                    return name, version
                except Exception:
                    pass
            return "Linux", platform.release()
        elif system == "Darwin":
            return "macOS", platform.mac_ver()[0] or platform.release()
        elif system == "Windows":
            return "Windows", platform.version()
        return system, platform.release()

    def _get_git_info(self, cwd: str) -> tuple[Optional[str], Optional[str]]:
        """Attempt to retrieve git repository root and current branch."""
        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd,
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
            repo_root = subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cwd,
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
            repo_name = os.path.basename(repo_root) if repo_root else None
            return branch, repo_name
        except Exception:
            return None, None

    def collect(self, custom_cwd: Optional[str] = None) -> TelemetryData:
        """
        Collect current environment state telemetry.
        """
        cwd = os.path.abspath(custom_cwd) if custom_cwd else os.getcwd()
        
        # User details
        try:
            username = getpass.getuser()
        except Exception:
            username = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))

        uid = getattr(os, 'getuid', lambda: -1)()
        gid = getattr(os, 'getgid', lambda: -1)()
        is_root = (uid == 0 or username == "root")

        # OS details
        os_name, os_version = self._get_os_info()

        # Shell
        shell = os.environ.get("SHELL", self.target_shell)

        # Hostname
        hostname = platform.node()

        # Git info
        git_branch, git_repo = self._get_git_info(cwd)

        return TelemetryData(
            user=username,
            uid=uid,
            gid=gid,
            is_root=is_root,
            cwd=cwd,
            os_name=os_name,
            os_version=os_version,
            shell=shell,
            hostname=hostname,
            git_branch=git_branch,
            git_repo=git_repo
        )
