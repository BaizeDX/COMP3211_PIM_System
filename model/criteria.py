"""Immutable Composite search criteria (SRS FR12-FR16; Design section 5)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from model.errors import ExpressionError, ValidationError
from model.records import PIR, RecordType
from model.validation import _LINE_BREAKS, _validate_datetime


_TEXT_FIELDS = frozenset(("text", "description", "name", "address", "mobile"))
_TIME_FIELDS = frozenset(("deadline", "start", "alarm"))


class SearchCriterion(ABC):
    """A Boolean predicate on a valid PIR, with no terminal or collection state."""

    __slots__ = ()

    @abstractmethod
    def matches(self, record: PIR) -> bool:
        """Return a Boolean; validated criteria raise no expected evaluation error."""


@dataclass(frozen=True, slots=True)
class TypeCriterion(SearchCriterion):
    """Match an exact RecordType; invalid construction raises ExpressionError."""

    expected_type: RecordType

    def __post_init__(self) -> None:
        if not isinstance(self.expected_type, RecordType):
            raise ExpressionError("Type condition requires a supported RecordType.")

    def matches(self, record: PIR) -> bool:
        return record.type == self.expected_type


@dataclass(frozen=True, slots=True)
class TextCriterion(SearchCriterion):
    """Match a literal nonempty substring, preserving its case and whitespace."""

    field: str
    substring: str

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or self.field not in _TEXT_FIELDS:
            raise ExpressionError(
                "Text conditions require text, description, name, address or mobile."
            )
        if not isinstance(self.substring, str) or not self.substring:
            raise ExpressionError("Search substring must be nonempty text.")
        if any(character in _LINE_BREAKS for character in self.substring):
            raise ExpressionError("Search substring must not contain line breaks.")

    def matches(self, record: PIR) -> bool:
        fields = record.business_fields()
        return self.field in fields and self.substring in fields[self.field]


@dataclass(frozen=True, slots=True)
class TimeCriterion(SearchCriterion):
    """Compare a complete naive local minute; invalid construction raises ExpressionError."""

    field: str
    operator: str
    time_value: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or self.field not in _TIME_FIELDS:
            raise ExpressionError("Time conditions require deadline, start or alarm.")
        if self.operator not in ("<", ">", "="):
            raise ExpressionError("Time comparison operator must be <, > or =.")
        try:
            _validate_datetime(self.time_value, self.field)
        except ValidationError as error:
            raise ExpressionError(error.reason) from error

    def matches(self, record: PIR) -> bool:
        fields = record.business_fields()
        if self.field not in fields:
            return False
        value = fields[self.field]
        if self.operator == "<":
            return value < self.time_value
        if self.operator == ">":
            return value > self.time_value
        return value == self.time_value


def _require_child(child: SearchCriterion) -> None:
    if not isinstance(child, SearchCriterion):
        raise ExpressionError("Logical operands must be SearchCriterion objects.")


@dataclass(frozen=True, slots=True)
class AndCriterion(SearchCriterion):
    """Own two valid criteria and evaluate their conjunction with short-circuiting."""

    left: SearchCriterion
    right: SearchCriterion

    def __post_init__(self) -> None:
        _require_child(self.left)
        _require_child(self.right)

    def matches(self, record: PIR) -> bool:
        return _evaluate(self, record)


@dataclass(frozen=True, slots=True)
class OrCriterion(SearchCriterion):
    """Own two valid criteria and evaluate their disjunction with short-circuiting."""

    left: SearchCriterion
    right: SearchCriterion

    def __post_init__(self) -> None:
        _require_child(self.left)
        _require_child(self.right)

    def matches(self, record: PIR) -> bool:
        return _evaluate(self, record)


@dataclass(frozen=True, slots=True)
class NotCriterion(SearchCriterion):
    """Own one valid criterion and negate its Boolean result."""

    operand: SearchCriterion

    def __post_init__(self) -> None:
        _require_child(self.operand)

    def matches(self, record: PIR) -> bool:
        return _evaluate(self, record)


def _evaluate(root: SearchCriterion, record: PIR) -> bool:
    """Evaluate Composite trees without call-stack growth, retaining short-circuiting."""
    pending = [(root, False)]
    result = False
    while pending:
        node, resumed = pending.pop()
        operation = type(node).matches
        if resumed:
            if operation is NotCriterion.matches:
                result = not result
            elif (operation is AndCriterion.matches and result) or (
                operation is OrCriterion.matches and not result
            ):
                pending.append((node.right, False))
        elif operation in (AndCriterion.matches, OrCriterion.matches):
            pending.append((node, True))
            pending.append((node.left, False))
        elif operation is NotCriterion.matches:
            pending.append((node, True))
            pending.append((node.operand, False))
        else:
            # Honor custom matches overrides, including Composite subclasses.
            result = node.matches(record)
    return result
