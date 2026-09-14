import shlex
import re
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class ParsedCommand:
    raw: str
    tokens: List[str]
    binary: str
    args: List[str]
    input_redirections: List[str] = field(default_factory=list)
    output_redirections: List[str] = field(default_factory=list)
    is_pipeline: bool = False
    operator: Optional[str] = None  # ';', '&&', '||', '|'

class BashParser:
    """
    Parser for bash command strings, splitting pipelines and sub-commands,
    extracting tokens, binaries, flags, and redirection paths.
    """

    # Regex to split on major bash control operators outside of quotes
    OPERATOR_SPLIT_REGEX = re.compile(r'(\&\&|\|\||\||;)')

    @classmethod
    def parse_full_command(cls, command_str: str) -> List[ParsedCommand]:
        """
        Parses a complex bash command string (potentially with ;, &&, ||, |)
        into a list of ParsedCommand objects.
        """
        command_str = command_str.strip()
        if not command_str:
            return []

        # Split into segments while preserving operators
        segments = cls._split_operators(command_str)
        parsed_list = []

        current_op = None
        for item in segments:
            item_str = item.strip()
            if item_str in ('&&', '||', '|', ';'):
                current_op = item_str
                if parsed_list:
                    parsed_list[-1].operator = current_op
                continue

            parsed_cmd = cls._parse_single_command(item_str)
            if current_op == '|':
                parsed_cmd.is_pipeline = True
            parsed_list.append(parsed_cmd)
            current_op = None

        return parsed_list

    @classmethod
    def _split_operators(cls, command_str: str) -> List[str]:
        """Splits shell string by control operators outside quotes."""
        # Simple lexer-assisted splitter
        parts = []
        current = []
        in_single = False
        in_double = False
        i = 0
        n = len(command_str)

        while i < n:
            char = command_str[i]
            if char == "'" and not in_double:
                in_single = not in_single
                current.append(char)
            elif char == '"' and not in_single:
                in_double = not in_double
                current.append(char)
            elif not in_single and not in_double:
                # Check 2-char operators &&, ||
                if i + 1 < n and command_str[i:i+2] in ('&&', '||'):
                    if current:
                        parts.append("".join(current))
                        current = []
                    parts.append(command_str[i:i+2])
                    i += 2
                    continue
                # Check 1-char operators |, ;
                elif char in ('|', ';'):
                    if current:
                        parts.append("".join(current))
                        current = []
                    parts.append(char)
                    i += 1
                    continue
                else:
                    current.append(char)
            else:
                current.append(char)
            i += 1

        if current:
            parts.append("".join(current))

        return parts

    @classmethod
    def _parse_single_command(cls, cmd_str: str) -> ParsedCommand:
        """Parses a single non-chained bash command segment."""
        raw = cmd_str
        try:
            raw_tokens = shlex.split(cmd_str, posix=True)
        except ValueError:
            # Fallback if unclosed quote
            raw_tokens = cmd_str.split()

        tokens = []
        input_redirs = []
        output_redirs = []

        i = 0
        n = len(raw_tokens)
        while i < n:
            token = raw_tokens[i]
            # Output redirections: >, >>, 1>, 2>, &>
            if token in ('>', '>>', '1>', '2>', '&>', '1>>', '2>>'):
                if i + 1 < n:
                    output_redirs.append(raw_tokens[i+1])
                    i += 2
                    continue
            elif token.startswith('>') or token.startswith('>>'):
                # E.g. >out.txt
                target = token.lstrip('>')
                if target:
                    output_redirs.append(target)
                i += 1
                continue
            # Input redirections: <, <<
            elif token in ('<', '<<'):
                if i + 1 < n:
                    input_redirs.append(raw_tokens[i+1])
                    i += 2
                    continue
            else:
                tokens.append(token)
            i += 1

        binary = tokens[0] if tokens else ""
        args = tokens[1:] if len(tokens) > 1 else []

        return ParsedCommand(
            raw=raw,
            tokens=tokens,
            binary=binary,
            args=args,
            input_redirections=input_redirs,
            output_redirections=output_redirs
        )
