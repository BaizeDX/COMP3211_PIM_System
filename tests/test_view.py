"""D 8 and FR18/20/27: stateless terminal formatting and retrying input adapters."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from cli.parser import CommandParser
from cli.view import PIMView
from model.records import Contact, Event, PlainText, Task
from model.search import CriteriaRegistry, ExpressionParser


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.view = PIMView()
        self.out = io.StringIO()

    def test_read_line_default_and_custom_prompt(self):
        """Input is a terminal boundary and does not trim user text."""
        with patch("builtins.input", return_value="  text  ") as reader:
            self.assertEqual(self.view.read_line(), "  text  ")
            reader.assert_called_once_with("pim> ")
            self.view.read_line("custom> ")
            reader.assert_called_with("custom> ")

    def test_complete_records_in_numeric_order_and_canonical_time_format(self):
        """FR18/20: each type includes ID/type/all fields, including year 0001."""
        records = (
            Contact(10, "王", "香港", "+00123"),
            Event(7, "event", datetime(2026, 1, 1), datetime(2025, 12, 31, 23, 59)),
            Task(2, "task", datetime(1, 1, 1)),
            PlainText(1, 'quote " slash \\ _'),
        )
        with redirect_stdout(self.out):
            self.view.show_records(records)
        output = self.out.getvalue()
        self.assertEqual(output, (
            'ID: 1\nType: PLAIN_TEXT\ntext: quote " slash \\ _\n\n'
            'ID: 2\nType: TASK\ndescription: task\ndeadline: 0001-01-01 00:00\n\n'
            'ID: 7\nType: EVENT\ndescription: event\nstart: 2026-01-01 00:00\n'
            'alarm: 2025-12-31 23:59\n\n'
            'ID: 10\nType: CONTACT\nname: 王\naddress: 香港\nmobile: +00123\n'
        ))

    def test_criteria_numeric_order_and_exact_original_expression(self):
        """FR30: C10 follows C9 and quoted content is never reformatted."""
        registry = CriteriaRegistry(ExpressionParser())
        items = tuple(registry.define(' text ~ " _ "  ') for _ in range(12))
        with redirect_stdout(self.out):
            self.view.show_criteria(tuple(reversed(items)))
        self.assertEqual(self.out.getvalue().splitlines(),
                         [f'C{i}:  text ~ " _ "  ' for i in range(1, 13)])

    def test_empty_criteria_and_controller_selected_record_empty_messages(self):
        """D 8: empty criteria explicit; controller chooses collection/search wording."""
        with redirect_stdout(self.out):
            self.view.show_criteria(())
            self.view.show_records(())
        self.assertEqual(self.out.getvalue(), "No criteria defined\n")

    def test_confirm_invalid_responses_retry_without_implied_consent(self):
        """Only lowercase y/n, with response outer whitespace stripped."""
        for final, expected in ((" y ", True), ("n", False)):
            with self.subTest(final=final), redirect_stdout(self.out), patch(
                "builtins.input", side_effect=["", "Y", "yes", final]
            ) as reader:
                self.assertIs(self.view.confirm("Proceed?"), expected)
                self.assertEqual(reader.call_count, 4)
                self.assertTrue(all("Proceed? [y/n]" in call.args[0]
                                    for call in reader.call_args_list))
        self.assertEqual(self.out.getvalue().count("ERROR Invalid confirmation"), 6)

    def test_unsaved_invalid_responses_retry_for_each_valid_choice(self):
        """FR35/36: only s/d/c can authorize the selected guard branch."""
        for final in ("s", "d", "c"):
            with self.subTest(final=final), redirect_stdout(self.out), patch(
                "builtins.input", side_effect=["", "D", "discard", f" {final} "]
            ) as reader:
                self.assertEqual(self.view.choose_unsaved(), final)
                self.assertEqual(reader.call_count, 4)
        self.assertEqual(self.out.getvalue().count("ERROR Invalid choice"), 9)

    def test_path_retry_and_shared_decoder_preserve_escapes(self):
        """The save-path prompt accepts the same literal grammar as save commands."""
        literal = r'"C:\\my folder\\a\"b.pim"'
        with redirect_stdout(self.out), patch(
            "builtins.input", side_effect=["unquoted", '""', r'"bad\q"', literal]
        ) as reader:
            result = self.view.read_path()
        self.assertEqual(reader.call_count, 4)
        self.assertEqual(result, CommandParser().parse(f"save {literal}").arguments["path"])
        self.assertEqual(result, Path('C:\\my folder\\a"b.pim'))
        self.assertEqual(self.out.getvalue().count("ERROR "), 3)

    def test_eof_and_keyboard_interrupt_propagate_from_all_input_methods(self):
        """Controller policies, not view retry loops, decide input interruption handling."""
        for method in (self.view.read_line, lambda: self.view.confirm("Proceed?"),
                       self.view.choose_unsaved, self.view.read_path):
            for error in (EOFError, KeyboardInterrupt):
                with self.subTest(method=method, error=error), patch(
                    "builtins.input", side_effect=error
                ) as reader:
                    with self.assertRaises(error):
                        method()
                    self.assertEqual(reader.call_count, 1)

    def test_error_prefix_exactly_once_and_normal_output_uses_stdout(self):
        """Expected errors preserve cause/input guidance and avoid stderr."""
        err = io.StringIO()
        with redirect_stdout(self.out), redirect_stderr(err):
            self.view.message("result")
            self.view.error('Invalid deadline. Expected YYYY-MM-DD HH:MM.')
            self.view.error("ERROR ERROR: already prefixed")
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(self.out.getvalue().splitlines(), [
            "result", "ERROR Invalid deadline. Expected YYYY-MM-DD HH:MM.",
            "ERROR already prefixed",
        ])

    def test_exceptional_closed_input_warning_uses_stderr_only(self):
        """User clarification: dirty EOF terminates exceptionally, without save/discard claims."""
        err = io.StringIO()
        with redirect_stdout(self.out), redirect_stderr(err):
            self.view._closed_input()
        self.assertEqual(self.out.getvalue(), "")
        self.assertEqual(err.getvalue(),
                         "ERROR Standard input is closed; terminating the session "
                         "with unsaved changes.\n")


if __name__ == "__main__":
    unittest.main()
