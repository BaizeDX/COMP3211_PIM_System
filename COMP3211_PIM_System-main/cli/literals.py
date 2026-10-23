"""Quoted-value decoder for commands and save-path prompts (Design section 7)."""

from pathlib import Path

from cli.errors import CommandError
from model.literals import LINE_BREAKS, LiteralSyntaxError, read_quoted_literal


def _read_literal(text: str, start: int) -> tuple[str, int]:
    """Decode exactly one quoted literal, allowing only quote/backslash escapes."""
    try:
        return read_quoted_literal(text, start)
    except LiteralSyntaxError as error:
        raise CommandError(error.reason) from error


def _parse_path(text: str) -> Path:
    """Parse one quoted path without performing model/file validation."""
    if any(character in LINE_BREAKS for character in text):
        raise CommandError("Expected a single-line quoted file path.")
    value, end = _read_literal(text, len(text) - len(text.lstrip()))
    if text[end:].strip():
        raise CommandError('Unexpected extra arguments. Expected one quoted path: "file.pim".')
    if not value or "\0" in value:
        raise CommandError('Expected a nonempty quoted file path without null bytes.')
    return Path(value)
