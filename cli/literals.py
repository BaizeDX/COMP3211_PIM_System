"""Private quoted-value decoder shared by commands and save-path prompts."""

from pathlib import Path

from cli.errors import CommandError


_LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")


def _read_literal(text: str, start: int) -> tuple[str, int]:
    """Decode exactly one quoted literal, allowing only quote/backslash escapes."""
    if start >= len(text) or text[start] != '"':
        raise CommandError('Expected a double-quoted value, for example "text".')
    characters = []
    index = start + 1
    while index < len(text):
        character = text[index]
        if character in _LINE_BREAKS:
            raise CommandError("Line breaks are invalid. Expected a single-line quoted value.")
        if character == '"':
            return "".join(characters), index + 1
        if character == "\\":
            index += 1
            if index == len(text) or text[index] not in ('"', "\\"):
                raise CommandError(
                    "Unsupported or incomplete escape. "
                    "Only escaped double quotes and backslashes are allowed."
                )
            character = text[index]
        characters.append(character)
        index += 1
    raise CommandError("Unclosed quoted value. Expected a closing double quote.")


def _parse_path(text: str) -> Path:
    """Parse one quoted path without performing model/file validation."""
    if any(character in _LINE_BREAKS for character in text):
        raise CommandError("Expected a single-line quoted file path.")
    value, end = _read_literal(text, len(text) - len(text.lstrip()))
    if text[end:].strip():
        raise CommandError('Unexpected extra arguments. Expected one quoted path: "file.pim".')
    if not value or "\0" in value:
        raise CommandError('Expected a nonempty quoted file path without null bytes.')
    return Path(value)
