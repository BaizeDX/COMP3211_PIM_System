"""Immutable PIR values and business-field interfaces (Design section 3)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from model.errors import ValidationError
from model.validation import (
    _validate_datetime,
    _validate_record_id,
    normalize_mobile,
    normalize_text,
)


class RecordType(Enum):
    """The four supported PIR types, using their exact persisted spellings."""

    PLAIN_TEXT = "PLAIN_TEXT"
    TASK = "TASK"
    EVENT = "EVENT"
    CONTACT = "CONTACT"


@dataclass(frozen=True, slots=True)
class PIR(ABC):
    """Abstract validated record; public fields are readable, not writable."""

    id: int
    type: RecordType = field(init=False)

    def __post_init__(self) -> None:
        _validate_record_id(self.id)
        for name, value in self.business_fields().items():
            if name in ("deadline", "start", "alarm"):
                _validate_datetime(value, name)
            else:
                try:
                    if name == "mobile":
                        normalized = normalize_mobile(value)
                    else:
                        normalized = normalize_text(
                            value, label=name[:1].upper() + name[1:]
                        )
                except ValidationError as error:
                    raise ValidationError(f"Invalid {name}. {error.reason}") from error
                # Frozen values may be normalized only while being constructed.
                object.__setattr__(self, name, normalized)

    @abstractmethod
    def business_fields(self) -> dict[str, str | datetime]:
        """Return a fresh mapping in design field order, excluding ID/type."""

    def duplicate_key(self) -> tuple[object, ...]:
        """Return type and normalized business values; deliberately exclude ID."""
        return (self.type, *self.business_fields().values())


@dataclass(frozen=True, slots=True)
class PlainText(PIR):
    """A single-line Unicode note. Invalid constructor values raise ValidationError."""

    text: str
    type: RecordType = field(default=RecordType.PLAIN_TEXT, init=False)

    def business_fields(self) -> dict[str, str | datetime]:
        return {"text": self.text}


@dataclass(frozen=True, slots=True)
class Task(PIR):
    """A description and local deadline, validated even on direct construction."""

    description: str
    deadline: datetime
    type: RecordType = field(default=RecordType.TASK, init=False)

    def business_fields(self) -> dict[str, str | datetime]:
        return {"description": self.description, "deadline": self.deadline}


@dataclass(frozen=True, slots=True)
class Event(PIR):
    """An event with stored alarm <= start; no notification behaviour."""

    description: str
    start: datetime
    alarm: datetime
    type: RecordType = field(default=RecordType.EVENT, init=False)

    def __post_init__(self) -> None:
        # Explicit base call avoids zero-argument super with slotted dataclasses.
        PIR.__post_init__(self)
        if self.alarm > self.start:
            raise ValidationError("Event alarm must be earlier than or equal to start.")

    def business_fields(self) -> dict[str, str | datetime]:
        return {"description": self.description, "start": self.start, "alarm": self.alarm}


@dataclass(frozen=True, slots=True)
class Contact(PIR):
    """A name, address and textual mobile number with preserved leading zeroes."""

    name: str
    address: str
    mobile: str
    type: RecordType = field(default=RecordType.CONTACT, init=False)

    def business_fields(self) -> dict[str, str | datetime]:
        return {"name": self.name, "address": self.address, "mobile": self.mobile}
