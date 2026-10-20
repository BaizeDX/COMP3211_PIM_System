"""SRS FR3-FR7 / Design 3: immutable, independently validated record values."""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from model.errors import ValidationError
from model.records import Contact, Event, PIR, PlainText, RecordType, Task
from model.validation import build_record


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 20, 20)
        self.alarm = datetime(2026, 11, 20, 19)
        self.records = (
            PlainText(1, "note"),
            Task(2, "report", self.start),
            Event(3, "meeting", self.start, self.alarm),
            Contact(4, "王", "香港", "+00123"),
        )

    def test_pir_is_abstract(self):
        """PIR supplies shared behaviour but cannot create incomplete records."""
        with self.assertRaises(TypeError):
            PIR(1)

    def test_exact_record_types_and_constructor_fields(self):
        """FR3: four concrete types carry fixed enum values, not caller overrides."""
        self.assertEqual(
            tuple(record.type for record in self.records),
            (RecordType.PLAIN_TEXT, RecordType.TASK, RecordType.EVENT, RecordType.CONTACT),
        )
        self.assertEqual(
            [kind.value for kind in RecordType],
            ["PLAIN_TEXT", "TASK", "EVENT", "CONTACT"],
        )
        for record in self.records:
            with self.subTest(kind=record.type):
                self.assertIsInstance(record, PIR)
                with self.assertRaises(TypeError):
                    type(record)(record.id, **record.business_fields(), type=record.type)

    def test_direct_constructors_normalize_text_and_mobile(self):
        """Direct calls must not bypass normalization used by the factory."""
        self.assertEqual(PlainText(1, " \t文字_  note ").text, "文字_  note")
        self.assertEqual(Task(1, " report ", self.start).description, "report")
        self.assertEqual(Event(1, " meeting ", self.start, self.alarm).description, "meeting")
        self.assertEqual(
            Contact(1, " 王 ", " 香港  A ", " +00123 "),
            Contact(1, "王", "香港  A", "+00123"),
        )

    def test_all_direct_constructors_reject_invalid_ids(self):
        """FR3: every constructor rejects non-positive and non-integer IDs."""
        for record in self.records:
            for record_id in (0, -1, True, False, 1.0, "1", None):
                with self.subTest(kind=record.type, record_id=record_id):
                    with self.assertRaises(ValidationError):
                        type(record)(record_id, **record.business_fields())

    def test_direct_constructors_reject_invalid_text_fields(self):
        """Every required text field is validated without relying on build_record."""
        for record in self.records:
            for name, value in record.business_fields().items():
                if isinstance(value, datetime):
                    continue
                for invalid in ("", "___", "\nvalid", "valid\u2028", None, 123):
                    fields = record.business_fields()
                    fields[name] = invalid
                    with self.subTest(kind=record.type, field=name, value=invalid):
                        with self.assertRaises(ValidationError) as caught:
                            type(record)(record.id, **fields)
                        self.assertIn(name, caught.exception.reason)

    def test_direct_contact_validates_mobile_syntax(self):
        """FR7: even a direct Contact cannot contain an invalid phone number."""
        for value in ("1 2", "++12", "123-456", "１２３", "1" * 16):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Contact(1, "Name", "Address", value)

    def test_direct_times_require_naive_minute_datetimes(self):
        """FR5-FR6: no strings, dates, seconds, microseconds or timezone conversion."""
        invalid_values = (
            "2026-11-20 20:00", date(2026, 11, 20), None, 123,
            self.start.replace(second=1), self.start.replace(microsecond=1),
            self.start.replace(tzinfo=timezone.utc),
            self.start.replace(tzinfo=timezone(timedelta(hours=8))),
        )
        for record in self.records:
            for name, value in record.business_fields().items():
                if not isinstance(value, datetime):
                    continue
                for invalid in invalid_values:
                    fields = record.business_fields()
                    fields[name] = invalid
                    with self.subTest(kind=record.type, field=name, value=invalid):
                        with self.assertRaises(ValidationError) as caught:
                            type(record)(record.id, **fields)
                        self.assertIn(name, caught.exception.reason)

    def test_past_and_extreme_datetimes_are_valid(self):
        """No current-clock restriction; the complete datetime year range is valid."""
        for value in (datetime(1, 1, 1), datetime(1900, 1, 1), datetime(9999, 12, 31, 23, 59)):
            with self.subTest(value=value):
                self.assertEqual(Task(1, "task", value).deadline, value)
                self.assertEqual(Event(1, "event", value, value).alarm, value)

    def test_event_alarm_before_equal_and_after_start(self):
        """FR6: alarm == start is allowed; alarm > start is rejected."""
        self.assertEqual(Event(1, "event", self.start, self.alarm).alarm, self.alarm)
        self.assertEqual(Event(1, "event", self.start, self.start).alarm, self.start)
        with self.assertRaises(ValidationError):
            Event(1, "event", self.start, self.start + timedelta(minutes=1))

    def test_all_record_fields_cannot_be_assigned_or_deleted(self):
        """ID, type and business fields all remain read-only after construction."""
        for record in self.records:
            for name in ("id", "type", *record.business_fields()):
                original = getattr(record, name)
                with self.subTest(kind=record.type, field=name):
                    with self.assertRaises(FrozenInstanceError):
                        setattr(record, name, original)
                    with self.assertRaises(FrozenInstanceError):
                        delattr(record, name)
                    self.assertEqual(getattr(record, name), original)
            self.assertFalse(hasattr(record, "__dict__"))

    def test_business_fields_are_fresh_ordered_mappings(self):
        """Design 3: callers can modify returned dictionaries without editing a PIR."""
        expected_fields = (
            {"text": "note"},
            {"description": "report", "deadline": self.start},
            {"description": "meeting", "start": self.start, "alarm": self.alarm},
            {"name": "王", "address": "香港", "mobile": "+00123"},
        )
        for record, expected in zip(self.records, expected_fields):
            with self.subTest(kind=record.type):
                exposed = record.business_fields()
                self.assertEqual(exposed, expected)
                self.assertEqual(tuple(exposed), tuple(expected))
                self.assertNotIn("id", exposed)
                self.assertNotIn("type", exposed)
                exposed.clear()
                exposed["injected"] = "changed"
                self.assertEqual(record.business_fields(), expected)

    def test_duplicate_keys_exclude_id_for_all_types(self):
        """FR32 support: same normalized business content yields the same key."""
        for record in self.records:
            with self.subTest(kind=record.type):
                other_id = type(record)(99, **record.business_fields())
                self.assertNotEqual(record, other_id)
                self.assertEqual(record.duplicate_key(), other_id.duplicate_key())
                self.assertEqual(
                    record.duplicate_key(),
                    (record.type, *record.business_fields().values()),
                )

    def test_duplicate_keys_are_case_sensitive_and_include_every_field(self):
        """Distinct type, text case or any changed business field changes the key."""
        self.assertNotEqual(
            PlainText(1, "Note").duplicate_key(), PlainText(1, "note").duplicate_key()
        )
        for record in self.records:
            for name, value in record.business_fields().items():
                if isinstance(value, datetime):
                    changed = value + timedelta(minutes=1)
                elif name == "mobile":
                    changed = "+00999"
                else:
                    changed = value + " changed"
                fields = record.business_fields()
                fields[name] = changed
                with self.subTest(kind=record.type, field=name):
                    candidate = type(record)(record.id, **fields)
                    self.assertNotEqual(record.duplicate_key(), candidate.duplicate_key())
        keys = {record.duplicate_key() for record in self.records}
        self.assertEqual(len(keys), 4)

    def test_duplicate_keys_use_normalized_values(self):
        """Outer whitespace does not distinguish otherwise identical business data."""
        self.assertEqual(
            PlainText(1, " note ").duplicate_key(), PlainText(2, "note").duplicate_key()
        )
        self.assertEqual(
            Contact(1, " 王 ", " 香港 ", " 00123 ").duplicate_key(),
            Contact(2, "王", "香港", "00123").duplicate_key(),
        )

    def test_invalid_replacement_does_not_change_original(self):
        """Immutable validated replacement supports future atomic service updates."""
        original = self.records[2]
        with self.assertRaises(ValidationError):
            replace(original, start=original.alarm - timedelta(minutes=1))
        self.assertEqual(original, Event(3, "meeting", self.start, self.alarm))
        changed = replace(original, description=" revised ")
        self.assertEqual(changed.description, "revised")
        self.assertEqual(original.description, "meeting")

    def test_record_model_needs_no_terminal_io(self):
        """NFR3: successful and rejected construction never calls input or print."""
        with patch("builtins.input", side_effect=AssertionError("Unexpected input")), patch(
            "builtins.print", side_effect=AssertionError("Unexpected output")
        ):
            record = build_record(
                1, RecordType.CONTACT,
                {"name": "Name", "address": "Address", "mobile": "00123"},
            )
            fields = record.business_fields()
            key = record.duplicate_key()
            with self.assertRaises(ValidationError):
                build_record(2, RecordType.PLAIN_TEXT, {"text": "___"})
        self.assertEqual(fields["mobile"], "00123")
        self.assertEqual(key, (RecordType.CONTACT, "Name", "Address", "00123"))


if __name__ == "__main__":
    unittest.main()
