"""FR27-FR36; Design 7/8/11: real service coordination, confirmations and input boundaries."""

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.controller import PIMController
from cli.errors import CommandError
from cli.parser import Command, CommandParser
from cli.view import PIMView
from model.errors import NotFoundError, PersistenceError
from model.persistence import PIMFileStorage
from model.records import PlainText, RecordType
from model.search import CriteriaRegistry, ExpressionParser
from model.service import PIMService


class ControllerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "saved collection.pim"
        self.incoming = self.directory / "incoming.pim"
        self.missing = self.directory / "missing" / "cannot-save.pim"
        self._reset()

    def _reset(self):
        parser = ExpressionParser()
        self.service = PIMService(PIMFileStorage(), CriteriaRegistry(parser), parser)
        self.view = PIMView()
        self.parser = CommandParser()

    def _record(self, text="original"):
        return self.service.create(RecordType.PLAIN_TEXT, {"text": text})

    def _state(self):
        return (self.service.all_records(), self.service._high_water,
                self.service.dirty, self.service.list_criteria())

    def _run(self, lines):
        """Feed actual input boundaries; a SystemExit is recorded, never hidden."""
        self.controller = PIMController(self.service, self.parser, self.view)
        out, err = io.StringIO(), io.StringIO()
        status = None
        with redirect_stdout(out), redirect_stderr(err), patch(
            "builtins.input", side_effect=lines
        ) as reader:
            try:
                self.controller.run()
            except SystemExit as error:
                status = error.code
        return out.getvalue(), err.getvalue(), status, reader.call_count

    def test_clean_startup_empty_messages_and_normal_exit(self):
        """FR1/FR18/FR20/FR29: start empty, distinguish empty outcomes, no guard if clean."""
        with patch.object(self.service, "load", wraps=self.service.load) as load:
            output, err, status, count = self._run(
                ["show all", 'search text~"missing"', "criteria", "exit"]
            )
        load.assert_not_called()
        self.assertIn("Collection is empty", output)
        self.assertIn("Zero matches", output)
        self.assertIn("No criteria defined", output)
        self.assertIn("Session ended.", output)
        self.assertEqual((err, status, count), ("", None, 4))
        self.assertFalse(self.controller._running)

    def test_execute_continuation_contract(self):
        """D 8: execute returns True to continue and False after an approved exit."""
        controller = PIMController(self.service, self.parser, self.view)
        with redirect_stdout(io.StringIO()):
            self.assertIs(controller.execute(self.parser.parse("show all")), True)
            self.assertIs(controller.execute(self.parser.parse("exit")), False)

    def test_complete_create_update_show_and_direct_saved_search(self):
        """Commands reach the real model, retaining original expressions and literal content."""
        expression = r'text ~ "a\\b\"c"'
        output, err, status, _ = self._run([
            r'create PLAIN_TEXT text=" a\\b\"c _ "',
            f"define {expression}", f"search {expression}", "search @C1", "criteria",
            r'update 1 text="new a\\b\"c _"', "show 1", "exit", "d",
        ])
        self.assertEqual(self.service.get(1).text, 'new a\\b"c _')
        self.assertEqual(self.service.list_criteria()[0].expression, expression)
        self.assertEqual(output.count("ID: 1"), 5)
        self.assertIn("C1: " + expression, output)
        self.assertEqual((err, status), ("", None))

    def test_expected_errors_recover_and_include_cause_and_guidance(self):
        """FR28/NFR1-2: command/domain/file errors do not prevent a later valid operation."""
        output, err, status, _ = self._run([
            "edit 1", 'create TASK description="bad" deadline="invalid"',
            'create PLAIN_TEXT text="good"', 'update 1 id="2"', "show 99",
            "search @C9", 'search unknown~"x"', f'load "{self.incoming}"', "c",
            "show all", "exit", "d",
        ])
        for cause in ("Unknown command", "Invalid deadline", "not editable", "does not exist",
                      "Unknown criterion", "Unknown search field"):
            self.assertIn(cause, output)
        errors = [line for line in output.splitlines() if line.startswith("ERROR")]
        self.assertEqual(len(errors), 6)
        self.assertTrue(all(not line.startswith("ERROR ERROR") for line in errors))
        self.assertIn("Expected", output)
        self.assertIn("Use show all", output)
        self.assertIn("Use criteria", output)
        self.assertEqual([record.id for record in self.service.all_records()], [1])
        self.assertEqual((err, status), ("", None))

    def test_model_expression_validation_is_not_repeated_in_controller(self):
        """Controller forwards each raw expression once, even on an empty collection."""
        expression = r'text ~ " _\\ " || type=TASK'
        with patch.object(self.service, "search", wraps=self.service.search) as search:
            self._run([f"search {expression}", "exit"])
        search.assert_called_once_with(expression)

    def test_show_and_search_display_numeric_ids_and_every_loaded_field(self):
        """FR18/20: full immutable values returned by the model are rendered in order."""
        PIMFileStorage().write(self.incoming, (PlainText(10, "ten"), PlainText(2, "two")))
        output, err, status, _ = self._run([
            f'load "{self.incoming}"', "show all", "search type=PLAIN_TEXT", "exit",
        ])
        self.assertLess(output.index("ID: 2"), output.index("ID: 10"))
        self.assertEqual(output.count("text: two"), 2)
        self.assertEqual(output.count("text: ten"), 2)
        self.assertEqual((err, status), ("", None))

    def test_duplicate_refusal_does_not_consume_id_or_change_dirty(self):
        """FR32: refused duplicate creation never calls the confirmed retry."""
        self._record()
        self.service.save(self.path)
        with patch.object(self.service, "create", wraps=self.service.create) as create:
            output, _, _, _ = self._run(['create PLAIN_TEXT text="original"', "n", "exit"])
        self.assertEqual(create.call_count, 1)
        self.assertEqual(self.service._high_water, 1)
        self.assertFalse(self.service.dirty)
        self.assertIn("Duplicate records: 1.", output)
        self.assertIn("Creation cancelled.", output)

    def test_duplicate_invalid_response_then_confirmation_allocates_new_id(self):
        """FR32: invalid y/n responses cannot mutate; confirmed retry is explicit."""
        self._record()
        self.service.create(RecordType.PLAIN_TEXT, {"text": "original"}, allow_duplicate=True)
        with patch.object(self.service, "create", wraps=self.service.create) as create:
            output, _, _, _ = self._run([
                'create PLAIN_TEXT text=" original "', "yes", "y", "exit", "d",
            ])
        self.assertEqual(create.call_count, 2)
        self.assertTrue(create.call_args.kwargs["allow_duplicate"])
        self.assertEqual([record.id for record in self.service.all_records()], [1, 2, 3])
        self.assertIn("Duplicate records: 1, 2.", output)
        self.assertIn("ERROR Invalid confirmation. Expected y or n.", output)

    def test_delete_displays_before_confirmation_then_selected_only_mutation(self):
        """FR21: the record is shown before consent; invalid response changes nothing."""
        first = self._record("first")
        second = self._record("second")
        output = io.StringIO()
        responses = iter(["delete 1", "invalid", "y", "exit", "d"])

        def read(prompt):
            if "Delete record" in prompt:
                self.assertIn("text: first", output.getvalue())
                self.assertEqual(self.service.get(1), first)
                self.assertEqual(self.service.get(2), second)
            return next(responses)

        controller = PIMController(self.service, self.parser, self.view)
        with redirect_stdout(output), patch("builtins.input", side_effect=read):
            controller.run()
        self.assertEqual(self.service.all_records(), (second,))
        self.assertEqual(self.service._high_water, 2)
        self.assertTrue(self.service.dirty)
        self.assertIn("Deleted record 1.", output.getvalue())

    def test_delete_refusal_and_missing_id_do_not_call_delete(self):
        """FR21: refusal/missing record never reaches the mutating service operation."""
        self._record()
        before = self._state()
        with patch.object(self.service, "delete", wraps=self.service.delete) as delete:
            output, _, _, _ = self._run(["delete 1", "n", "delete 99", "exit", "d"])
        delete.assert_not_called()
        self.assertEqual(self._state(), before)
        self.assertIn("Deletion cancelled.", output)
        self.assertIn("ERROR Record 99 does not exist.", output)

    def test_overwrite_refusal_preserves_target_dirty_and_reports_no_success(self):
        """FR33: existing-file refusal does not count as a save."""
        self._record()
        self.path.write_bytes(b"original target")
        before = self._state()
        with patch.object(self.service, "save", wraps=self.service.save) as save:
            output, _, _, _ = self._run([f'save "{self.path}"', "n", "exit", "d"])
        self.assertEqual(save.call_count, 1)
        self.assertEqual(self._state(), before)
        self.assertEqual(self.path.read_bytes(), b"original target")
        self.assertNotIn("Saved collection", output)
        self.assertIn("Save cancelled", output)

    def test_overwrite_invalid_response_then_confirmed_retry(self):
        """FR33: retry passes overwrite=True only after y; success clears dirty."""
        self._record()
        self.path.write_bytes(b"old")
        with patch.object(self.service, "save", wraps=self.service.save) as save:
            output, _, _, _ = self._run([f'save "{self.path}"', "Y", "y", "exit"])
        self.assertEqual(save.call_count, 2)
        self.assertEqual(save.call_args.kwargs, {"overwrite": True})
        self.assertFalse(self.service.dirty)
        self.assertEqual(PIMFileStorage().read(self.path), self.service.all_records())
        self.assertEqual(output.count("Saved collection"), 1)
        self.assertIn("ERROR Invalid confirmation", output)

    def test_clean_load_skips_guard_and_preserves_criteria(self):
        """FR24/31: explicit load replaces, with no save/discard prompt when clean."""
        item = self.service.define_criterion('text~"new"')
        PIMFileStorage().write(self.incoming, (PlainText(9, "new"),))
        with patch.object(
            self.view, "choose_unsaved", side_effect=AssertionError("Unexpected guard")
        ):
            output, _, _, count = self._run([f'load "{self.incoming}"', "search @C1", "exit"])
        self.assertEqual(count, 3)
        self.assertIs(self.service.list_criteria()[0], item)
        self.assertIn("ID: 9", output)
        self.assertFalse(self.service.dirty)

    def test_dirty_load_cancel_stops_before_file_access(self):
        """FR36: cancelling load preserves state and never opens the incoming path."""
        self._record()
        before = self._state()
        with patch.object(self.service, "load", wraps=self.service.load) as load:
            output, _, _, _ = self._run([f'load "{self.incoming}"', "c", "exit", "d"])
        load.assert_not_called()
        self.assertEqual(self._state(), before)
        self.assertIn("Action cancelled.", output)

    def test_dirty_exit_cancel_returns_to_command_prompt(self):
        """FR35: c must not end the session or clear dirty."""
        self._record()
        before = self._state()
        output, _, _, count = self._run(["exit", "c", "show all", "exit", "d"])
        self.assertEqual(count, 5)
        self.assertEqual(self._state(), before)
        self.assertLess(output.index("Action cancelled."), output.index("ID: 1"))
        self.assertEqual(output.count("Session ended."), 1)

    def test_discard_load_commits_only_after_successful_validation(self):
        """FR36: d authorizes load; live state is unchanged when storage is entered."""
        self._record()
        before = self._state()
        PIMFileStorage().write(self.incoming, (PlainText(5, "new"),))
        original_load = self.service.load

        def load(path):
            self.assertEqual(self._state(), before)
            original_load(path)

        with patch.object(self.service, "load", side_effect=load):
            output, _, _, _ = self._run([f'load "{self.incoming}"', "d", "exit"])
        self.assertEqual(self.service.all_records(), (PlainText(5, "new"),))
        self.assertFalse(self.service.dirty)
        self.assertIn("Loaded collection", output)

    def test_failed_load_after_discard_retains_original_dirty_records(self):
        """FR25/36: d never pre-clears the collection or dirty flag."""
        self._record()
        self.service.define_criterion('text~"original"')
        self.incoming.write_bytes(b"bad file")
        before = self._state()
        output, err, _, _ = self._run([
            f'load "{self.incoming}"', "d", "show all", "exit", "d",
        ])
        self.assertEqual(self._state(), before)
        self.assertIn("ERROR Cannot load", output)
        self.assertNotIn("Loaded collection", output)
        self.assertIn("text: original", output)
        self.assertEqual(err, "")

    def test_failed_load_after_successful_preliminary_save_retains_clean_records(self):
        """FR25/36: completed save is retained even when the subsequent load fails."""
        record = self._record()
        self.incoming.write_bytes(b"bad file")
        output, _, _, count = self._run([
            f'load "{self.incoming}"', "s", f'"{self.path}"', "show all", "exit",
        ])
        self.assertEqual(count, 5)
        self.assertEqual(self.service.all_records(), (record,))
        self.assertFalse(self.service.dirty)
        self.assertEqual(PIMFileStorage().read(self.path), (record,))
        self.assertLess(output.index("Saved collection"), output.index("ERROR Cannot load"))
        self.assertNotIn("Loaded collection", output)

    def test_save_then_load_successful_transaction_sequence(self):
        """FR36: saved original collection and loaded replacement are distinct snapshots."""
        original = self._record()
        PIMFileStorage().write(self.incoming, (PlainText(7, "new"),))
        output, _, _, _ = self._run([
            f'load "{self.incoming}"', "s", f'"{self.path}"', "exit",
        ])
        self.assertEqual(PIMFileStorage().read(self.path), (original,))
        self.assertEqual(self.service.all_records(), (PlainText(7, "new"),))
        self.assertFalse(self.service.dirty)
        self.assertLess(output.index("Saved collection"), output.index("Loaded collection"))

    def test_exit_save_success_and_discard_are_distinct(self):
        """FR35: s genuinely saves; d exits without creating or clearing model data."""
        self._record()
        output, _, _, _ = self._run(["exit", "s", f'"{self.path}"'])
        self.assertTrue(self.path.exists())
        self.assertFalse(self.service.dirty)
        self.assertIn("Saved collection", output)
        self.service.update(1, "text", "changed")
        saved = self.path.read_bytes()
        output, _, _, _ = self._run(["exit", "d"])
        self.assertTrue(self.service.dirty)
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertNotIn("Saved collection", output)

    def test_failed_preliminary_save_stops_load_or_exit_and_allows_later_discard(self):
        """FR35/36: failed save never continues the pending action; later d is separate."""
        for action in (f'load "{self.incoming}"', "exit"):
            with self.subTest(action=action):
                self._reset()
                self._record()
                before = self._state()
                with patch.object(self.service, "load", wraps=self.service.load) as load:
                    output, _, _, count = self._run([
                        action, "s", f'"{self.missing}"', "show all", "exit", "d",
                    ])
                load.assert_not_called()
                self.assertEqual(count, 6)
                self.assertEqual(self._state(), before)
                self.assertIn("ERROR Cannot save", output)
                self.assertIn("text: original", output)
                self.assertNotIn("Saved collection", output)
                self.assertEqual(output.count("Session ended."), 1)

    def test_declined_preliminary_overwrite_stops_load_or_exit(self):
        """FR33/35/36: n is not a successful save and never authorizes a pending action."""
        for action in (f'load "{self.incoming}"', "exit"):
            with self.subTest(action=action):
                self._reset()
                self._record()
                self.path.write_bytes(b"existing")
                before = self._state()
                with patch.object(self.service, "load", wraps=self.service.load) as load:
                    output, _, _, count = self._run([
                        action, "s", f'"{self.path}"', "n", "show all", "exit", "d",
                    ])
                load.assert_not_called()
                self.assertEqual(count, 7)
                self.assertEqual(self._state(), before)
                self.assertEqual(self.path.read_bytes(), b"existing")
                self.assertNotIn("Saved collection", output)
                self.assertIn("text: original", output)

    def test_failed_confirmed_overwrite_stops_pending_action(self):
        """Even a y response cannot turn a failed replacement into successful saving."""
        self._record()
        self.path.write_bytes(b"existing")
        before = self._state()
        with patch(
            "model.persistence.os.replace", side_effect=PermissionError("Controlled denial")
        ):
            output, _, _, _ = self._run(["exit", "s", f'"{self.path}"', "y",
                                          "show all", "exit", "d"])
        self.assertEqual(self._state(), before)
        self.assertEqual(self.path.read_bytes(), b"existing")
        self.assertNotIn("Saved collection", output)
        self.assertIn("ERROR Cannot save", output)
        self.assertIn("text: original", output)

    def test_user_can_retry_save_after_failed_exit_save(self):
        """Failure returns to main input; explicit retry can save before a later exit."""
        original = self._record()
        output, _, _, count = self._run([
            "exit", "s", f'"{self.missing}"', f'save "{self.path}"', "exit",
        ])
        self.assertEqual(count, 5)
        self.assertFalse(self.service.dirty)
        self.assertEqual(PIMFileStorage().read(self.path), (original,))
        self.assertIn("ERROR Cannot save", output)
        self.assertEqual(output.count("Saved collection"), 1)

    def test_invalid_guard_and_save_path_inputs_repeat_without_mutation(self):
        """Invalid choices/path syntax remain at their own input boundaries."""
        original = self._record()
        output, _, _, count = self._run([
            "exit", "invalid", "s", "unquoted", '""', f'"{self.path}"',
        ])
        self.assertEqual(count, 6)
        self.assertEqual(PIMFileStorage().read(self.path), (original,))
        self.assertFalse(self.service.dirty)
        self.assertEqual(output.count("ERROR "), 3)

    def test_recoverable_interrupt_at_each_input_boundary_preserves_state(self):
        """R13/Q6: cancel uncommitted input only, with bounded recovery at all prompts."""
        scripts = (
            [KeyboardInterrupt],
            ['create PLAIN_TEXT text="original"', KeyboardInterrupt],
            ["delete 1", KeyboardInterrupt],
            [f'save "{self.path}"', KeyboardInterrupt],
            ["exit", KeyboardInterrupt],
            ["exit", "s", KeyboardInterrupt],
        )
        for prefix in scripts:
            with self.subTest(prefix=prefix):
                self._reset()
                self._record()
                self.path.write_bytes(b"existing")
                before = self._state()
                output, err, status, _ = self._run(prefix + ["show all", "exit", "d"])
                self.assertEqual(self._state(), before)
                self.assertEqual(self.path.read_bytes(), b"existing")
                self.assertIn("ERROR Input interrupted", output)
                self.assertIn("text: original", output)
                self.assertEqual((err, status), ("", None))

    def test_interrupt_at_overwrite_prompt_after_preliminary_save_does_not_load(self):
        """Interruption is not overwrite consent or permission to continue the pending load."""
        self._record()
        self.path.write_bytes(b"existing")
        before = self._state()
        with patch.object(self.service, "load", wraps=self.service.load) as load:
            output, _, _, _ = self._run([
                f'load "{self.incoming}"', "s", f'"{self.path}"', KeyboardInterrupt,
                "show all", "exit", "d",
            ])
        load.assert_not_called()
        self.assertEqual(self._state(), before)
        self.assertIn("Input interrupted", output)

    def test_keyboard_interrupt_from_model_commit_is_not_caught_and_retried(self):
        """The recovery catch surrounds terminal reads, never service mutation/commit code."""
        controller = PIMController(self.service, self.parser, self.view)
        with patch(
            "builtins.input", return_value='create PLAIN_TEXT text="x"'
        ) as reader, patch.object(
            self.service.__class__, "create", side_effect=KeyboardInterrupt
        ), redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                controller.run()
        self.assertEqual(reader.call_count, 1)
        with patch("builtins.input", return_value="show all"), patch.object(
            self.service, "all_records", side_effect=RuntimeError("Programming defect")
        ):
            with self.assertRaises(RuntimeError):
                controller.run()

    def test_dirty_permanent_eof_at_all_prompts_never_mutates_or_loops(self):
        """Q6: nonzero status, stderr warning, no implicit save/discard/pending mutation."""
        scripts = (
            [],
            ['create PLAIN_TEXT text="original"'],
            ["delete 1"],
            [f'save "{self.path}"'],
            ["exit"],
            ["exit", "s"],
            [f'load "{self.incoming}"'],
            [f'load "{self.incoming}"', "s", f'"{self.path}"'],
        )
        for prefix in scripts:
            with self.subTest(prefix=prefix):
                self._reset()
                self._record()
                self.service.define_criterion('text~"original"')
                self.path.write_bytes(b"existing")
                before = self._state()
                with patch.object(self.service, "load", wraps=self.service.load) as load:
                    output, err, status, count = self._run(prefix + [EOFError])
                load.assert_not_called()
                self.assertEqual(count, len(prefix) + 1)
                self.assertEqual(status, 1)
                self.assertEqual(self._state(), before)
                self.assertEqual(self.path.read_bytes(), b"existing")
                self.assertIn("terminating the session with unsaved changes", err)
                self.assertNotIn("Saved collection", output)
                self.assertNotIn("Session ended.", output)

    def test_clean_eof_and_eof_after_completed_save_do_not_claim_discard(self):
        """Q6: EOF reflects the current dirty state and never fabricates a save."""
        output, err, status, count = self._run([EOFError])
        self.assertEqual((output, err, status, count), ("", "", 0, 1))
        self._record()
        output, err, status, count = self._run([f'save "{self.path}"', EOFError])
        self.assertEqual((err, status, count), ("", 0, 2))
        self.assertFalse(self.service.dirty)
        self.assertEqual(output.count("Saved collection"), 1)
        self.assertNotIn("Session ended.", output)

    def test_eof_after_preliminary_save_and_failed_load_keeps_clean_result(self):
        """Q6/FR36: EOF cannot undo an independently completed save."""
        original = self._record()
        self.incoming.write_bytes(b"bad file")
        output, err, status, count = self._run([
            f'load "{self.incoming}"', "s", f'"{self.path}"', EOFError,
        ])
        self.assertEqual((err, status, count), ("", 0, 4))
        self.assertEqual(self.service.all_records(), (original,))
        self.assertFalse(self.service.dirty)
        self.assertEqual(PIMFileStorage().read(self.path), (original,))
        self.assertIn("ERROR Cannot load", output)

    def test_execute_propagates_expected_domain_errors_to_run_boundary(self):
        """execute has the documented raising contract; only run renders expected errors."""
        controller = PIMController(self.service, self.parser, self.view)
        with self.assertRaises(NotFoundError):
            controller.execute(self.parser.parse("show 99"))
        with self.assertRaises(PersistenceError):
            controller.execute(self.parser.parse(f'load "{self.incoming}"'))
        with self.assertRaisesRegex(CommandError, "Unknown command carrier"):
            controller.execute(Command("unsupported", {}))


if __name__ == "__main__":
    unittest.main()
