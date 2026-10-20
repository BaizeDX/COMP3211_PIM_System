"""SRS collection/search/dirty rules; Design 4-5 in-memory service contracts."""

import unittest
from datetime import datetime
from unittest.mock import patch

from model.errors import (
    DuplicateRecordError,
    ExpressionError,
    NotFoundError,
    UnknownCriterionError,
    ValidationError,
)
from model.records import Contact, Event, PlainText, RecordType, Task
from model.search import CriteriaRegistry, ExpressionParser
from model.service import PIMService
from model.validation import MAX_RECORD_ID


class _ForbiddenStorage:
    """Catch unintended storage access in tests of in-memory service operations."""

    def read(self, *args, **kwargs):
        raise AssertionError("Unexpected storage access in an in-memory operation test.")

    def write(self, *args, **kwargs):
        raise AssertionError("Unexpected storage access in an in-memory operation test.")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.parser = ExpressionParser()
        self.registry = CriteriaRegistry(self.parser)
        self.store = _ForbiddenStorage()
        self.service = PIMService(self.store, self.registry, self.parser)
        self.time = datetime(2026, 11, 20, 20)

    def _seed_records(self, records, dirty=False):
        """Install valid unit fixtures, not an emulated successful save or load.

        Clean nonempty state and reversed dictionary order isolate in-memory
        invariants without implementing the next stage's persistence behaviour.
        """
        self.service._records = {record.id: record for record in records}
        self.service._high_water = max((record.id for record in records), default=0)
        self.service._dirty = dirty

    def _snapshot(self):
        return (
            self.service.all_records(),
            self.service._high_water,
            self.service.dirty,
            self.service.list_criteria(),
        )

    def test_empty_startup_without_store_access(self):
        """FR1/FR34: constructor starts empty and clean, without auto-loading."""
        self.assertEqual(self.service.all_records(), ())
        self.assertEqual(self.service.list_criteria(), ())
        self.assertIs(self.service.dirty, False)
        self.assertEqual(self.service._high_water, 0)
        self.assertIs(self.service._store, self.store)
        self.assertIs(self.service._criteria, self.registry)
        self.assertIs(self.service._parser, self.parser)

    def test_persistence_methods_delegate_without_faking_success(self):
        """Stage 4 delegates to the store; a store failure must never become success."""
        from pathlib import Path

        before = self._snapshot()
        with self.assertRaises(AssertionError):
            self.service.save(Path("unused.pim"))
        self.assertEqual(self._snapshot(), before)
        with self.assertRaises(AssertionError):
            self.service.load(Path("unused.pim"))
        self.assertEqual(self._snapshot(), before)

    def test_create_all_four_normalized_record_types(self):
        """FR2-FR8: valid creation stores complete records with consecutive IDs."""
        cases = (
            (RecordType.PLAIN_TEXT, {"text": " note "}, PlainText(1, "note")),
            (
                RecordType.TASK,
                {"description": " report ", "deadline": "2026-11-20 20:00"},
                Task(2, "report", self.time),
            ),
            (
                RecordType.EVENT,
                {
                    "description": " meeting ", "start": "2026-11-20 20:00",
                    "alarm": "2026-11-20 19:00",
                },
                Event(3, "meeting", self.time, datetime(2026, 11, 20, 19)),
            ),
            (
                RecordType.CONTACT,
                {"name": " 王 ", "address": " 香港 ", "mobile": " +00123 "},
                Contact(4, "王", "香港", "+00123"),
            ),
        )
        for kind, fields, expected in cases:
            with self.subTest(kind=kind):
                actual = self.service.create(kind, fields)
                self.assertEqual(actual, expected)
                self.assertIs(self.service.get(expected.id), actual)
                self.assertIs(self.service.dirty, True)
                self.assertEqual(self.service._high_water, expected.id)
        self.assertEqual([record.id for record in self.service.all_records()], [1, 2, 3, 4])

    def test_input_dictionary_and_returned_field_copy_cannot_edit_collection(self):
        """FR8/Design 3: the service owns immutable values, not caller dictionaries."""
        fields = {"text": " note "}
        record = self.service.create(RecordType.PLAIN_TEXT, fields)
        self.assertEqual(fields, {"text": " note "})
        fields["text"] = "caller change"
        exposed = record.business_fields()
        exposed["text"] = "another change"
        self.assertEqual(self.service.get(1).text, "note")

    def test_get_and_list_return_immutable_snapshot_values(self):
        """Reads expose valid PIRs and detached tuples, never the live dictionary."""
        first = self.service.create(RecordType.PLAIN_TEXT, {"text": "first"})
        snapshot = self.service.all_records()
        self.service.create(RecordType.PLAIN_TEXT, {"text": "second"})
        self.assertIs(self.service.get(1), first)
        self.assertIsInstance(snapshot, tuple)
        self.assertEqual(snapshot, (first,))
        self.assertEqual(len(self.service.all_records()), 2)
        self.assertEqual(snapshot[0].text, "first")

    def test_lists_and_searches_sort_numeric_ids_not_dictionary_order(self):
        """FR18/FR20: IDs 1,2,10 sort numerically even with reversed insertion."""
        self._seed_records((
            Task(10, "report ten", self.time),
            Task(2, "report two", self.time),
            Task(1, "report one", self.time),
        ))
        saved = self.service.define_criterion('description~"report"')
        for records in (
            self.service.all_records(), self.service.search("type=TASK"),
            self.service.search_saved(saved.id),
        ):
            with self.subTest(ids=[record.id for record in records]):
                self.assertEqual([record.id for record in records], [1, 2, 10])
                self.assertIsInstance(records, tuple)
                self.assertEqual(records[0].description, "report one")
        self.assertFalse(self.service.dirty)

    def test_invalid_ids_cannot_alias_existing_integer_keys(self):
        """FR10/FR19/FR21: True/1.0/string and unhashable IDs are not record ID 1."""
        for dirty in (False, True):
            self._seed_records((PlainText(1, "note"),), dirty)
            before = self._snapshot()
            for record_id in (True, False, 1.0, "1", 0, -1, None, [], {}):
                operations = (
                    lambda: self.service.get(record_id),
                    lambda: self.service.update(record_id, "text", "changed"),
                    lambda: self.service.delete(record_id),
                )
                for operation in operations:
                    with self.subTest(dirty=dirty, record_id=record_id):
                        with self.assertRaises(ValidationError):
                            operation()
                        self.assertEqual(self._snapshot(), before)

    def test_absent_ids_report_not_found_without_mutation(self):
        """Valid absent IDs have a specific error for get, update and delete."""
        for dirty in (False, True):
            self._seed_records((PlainText(1, "note"),), dirty)
            before = self._snapshot()
            for record_id in (2, 99, MAX_RECORD_ID):
                for operation in (
                    lambda: self.service.get(record_id),
                    lambda: self.service.update(record_id, "text", "changed"),
                    lambda: self.service.delete(record_id),
                ):
                    with self.subTest(dirty=dirty, record_id=record_id):
                        with self.assertRaises(NotFoundError) as caught:
                            operation()
                        self.assertIn(str(record_id), caught.exception.reason)
                        self.assertEqual(self._snapshot(), before)

    def test_deleting_highest_or_all_records_does_not_reuse_ids(self):
        """FR2: allocation reflects session history, not the current maximum key."""
        records = [
            self.service.create(RecordType.PLAIN_TEXT, {"text": f"note {number}"})
            for number in range(3)
        ]
        self.service.delete(records[2].id)
        self.assertEqual(self.service._high_water, 3)
        fourth = self.service.create(RecordType.PLAIN_TEXT, {"text": "fourth"})
        self.assertEqual(fourth.id, 4)
        for record in self.service.all_records():
            self.service.delete(record.id)
        self.assertEqual(self.service.all_records(), ())
        self.assertEqual(self.service._high_water, 4)
        self.assertEqual(self.service.create(RecordType.PLAIN_TEXT, {"text": "fifth"}).id, 5)

    def test_invalid_creation_does_not_consume_ids_or_change_dirty(self):
        """FR8/FR34: invalid creation is atomic in initially clean and dirty states."""
        invalid_requests = (
            (RecordType.PLAIN_TEXT, {}),
            (RecordType.PLAIN_TEXT, {"text": "___"}),
            (RecordType.TASK, {"description": "task", "deadline": "bad"}),
            (RecordType.CONTACT, {"name": "A", "address": "B", "mobile": "12 34"}),
            ("PLAIN_TEXT", {"text": "note"}),
        )
        for dirty in (False, True):
            self._seed_records((PlainText(5, "existing"),), dirty)
            before = self._snapshot()
            for kind, fields in invalid_requests:
                with self.subTest(dirty=dirty, kind=kind, fields=fields):
                    with self.assertRaises(ValidationError):
                        self.service.create(kind, fields)
                    self.assertEqual(self._snapshot(), before)
            created = self.service.create(RecordType.PLAIN_TEXT, {"text": "valid"})
            self.assertEqual(created.id, 6)

    def test_duplicates_use_all_normalized_fields_and_report_sorted_ids(self):
        """FR32: same-type normalized content excludes ID and reports every match."""
        cases = (
            (PlainText(2, "note"), PlainText(10, "note"),
             RecordType.PLAIN_TEXT, {"text": " note "}),
            (Task(2, "report", self.time), Task(10, "report", self.time),
             RecordType.TASK, {"description": " report ", "deadline": "2026-11-20 20:00"}),
            (
                Event(2, "meeting", self.time, self.time),
                Event(10, "meeting", self.time, self.time),
                RecordType.EVENT,
                {"description": " meeting ", "start": "2026-11-20 20:00",
                 "alarm": "2026-11-20 20:00"},
            ),
            (
                Contact(2, "王", "香港", "+00123"), Contact(10, "王", "香港", "+00123"),
                RecordType.CONTACT, {"name": " 王 ", "address": " 香港 ", "mobile": " +00123 "},
            ),
        )
        for first, second, kind, fields in cases:
            for dirty in (False, True):
                self._seed_records((second, first), dirty)
                before = self._snapshot()
                with self.subTest(kind=kind, dirty=dirty):
                    with self.assertRaises(DuplicateRecordError) as caught:
                        self.service.create(kind, fields)
                    self.assertEqual(caught.exception.matching_ids, (2, 10))
                    self.assertEqual(self._snapshot(), before)
                    confirmed = self.service.create(kind, fields, allow_duplicate=True)
                    self.assertEqual(confirmed.id, 11)
                    self.assertEqual(confirmed.duplicate_key(), first.duplicate_key())
                    self.assertEqual(len(self.service.all_records()), 3)
                    self.assertTrue(self.service.dirty)

    def test_refusing_duplicate_means_no_retry_and_no_id_consumption(self):
        """A caller declining DuplicateRecordError leaves state exactly as it was."""
        self._seed_records((PlainText(7, "note"),))
        before = self._snapshot()
        with self.assertRaises(DuplicateRecordError):
            self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.service.create(RecordType.PLAIN_TEXT, {"text": "different"}).id, 8)

    def test_duplicate_comparison_is_case_sensitive_and_type_specific(self):
        """FR32: case, type or any differing business value permits normal creation."""
        self.service.create(
            RecordType.TASK, {"description": "report", "deadline": "2026-11-20 20:00"}
        )
        case_change = self.service.create(
            RecordType.TASK, {"description": "Report", "deadline": "2026-11-20 20:00"}
        )
        time_change = self.service.create(
            RecordType.TASK, {"description": "report", "deadline": "2026-11-20 20:01"}
        )
        event = self.service.create(
            RecordType.EVENT,
            {"description": "report", "start": "2026-11-20 20:00", "alarm": "2026-11-20 20:00"},
        )
        self.assertEqual([case_change.id, time_change.id, event.id], [2, 3, 4])

    def test_invalid_request_is_not_a_duplicate_confirmation(self):
        """FR8: allowing duplicate content never bypasses record validation."""
        self._seed_records((Task(1, "report", self.time),))
        before = self._snapshot()
        for allow_duplicate in (False, True):
            with self.subTest(allow_duplicate=allow_duplicate):
                with self.assertRaises(ValidationError):
                    self.service.create(
                        RecordType.TASK, {"description": "report", "deadline": "bad"},
                        allow_duplicate=allow_duplicate,
                    )
                self.assertEqual(self._snapshot(), before)

    def test_truthy_non_boolean_duplicate_flags_cannot_imply_confirmation(self):
        """The Boolean interface must not interpret a string or integer as consent."""
        self._seed_records((PlainText(1, "note"),))
        before = self._snapshot()
        for flag in ("y", "false", 1, 0, None, []):
            with self.subTest(flag=flag), self.assertRaises(ValidationError):
                self.service.create(RecordType.PLAIN_TEXT, {"text": "note"}, flag)
            self.assertEqual(self._snapshot(), before)

    def test_update_each_business_field_preserves_other_data_id_and_type(self):
        """FR9: each successful edit changes exactly one normalized business field."""
        cases = (
            (PlainText(2, "note"), "text", " revised ", "revised"),
            (Task(2, "task", self.time), "description", " revised ", "revised"),
            (Task(2, "task", self.time), "deadline", "2026-11-21 00:00", datetime(2026, 11, 21)),
            (Event(2, "event", self.time, self.time), "description", "revised", "revised"),
            (Event(2, "event", self.time, self.time), "start",
             "2026-11-20 21:00", datetime(2026, 11, 20, 21)),
            (Event(2, "event", self.time, self.time), "alarm",
             "2026-11-20 19:00", datetime(2026, 11, 20, 19)),
            (Contact(2, "A", "B", "00123"), "name", " 王 ", "王"),
            (Contact(2, "A", "B", "00123"), "address", " 香港 ", "香港"),
            (Contact(2, "A", "B", "00123"), "mobile", " +00500 ", "+00500"),
        )
        other = PlainText(7, "unrelated")
        for original, field, value, expected in cases:
            self._seed_records((original, other))
            before = original.business_fields()
            with self.subTest(kind=original.type, field=field):
                updated = self.service.update(2, field, value)
                self.assertIs(self.service.get(2), updated)
                self.assertIsNot(updated, original)
                self.assertEqual(updated.id, original.id)
                self.assertEqual(updated.type, original.type)
                expected_fields = dict(before, **{field: expected})
                self.assertEqual(updated.business_fields(), expected_fields)
                self.assertEqual(original.business_fields(), before)
                self.assertIs(self.service.get(7), other)
                self.assertEqual(self.service._high_water, 7)
                self.assertTrue(self.service.dirty)

    def test_noop_updates_preserve_original_identity_and_both_dirty_states(self):
        """FR34: normalized no-op edits neither introduce nor clear unsaved changes."""
        cases = (
            (PlainText(1, "note"), "text", " note "),
            (Task(1, "task", self.time), "description", " task "),
            (Task(1, "task", self.time), "deadline", "2026-11-20 20:00"),
            (Event(1, "event", self.time, self.time), "start", "2026-11-20 20:00"),
            (Event(1, "event", self.time, self.time), "alarm", "2026-11-20 20:00"),
            (Contact(1, "A", "B", "00123"), "mobile", " 00123 "),
        )
        for original, field, value in cases:
            for dirty in (False, True):
                self._seed_records((original,), dirty)
                before = self._snapshot()
                with self.subTest(kind=original.type, field=field, dirty=dirty):
                    self.assertIs(self.service.update(1, field, value), original)
                    self.assertEqual(self._snapshot(), before)

    def test_invalid_field_or_id_type_edit_cannot_change_state(self):
        """FR9-FR10: ID/type, missing/wrong-type fields and malformed names are forbidden."""
        for dirty in (False, True):
            original = Task(1, "task", self.time)
            self._seed_records((original,), dirty)
            before = self._snapshot()
            for field in ("id", "type", "text", "start", "name", "", "Deadline", None, [], 1):
                with self.subTest(field=field, dirty=dirty), self.assertRaises(ValidationError):
                    self.service.update(1, field, "new")
                self.assertEqual(self._snapshot(), before)
                self.assertIs(self.service.get(1), original)

    def test_invalid_field_values_leave_original_and_dirty_unchanged(self):
        """FR10: bad text/mobile/calendar/time values cannot partially replace a PIR."""
        cases = (
            (PlainText(1, "note"), "text", "___"),
            (PlainText(1, "note"), "text", "\nnote"),
            (PlainText(1, "note"), "text", None),
            (Task(1, "task", self.time), "deadline", "2026-02-29 00:00"),
            (Task(1, "task", self.time), "deadline", "2026-11-20 20:00:00"),
            (Task(1, "task", self.time), "deadline", self.time),
            (Contact(1, "A", "B", "00123"), "mobile", "12 34"),
        )
        for original, field, value in cases:
            for dirty in (False, True):
                self._seed_records((original,), dirty)
                before = self._snapshot()
                with self.subTest(field=field, value=value, dirty=dirty):
                    with self.assertRaises(ValidationError):
                        self.service.update(1, field, value)
                    self.assertEqual(self._snapshot(), before)
                    self.assertIs(self.service.get(1), original)

    def test_complete_event_candidate_revalidates_alarm_and_start_atomically(self):
        """FR9: individually valid time edits still enforce the complete Event invariant."""
        original = Event(1, "event", self.time, datetime(2026, 11, 20, 19))
        for dirty in (False, True):
            self._seed_records((original,), dirty)
            before = self._snapshot()
            for field, value in (("start", "2026-11-20 18:59"), ("alarm", "2026-11-20 20:01")):
                with self.subTest(field=field, dirty=dirty), self.assertRaises(ValidationError):
                    self.service.update(1, field, value)
                self.assertEqual(self._snapshot(), before)
                self.assertIs(self.service.get(1), original)
        updated = self.service.update(1, "start", "2026-11-20 19:00")
        self.assertEqual(updated.start, updated.alarm)

    def test_editing_other_fields_preserves_year_0001_without_reformatting(self):
        """D 3: updating text must not corrupt untouched early-year datetime values."""
        original = Event(1, "event", datetime(1, 1, 1), datetime(1, 1, 1))
        self._seed_records((original,))
        updated = self.service.update(1, "description", "revised")
        self.assertEqual(updated.start, datetime(1, 1, 1))
        self.assertEqual(updated.alarm, datetime(1, 1, 1))
        self.assertEqual(self.service._high_water, 1)

    def test_updates_can_produce_duplicate_content_without_prompting(self):
        """FR32 applies to creation only; a valid update may match an existing PIR."""
        first = PlainText(1, "note")
        second = PlainText(2, "other")
        self._seed_records((first, second))
        updated = self.service.update(2, "text", " note ")
        self.assertEqual(updated.duplicate_key(), first.duplicate_key())
        self.assertEqual([record.id for record in self.service.all_records()], [1, 2])
        self.assertTrue(self.service.dirty)
        with self.assertRaises(DuplicateRecordError) as caught:
            self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        self.assertEqual(caught.exception.matching_ids, (1, 2))

    def test_delete_returns_selected_record_and_sets_dirty_without_touching_others(self):
        """FR21 model boundary: caller-confirmed delete removes only the selected PIR."""
        first, second = PlainText(1, "first"), PlainText(10, "second")
        self._seed_records((second, first))
        self.assertIs(self.service.delete(1), first)
        self.assertEqual(self.service.all_records(), (second,))
        self.assertEqual(self.service._high_water, 10)
        self.assertTrue(self.service.dirty)
        with self.assertRaises(NotFoundError):
            self.service.get(1)

    def test_dirty_property_is_read_only(self):
        """D 4.2: callers cannot clear dirty through the public interface."""
        with self.assertRaises(AttributeError):
            self.service.dirty = True
        self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        with self.assertRaises(AttributeError):
            self.service.dirty = False
        self.assertTrue(self.service.dirty)

    def test_search_uses_all_current_records_without_mutation(self):
        """FR11-FR18: direct expressions return complete immutable records in ID order."""
        task = Task(2, "COMP3211 report", self.time)
        self._seed_records((
            Event(10, "COMP3211 meeting", self.time, self.time), task,
            Contact(1, "A", "B", "00123"),
        ))
        before = self._snapshot()
        result = self.service.search(
            'type=TASK && description~"COMP3211" && deadline<"2026-11-21 00:00"'
        )
        self.assertEqual(result, (task,))
        self.assertIs(result[0], task)
        self.assertEqual(self.service.search('name~"missing"'), ())
        self.assertEqual(self._snapshot(), before)

    def test_invalid_search_is_validated_even_when_collection_is_empty(self):
        """FR17: neither empty data nor short-circuit branches hide expression errors."""
        for records in ((), (PlainText(1, "note"),)):
            for dirty in (False, True):
                self._seed_records(records, dirty)
                before = self._snapshot()
                for expression in ("", 'unknown~"x"', 'type=TASK || deadline<"bad"'):
                    with self.subTest(records=records, dirty=dirty, expression=expression):
                        with self.assertRaises(ExpressionError):
                            self.service.search(expression)
                        self.assertEqual(self._snapshot(), before)

    def test_saved_criteria_reevaluate_after_create_update_and_delete(self):
        """FR31: criteria use live values, remain defined and never cache old results."""
        first = self.service.create(
            RecordType.TASK, {"description": "report", "deadline": "2026-11-20 20:00"}
        )
        saved = self.service.define_criterion('type=TASK && description~"report"')
        definitions = self.service.list_criteria()
        self.assertEqual(self.service.search_saved(saved.id), (first,))
        second = self.service.create(
            RecordType.TASK, {"description": "new report", "deadline": "2026-11-21 00:00"}
        )
        self.assertEqual(self.service.search_saved(saved.id), (first, second))
        self.service.update(first.id, "description", "exam")
        self.assertEqual(self.service.search_saved(saved.id), (second,))
        self.service.delete(second.id)
        self.assertEqual(self.service.search_saved(saved.id), ())
        self.assertEqual(self.service.list_criteria(), definitions)
        self.assertEqual(saved.expression, 'type=TASK && description~"report"')

    def test_criteria_definition_listing_and_search_preserve_both_dirty_states(self):
        """FR30/FR34: criterion operations never change record data, IDs or dirty."""
        for dirty in (False, True):
            self._seed_records((PlainText(4, "note"),), dirty)
            record_state = self._snapshot()[:3]
            item = self.service.define_criterion('text~"note"')
            self.assertIs(self.service.list_criteria()[-1], item)
            self.assertEqual(self.service.search_saved(item.id), (self.service.get(4),))
            self.assertEqual(self.service.search('text~"note"'), (self.service.get(4),))
            self.assertEqual(self._snapshot()[:3], record_state)

    def test_unknown_saved_criterion_preserves_all_service_state(self):
        """FR17: malformed/unknown criterion IDs are errors without mutation."""
        item = self.service.define_criterion("type=TASK")
        before = self._snapshot()
        for value in ("C2", "c1", "@C1", "", None, [], 1):
            with self.subTest(value=value), self.assertRaises(UnknownCriterionError):
                self.service.search_saved(value)
            self.assertEqual(self._snapshot(), before)
        self.assertIs(self.service.list_criteria()[0], item)

    def test_invalid_criterion_definition_does_not_consume_c_or_record_id(self):
        """FR30: rejected definitions preserve entries and independent ID counters."""
        before = self._snapshot()
        with self.assertRaises(ExpressionError):
            self.service.define_criterion('description~""')
        self.assertEqual(self._snapshot(), before)
        item = self.service.define_criterion("type=TASK")
        self.assertEqual(item.id, "C1")
        self.assertEqual(self.service.create(RecordType.PLAIN_TEXT, {"text": "note"}).id, 1)

    def test_criterion_listing_is_numeric_and_search_does_not_define_criteria(self):
        """Criteria IDs and record IDs have separate allocation and read-only search."""
        self.service.search("type=TASK")
        for number in range(1, 13):
            self.assertEqual(self.service.define_criterion("type=TASK").id, f"C{number}")
        self.assertEqual(
            [item.id for item in self.service.list_criteria()],
            [f"C{number}" for number in range(1, 13)],
        )
        self.assertEqual(self.service.all_records(), ())
        self.assertEqual(self.service._high_water, 0)
        self.assertFalse(self.service.dirty)

    def test_reads_and_failures_do_not_clear_existing_dirty_state(self):
        """FR34: successful reads and expected failures never lose unsaved changes."""
        record = self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        before = self._snapshot()
        self.service.get(record.id)
        self.service.all_records()
        self.service.search('text~"note"')
        with self.assertRaises(ValidationError):
            self.service.update(record.id, "text", "")
        with self.assertRaises(NotFoundError):
            self.service.delete(99)
        with self.assertRaises(DuplicateRecordError):
            self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        self.assertEqual(self._snapshot(), before)

    def test_existing_snapshots_keep_old_values_after_update_and_delete(self):
        """Immutable snapshots cannot become live views of later collection mutations."""
        record = self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
        snapshot = self.service.all_records()
        search_result = self.service.search('text~"note"')
        self.service.update(record.id, "text", "revised")
        self.service.delete(record.id)
        self.assertEqual(snapshot, (record,))
        self.assertEqual(search_result, (record,))
        self.assertEqual(record.text, "note")
        self.assertEqual(self.service.all_records(), ())

    def test_service_operations_never_use_terminal_or_storage(self):
        """NFR3: every in-memory public operation works without input/output or files."""
        with patch("builtins.input", side_effect=AssertionError("Unexpected input")), patch(
            "builtins.print", side_effect=AssertionError("Unexpected output")
        ):
            record = self.service.create(RecordType.PLAIN_TEXT, {"text": "note"})
            self.assertIs(self.service.get(record.id), record)
            item = self.service.define_criterion('text~"note"')
            self.assertEqual(self.service.list_criteria(), (item,))
            self.assertEqual(self.service.search('text~"note"'), (record,))
            self.assertEqual(self.service.search_saved(item.id), (record,))
            self.assertEqual(self.service.all_records(), (record,))
            self.service.update(record.id, "text", "revised")
            with self.assertRaises(ValidationError):
                self.service.update(record.id, "id", "2")
            self.service.delete(record.id)
            self.assertEqual(self.service.all_records(), ())
            self.assertTrue(self.service.dirty)


if __name__ == "__main__":
    unittest.main()
