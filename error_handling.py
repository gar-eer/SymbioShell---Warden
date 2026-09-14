"""
Dev A - The Translator
Part 3: Error Handling / Self-Correction Loop

The basic self_correct() in nl_shell_translator.py does a single feedback
pass. This module upgrades that with:

  1. Error classification - distinguish "the LLM guessed a bad flag/command"
     (worth retrying) from "permission denied / sandbox blocked it" (NOT
     worth retrying via LLM - that's Dev B's territory, surface it to the
     user directly instead).
  2. A multi-attempt loop that keeps the full history of failed attempts
     in context, so the model doesn't repeat the same wrong guess twice.
  3. A clean result object so cli_ux.py can tell the difference between
     "fixed it", "gave up", and "not my problem, this is a permissions issue".
"""

import re
import json
from dataclasses import dataclass, field

from nl_shell_translator import (
    client,
    MODEL,
    SYSTEM_PROMPT,
    _strip_fences,
    _validate,
)

MAX_CORRECTION_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# 1. Error classification
# ---------------------------------------------------------------------------
# Patterns that mean "the command itself was wrong" - LLM should retry.
TRANSLATION_ERROR_PATTERNS = [
    r"command not found",
    r"invalid option",
    r"unrecognized option",
    r"unknown option",
    r"illegal option",
    r"invalid argument",
    r"usage:",
    r"no such file or directory",  # often a typo'd path the LLM can fix
    r"is not recognized as an internal or external command",
]

# Patterns that mean "the environment/permissions blocked it" - don't retry
# via LLM, this needs a human decision or Dev B's sandbox logic.
ENVIRONMENT_ERROR_PATTERNS = [
    r"permission denied",
    r"operation not permitted",
    r"read-only file system",
    r"disk quota exceeded",
    r"authentication failure",
    r"connection refused",
    r"network is unreachable",
]


def classify_error(stderr: str) -> str:
    """
    Returns one of: "translation", "environment", "unknown"
    """
    text = stderr.lower()

    for pattern in ENVIRONMENT_ERROR_PATTERNS:
        if re.search(pattern, text):
            return "environment"

    for pattern in TRANSLATION_ERROR_PATTERNS:
        if re.search(pattern, text):
            return "translation"

    return "unknown"


# ---------------------------------------------------------------------------
# 2. Result object
# ---------------------------------------------------------------------------
@dataclass
class CorrectionResult:
    status: str  # "fixed", "gave_up", "not_retriable"
    command: dict = None
    attempts: int = 0
    message: str = ""
    history: list = field(default_factory=list)  # list of (command, error) tried


# ---------------------------------------------------------------------------
# 3. Multi-attempt self-correction loop
# ---------------------------------------------------------------------------
def handle_execution_error(
    user_request: str,
    state_context: str,
    failed_command: str,
    terminal_error: str,
    max_attempts: int = MAX_CORRECTION_ATTEMPTS,
) -> CorrectionResult:
    """
    Called by the CLI layer when a generated command fails at execution.
    Classifies the error first; only engages the LLM retry loop for
    translation-type errors (bad flags, typos, hallucinated syntax).
    """
    error_type = classify_error(terminal_error)

    if error_type == "environment":
        return CorrectionResult(
            status="not_retriable",
            message=(
                "This looks like a permissions or environment issue, not a "
                "bad command. Re-running through the LLM won't help - check "
                "with sudo/ownership or flag it to the sandbox layer."
            ),
        )

    history = [(failed_command, terminal_error)]
    current_command = failed_command
    current_error = terminal_error

    for attempt in range(1, max_attempts + 1):
        correction_prompt = _build_correction_prompt(
            user_request, state_context, history
        )

        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": correction_prompt}],
        )
        raw_text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        cleaned = _strip_fences(raw_text)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            history.append((current_command, "LLM returned invalid JSON, could not parse."))
            continue

        if not _validate(parsed):
            history.append((current_command, "LLM response missing required fields."))
            continue

        if not parsed.get("command"):
            # Model gave up / says it needs more info
            return CorrectionResult(
                status="gave_up",
                attempts=attempt,
                message=parsed.get("explanation", "Model could not generate a fix."),
                history=history,
            )

        # Avoid infinite loop on the exact same command being suggested again
        if parsed["command"] == current_command:
            history.append((current_command, current_error))
            continue

        return CorrectionResult(
            status="fixed",
            command=parsed,
            attempts=attempt,
            history=history,
        )

    return CorrectionResult(
        status="gave_up",
        attempts=max_attempts,
        message=f"Could not resolve after {max_attempts} attempts.",
        history=history,
    )


def _build_correction_prompt(user_request: str, state_context: str, history: list) -> str:
    """Builds a prompt that includes every previously failed attempt, so the
    model doesn't repeat the same mistake."""
    attempts_text = "\n".join(
        f'Attempt {i+1}: command="{cmd}" -> error: "{err.strip()}"'
        for i, (cmd, err) in enumerate(history)
    )

    return (
        f"User request: {user_request}\n"
        f"Context: {state_context}\n\n"
        f"Previous failed attempts (do NOT repeat these mistakes):\n"
        f"{attempts_text}\n\n"
        f"Generate a corrected command that avoids all of the above errors. "
        f"If you cannot determine a fix, set \"command\" to an empty string "
        f"and explain what information is needed. "
        f"Respond with ONLY the JSON object per the schema."
    )


# ---------------------------------------------------------------------------
# Quick manual test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ctx = "USER: sanchit, CWD: /home/sanchit, OS: Ubuntu 22.04"
    result = handle_execution_error(
        user_request="list files sorted by size",
        state_context=ctx,
        failed_command="ls -lS --sortbysize",
        terminal_error="ls: unrecognized option '--sortbysize'",
    )
    print(f"status: {result.status}")
    if result.command:
        print(json.dumps(result.command, indent=2))
    else:
        print(result.message)
