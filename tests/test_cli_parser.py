"""FR27-FR28; Design 7: exact command grammar, immutable carriers and raw expressions."""

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from cli.errors import CommandError
from cli.parser import Command, CommandParser
from model.records import RecordType
from model.search import ExpressionParser
from model.validation import MAX_RECORD_ID


class CommandParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = CommandParser()

    def test_all_command_forms_and_argument_types(self):
        """D 7.1: commands carry typed IDs/types/paths; model values remain strings."""
        cases = (
            ('create PLAIN_TEXT text="note"', "create",
             {"kind": RecordType.PLAIN_TEXT, "fields": {"text": "note"}}),
            ('create TASK description="task" deadline="0001-01-01 00:00"', "create",
             {"kind": RecordType.TASK,
              "fields": {"description": "task", "deadline": "0001-01-01 00:00"}}),
            ('create EVENT description="event" start="a" alarm="b"', "create",
             {"kind": RecordType.EVENT,
              "fields": {"description": "event", "start": "a", "alarm": "b"}}),
            ('create CONTACT mobile="+001" address="B" name="A"', "create",
             {"kind": RecordType.CONTACT,
              "fields": {"mobile": "+001", "address": "B", "name": "A"}}),
            ('update 02 deadline="invalid"', "update",
             {"record_id": 2, "field": "deadline", "value": "invalid"}),
            ("show 10", "show", {"record_id": 10}),
            ("show all", "show", {}),
            ("delete 7", "delete", {"record_id": 7}),
            ('define type = TASK', "define", {"expression": "type = TASK"}),
            ("criteria", "criteria", {}),
            ('search text ~ "word"', "search", {"expression": 'text ~ "word"'}),
            ("search @C12", "search", {"criterion_id": "C12"}),
            ('save "folder with spaces/data.pim"', "save",
             {"path": Path("folder with spaces/data.pim")}),
            ('load "file.pim"', "load", {"path": Path("file.pim")}),
            ("exit", "exit", {}),
        )
        for line, verb, arguments in cases:
            with self.subTest(line=line):
                result = self.parser.parse(line)
                self.assertEqual(result.verb, verb)
                self.assertEqual(result.arguments, arguments)

    def test_command_copies_and_freezes_outer_and_nested_maps(self):
        """The caller cannot mutate a parsed command through either mapping."""
        fields = {"text": "original"}
        source = {"kind": RecordType.PLAIN_TEXT, "fields": fields}
        result = Command("create", source)
        source["kind"] = RecordType.TASK
        fields["text"] = "changed"
        self.assertEqual(result.arguments["kind"], RecordType.PLAIN_TEXT)
        self.assertEqual(result.arguments["fields"]["text"], "original")
        with self.assertRaises(TypeError):
            result.arguments["kind"] = RecordType.CONTACT
        with self.assertRaises(TypeError):
            result.arguments["fields"]["text"] = "edited"
        with self.assertRaises(FrozenInstanceError):
            result.verb = "delete"
        with self.assertRaises((AttributeError, TypeError)):
            result.__dict__ = {}

    def test_expression_tail_preserves_quotes_backslashes_and_trailing_spaces(self):
        """FR13/FR15: the command layer must never decode an expression literal."""
        expression = r'text ~ " a\\b\"c && OR _ " || type=TASK' + "  "
        for verb in ("define", "search"):
            command = self.parser.parse(f" \t{verb}\t {expression}")
            self.assertEqual(command.arguments["expression"], expression)
            tree = ExpressionParser().parse(command.arguments["expression"])
            self.assertEqual(tree.left.substring, ' a\\b"c && OR _ ')

    def test_command_literals_decode_once_without_trimming(self):
        """Creation/update decode exactly once; stored-value normalization is model work."""
        value = self.parser.parse(r'create PLAIN_TEXT text="  a\\b\"c  "')
        self.assertEqual(value.arguments["fields"]["text"], '  a\\b"c  ')
        value = self.parser.parse(r'update 1 text="\\n"')
        self.assertEqual(value.arguments["value"], "\\n")

    def test_escaped_windows_paths_and_forward_slashes(self):
        """Only documented escaping applies; no shell/environment expansion."""
        for line, expected in (
            (r'save "C:\\Users\\Name\\my data.pim"', r"C:\Users\Name\my data.pim"),
            ('load "C:/Users/Name/my data.pim"', "C:/Users/Name/my data.pim"),
            ('save "$HOME/~/data.pim"', "$HOME/~/data.pim"),
        ):
            with self.subTest(line=line):
                self.assertEqual(self.parser.parse(line).arguments["path"], Path(expected))

    def test_whitespace_and_assignment_order(self):
        """Separating whitespace, including around =, does not trim quoted content."""
        value = self.parser.parse(' \tcreate TASK\tdeadline = "date" description= "  text  " \t')
        self.assertEqual(value.arguments["fields"],
                         {"deadline": "date", "description": "  text  "})

    def test_invalid_command_and_aliases(self):
        """Only approved lowercase command words are accepted, without numbered menus."""
        for line in ("", " \t", "1", "help", "edit 1 text=\"x\"", "UPDATE 1 text=\"x\"",
                     "quit", "showall", "search@C1", ":cancel"):
            with self.subTest(line=line), self.assertRaises(CommandError) as caught:
                self.parser.parse(line)
            self.assertIn("Expected", caught.exception.reason)

    def test_invalid_record_ids(self):
        """R8: positive ASCII decimal IDs; leading zeroes accepted, malformed IDs rejected."""
        for value in ("0", "-1", "+1", "1.0", "True", "１２", "1 2", "1x", "9" * 5000):
            for verb in ("show", "delete", "update"):
                line = f'{verb} {value}' + (' text="x"' if verb == "update" else "")
                with self.subTest(line=line), self.assertRaises(CommandError):
                    self.parser.parse(line)
        self.assertEqual(self.parser.parse("show 0002").arguments["record_id"], 2)

    def test_record_id_range_checked_before_decimal_conversion(self):
        """Accept MAX/leading zeroes; reject MAX+1 and enormous inputs in every ID verb."""
        for verb in ("show", "delete", "update"):
            suffix = ' text="changed"' if verb == "update" else ""
            for digits in (str(MAX_RECORD_ID), "0" * 5000 + str(MAX_RECORD_ID)):
                command = self.parser.parse(f"{verb} {digits}{suffix}")
                self.assertEqual(command.arguments["record_id"], MAX_RECORD_ID)
            for digits in (str(MAX_RECORD_ID + 1), "9" * 4300, "9" * 5000, "0" * 5000):
                with self.assertRaises(CommandError) as caught:
                    self.parser.parse(f"{verb} {digits}{suffix}")
                self.assertIn(str(MAX_RECORD_ID), str(caught.exception))
                self.assertLess(len(str(caught.exception)), 200)

    def test_missing_extra_repeated_and_unknown_create_fields(self):
        """Command grammar checks exact assignment sets, never business values."""
        for line in (
            "create", "create TASK", 'create TASK description="x"',
            'create PLAIN_TEXT text="x" text="y"',
            'create PLAIN_TEXT text="x" other="y"',
            'create PLAIN_TEXT description="x"',
            'create PLAIN_TEXT text="x" id="1"',
            'create UNKNOWN text="x"', 'create task description="x" deadline="y"',
        ):
            with self.subTest(line=line), self.assertRaises(CommandError):
                self.parser.parse(line)

    def test_update_requires_exactly_one_assignment(self):
        """FR9: update never accepts multiple fields or interactive field entry."""
        for line in ("update", "update 1", 'update 1 text="x" text="y"',
                     'update 1 name="x" address="y"', 'update 1 text="x" extra'):
            with self.subTest(line=line), self.assertRaises(CommandError):
                self.parser.parse(line)
        # Business-field permission depends on the current record and belongs to the model.
        self.assertEqual(self.parser.parse('update 1 id="2"').arguments["field"], "id")

    def test_bad_assignment_separators_quotes_and_escapes(self):
        """Generic shell quoting and unsupported escape sequences are rejected."""
        tails = (
            "text=unquoted", "text='single'", 'text="unclosed', r'text="bad\n"',
            r'text="bad\q"', 'text "missing equal"', 'text=="x"',
            'text="x"text="y"', 'text="x";delete 1', 'text="x" #comment',
        )
        for tail in tails:
            with self.subTest(tail=tail), self.assertRaises(CommandError):
                self.parser.parse(f"create PLAIN_TEXT {tail}")

    def test_bad_paths_and_extra_arguments(self):
        """Save/load take exactly one quoted nonempty path."""
        for verb in ("save", "load"):
            for tail in ("", "file.pim", '""', '"x.pim" extra', '"x.pim" "y.pim"',
                         r'"C:\bad.pim"', '"bad\0.pim"'):
                with self.subTest(verb=verb, tail=tail), self.assertRaises(CommandError):
                    self.parser.parse(f"{verb} {tail}")

    def test_extra_arguments_on_simple_commands_and_references(self):
        """No trailing command tokens, malformed criterion references or aliases."""
        for line in ("exit now", "criteria 1", "show all extra", "delete all",
                     "search @C0", "search @C01", "search @c1", "search @C1 extra",
                     "search @C1 || type=TASK", "define", "search"):
            with self.subTest(line=line), self.assertRaises(CommandError):
                self.parser.parse(line)

    def test_model_parses_even_malformed_expression_tail(self):
        """The command parser must not duplicate expression syntax or semantic validation."""
        for expression in ('unknown ~ "x"', "type=TASK OR type=EVENT", 'text~""',
                           'text~"bad\\q"', "type=TASK &&"):
            for verb in ("define", "search"):
                with self.subTest(expression=expression, verb=verb):
                    self.assertEqual(
                        self.parser.parse(f"{verb} {expression}").arguments["expression"],
                        expression,
                    )
        self.parser.parse('create TASK description="" deadline="invalid"')

    def test_single_line_type_check_and_parser_reuse_without_terminal_io(self):
        """Syntax failures do not retain reader state or call the model/search parser."""
        for line in (None, 1, 'show all\n', 'create PLAIN_TEXT text="a\u2028b"'):
            with self.subTest(line=line), self.assertRaises(CommandError):
                self.parser.parse(line)
        with patch("builtins.input", side_effect=AssertionError("Unexpected input")), patch(
            "builtins.print", side_effect=AssertionError("Unexpected output")
        ), patch.object(ExpressionParser, "parse", side_effect=AssertionError("Model parsing")):
            self.assertEqual(self.parser.parse("exit").verb, "exit")
            self.parser.parse('search unknown~"x"')


if __name__ == "__main__":
    unittest.main()
