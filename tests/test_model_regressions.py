"""Audit regressions using public model behaviour (SRS FR2/9/11/17/31; Design 10)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from model.criteria import AndCriterion, OrCriterion, TypeCriterion
from model.errors import DuplicateRecordError, ExpressionError, PersistenceError, ValidationError
from model.persistence import PIMFileStorage
from model.records import Contact, PlainText, RecordType, Task
from model.search import _MAX_CONDITIONS, CriteriaRegistry, ExpressionParser
from model.service import PIMService
from model.validation import MAX_RECORD_ID


class ModelRegressionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "records.pim"
        parser = ExpressionParser()
        self.service = PIMService(PIMFileStorage(), CriteriaRegistry(parser), parser)

    def test_flat_conjunction_at_condition_limit_works_and_one_more_is_rejected(self):
        """Limit-sized chains work directly and saved; one more fails before any C ID."""
        note = self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        self.service.create(
            RecordType.CONTACT, {"name": "A", "address": "B", "mobile": "001"}
        )
        expression = " && ".join(["type=PLAIN_TEXT"] * _MAX_CONDITIONS)
        item = self.service.define_criterion(expression)
        self.assertEqual(self.service.search(expression), (note,))
        self.assertEqual(self.service.search_saved(item.id), (note,))
        too_long = " && ".join(["type=PLAIN_TEXT"] * (_MAX_CONDITIONS + 1))
        reason = f"at most {_MAX_CONDITIONS} conditions"
        with self.assertRaisesRegex(ExpressionError, reason):
            self.service.search(too_long)
        with self.assertRaisesRegex(ExpressionError, reason):
            self.service.define_criterion(too_long)
        self.assertEqual([saved.id for saved in self.service.list_criteria()], ["C1"])

    def test_oversized_file_ids_reject_whole_load_preserving_session(self):
        """Original 4300-nine ID and MAX+1 reject atomically, even after a valid prefix."""
        valid = '{"id":999,"type":"PLAIN_TEXT","text":"must not commit"}'
        for digits in ("9" * 4300, str(MAX_RECORD_ID + 1), "9" * 5000):
            invalid = '{"id":' + digits + ',"type":"PLAIN_TEXT","text":"invalid"}'
            for prefix in ("", valid + ","):
                for dirty in (False, True):
                    with self.subTest(digits=len(digits), prefix=bool(prefix), dirty=dirty):
                        parser = ExpressionParser()
                        service = PIMService(PIMFileStorage(), CriteriaRegistry(parser), parser)
                        PIMFileStorage().write(self.path, (PlainText(9, "original"),),
                                               overwrite=True)
                        service.load(self.path)
                        saved = service.define_criterion('type=PLAIN_TEXT')
                        if dirty:
                            service.update(9, "text", "changed")
                        before = service.all_records()
                        self.path.write_text(
                            '{"format":"PIM","version":1,"records":[' + prefix + invalid + ']}',
                            encoding="utf-8",
                        )
                        with self.assertRaises(PersistenceError) as caught:
                            service.load(self.path)
                        self.assertLess(len(str(caught.exception)), 1000)
                        self.assertEqual(service.all_records(), before)
                        self.assertEqual(service.dirty, dirty)
                        self.assertEqual(service.list_criteria(), (saved,))
                        self.assertEqual(service.search_saved(saved.id), before)
                        # Proves a rejected valid prefix/huge ID never raised high-water.
                        self.assertEqual(
                            service.create(RecordType.PLAIN_TEXT, {"text": "probe"}).id, 10
                        )

    def test_final_id_allocates_once_then_exhaustion_preserves_clean_and_dirty_states(self):
        """MAX-1 allocates MAX exactly once; refusal never mutates records/counter/dirty."""
        PIMFileStorage().write(self.path, (PlainText(MAX_RECORD_ID - 1, "previous"),))
        self.service.load(self.path)
        final = self.service.create(RecordType.PLAIN_TEXT, {"text": "last"})
        self.assertEqual(final.id, MAX_RECORD_ID)
        for clean in (False, True):
            if clean:
                self.service.save(self.path, overwrite=True)
            before = self.service.all_records()
            dirty = self.service.dirty
            high_water = self.service._high_water
            for allow_duplicate in (False, True):
                with self.assertRaises(ValidationError) as caught:
                    self.service.create(RecordType.PLAIN_TEXT, {"text": "new"},
                                        allow_duplicate=allow_duplicate)
                self.assertIn("exhausted", str(caught.exception))
                self.assertEqual(self.service.all_records(), before)
                self.assertEqual(self.service.dirty, dirty)
                # At exhaustion every later allocation also fails, so explicitly
                # check the otherwise unobservable counter invariant.
                self.assertEqual(self.service._high_water, high_water)
            self.assertEqual(self.service.get(final.id), final)

    def test_exhausted_session_keeps_existing_operations_and_never_reuses_ids(self):
        """Read/search/update/delete/save/load work at MAX; lower/empty loads cannot reset it."""
        maximum = PlainText(MAX_RECORD_ID, "boundary")
        PIMFileStorage().write(self.path, (maximum,))
        self.service.load(self.path)
        saved = self.service.define_criterion('text~"bound"')
        self.assertEqual(self.service.get(MAX_RECORD_ID), maximum)
        self.assertEqual(self.service.search('type=PLAIN_TEXT'), (maximum,))
        self.assertEqual(self.service.search_saved(saved.id), (maximum,))
        self.service.update(MAX_RECORD_ID, "text", "boundary changed")
        self.service.save(self.path, overwrite=True)
        self.service.load(self.path)
        self.assertEqual(self.service.search_saved(saved.id)[0].text, "boundary changed")
        self.service.delete(MAX_RECORD_ID)
        self.service.save(self.path, overwrite=True)
        for records in ((), (PlainText(1, "lower"),)):
            PIMFileStorage().write(self.path, records, overwrite=True)
            self.service.load(self.path)
            before = self.service.all_records()
            with self.assertRaises(ValidationError):
                self.service.create(RecordType.PLAIN_TEXT, {"text": "no reuse"})
            self.assertEqual(self.service.all_records(), before)
            self.assertFalse(self.service.dirty)

    def test_huge_direct_lookup_errors_never_format_rejected_ids(self):
        """get/update/delete reject arbitrary huge Python integers with safe domain messages."""
        original = self.service.create(RecordType.PLAIN_TEXT, {"text": "keep"})
        for action in (self.service.get, self.service.delete,
                       lambda value: self.service.update(value, "text", "change")):
            with self.assertRaises(ValidationError) as caught:
                action(10 ** 5000)
            self.assertLess(len(str(caught.exception)), 200)
        self.assertEqual(self.service.all_records(), (original,))

    def test_long_disjunction_and_negation_keep_boolean_semantics(self):
        """A late true OR leaf and negated AND must work for mixed record types."""
        note = self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        contact = self.service.create(
            RecordType.CONTACT, {"name": "A", "address": "B", "mobile": "001"}
        )
        expression = " || ".join(["type=TASK"] * (_MAX_CONDITIONS - 1) + ["type=CONTACT"])
        self.assertEqual(self.service.search(expression), (contact,))
        conjunction = " && ".join(["type=PLAIN_TEXT"] * _MAX_CONDITIONS)
        self.assertEqual(self.service.search(f"!({conjunction})"), (contact,))
        self.assertEqual(self.service.get(note.id), note)

    def test_invalid_branch_after_long_valid_prefix_is_still_fully_validated(self):
        """Short-circuit candidates cannot hide a final invalid condition or allocate a C ID."""
        note = self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        prefix = " || ".join(["type=PLAIN_TEXT"] * (_MAX_CONDITIONS - 1))
        for tail, reason in (('unknown~"x"', "Unknown search field"),
                             ('deadline<"invalid"', "Invalid deadline comparison"),
                             ('text~""', "nonempty")):
            expression = f"{prefix} || {tail}"
            with self.subTest(tail=tail):
                with self.assertRaisesRegex(ExpressionError, reason):
                    self.service.search(expression)
                with self.assertRaisesRegex(ExpressionError, reason):
                    self.service.define_criterion(expression)
        self.assertEqual(self.service.list_criteria(), ())
        self.assertEqual(self.service.define_criterion("type=TASK").id, "C1")
        self.assertEqual(self.service.all_records(), (note,))

    def test_design_search_then_update_scenario_and_reload(self):
        """D Figure 5: [2,7] becomes [7]; Task 7 unchanged; reload updates saved search."""
        task2 = Task(2, "COMP3211 report", datetime(2026, 11, 20, 20))
        task7 = Task(7, "COMP3211 tests", datetime(2026, 11, 21, 18))
        PIMFileStorage().write(self.path, (task7, task2))
        self.service.load(self.path)
        expression = (
            'type = TASK && description ~ "COMP3211" && deadline < "2026-11-22 00:00"'
        )
        item = self.service.define_criterion(expression)
        self.assertEqual(self.service.search(expression), (task2, task7))
        self.service.update(2, "deadline", "2026-11-25 23:59")
        self.assertEqual(self.service.search(expression), (task7,))
        self.assertEqual(self.service.search_saved(item.id), (task7,))
        self.assertEqual(self.service.get(7), task7)
        self.assertEqual(self.service.get(2).description, task2.description)
        self.service.load(self.path)
        self.assertIs(self.service.list_criteria()[0], item)
        self.assertEqual(self.service.search_saved(item.id), (task2, task7))
        self.assertFalse(self.service.dirty)

    def test_public_workflow_high_water_refusal_noop_failure_and_lower_load(self):
        """ID history spans deletion/load; rejected/declined/no-op edits cannot advance it."""
        PIMFileStorage().write(self.path, (PlainText(20, "same"),))
        self.service.load(self.path)
        record = self.service.create(RecordType.PLAIN_TEXT, {"text": "new"})
        self.assertEqual(record.id, 21)
        self.service.delete(21)
        self.service.save(self.path, overwrite=True)
        with self.assertRaises(DuplicateRecordError):
            self.service.create(RecordType.PLAIN_TEXT, {"text": "same"})
        self.assertIs(self.service.update(20, "text", " same "), self.service.get(20))
        with self.assertRaises(ValidationError):
            self.service.update(20, "text", "___")
        self.assertFalse(self.service.dirty)
        PIMFileStorage().write(self.path, (PlainText(2, "lower"),), overwrite=True)
        self.service.load(self.path)
        self.assertEqual(self.service.create(RecordType.PLAIN_TEXT, {"text": "next"}).id, 22)

    def test_full_model_workflow_without_terminal_or_network(self):
        """NFR3/5: independent model CRUD/criteria/save/load need no terminal or sockets."""
        with patch("builtins.input", side_effect=AssertionError("Terminal input")), patch(
            "builtins.print", side_effect=AssertionError("Terminal output")
        ), patch("socket.socket", side_effect=AssertionError("Network access")):
            note = self.service.create(RecordType.PLAIN_TEXT, {"text": "中文 _ report"})
            item = self.service.define_criterion('text~" _ "')
            self.service.save(self.path)
            self.service.update(note.id, "text", "changed")
            self.assertEqual(self.service.search_saved(item.id), ())
            self.service.load(self.path)
            self.assertEqual(self.service.search_saved(item.id), (note,))
            self.service.delete(note.id)
            self.assertEqual(self.service.all_records(), ())

    def test_composites_honor_child_subclass_matching_contracts(self):
        """D Figure 4 allows any SearchCriterion subtype, including overridden matches."""
        class FalseAnd(AndCriterion):
            def matches(self, record):
                return False

        note_condition = TypeCriterion(RecordType.PLAIN_TEXT)
        root = OrCriterion(
            FalseAnd(note_condition, note_condition), TypeCriterion(RecordType.CONTACT)
        )
        self.assertFalse(root.matches(PlainText(1, "note")))
        self.assertTrue(root.matches(Contact(2, "A", "B", "001")))


if __name__ == "__main__":
    unittest.main()
