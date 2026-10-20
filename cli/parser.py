"""Stateless command grammar (Design section 7); no domain-value/search parsing."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cli.errors import CommandError
from cli.literals import _LINE_BREAKS, _parse_path, _read_literal
from model.records import RecordType


_COMMANDS = "create, update, show, delete, define, criteria, search, save, load, exit"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_CREATE_FIELDS = {
    RecordType.PLAIN_TEXT: {"text"},
    RecordType.TASK: {"description", "deadline"},
    RecordType.EVENT: {"description", "start", "alarm"},
    RecordType.CONTACT: {"name", "address", "mobile"},
}


@dataclass(frozen=True, slots=True, init=False)
class Command:
    """Immutable syntax carrier, defensively copying outer and nested field maps."""

    verb: str
    arguments: Mapping[str, object]

    def __init__(self, verb: str, arguments: dict[str, object]) -> None:
        copied = {
            key: MappingProxyType(dict(value)) if isinstance(value, Mapping) else value
            for key, value in arguments.items()
        }
        object.__setattr__(self, "verb", verb)
        object.__setattr__(self, "arguments", MappingProxyType(copied))


def _record_id(text: str) -> int:
    if not re.fullmatch(r"[0-9]+", text):
        raise CommandError("Invalid record ID. Expected a positive ASCII decimal integer.")
    try:
        result = int(text)
    except ValueError as error:
        raise CommandError(
            "Record ID is too long. Expected a positive decimal integer."
        ) from error
    if result <= 0:
        raise CommandError("Invalid record ID. Expected a positive ASCII decimal integer.")
    return result


def _assignments(text: str) -> dict[str, str]:
    fields = {}
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            break
        match = _IDENTIFIER.match(text, index)
        if match is None:
            raise CommandError('Expected field="value" assignments separated by whitespace.')
        field = match.group()
        index = match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text) or text[index] != "=":
            raise CommandError('Expected = after the field name: field="value".')
        index += 1
        while index < len(text) and text[index].isspace():
            index += 1
        value, index = _read_literal(text, index)
        if index < len(text) and not text[index].isspace():
            raise CommandError(
                "Expected whitespace between assignments; extra tokens are invalid."
            )
        if field in fields:
            raise CommandError(f"Repeated field {field!r}. Expected each field exactly once.")
        fields[field] = value
    return fields


class CommandParser:
    """Parse command syntax only; search expressions remain untouched model input."""

    def parse(self, line: str) -> Command:
        if not isinstance(line, str) or any(character in _LINE_BREAKS for character in line):
            raise CommandError("Expected one line of command text without line breaks.")
        parts = line.lstrip().split(maxsplit=1)
        if not parts:
            raise CommandError(f"Empty command. Expected one of: {_COMMANDS}.")
        verb = parts[0]
        # split(maxsplit=1) excludes separator whitespace but preserves the raw tail.
        tail = parts[1] if len(parts) == 2 else ""
        if verb in ("exit", "criteria"):
            if tail.strip():
                raise CommandError(f"Unexpected arguments. Expected {verb} alone.")
            return Command(verb, {})
        if verb in ("save", "load"):
            return Command(verb, {"path": _parse_path(tail)})
        if verb in ("define", "search"):
            if not tail.strip():
                raise CommandError(f"Expected {verb} followed by an expression.")
            if verb == "search" and tail.startswith("@"):
                if not re.fullmatch(r"@C[1-9][0-9]*", tail.strip()):
                    raise CommandError("Invalid saved reference. Expected search @C1, @C2, etc.")
                return Command(verb, {"criterion_id": tail.strip()[1:]})
            return Command(verb, {"expression": tail})
        if verb in ("show", "delete"):
            value = tail.strip()
            if verb == "show" and value == "all":
                return Command(verb, {})
            return Command(verb, {"record_id": _record_id(value)})
        if verb in ("create", "update"):
            values = tail.split(maxsplit=1)
            if len(values) != 2:
                syntax = 'create TYPE field="value" ...' if verb == "create" else (
                    'update ID field="value"'
                )
                raise CommandError(f"Incomplete command. Expected {syntax}.")
            fields = _assignments(values[1])
            if verb == "create":
                try:
                    kind = RecordType(values[0])
                except ValueError as error:
                    raise CommandError(
                        "Expected type PLAIN_TEXT, TASK, EVENT or CONTACT."
                    ) from error
                if set(fields) != _CREATE_FIELDS[kind]:
                    expected = ", ".join(sorted(_CREATE_FIELDS[kind]))
                    raise CommandError(
                        f"Invalid fields for {kind.value}. Expected exactly: {expected}."
                    )
                return Command(verb, {"kind": kind, "fields": fields})
            if len(fields) != 1:
                raise CommandError('Expected exactly one field: update ID field="value".')
            field, value = next(iter(fields.items()))
            return Command(verb, {
                "record_id": _record_id(values[0]), "field": field, "value": value,
            })
        raise CommandError(f"Unknown command {verb!r}. Expected one of: {_COMMANDS}.")
