"""
Dev A - The Translator
Converts natural language requests into structured shell command JSON.

Design goals:
  1. Force strict JSON output (no conversational text, no markdown fences)
  2. Include few-shot examples to reduce flag hallucination
  3. Bake in a destructive/read-write flag so Dev B's sandbox can gate execution
  4. Validate output; retry once with a corrective nudge if the model breaks format
"""

import json
import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# 1. SYSTEM PROMPT
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a shell command generator embedded inside a CLI tool.

You will receive:
  - A natural language request from the user
  - System state context (user, cwd, OS) appended by the host program

Your ONLY job is to output a single JSON object. Never output conversational
text, greetings, apologies, or markdown code fences. Your entire response
must be valid JSON and nothing else.

OUTPUT SCHEMA (all fields required):
{
  "command": "<the exact shell command to run>",
  "explanation": "<one sentence, plain language, explaining what it does>",
  "is_destructive": <true|false>,
  "requires_target_permission": <true|false>
}

Field rules:
- "command": a single valid command for the OS given in context. Do not
  invent flags that don't exist for that OS/tool. If unsure a flag exists,
  prefer a more common, well-documented alternative.
- "is_destructive": true if the command modifies, deletes, moves, or
  overwrites ANY system state (files, permissions, processes, packages,
  network config). false only for pure read operations (ls, cat, grep, ps,
  df, etc).
- "requires_target_permission": true if the command acts on a specific file
  or path the user does not clearly own or that lives outside their home
  directory (e.g. /etc, /var, another user's home).

If the request is ambiguous or missing a required target (e.g. "delete the
file" with no filename), set "command" to an empty string and use
"explanation" to state what additional information is needed. Never guess
a destructive target.

If the request cannot be mapped to a shell command at all, set "command" to
an empty string and explain why in "explanation".

EXAMPLES

User: list all files including hidden ones
Context: USER: sanchit, CWD: /home/sanchit, OS: Ubuntu 22.04
{"command": "ls -la", "explanation": "Lists all files in the current directory, including hidden ones.", "is_destructive": false, "requires_target_permission": false}

User: free up disk space by removing log files older than 7 days
Context: USER: root, CWD: /var/log, OS: Ubuntu 22.04
{"command": "find /var/log -name '*.log' -mtime +7 -delete", "explanation": "Deletes log files in /var/log that haven't been modified in the last 7 days.", "is_destructive": true, "requires_target_permission": true}

User: show me what's using port 8080
Context: USER: sanchit, CWD: /home/sanchit, OS: Ubuntu 22.04
{"command": "lsof -i :8080", "explanation": "Shows which process is listening on port 8080.", "is_destructive": false, "requires_target_permission": false}

User: delete the file
Context: USER: sanchit, CWD: /home/sanchit, OS: Ubuntu 22.04
{"command": "", "explanation": "Which file should be deleted? Please specify a filename or path.", "is_destructive": false, "requires_target_permission": false}

Respond with ONLY the JSON object. No preamble, no trailing text, no code fences.
"""

# ---------------------------------------------------------------------------
# 2. CORE CALL + VALIDATION
# ---------------------------------------------------------------------------
REQUIRED_KEYS = {"command", "explanation", "is_destructive", "requires_target_permission"}


def _strip_fences(text: str) -> str:
    """Defensive cleanup in case the model wraps JSON in ```json fences anyway."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _validate(obj: dict) -> bool:
    if not isinstance(obj, dict):
        return False
    if not REQUIRED_KEYS.issubset(obj.keys()):
        return False
    if not isinstance(obj["command"], str) or not isinstance(obj["explanation"], str):
        return False
    if not isinstance(obj["is_destructive"], bool):
        return False
    if not isinstance(obj["requires_target_permission"], bool):
        return False
    return True


def generate_command(user_request: str, state_context: str, retry: bool = True) -> dict:
    """
    user_request: raw natural language from the user
    state_context: string built by Dev B, e.g. "USER: root, CWD: /var/log, OS: Ubuntu 22.04"
    Returns a validated dict matching the schema, or an error dict.
    """
    user_message = f"User: {user_request}\nContext: {state_context}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    cleaned = _strip_fences(raw_text)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None

    if parsed is not None and _validate(parsed):
        return parsed

    if retry:
        # One corrective retry: tell the model exactly what it did wrong
        correction_prompt = (
            f"Your previous response was not valid JSON matching the schema. "
            f"Your previous output was:\n{raw_text}\n\n"
            f"Return ONLY the corrected JSON object, nothing else."
        )
        response2 = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": raw_text},
                {"role": "user", "content": correction_prompt},
            ],
        )
        raw_text2 = "".join(
            block.text for block in response2.content if block.type == "text"
        )
        cleaned2 = _strip_fences(raw_text2)
        try:
            parsed2 = json.loads(cleaned2)
            if _validate(parsed2):
                return parsed2
        except json.JSONDecodeError:
            pass

    return {
        "command": "",
        "explanation": "Failed to generate a valid command after retry. Please rephrase your request.",
        "is_destructive": False,
        "requires_target_permission": False,
        "error": True,
    }


# ---------------------------------------------------------------------------
# 3. SELF-CORRECTION LOOP (for after execution, not generation)
#    Call this when Dev B's sandbox actually runs the command and it fails.
# ---------------------------------------------------------------------------
def self_correct(user_request: str, state_context: str, failed_command: str,
                  terminal_error: str, max_retries: int = 2) -> dict:
    """
    Feed a failed command + its terminal error back to the LLM for correction.
    Returns a new validated command dict.
    """
    correction_context = (
        f"User: {user_request}\n"
        f"Context: {state_context}\n\n"
        f"The command \"{failed_command}\" was executed and failed with this error:\n"
        f"{terminal_error}\n\n"
        f"Generate a corrected command that fixes this error. "
        f"Respond with ONLY the JSON object per the schema."
    )

    attempt = 0
    last_result = None
    while attempt < max_retries:
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": correction_context}],
        )
        raw_text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        cleaned = _strip_fences(raw_text)
        try:
            parsed = json.loads(cleaned)
            if _validate(parsed):
                return parsed
        except json.JSONDecodeError:
            pass
        attempt += 1

    return {
        "command": "",
        "explanation": f"Could not self-correct after {max_retries} attempts.",
        "is_destructive": False,
        "requires_target_permission": False,
        "error": True,
    }


# ---------------------------------------------------------------------------
# Quick manual test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ctx = "USER: sanchit, CWD: /home/sanchit, OS: Ubuntu 22.04"
    result = generate_command("show me all running python processes", ctx)
    print(json.dumps(result, indent=2))
