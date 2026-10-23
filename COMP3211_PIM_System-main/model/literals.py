"""Shared quoted-literal decoding for commands and search expressions.

Design section 7 requires command and search double-quoted literals to use the
same quote and backslash rules. Only escaped double quotes and escaped
backslashes are accepted.
"""

LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")


class LiteralSyntaxError(Exception):
    """Malformed quoted literal; callers map this to CommandError or ExpressionError."""

    def __init__(self, reason: str, *, kind: str, position: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.kind = kind
        self.position = position


def read_quoted_literal(text: str, start: int) -> tuple[str, int]:
    """Decode one double-quoted literal starting at start; return (value, end_index).

    end_index is the index after the closing quote. Raises LiteralSyntaxError.
    """
    if start >= len(text) or text[start] != '"':
        raise LiteralSyntaxError(
            'Expected a double-quoted value, for example "text".',
            kind="missing_open",
            position=start,
        )
    characters = []
    index = start + 1
    while index < len(text):
        character = text[index]
        if character in LINE_BREAKS:
            raise LiteralSyntaxError(
                "Line breaks are invalid. Expected a single-line quoted value.",
                kind="line_break",
                position=index,
            )
        if character == '"':
            return "".join(characters), index + 1
        if character == "\\":
            index += 1
            if index == len(text) or text[index] not in ('"', "\\"):
                raise LiteralSyntaxError(
                    "Unsupported or incomplete escape. Only escaped double quotes "
                    "and backslashes are allowed.",
                    kind="bad_escape",
                    position=index,
                )
            character = text[index]
        characters.append(character)
        index += 1
    raise LiteralSyntaxError(
        "Unclosed quoted value. Expected a closing double quote.",
        kind="unclosed",
        position=start,
    )
