"""SRS FR11-FR17, FR30-FR31 / Design 6: complete parsing and session criteria."""

import unittest
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime
from unittest.mock import patch

from model.criteria import (
    AndCriterion,
    NotCriterion,
    OrCriterion,
    SearchCriterion,
    TextCriterion,
    TimeCriterion,
    TypeCriterion,
)
from model.errors import ExpressionError, UnknownCriterionError
from model.records import Contact, Event, PlainText, RecordType, Task
from model.search import CriteriaRegistry, ExpressionParser, SavedCriterion


class ExpressionParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = ExpressionParser()
        self.time = datetime(2026, 11, 20, 20)
        self.records = (
            PlainText(1, "project _ notes"),
            Task(2, "COMP3211 report", self.time),
            Event(3, "COMP3211 meeting", self.time, datetime(2026, 11, 20, 19)),
            Contact(4, "王", "香港 Address", "+00123"),
        )

    def matching_ids(self, expression):
        root = self.parser.parse(expression)
        return [record.id for record in self.records if root.matches(record)]

    def test_each_type_comparison(self):
        """FR12: unquoted exact enum spellings create TypeCriterion leaves."""
        for kind in RecordType:
            with self.subTest(kind=kind):
                self.assertEqual(self.parser.parse("type = " + kind.value), TypeCriterion(kind))

    def test_every_text_field(self):
        """FR13: parser forwards every recognized text field to literal matching."""
        for field, value, expected in (
            ("text", "project", [1]), ("description", "COMP3211", [2, 3]),
            ("name", "王", [4]), ("address", "香港", [4]), ("mobile", "001", [4]),
        ):
            with self.subTest(field=field):
                self.assertEqual(self.matching_ids(f'{field} ~ "{value}"'), expected)

    def test_every_time_field_and_comparison_operator(self):
        """FR14: time literals become validated local datetime values."""
        for field in ("deadline", "start", "alarm"):
            for operator in ("<", ">", "="):
                with self.subTest(field=field, operator=operator):
                    self.assertEqual(
                        self.parser.parse(f'{field} {operator} "2026-11-20 20:00"'),
                        TimeCriterion(field, operator, self.time),
                    )

    def test_comparison_not_and_or_precedence_in_ast(self):
        """FR15: comparisons bind before !, which binds before &&, then ||."""
        root = self.parser.parse("!type = TASK && type = CONTACT || type = EVENT")
        self.assertEqual(
            root,
            OrCriterion(
                AndCriterion(
                    NotCriterion(TypeCriterion(RecordType.TASK)),
                    TypeCriterion(RecordType.CONTACT),
                ),
                TypeCriterion(RecordType.EVENT),
            ),
        )
        self.assertEqual([record.id for record in self.records if root.matches(record)], [3, 4])

    def test_grouping_changes_results_and_nested_parentheses_work(self):
        """FR15: parentheses override AND's stronger binding than OR."""
        self.assertEqual(self.matching_ids('type=TASK || type=EVENT && text~"x"'), [2])
        self.assertEqual(self.matching_ids('(type=TASK || type=EVENT) && text~"x"'), [])
        self.assertEqual(self.matching_ids('((type=TASK) || ((type=EVENT)))'), [2, 3])

    def test_repeated_negation_and_left_associative_chains(self):
        """Design 6.2 grammar: unary recurses and binary repetitions fold left."""
        leaf = TypeCriterion(RecordType.TASK)
        self.assertEqual(
            self.parser.parse("!!!type=TASK"), NotCriterion(NotCriterion(NotCriterion(leaf)))
        )
        for symbol, composite in (("&&", AndCriterion), ("||", OrCriterion)):
            expression = f"type=TASK {symbol} type=EVENT {symbol} type=CONTACT"
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    self.parser.parse(expression),
                    composite(
                        composite(leaf, TypeCriterion(RecordType.EVENT)),
                        TypeCriterion(RecordType.CONTACT),
                    ),
                )

    def test_symbol_spacing_and_literal_whitespace_are_independent(self):
        """Separating whitespace is ignored; literal contents are never trimmed."""
        root = self.parser.parse(' \t !( type = TASK )&&text ~ " _ "  ')
        self.assertEqual(
            root,
            AndCriterion(
                NotCriterion(TypeCriterion(RecordType.TASK)), TextCriterion("text", " _ ")
            ),
        )
        self.assertTrue(root.matches(self.records[0]))
        self.assertEqual(self.parser.parse('text~"  "'), TextCriterion("text", "  "))
        self.assertEqual(self.parser.parse('text~"___"'), TextCriterion("text", "___"))

    def test_escaped_quotes_backslashes_and_no_double_decoding(self):
        """Only \" and \\ escapes are decoded, exactly once."""
        expression = r'text ~ "say \"hi\" at C:\\notes"'
        root = self.parser.parse(expression)
        self.assertEqual(root, TextCriterion("text", 'say "hi" at C:\\notes'))
        self.assertTrue(root.matches(PlainText(1, 'say "hi" at C:\\notes')))
        self.assertEqual(self.parser.parse(r'text~"\\n"'), TextCriterion("text", r"\n"))
        self.assertEqual(self.parser.parse(r'text~"\\"'), TextCriterion("text", "\\"))
        self.assertEqual(self.parser.parse(r'text~"\""'), TextCriterion("text", '"'))

    def test_operator_characters_and_word_aliases_are_literal_inside_quotes(self):
        """Operators/keywords inside STRING never become syntax or regular expressions."""
        value = "&& || ! ( ) ~ < > = CONTAINS AND OR NOT .*"
        root = self.parser.parse(f'text ~ "{value}"')
        self.assertEqual(root, TextCriterion("text", value))
        self.assertTrue(root.matches(PlainText(1, "prefix " + value + " suffix")))

    def test_missing_field_negation_applies_after_atomic_false(self):
        """FR16: negation may include contacts unless a type restriction is supplied."""
        comparison = 'deadline < "2026-11-21 00:00"'
        self.assertEqual(self.matching_ids(comparison), [2])
        self.assertEqual(self.matching_ids("!(" + comparison + ")"), [1, 3, 4])
        self.assertEqual(self.matching_ids("type=TASK && !(" + comparison + ")"), [])

    def test_unknown_fields_types_and_case_mismatches(self):
        """FR17: unknown identifiers are errors rather than always-false conditions."""
        expressions = (
            'unknown ~ "x"', 'id = "1"', 'Type = TASK', "type = task",
            "type = UNKNOWN", 'Text ~ "x"', 'Deadline < "2026-11-20 20:00"',
            'type = "TASK"', '"type" = TASK',
        )
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaises(ExpressionError):
                self.parser.parse(expression)

    def test_textual_operator_aliases_are_rejected(self):
        """FR15: no textual aliases, in any capitalization, are accepted."""
        for word in ("CONTAINS", "contains", "AND", "and", "OR", "or", "NOT", "not"):
            expressions = (
                f'text {word} "note"', f"type=TASK {word} type=EVENT", f"{word} type=TASK",
            )
            for expression in expressions:
                with self.subTest(expression=expression), self.assertRaises(ExpressionError):
                    self.parser.parse(expression)

    def test_incompatible_and_unsupported_operators_are_rejected(self):
        """FR17: exact field/operator pairings, never <=, >=, !=, == or Python syntax."""
        expressions = (
            'text = "note"', 'description < "report"', 'mobile > "123"',
            'deadline ~ "2026-11-20 20:00"', "type ~ TASK", "type < TASK",
            "type == TASK", "type != TASK", 'deadline <= "2026-11-20 20:00"',
            'deadline >= "2026-11-20 20:00"', 'deadline != "2026-11-20 20:00"',
            'deadline == "2026-11-20 20:00"', "type=TASK & type=EVENT",
            "type=TASK | type=EVENT", "type=TASK &&& type=EVENT",
            "type=TASK ||| type=EVENT", "True", 'text in "note"',
        )
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaises(ExpressionError):
                self.parser.parse(expression)

    def test_malformed_structure_and_trailing_tokens_are_rejected(self):
        """Design 6.2: require operands, balanced groups and complete consumption."""
        expressions = (
            "", " \t ", "()", "!", "!!", "type", "type=", "type=TASK &&",
            "|| type=TASK", "(type=TASK", "type=TASK)", "type=TASK type=EVENT",
            'text~"x" "y"', 'text~"x" && ()', "type=TASK (type=EVENT)",
            '(type=TASK)(type=EVENT)', 'text~""', "text~x", "text~'x'",
            'deadline < 2026-11-20 20:00', "type=TASK;exit",
        )
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaises(ExpressionError):
                self.parser.parse(expression)

    def test_bad_escapes_unclosed_quotes_and_line_breaks_are_rejected(self):
        """Quoted literals allow no newline, generic escape decoder or incomplete escape."""
        expressions = (
            r'text~"\n"', r'text~"\t"', r'text~"\r"', r'text~"\u0041"',
            r'text~"\x41"', r'text~"\q"', r'text~"\/"', 'text~"unclosed',
            'text~"trailing' + "\\",
        )
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaises(ExpressionError):
                self.parser.parse(expression)
        for separator in ("\n", "\r", "\v", "\f", "\x85", "\u2028", "\u2029"):
            with self.subTest(separator=separator), self.assertRaises(ExpressionError):
                self.parser.parse('text~"x' + separator + 'y"')

    def test_invalid_time_literals_use_domain_expression_errors(self):
        """FR14/FR17: invalid calendar/syntax is an ExpressionError, not ValidationError."""
        for value in (
            "", "2026-02-29 12:00", "0000-01-01 00:00", "2026-11-20 24:00",
            "2026-1-01 00:00", "2026-11-20 20:00:00", "2026-11-20 20:00Z",
            "2026-11-20 20:00 ", "２０２６-11-20 20:00",
        ):
            with self.subTest(value=value), self.assertRaises(ExpressionError) as caught:
                self.parser.parse(f'deadline < "{value}"')
            self.assertIn("deadline", caught.exception.reason)

    def test_valid_extreme_and_past_time_literals(self):
        """The parser shares Stage 1's exact date validation and full year range."""
        for value, expected in (
            ("0001-01-01 00:00", datetime(1, 1, 1)),
            ("9999-12-31 23:59", datetime(9999, 12, 31, 23, 59)),
            ("2000-02-29 12:00", datetime(2000, 2, 29, 12)),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    self.parser.parse(f'deadline="{value}"'),
                    TimeCriterion("deadline", "=", expected),
                )

    def test_validate_all_branches_before_any_record_evaluation(self):
        """FR17: false AND / true OR must not hide lexical, syntactic or semantic errors."""
        invalid_branches = (
            'unknown~"x"', 'deadline<"bad"', 'description~""',
            'name="x"', '(type=EVENT', r'text~"\n"', 'text~"unclosed',
            "type=UNKNOWN", "type=EVENT trailing",
        )
        with patch.object(TypeCriterion, "matches", side_effect=AssertionError("Premature match")):
            for operator in ("&&", "||"):
                for branch in invalid_branches:
                    expression = f"type=TASK {operator} {branch}"
                    with self.subTest(expression=expression), self.assertRaises(ExpressionError):
                        self.parser.parse(expression)

    def test_parser_reuse_has_no_retained_success_or_failure_state(self):
        """Design 6.1: every call starts independently after success or rejection."""
        first = self.parser.parse("type=TASK")
        with self.assertRaises(ExpressionError):
            self.parser.parse('description~"')
        second = self.parser.parse('name~"王"')
        self.assertEqual(first, TypeCriterion(RecordType.TASK))
        self.assertEqual(second, TextCriterion("name", "王"))
        self.assertIsNot(self.parser.parse("type=TASK"), first)

    def test_parser_never_uses_eval(self):
        """User expressions are grammar input; even valid parsing needs no Python eval."""
        with patch("builtins.eval", side_effect=AssertionError("eval must not be used")):
            self.assertIsInstance(self.parser.parse("type=TASK"), SearchCriterion)
            with self.assertRaises(ExpressionError):
                self.parser.parse('__import__("os")')

    def test_non_text_expression_is_rejected(self):
        """Invalid API input does not leak a Python TypeError."""
        for value in (None, 123, True, [], {}, b"type=TASK"):
            with self.subTest(value=value), self.assertRaises(ExpressionError):
                self.parser.parse(value)

    def test_excessive_nesting_reports_expression_error_and_parser_recovers(self):
        """Interpreter recursion limits must not leak RecursionError to the caller."""
        with self.assertRaises(ExpressionError):
            self.parser.parse("!" * 2000 + "type=TASK")
        self.assertEqual(self.parser.parse("type=TASK"), TypeCriterion(RecordType.TASK))


class CriteriaRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = CriteriaRegistry(ExpressionParser())

    def test_empty_registry_and_new_session_start_at_c1(self):
        """FR30-FR31: fresh session registries are empty and allocate independently."""
        self.assertEqual(self.registry.all(), ())
        self.assertEqual(self.registry.define("type=TASK").id, "C1")
        other = CriteriaRegistry(ExpressionParser())
        self.assertEqual(other.all(), ())
        self.assertEqual(other.define("type=EVENT").id, "C1")

    def test_original_expression_and_validated_tree_are_retained(self):
        """Definitions preserve exact original text and immutable parsed representation."""
        expression = ' \t type = TASK && description ~ " _ "  '
        item = self.registry.define(expression)
        self.assertIsInstance(item, SavedCriterion)
        self.assertEqual(item.expression, expression)
        self.assertEqual(
            item.root,
            AndCriterion(TypeCriterion(RecordType.TASK), TextCriterion("description", " _ ")),
        )
        self.assertIs(self.registry.get("C1"), item)

    def test_numeric_id_allocation_and_listing_beyond_c9(self):
        """FR30: C10 follows C9; listing must not sort IDs lexicographically."""
        for number in range(1, 13):
            self.assertEqual(self.registry.define("type=TASK").id, f"C{number}")
        self.assertEqual(
            [item.id for item in self.registry.all()], [f"C{i}" for i in range(1, 13)]
        )

    def test_invalid_definitions_consume_no_id_or_modify_existing_entries(self):
        """FR30: full parse/validation succeeds before any registry mutation."""
        first = self.registry.define("type=TASK")
        for expression in ('unknown~"x"', 'text~""', 'deadline<"bad"', "type=TASK ||"):
            with self.subTest(expression=expression):
                with self.assertRaises(ExpressionError):
                    self.registry.define(expression)
                self.assertEqual(self.registry.all(), (first,))
                self.assertIs(self.registry.get("C1"), first)
        self.assertEqual(self.registry.define("type=EVENT").id, "C2")

    def test_changed_or_repeated_expression_gets_new_definition(self):
        """Definitions are never edited or deduplicated; new definitions get new IDs."""
        first = self.registry.define("type=TASK")
        second = self.registry.define("type=EVENT")
        third = self.registry.define("type=TASK")
        self.assertEqual([first.id, second.id, third.id], ["C1", "C2", "C3"])
        self.assertEqual(first.expression, "type=TASK")
        self.assertEqual(first.root, third.root)
        self.assertIsNot(first, third)

    def test_unknown_or_malformed_criterion_id_raises_without_mutation(self):
        """FR17: no silent ID normalization or TypeError for malformed API IDs."""
        item = self.registry.define("type=TASK")
        for value in ("C2", "C0", "C01", "c1", "@C1", " C1", "", None, 1, [], {}):
            with self.subTest(value=value), self.assertRaises(UnknownCriterionError):
                self.registry.get(value)
            self.assertEqual(self.registry.all(), (item,))
        self.assertEqual(self.registry.define("type=EVENT").id, "C2")

    def test_saved_definition_and_tree_are_immutable(self):
        """FR30: ID, original text and root cannot be changed after definition."""
        item = self.registry.define('type=TASK && description~"report"')
        for field in fields(item):
            with self.subTest(field=field.name):
                with self.assertRaises(FrozenInstanceError):
                    setattr(item, field.name, getattr(item, field.name))
                with self.assertRaises(FrozenInstanceError):
                    delattr(item, field.name)
        with self.assertRaises(FrozenInstanceError):
            item.root.left.expected_type = RecordType.EVENT
        self.assertFalse(hasattr(item, "__dict__"))

    def test_listing_is_an_independent_immutable_snapshot(self):
        """Returning/listing entries cannot expose the live registry dictionary."""
        first = self.registry.define("type=TASK")
        snapshot = self.registry.all()
        self.registry.define("type=EVENT")
        self.assertIsInstance(snapshot, tuple)
        self.assertEqual(snapshot, (first,))
        self.assertEqual(len(self.registry.all()), 2)

    def test_reuse_evaluates_current_record_values_and_replacement_collection(self):
        """FR31 foundation: saved trees store no results or record references."""
        item = self.registry.define('type=TASK && description~"report"')
        old_task = Task(1, "report", datetime(2026, 11, 20, 20))
        current = [old_task, Contact(2, "Name", "Address", "00123")]
        self.assertEqual([r.id for r in current if item.root.matches(r)], [1])
        current[0] = replace(old_task, description="exam")
        self.assertEqual([r.id for r in current if item.root.matches(r)], [])
        current = [Task(9, "new report", datetime(2026, 12, 1))]
        self.assertEqual([r.id for r in current if item.root.matches(r)], [9])
        current.clear()
        self.assertEqual([r.id for r in current if item.root.matches(r)], [])
        self.assertIs(self.registry.get("C1"), item)
        self.assertEqual(old_task.description, "report")

    def test_registry_has_no_record_data_or_persistence_interface(self):
        """FR22/FR31 foundation: saved criteria remain separate from record business data."""
        record = PlainText(1, "note")
        before = record.business_fields()
        item = self.registry.define('text~"note"')
        self.assertEqual(tuple(field.name for field in fields(item)), ("id", "expression", "root"))
        self.assertEqual(record.business_fields(), before)
        self.assertEqual(record.duplicate_key(), (RecordType.PLAIN_TEXT, "note"))
        for name in ("save", "load", "write", "read", "update", "delete"):
            self.assertFalse(hasattr(self.registry, name))

    def test_search_model_needs_no_terminal_io(self):
        """NFR3: parse, define, list, lookup, match and expected failures are headless."""
        record = Task(1, "report", datetime(2026, 11, 20, 20))
        with patch("builtins.input", side_effect=AssertionError("Unexpected input")), patch(
            "builtins.print", side_effect=AssertionError("Unexpected output")
        ):
            item = self.registry.define('type=TASK && description~"report"')
            self.assertTrue(item.root.matches(record))
            self.assertEqual(self.registry.all(), (item,))
            self.assertIs(self.registry.get("C1"), item)
            with self.assertRaises(ExpressionError):
                self.registry.define('unknown~"x"')
            with self.assertRaises(UnknownCriterionError):
                self.registry.get("C2")


if __name__ == "__main__":
    unittest.main()
