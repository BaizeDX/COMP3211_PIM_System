"""Expression grammar and session-only saved criteria (Design section 6).

expression := or_expr
or_expr    := and_expr { "||" and_expr }
and_expr   := unary { "&&" unary }
unary      := "!" unary | "(" expression ")" | comparison
comparison := "type" "=" TYPE
            | TEXT_FIELD "~" STRING
            | TIME_FIELD ("<" | ">" | "=") STRING

Parsing constructs the entire validated tree before any record evaluation.
Only escaped double quotes and escaped backslashes are decoded in STRING.
"""

import re
from dataclasses import dataclass

from model.criteria import (
    TEXT_FIELDS,
    TIME_FIELDS,
    AndCriterion,
    NotCriterion,
    OrCriterion,
    SearchCriterion,
    TextCriterion,
    TimeCriterion,
    TypeCriterion,
)
from model.errors import ExpressionError, UnknownCriterionError, ValidationError
from model.literals import LiteralSyntaxError, read_quoted_literal
from model.records import RecordType
from model.validation import parse_time


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
# Bound nesting below typical interpreter recursion limits (each paren level uses
# several call frames through or/and/unary). Keep RecursionError as a safety net.
_MAX_EXPRESSION_DEPTH = 200


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    value: str
    position: int


def _read_string(expression: str, start: int) -> tuple[_Token, int]:
    try:
        value, end = read_quoted_literal(expression, start)
    except LiteralSyntaxError as error:
        if error.kind == "line_break":
            raise ExpressionError(
                f"Line break in quoted literal at character {error.position + 1}."
            ) from error
        if error.kind == "bad_escape":
            raise ExpressionError(
                f"Unsupported or incomplete escape at character {error.position}. "
                "Only escaped double quotes and backslashes are allowed."
            ) from error
        if error.kind == "unclosed":
            raise ExpressionError(
                f"Unclosed quoted literal at character {start + 1}."
            ) from error
        raise ExpressionError(error.reason) from error
    return _Token("STRING", value, start), end


def _tokenize(expression: str) -> tuple[_Token, ...]:
    tokens = []
    index = 0
    while index < len(expression):
        character = expression[index]
        if character.isspace():
            index += 1
        elif character == '"':
            token, index = _read_string(expression, index)
            tokens.append(token)
        elif expression[index:index + 2] in ("&&", "||"):
            symbol = expression[index:index + 2]
            tokens.append(_Token(symbol, symbol, index))
            index += 2
        elif character in "~<>=!()":
            tokens.append(_Token(character, character, index))
            index += 1
        else:
            match = _IDENTIFIER.match(expression, index)
            if match is None:
                raise ExpressionError(
                    f"Unexpected character {character!r} at character {index + 1}."
                )
            tokens.append(_Token("IDENTIFIER", match.group(), index))
            index = match.end()
    tokens.append(_Token("END", "", len(expression)))
    return tuple(tokens)


class _ExpressionReader:
    """Private recursive-descent state belonging to exactly one parse call."""

    def __init__(self, tokens: tuple[_Token, ...]) -> None:
        self._tokens = tokens
        self._index = 0
        self._paren_depth = 0

    @property
    def _current(self) -> _Token:
        return self._tokens[self._index]

    def _accept(self, kind: str) -> bool:
        if self._current.kind != kind:
            return False
        self._index += 1
        return True

    def _expected(self, description: str) -> ExpressionError:
        found = repr(self._current.value) if self._current.kind != "END" else "end of input"
        return ExpressionError(
            f"Expected {description} at character {self._current.position + 1}; found {found}."
        )

    def _expect(self, kind: str, description: str) -> _Token:
        token = self._current
        if not self._accept(kind):
            raise self._expected(description)
        return token

    def _too_deep(self) -> ExpressionError:
        return ExpressionError("Search expression nesting is too deep.")

    def _parse(self) -> SearchCriterion:
        root = self._or_expr()
        self._expect("END", "end of expression")
        return root

    def _or_expr(self) -> SearchCriterion:
        root = self._and_expr()
        while self._accept("||"):
            root = OrCriterion(root, self._and_expr())
        return root

    def _and_expr(self) -> SearchCriterion:
        root = self._unary()
        while self._accept("&&"):
            root = AndCriterion(root, self._unary())
        return root

    def _unary(self) -> SearchCriterion:
        # Flatten ! chains iteratively so deep negation does not grow the call stack.
        not_count = 0
        while self._accept("!"):
            not_count += 1
            if not_count > _MAX_EXPRESSION_DEPTH:
                raise self._too_deep()
        if self._accept("("):
            self._paren_depth += 1
            if self._paren_depth > _MAX_EXPRESSION_DEPTH:
                raise self._too_deep()
            try:
                root = self._or_expr()
                self._expect(")", "closing parenthesis")
            finally:
                self._paren_depth -= 1
        else:
            root = self._comparison()
        for _ in range(not_count):
            root = NotCriterion(root)
        return root

    def _comparison(self) -> SearchCriterion:
        field = self._expect("IDENTIFIER", "a field name").value
        if field == "type":
            self._expect("=", "= after type")
            value = self._expect("IDENTIFIER", "PLAIN_TEXT, TASK, EVENT or CONTACT").value
            try:
                kind = RecordType(value)
            except ValueError as error:
                raise ExpressionError(f"Unknown record type {value!r}.") from error
            return TypeCriterion(kind)
        if field in TEXT_FIELDS:
            self._expect("~", "~ after a text field")
            return TextCriterion(field, self._expect("STRING", "a double-quoted substring").value)
        if field in TIME_FIELDS:
            operator = self._current.kind
            if operator not in ("<", ">", "="):
                raise self._expected("<, > or = after a time field")
            self._index += 1
            value = self._expect("STRING", "a double-quoted YYYY-MM-DD HH:MM time").value
            try:
                time_value = parse_time(value)
            except ValidationError as error:
                raise ExpressionError(f"Invalid {field} comparison. {error.reason}") from error
            return TimeCriterion(field, operator, time_value)
        raise ExpressionError(f"Unknown search field {field!r}.")


class ExpressionParser:
    """Stateless public parser; invalid expressions raise ExpressionError."""

    __slots__ = ()

    def parse(self, expression: str) -> SearchCriterion:
        """Return a fully validated immutable AST, requiring complete input consumption."""
        if not isinstance(expression, str):
            raise ExpressionError("Search expression must be text.")
        try:
            return _ExpressionReader(_tokenize(expression))._parse()
        except RecursionError as error:
            raise ExpressionError("Search expression nesting is too deep.") from error


@dataclass(frozen=True, slots=True)
class SavedCriterion:
    """Registry-created immutable definition; no record snapshots or persistence data."""

    id: str
    expression: str
    root: SearchCriterion


class CriteriaRegistry:
    """Session definitions with monotonic C IDs and no result cache or file operations."""

    def __init__(self, parser: ExpressionParser) -> None:
        self._parser = parser
        self._items: dict[str, SavedCriterion] = {}
        self._next_id = 1

    def define(self, expression: str) -> SavedCriterion:
        """Parse before allocating an ID; ExpressionError leaves the registry unchanged."""
        root = self._parser.parse(expression)
        item = SavedCriterion(f"C{self._next_id}", expression, root)
        self._items[item.id] = item
        self._next_id += 1
        return item

    def get(self, criterion_id: str) -> SavedCriterion:
        """Return an existing definition or raise UnknownCriterionError, without mutation."""
        if not isinstance(criterion_id, str) or criterion_id not in self._items:
            raise UnknownCriterionError(f"Unknown criterion {criterion_id!r}.")
        return self._items[criterion_id]

    def all(self) -> tuple[SavedCriterion, ...]:
        """Return an immutable snapshot in numeric C-ID order."""
        return tuple(sorted(self._items.values(), key=lambda item: int(item.id[1:])))
