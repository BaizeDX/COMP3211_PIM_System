"""Record normalization and construction (SRS 5.3; Design 4.1).

These rules apply to stored record data. Search substrings must not use
normalize_text, since their whitespace and underscores have different rules.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from model.errors import ValidationError
from model.literals import LINE_BREAKS

if TYPE_CHECKING:
    from model.records import PIR, RecordType


# User-approved ID-range clarification: positive signed 64-bit record IDs.
MAX_RECORD_ID = 9223372036854775807

_TIME_PATTERN = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2})"
)
_MOBILE_PATTERN = re.compile(r"\+?[0-9]{1,15}")


def _single_line(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be text.")
    # Check before stripping, including line breaks at either end.
    if any(character in LINE_BREAKS for character in value):
        raise ValidationError(f"{label} must be a single line without line breaks.")
    return value.strip()


def normalize_text(value: str, label: str = "Text") -> str:
    """Trim outer whitespace; reject empty, blank/underscore-only or multiline text.

    Internal whitespace and Unicode are preserved. Raises ValidationError.
    Pass label to identify the affected field in error text (NFR1).
    """
    normalized = _single_line(value, label)
    if not normalized or all(
        character == "_" or character.isspace() for character in normalized
    ):
        raise ValidationError(
            f"{label} must contain more than whitespace and underscores."
        )
    return normalized


def parse_time(value: str) -> datetime:
    """Parse exact local YYYY-MM-DD HH:MM, years 0001-9999, without conversion.

    Past dates are valid. Raises ValidationError for syntax or calendar errors.
    """
    reason = "Expected a valid local date and time in YYYY-MM-DD HH:MM format."
    if not isinstance(value, str):
        raise ValidationError(reason)
    match = _TIME_PATTERN.fullmatch(value)
    if match is None:
        raise ValidationError(reason)
    try:
        return datetime(*(int(part) for part in match.groups()))
    except ValueError as error:
        raise ValidationError(reason) from error


def format_time(value: datetime) -> str:
    """Format a naive local minute as canonical YYYY-MM-DD HH:MM (zero-padded years)."""
    return (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d} "
        f"{value.hour:02d}:{value.minute:02d}"
    )


def normalize_mobile(value: str) -> str:
    """Trim outer whitespace; retain an optional + and 1-15 ASCII digits.

    Leading zeroes are preserved. Raises ValidationError; no subscriber lookup.
    """
    normalized = _single_line(value, "Mobile")
    if _MOBILE_PATTERN.fullmatch(normalized) is None:
        raise ValidationError("Mobile must contain an optional + and 1-15 ASCII digits.")
    return normalized


def _validate_record_id(record_id: int) -> None:
    if type(record_id) is not int or not 1 <= record_id <= MAX_RECORD_ID:
        # Never format the rejected value: arbitrary Python integers can exceed
        # the interpreter's safe decimal-conversion limit.
        raise ValidationError(
            f"Record ID must be an integer from 1 through {MAX_RECORD_ID}, "
            "excluding Boolean values."
        )


def _validate_datetime(value: datetime, field: str) -> None:
    if not isinstance(value, datetime):
        raise ValidationError(f"Invalid {field}. Expected a datetime value.")
    if value.tzinfo is not None or value.second != 0 or value.microsecond != 0:
        raise ValidationError(
            f"Invalid {field}. Expected a naive local datetime at minute precision."
        )


def build_record(
    record_id: int, kind: RecordType, fields: dict[str, str]
) -> PIR:
    """Validate exact business fields and construct a normalized immutable record.

    Time inputs are strings here; direct record constructors accept datetimes.
    Neither the supplied dictionary nor its values are mutated. ID and type are
    separate arguments, never editable business fields. Raises ValidationError.
    """
    # Records use the primitive validators above; defer this reverse import to
    # construction time to keep both modules independently importable.
    from model.records import Contact, Event, PlainText, RecordType, Task

    _validate_record_id(record_id)
    if not isinstance(kind, RecordType):
        raise ValidationError("Type must be PLAIN_TEXT, TASK, EVENT or CONTACT as a RecordType.")
    if not isinstance(fields, dict) or any(not isinstance(key, str) for key in fields):
        raise ValidationError("Business fields must be a dictionary with text field names.")

    record_class, names = {
        RecordType.PLAIN_TEXT: (PlainText, ("text",)),
        RecordType.TASK: (Task, ("description", "deadline")),
        RecordType.EVENT: (Event, ("description", "start", "alarm")),
        RecordType.CONTACT: (Contact, ("name", "address", "mobile")),
    }[kind]
    if set(fields) != set(names):
        raise ValidationError(
            f"Invalid fields for {kind.value}. Expected exactly: {', '.join(names)}."
        )

    values: dict[str, str | datetime] = {}
    for name in names:
        value = fields[name]
        try:
            if name in ("deadline", "start", "alarm"):
                values[name] = parse_time(value)
            elif name == "mobile":
                values[name] = normalize_mobile(value)
            else:
                values[name] = normalize_text(value, label=name[:1].upper() + name[1:])
        except ValidationError as error:
            raise ValidationError(f"Invalid {name}. {error.reason}") from error
    return record_class(record_id, **values)
