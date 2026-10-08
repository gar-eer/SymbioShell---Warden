#!/usr/bin/env python3
"""
Symbioshell CLI - Dev B: The Warden (System Telemetry & Semantic Sandbox Demonstration)
testing commit
"""

import sys
import json
import argparse
from warden import SemanticSandbox, SandboxDecision

def main():
    parser = argparse.ArgumentParser(description="Symbioshell - Dev B Warden (Telemetry & Semantic Sandbox)")
    parser.add_argument("command", nargs="*", help="Bash command to evaluate through Semantic Sandbox")
    parser.add_argument("--telemetry", action="store_true", help="Print system telemetry context string")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--cwd", help="Override working directory for evaluation")

    args = parser.parse_args()

    sandbox = SemanticSandbox()

    if args.telemetry and not args.command:
        prompt_str = sandbox.get_telemetry_prompt_string(custom_cwd=args.cwd)
        print("=== TELEMETRY CONTEXT ===")
        print(prompt_str)
        sys.exit(0)

    if not args.command:
        print("Symbioshell Warden CLI")
        print("Telemetry string:")
        print(f"  {sandbox.get_telemetry_prompt_string(custom_cwd=args.cwd)}")
        print("\nUsage examples:")
        print("  python cli.py 'ls -la /var/log'")
        print("  python cli.py 'rm -rf /'")
        print("  python cli.py --telemetry")
        sys.exit(0)

    full_cmd = " ".join(args.command)
    result = sandbox.evaluate(full_cmd, custom_cwd=args.cwd)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("\n" + "="*50)
        print("SYMBIOSHELL WARDEN EVALUATION")
        print("="*50)
        print(f"Command         : {result.command}")
        print(f"Decision        : {result.decision.value}")
        print(f"Allowed         : {result.allowed}")
        print(f"State           : {result.state.value}")
        print(f"State Detail    : {result.state_explanation}")
        print(f"Reason          : {result.reason}")
        if result.errors:
            print("Errors          :")
            for err in result.errors:
                print(f"  - {err}")
        if result.telemetry:
            print(f"Telemetry Prompt: {result.telemetry.to_prompt_string()}")
        print("="*50 + "\n")

    sys.exit(0 if result.allowed else 1)

if __name__ == "__main__":
    main()
