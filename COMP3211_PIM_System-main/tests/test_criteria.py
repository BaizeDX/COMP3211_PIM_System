"""SRS FR12-FR16 / Design 5: leaf and Composite predicate contracts."""

import unittest
from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timedelta, timezone

from model.criteria import (
    AndCriterion,
    NotCriterion,
    OrCriterion,
    SearchCriterion,
    TextCriterion,
    TimeCriterion,
    TypeCriterion,
)
from model.errors import ExpressionError
from model.records import Contact, Event, PlainText, RecordType, Task


class _ProbeCriterion(SearchCriterion):
    """Test double recording evaluation order and detecting skipped branches."""

    def __init__(self, result, calls, label, fail=False):
        self.result = result
        self.calls = calls
        self.label = label
        self.fail = fail

    def matches(self, record):
        self.calls.append(self.label)
        if self.fail:
            raise AssertionError("This operand should have been skipped.")
        return self.result


class LeafCriterionTests(unittest.TestCase):
    def setUp(self):
        self.time = datetime(2026, 11, 20, 20)
        self.records = (
            PlainText(1, 'Alpha  _βeta "quoted" C:\\notes && ! (literal).* 中\tend'),
            Task(2, "COMP3211 report", self.time),
            Event(3, "COMP3211 meeting", self.time, self.time - timedelta(hours=1)),
            Contact(4, "王", "香港 Address", "+00123"),
        )

    def test_search_criterion_is_abstract(self):
        """The common interface cannot be instantiated without matches."""
        with self.assertRaises(TypeError):
            SearchCriterion()

    def test_type_matches_each_supported_type(self):
        """FR12: a type predicate is true for exactly the corresponding PIR type."""
        for kind in RecordType:
            criterion = TypeCriterion(kind)
            with self.subTest(kind=kind):
                self.assertEqual(
                    [record.type for record in self.records if criterion.matches(record)],
                    [kind],
                )

    def test_invalid_type_constructor_values(self):
        """Direct construction requires the enum, never a string/unknown value."""
        for value in ("TASK", "task", None, True, 1, [], {}):
            with self.subTest(value=value), self.assertRaises(ExpressionError):
                TypeCriterion(value)

    def test_literal_substrings_are_case_sensitive_without_patterns(self):
        """FR13: quotes, slashes, operators and regex-like symbols remain literal."""
        record = self.records[0]
        for value in ("Alpha", "  ", "_", "βeta", '"quoted"', "\\notes", "&& !", ".*", "中\t"):
            with self.subTest(value=value):
                self.assertTrue(TextCriterion("text", value).matches(record))
        for value in ("alpha", "A*", "A.*β", "beta", "missing"):
            with self.subTest(value=value):
                self.assertFalse(TextCriterion("text", value).matches(record))

    def test_every_text_field_and_shared_description(self):
        """FR13: all five text fields work; description belongs to Task and Event."""
        cases = (
            ("text", "Alpha", [1]),
            ("description", "COMP3211", [2, 3]),
            ("name", "王", [4]),
            ("address", "Address", [4]),
            ("mobile", "001", [4]),
        )
        for field, substring, expected in cases:
            with self.subTest(field=field):
                criterion = TextCriterion(field, substring)
                self.assertEqual(
                    [record.id for record in self.records if criterion.matches(record)],
                    expected,
                )

    def test_substring_is_preserved_without_trimming_or_unicode_normalization(self):
        """Whitespace/underscores are valid; Unicode code points are compared literally."""
        criterion = TextCriterion("text", " _ ")
        self.assertEqual(criterion.substring, " _ ")
        self.assertTrue(criterion.matches(PlainText(1, "x _ y")))
        self.assertFalse(criterion.matches(PlainText(2, "x_y")))
        self.assertTrue(TextCriterion("text", "\t").matches(PlainText(3, "x\ty")))
        self.assertFalse(TextCriterion("text", "é").matches(PlainText(4, "e\u0301")))

    def test_invalid_text_field_names_and_substrings(self):
        """FR17: constructor validation is independent of any expression parser."""
        for field in ("deadline", "type", "id", "Text", "unknown", None, []):
            with self.subTest(field=field), self.assertRaises(ExpressionError):
                TextCriterion(field, "x")
        for value in ("", None, 1, True, [], "\n", "x\r", "x\u2028y", "\x85x"):
            with self.subTest(substring=value), self.assertRaises(ExpressionError):
                TextCriterion("text", value)

    def test_all_time_fields_and_comparisons(self):
        """FR14: compare the entire calendar minute for deadline, start and alarm."""
        for field, record, stored in (
            ("deadline", self.records[1], self.time),
            ("start", self.records[2], self.time),
            ("alarm", self.records[2], self.time - timedelta(hours=1)),
        ):
            for delta in (-1441, -1, 0, 1, 1441):
                given = stored + timedelta(minutes=delta)
                for operator, expected in (
                    ("<", stored < given), (">", stored > given), ("=", stored == given),
                ):
                    with self.subTest(field=field, delta=delta, operator=operator):
                        self.assertEqual(
                            TimeCriterion(field, operator, given).matches(record), expected
                        )

    def test_missing_fields_are_false_for_text_and_every_time_operator(self):
        """FR16: absent fields are false, including time equality and inequality."""
        contact = self.records[3]
        self.assertFalse(TextCriterion("description", "report").matches(contact))
        for field in ("deadline", "start", "alarm"):
            for operator in ("<", ">", "="):
                with self.subTest(field=field, operator=operator):
                    self.assertFalse(TimeCriterion(field, operator, self.time).matches(contact))

    def test_invalid_time_fields_operators_and_datetime_values(self):
        """FR17: direct time conditions enforce the documented field/operator/value types."""
        for field in ("text", "description", "type", "id", "Deadline", None, []):
            with self.subTest(field=field), self.assertRaises(ExpressionError):
                TimeCriterion(field, "<", self.time)
        for operator in ("<=", ">=", "!=", "==", "~", "before", None, [], 1):
            with self.subTest(operator=operator), self.assertRaises(ExpressionError):
                TimeCriterion("deadline", operator, self.time)
        for value in (
            "2026-11-20 20:00", date(2026, 11, 20), None, True,
            self.time.replace(second=1), self.time.replace(microsecond=1),
            self.time.replace(tzinfo=timezone.utc),
        ):
            with self.subTest(time=value), self.assertRaises(ExpressionError):
                TimeCriterion("deadline", "=", value)

    def test_extreme_time_values_and_equal_minute(self):
        """Past times and years 0001/9999 remain valid search operands."""
        for value in (datetime(1, 1, 1), datetime(9999, 12, 31, 23, 59)):
            with self.subTest(value=value):
                self.assertTrue(TimeCriterion("deadline", "=", value).matches(Task(1, "x", value)))


class CompositeCriterionTests(unittest.TestCase):
    def setUp(self):
        self.record = PlainText(1, "note")

    def test_boolean_truth_tables(self):
        """FR15: AND/OR/NOT implement ordinary Boolean truth values."""
        for left in (False, True):
            for right in (False, True):
                lhs = _ProbeCriterion(left, [], "left")
                rhs = _ProbeCriterion(right, [], "right")
                with self.subTest(left=left, right=right):
                    self.assertIs(AndCriterion(lhs, rhs).matches(self.record), left and right)
                    self.assertIs(OrCriterion(lhs, rhs).matches(self.record), left or right)
                    self.assertIs(NotCriterion(lhs).matches(self.record), not left)

    def test_short_circuit_skips_only_the_unneeded_operand(self):
        """Design 5.1: valid trees short-circuit during evaluation, not parsing."""
        for composite, left_value in ((AndCriterion, False), (OrCriterion, True)):
            calls = []
            left = _ProbeCriterion(left_value, calls, "left")
            right = _ProbeCriterion(False, calls, "right", fail=True)
            with self.subTest(composite=composite.__name__):
                self.assertIs(composite(left, right).matches(self.record), left_value)
                self.assertEqual(calls, ["left"])
        for composite, left_value in ((AndCriterion, True), (OrCriterion, False)):
            calls = []
            criterion = composite(
                _ProbeCriterion(left_value, calls, "left"),
                _ProbeCriterion(True, calls, "right"),
            )
            with self.subTest(composite=composite.__name__):
                self.assertTrue(criterion.matches(self.record))
                self.assertEqual(calls, ["left", "right"])

    def test_nested_composition_and_missing_field_negation(self):
        """FR15-FR16: a Contact satisfies a negated missing deadline comparison."""
        contact = Contact(4, "Name", "Address", "00123")
        missing = TimeCriterion("deadline", "<", datetime(2026, 11, 20, 20))
        self.assertTrue(NotCriterion(missing).matches(contact))
        restricted = AndCriterion(TypeCriterion(RecordType.TASK), NotCriterion(missing))
        self.assertFalse(restricted.matches(contact))
        self.assertTrue(OrCriterion(restricted, TextCriterion("mobile", "001")).matches(contact))
        self.assertFalse(NotCriterion(NotCriterion(missing)).matches(contact))

    def test_invalid_children_are_rejected_at_construction(self):
        """All public Composite constructors reject objects without the criterion contract."""
        valid = TypeCriterion(RecordType.PLAIN_TEXT)
        for invalid in (None, True, "x", [], object()):
            for constructor, arguments in (
                (AndCriterion, (valid, invalid)), (AndCriterion, (invalid, valid)),
                (OrCriterion, (valid, invalid)), (OrCriterion, (invalid, valid)),
                (NotCriterion, (invalid,)),
            ):
                with self.subTest(constructor=constructor.__name__, invalid=invalid):
                    with self.assertRaises(ExpressionError):
                        constructor(*arguments)

    def test_all_six_criterion_types_are_immutable(self):
        """Design 5: public fields are read-only, including all child references."""
        leaf = TypeCriterion(RecordType.PLAIN_TEXT)
        criteria = (
            leaf, TextCriterion("text", " "), TimeCriterion("start", "=", datetime(1, 1, 1)),
            AndCriterion(leaf, leaf), OrCriterion(leaf, leaf), NotCriterion(leaf),
        )
        for criterion in criteria:
            for field in fields(criterion):
                original = getattr(criterion, field.name)
                with self.subTest(kind=type(criterion).__name__, field=field.name):
                    with self.assertRaises(FrozenInstanceError):
                        setattr(criterion, field.name, original)
                    with self.assertRaises(FrozenInstanceError):
                        delattr(criterion, field.name)
            self.assertFalse(hasattr(criterion, "__dict__"))

    def test_evaluation_does_not_change_record_fields(self):
        """FR11 support: repeated matching neither edits the record nor caches its result."""
        before = self.record.business_fields()
        criterion = AndCriterion(
            TypeCriterion(RecordType.PLAIN_TEXT), NotCriterion(TextCriterion("text", "_"))
        )
        self.assertTrue(criterion.matches(self.record))
        self.assertTrue(criterion.matches(self.record))
        self.assertEqual(self.record.business_fields(), before)


if __name__ == "__main__":
    unittest.main()
