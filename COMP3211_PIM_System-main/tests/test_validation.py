"""SRS 5.3 / Design 4.1: normal, invalid and boundary record input values."""

import unittest
from datetime import datetime

from model.errors import ValidationError
from model.records import Contact, Event, PlainText, RecordType, Task
from model.validation import MAX_RECORD_ID, build_record, normalize_mobile, normalize_text, parse_time


class TextValidationTests(unittest.TestCase):
    def test_outer_whitespace_removed_internal_unicode_preserved(self):
        """FR4-FR7: retain case, Unicode, underscores and internal whitespace."""
        self.assertEqual(normalize_text(" \t 會議_ notes  A\tB \u3000"), "會議_ notes  A\tB")
        self.assertEqual(normalize_text("e\u0301"), "e\u0301")
        self.assertEqual(normalize_text("_A_"), "_A_")

    def test_empty_blank_and_underscore_only_rejected(self):
        """Stored text, unlike search text, must contain meaningful characters."""
        for value in ("", " ", "\t", "___", " _ \t__ ", "\u3000_\u00a0"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                normalize_text(value)

    def test_line_breaks_rejected_before_trimming(self):
        """Single-line rule includes leading/trailing and Unicode line breaks."""
        separators = (
            "\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e",
            "\x85", "\u2028", "\u2029",
        )
        for separator in separators:
            for value in (separator + "note", "note" + separator, "a" + separator + "b"):
                with self.subTest(value=value), self.assertRaises(ValidationError):
                    normalize_text(value)

    def test_non_text_rejected_as_validation_error(self):
        """Bad API input must not leak TypeError or AttributeError."""
        for value in (None, 123, True, b"note", [], {}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                normalize_text(value)

    def test_normalize_text_label_identifies_affected_field(self):
        """NFR1: callers can name the business field in validation feedback."""
        with self.assertRaises(ValidationError) as caught:
            normalize_text("___", label="Description")
        self.assertIn("Description", caught.exception.reason)
        with self.assertRaises(ValidationError) as caught:
            normalize_text("a\nb", label="Name")
        self.assertIn("Name", caught.exception.reason)


class MobileValidationTests(unittest.TestCase):
    def test_plus_zeroes_and_digit_boundaries_preserved(self):
        """FR7: mobile is text, optionally + and 1-15 ASCII digits."""
        for value in ("0", "+0", "00123", "+00123", "1" * 15, "+" + "0" * 15):
            with self.subTest(value=value):
                self.assertEqual(normalize_mobile(" \t" + value + " \u3000"), value)

    def test_invalid_syntax_and_non_ascii_digits_rejected(self):
        """Reject missing/too many digits, internal spaces and non-ASCII digit classes."""
        invalid_values = (
            "", " ", "+", "1" * 16, "+" + "1" * 16, "++123", "12+3",
            "-123", "12 34", "12\t34", "123-456", "1.0", "１２３", "١٢٣",
            "²", "_", "123x",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                normalize_mobile(value)

    def test_line_breaks_are_not_trimmed_into_valid_mobile(self):
        """The stored-field single-line rule also applies to mobile numbers."""
        for separator in ("\n", "\r", "\v", "\f", "\x85", "\u2028", "\u2029"):
            for value in (separator + "123", "123" + separator, "12" + separator + "3"):
                with self.subTest(value=value), self.assertRaises(ValidationError):
                    normalize_mobile(value)

    def test_non_text_rejected(self):
        """Never coerce numeric mobile input, which could lose leading zeroes."""
        for value in (None, 123, True, b"123", [], {}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                normalize_mobile(value)


class TimeValidationTests(unittest.TestCase):
    def test_normal_past_leap_and_extreme_years(self):
        """FR5-FR6: full calendar minute precision, including years 0001 and 9999."""
        cases = {
            "0001-01-01 00:00": datetime(1, 1, 1),
            "9999-12-31 23:59": datetime(9999, 12, 31, 23, 59),
            "2000-02-29 12:30": datetime(2000, 2, 29, 12, 30),
            "2024-02-29 00:00": datetime(2024, 2, 29),
            "1900-01-01 00:00": datetime(1900, 1, 1),
            "2026-11-20 20:00": datetime(2026, 11, 20, 20),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                result = parse_time(value)
                self.assertEqual(result, expected)
                self.assertIsNone(result.tzinfo)
                self.assertEqual((result.second, result.microsecond), (0, 0))

    def test_invalid_calendar_and_clock_boundaries(self):
        """Reject invalid years, month lengths, leap rules and clock values."""
        invalid_values = (
            "0000-01-01 00:00", "2026-00-01 00:00", "2026-13-01 00:00",
            "2026-01-00 00:00", "2026-04-31 00:00", "2026-02-29 00:00",
            "1900-02-29 00:00", "2026-01-01 24:00", "2026-01-01 23:60",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_time(value)

    def test_exact_ascii_format_without_trimming_or_extra_precision(self):
        """Reject permissive date spellings, timezone suffixes and non-minute inputs."""
        invalid_values = (
            "", "2026-1-01 00:00", "026-01-01 00:00", "10000-01-01 00:00",
            "2026-01-1 00:00", "2026-01-01 0:00", "2026-01-01 00:0",
            "2026/01/01 00:00", "2026-01-01T00:00", " 2026-01-01 00:00",
            "2026-01-01 00:00 ", "2026-01-01 00:00\n", "2026-01-01 00:00:00",
            "2026-01-01 00:00Z", "2026-01-01 00:00+08:00", "２０２６-01-01 00:00",
            "2026-01-01\t00:00",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_time(value)

    def test_non_text_time_rejected(self):
        """The factory's input format is a string, even for valid datetime objects."""
        for value in (None, 123, True, b"2026-01-01 00:00", datetime(2026, 1, 1), []):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_time(value)


class RecordFactoryTests(unittest.TestCase):
    def test_build_all_record_types_with_normalized_values(self):
        """FR3-FR7: exact type-specific fields produce the designed record values."""
        cases = (
            (RecordType.PLAIN_TEXT, {"text": " note "}, PlainText(1, "note")),
            (
                RecordType.TASK,
                {"description": " report ", "deadline": "2026-11-20 20:00"},
                Task(1, "report", datetime(2026, 11, 20, 20)),
            ),
            (
                RecordType.EVENT,
                {
                    "description": " meeting ", "start": "2026-11-20 20:00",
                    "alarm": "2026-11-20 19:00",
                },
                Event(1, "meeting", datetime(2026, 11, 20, 20), datetime(2026, 11, 20, 19)),
            ),
            (
                RecordType.CONTACT,
                {"name": " 王 ", "address": " 香港 ", "mobile": " +00123 "},
                Contact(1, "王", "香港", "+00123"),
            ),
        )
        for kind, fields, expected in cases:
            with self.subTest(kind=kind):
                self.assertEqual(build_record(1, kind, fields), expected)

    def test_missing_extra_id_and_type_fields_rejected(self):
        """FR8: business fields must be exact; ID/type cannot be supplied as data."""
        required = {
            RecordType.PLAIN_TEXT: {"text": "note"},
            RecordType.TASK: {"description": "report", "deadline": "2026-11-20 20:00"},
            RecordType.EVENT: {
                "description": "meeting", "start": "2026-11-20 20:00",
                "alarm": "2026-11-20 19:00",
            },
            RecordType.CONTACT: {"name": "A", "address": "B", "mobile": "00123"},
        }
        for kind, fields in required.items():
            invalid = [
                {key: value for key, value in fields.items() if key != missing}
                for missing in fields
            ]
            invalid += [
                dict(fields, unexpected="x"), dict(fields, id="1"),
                dict(fields, type=kind.value),
            ]
            for candidate in invalid:
                with self.subTest(kind=kind, fields=candidate), self.assertRaises(ValidationError):
                    build_record(1, kind, candidate)

    def test_invalid_ids_rejected_without_coercion(self):
        """Signed 64-bit IDs exclude Boolean, floats, strings and values above MAX."""
        for record_id in (0, -1, True, False, 1.0, "1", None, MAX_RECORD_ID + 1, 10**100):
            with self.subTest(record_id=record_id), self.assertRaises(ValidationError):
                build_record(record_id, RecordType.PLAIN_TEXT, {"text": "note"})
        self.assertEqual(
            build_record(MAX_RECORD_ID, RecordType.PLAIN_TEXT, {"text": "note"}).id,
            MAX_RECORD_ID,
        )

    def test_unknown_or_raw_string_type_rejected(self):
        """The public factory accepts RecordType, not arbitrary strings or enums."""
        for kind in ("PLAIN_TEXT", "plain_text", "UNKNOWN", None, 1, True):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                build_record(1, kind, {"text": "note"})

    def test_invalid_field_containers_and_keys_rejected(self):
        """Invalid API containers produce domain errors rather than incidental exceptions."""
        for fields in (None, [], [("text", "note")], "note", {1: "note"}, {None: "note"}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                build_record(1, RecordType.PLAIN_TEXT, fields)

    def test_each_invalid_business_value_identifies_affected_field(self):
        """FR8 / NFR1 support: malformed values produce actionable field reasons."""
        valid = {
            RecordType.PLAIN_TEXT: {"text": "note"},
            RecordType.TASK: {"description": "report", "deadline": "2026-11-20 20:00"},
            RecordType.EVENT: {
                "description": "meeting", "start": "2026-11-20 20:00",
                "alarm": "2026-11-20 19:00",
            },
            RecordType.CONTACT: {"name": "A", "address": "B", "mobile": "00123"},
        }
        for kind, fields in valid.items():
            for name in fields:
                for invalid in ("", None, 123):
                    candidate = dict(fields, **{name: invalid})
                    with self.subTest(kind=kind, field=name, value=invalid):
                        with self.assertRaises(ValidationError) as caught:
                            build_record(1, kind, candidate)
                        self.assertIn(name, caught.exception.reason)

    def test_factory_enforces_alarm_relationship(self):
        """FR6: individually valid times must also satisfy the Event invariant."""
        with self.assertRaises(ValidationError):
            build_record(
                1, RecordType.EVENT,
                {
                    "description": "meeting", "start": "2026-11-20 20:00",
                    "alarm": "2026-11-20 20:01",
                },
            )

    def test_input_dictionary_unchanged_on_success_and_failure(self):
        """Record construction never mutates caller data, including on rejection."""
        fields = {"text": " note "}
        record = build_record(1, RecordType.PLAIN_TEXT, fields)
        self.assertEqual(fields, {"text": " note "})
        self.assertEqual(record.text, "note")
        fields["text"] = "___"
        with self.assertRaises(ValidationError):
            build_record(2, RecordType.PLAIN_TEXT, fields)
        self.assertEqual(fields, {"text": "___"})
        self.assertEqual(record.text, "note")


if __name__ == "__main__":
    unittest.main()
