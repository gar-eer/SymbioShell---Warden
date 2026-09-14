"""
Dev A - The Translator
Part 2: CLI UX

Handles the interactive loop: take natural language input, show a spinner
while the LLM generates a command, then display the result for review
before anything executes.

Falls back to a plain ANSI spinner if `rich` isn't installed, so this
runs even before you've set up your venv. For the nicer version:
    pip install rich --break-system-packages
"""

import sys
import time
import threading
import subprocess

from nl_shell_translator import generate_command
from error_handling import handle_execution_error

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.status import Status
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False

# ANSI fallback colors
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------
class PlainSpinner:
    """Minimal dependency-free spinner for terminals without rich."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message="Thinking..."):
        self.message = message
        self._stop_event = threading.Event()
        self._thread = None

    def _spin(self):
        i = 0
        while not self._stop_event.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r{CYAN}{frame} {self.message}{RESET}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1
        # clear the line when done
        sys.stdout.write("\r" + " " * (len(self.message) + 4) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_event.set()
        self._thread.join()


def spinner(message="Generating command..."):
    if RICH_AVAILABLE:
        return console.status(f"[cyan]{message}[/cyan]", spinner="dots")
    return PlainSpinner(message)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
def show_result(result: dict):
    """Render the generated command for review before execution."""
    if not result.get("command"):
        # No command was generated - either ambiguous request or refusal
        if RICH_AVAILABLE:
            console.print(Panel(result["explanation"], title="Need more info", border_style="yellow"))
        else:
            print(f"{YELLOW}⚠ {result['explanation']}{RESET}")
        return

    danger = result.get("is_destructive", False)
    needs_perm = result.get("requires_target_permission", False)

    if RICH_AVAILABLE:
        style = "red" if danger else "green"
        tag = "[bold red]DESTRUCTIVE[/bold red]" if danger else "[bold green]read-only[/bold green]"
        body = f"[bold]{result['command']}[/bold]\n\n{result['explanation']}"
        if needs_perm:
            body += "\n\n[yellow]⚠ Targets a path you may not own.[/yellow]"
        console.print(Panel(body, title=f"Generated command ({tag})", border_style=style))
    else:
        color = RED if danger else GREEN
        tag = "DESTRUCTIVE" if danger else "read-only"
        print(f"\n{color}{BOLD}┌─ Generated command [{tag}] ─{RESET}")
        print(f"{color}│{RESET} {BOLD}{result['command']}{RESET}")
        print(f"{color}│{RESET} {result['explanation']}")
        if needs_perm:
            print(f"{YELLOW}│ ⚠ Targets a path you may not own.{RESET}")
        print(f"{color}└{'─' * 30}{RESET}\n")


def confirm(prompt="Run this command? [y/N/e(dit)]: ") -> str:
    """Returns 'yes', 'no', or 'edit'."""
    choice = input(prompt).strip().lower()
    if choice in ("y", "yes"):
        return "yes"
    if choice in ("e", "edit"):
        return "edit"
    return "no"


# ---------------------------------------------------------------------------
# Execution + self-correction wiring
# ---------------------------------------------------------------------------
def execute_command(command: str) -> tuple[int, str, str]:
    """Runs the command, returns (returncode, stdout, stderr)."""
    proc = subprocess.run(command, shell=True, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def run_interactive_loop(state_context_fn):
    """
    state_context_fn: a callable (provided by Dev B) that returns the current
    state string, e.g. "USER: sanchit, CWD: /home/sanchit, OS: Ubuntu 22.04"
    Called fresh each turn so CWD/user changes are picked up.
    """
    print(f"{BOLD}symbioshell{RESET} — type a request in plain English ('exit' to quit)\n")

    while True:
        try:
            user_input = input(f"{CYAN}➜{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        context = state_context_fn()

        with spinner("Generating command..."):
            result = generate_command(user_input, context)

        show_result(result)

        if not result.get("command"):
            continue

        action = confirm()

        if action == "no":
            print("Skipped.\n")
            continue

        if action == "edit":
            edited = input(f"Edit command: {result['command']}\n> ").strip()
            if edited:
                result["command"] = edited

        with spinner("Running..."):
            code, out, err = execute_command(result["command"])

        if out:
            print(out)

        if code != 0:
            print(f"{RED}Command failed (exit {code}):{RESET} {err.strip()}")
            retry = input("Try self-correction? [y/N]: ").strip().lower()
            if retry == "y":
                with spinner("Self-correcting..."):
                    correction = handle_execution_error(user_input, context, result["command"], err)

                if correction.status == "not_retriable":
                    print(f"{YELLOW}⚠ {correction.message}{RESET}")
                elif correction.status == "gave_up":
                    print(f"{RED}✗ {correction.message}{RESET}")
                    for i, (cmd, e) in enumerate(correction.history, 1):
                        print(f"  attempt {i}: {cmd}  ->  {e.strip()}")
                else:  # fixed
                    print(f"{GREEN}Fixed after {correction.attempts} attempt(s).{RESET}")
                    show_result(correction.command)
                    if confirm("Run the corrected command? [y/N]: ") == "yes":
                        code2, out2, err2 = execute_command(correction.command["command"])
                        if out2:
                            print(out2)
                        if code2 != 0:
                            print(f"{RED}Still failing:{RESET} {err2.strip()}")
        print()


if __name__ == "__main__":
    import os

    def dummy_state_context():
        # Placeholder until Dev B wires in real state telemetry
        return f"USER: {os.getenv('USER', 'unknown')}, CWD: {os.getcwd()}, OS: Ubuntu 22.04"

    run_interactive_loop(dummy_state_context)
