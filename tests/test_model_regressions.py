"""Audit regressions using public model behaviour (SRS FR2/9/11/17/31; Design 10)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from model.criteria import AndCriterion, OrCriterion, TypeCriterion
from model.errors import DuplicateRecordError, ExpressionError, ValidationError
from model.persistence import PIMFileStorage
from model.records import Contact, PlainText, RecordType, Task
from model.search import CriteriaRegistry, ExpressionParser
from model.service import PIMService


class ModelRegressionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "records.pim"
        parser = ExpressionParser()
        self.service = PIMService(PIMFileStorage(), CriteriaRegistry(parser), parser)

    def test_long_flat_conjunction_works_directly_and_as_saved_criterion(self):
        """A grammar-valid conjunction must not crash on Python's evaluation recursion limit."""
        note = self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        self.service.create(
            RecordType.CONTACT, {"name": "A", "address": "B", "mobile": "001"}
        )
        expression = " && ".join(["type=PLAIN_TEXT"] * 1500)
        item = self.service.define_criterion(expression)
        self.assertEqual(self.service.search(expression), (note,))
        self.assertEqual(self.service.search_saved(item.id), (note,))

    def test_long_disjunction_and_negation_keep_boolean_semantics(self):
        """A late true OR leaf and negated AND must work for mixed record types."""
        note = self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        contact = self.service.create(
            RecordType.CONTACT, {"name": "A", "address": "B", "mobile": "001"}
        )
        expression = " || ".join(["type=TASK"] * 1500 + ["type=CONTACT"])
        self.assertEqual(self.service.search(expression), (contact,))
        conjunction = " && ".join(["type=PLAIN_TEXT"] * 1500)
        self.assertEqual(self.service.search(f"!({conjunction})"), (contact,))
        self.assertEqual(self.service.get(note.id), note)

    def test_invalid_branch_after_long_valid_prefix_is_still_fully_validated(self):
        """Short-circuit candidates cannot hide a final invalid condition or allocate a C ID."""
        note = self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        prefix = " || ".join(["type=PLAIN_TEXT"] * 1500)
        for tail in ('unknown~"x"', 'deadline<"invalid"', 'text~""'):
            expression = f"{prefix} || {tail}"
            with self.subTest(tail=tail):
                with self.assertRaises(ExpressionError):
                    self.service.search(expression)
                with self.assertRaises(ExpressionError):
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
