"""SRS FR22-FR26/FR33-FR34 and Design 9: files and service commit boundaries."""

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from model.errors import OverwriteRequiredError, PersistenceError
from model.persistence import PIMFileStorage
from model.records import Contact, Event, PlainText, RecordType, Task
from model.search import CriteriaRegistry, ExpressionParser
from model.service import PIMService


class _FaultyTemporary:
    """Wrap a real temporary file to fail at a controlled write/flush/close phase."""

    def __init__(self, actual, phase):
        self.actual = actual
        self.name = actual.name
        self.phase = phase

    def __enter__(self):
        return self

    def write(self, payload):
        if self.phase in ("write", "short"):
            count = self.actual.write(payload[:5])
            if self.phase == "write":
                raise OSError("Controlled write failure.")
            return count
        return self.actual.write(payload)

    def flush(self):
        if self.phase == "flush":
            raise OSError("Controlled flush failure.")
        self.actual.flush()

    def __exit__(self, exc_type, exc_value, traceback):
        result = self.actual.__exit__(exc_type, exc_value, traceback)
        if self.phase == "close" and exc_type is None:
            raise OSError("Controlled close failure.")
        return result


class StorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "records.pim"
        self.store = PIMFileStorage()
        self.records = (
            Contact(10, "王", "香港  _ A", "+00123"),
            Event(7, "meeting", datetime(2026, 11, 20, 20), datetime(2026, 11, 20, 19)),
            Task(2, "report", datetime(1, 1, 1)),
            PlainText(1, 'Unicode 中 😀 "quoted" C:\\notes _'),
        )

    def _document(self):
        return {
            "format": "PIM", "version": 1,
            "records": [{"id": 1, "type": "PLAIN_TEXT", "text": "note"}],
        }

    def _write_document(self, document):
        self.path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def test_all_types_round_trip_preserves_exact_values_and_numeric_ids(self):
        """FR26: IDs, complete fields, Unicode, zeroes and early years survive."""
        self.assertIsNone(self.store.write(self.path, self.records))
        loaded = self.store.read(self.path)
        self.assertIsInstance(loaded, tuple)
        self.assertEqual(loaded, tuple(sorted(self.records, key=lambda record: record.id)))
        self.assertEqual([record.id for record in loaded], [1, 2, 7, 10])
        self.assertEqual(loaded[1].deadline, datetime(1, 1, 1))
        self.assertEqual(loaded[-1].mobile, "+00123")

    def test_unicode_space_paths_crlf_json_and_closed_read_handle(self):
        """Native Unicode/space paths and CRLF JSON round-trip; read releases its handle."""
        directory = self.directory / "资料 文件"
        directory.mkdir()
        path = directory / "记录 中文.pim"
        self.store.write(path, self.records)
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        loaded = self.store.read(path)
        self.assertEqual(loaded, tuple(sorted(self.records, key=lambda record: record.id)))
        moved = directory / "改名 记录.pim"
        path.rename(moved)
        moved.unlink()
        self.assertEqual(list(directory.iterdir()), [])

    def test_failed_staging_closes_handle_before_cleanup(self):
        """A Windows unlink must never be attempted while our temporary handle is open."""
        self.path.write_bytes(b"original")
        original_factory = tempfile.NamedTemporaryFile
        original_unlink = Path.unlink
        handles, cleaned = [], []

        def factory(**kwargs):
            actual = original_factory(**kwargs)
            handles.append(actual)
            return _FaultyTemporary(actual, "flush")

        def cleanup(path, *args, **kwargs):
            self.assertTrue(handles[-1].closed)
            cleaned.append(path)
            return original_unlink(path, *args, **kwargs)

        with patch("model.persistence.tempfile.NamedTemporaryFile", side_effect=factory), patch(
            "model.persistence.Path.unlink", autospec=True, side_effect=cleanup
        ):
            with self.assertRaises(PersistenceError):
                self.store.write(self.path, self.records, overwrite=True)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_exact_schema_encoding_and_fixed_key_order(self):
        """D 9.2/R9: UTF-8 without BOM, direct Unicode and canonical numeric order."""
        self.store.write(self.path, self.records)
        raw = self.path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("王".encode("utf-8"), raw)
        self.assertIn("😀".encode("utf-8"), raw)
        self.assertTrue(raw.endswith(b"\n"))
        document = json.loads(raw)
        self.assertEqual(list(document), ["format", "version", "records"])
        self.assertEqual(document["format"], "PIM")
        self.assertIs(type(document["version"]), int)
        self.assertEqual(document["version"], 1)
        expected = (
            ["id", "type", "text"], ["id", "type", "description", "deadline"],
            ["id", "type", "description", "start", "alarm"],
            ["id", "type", "name", "address", "mobile"],
        )
        for record, keys in zip(document["records"], expected):
            self.assertEqual(list(record), keys)
        self.assertEqual(document["records"][1]["deadline"], "0001-01-01 00:00")

    def test_empty_collection_is_a_valid_round_trip(self):
        """FR22/FR24: an empty records array is valid, unlike an empty file."""
        self.store.write(self.path, ())
        self.assertEqual(self.store.read(self.path), ())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["records"], [])
        self.path.write_bytes(b"")
        with self.assertRaises(PersistenceError):
            self.store.read(self.path)

    def test_duplicate_business_content_under_distinct_ids_is_valid(self):
        """FR26: load/save never deduplicates equal contents or seeks confirmation."""
        records = (PlainText(10, "same"), PlainText(2, "same"))
        self.store.write(self.path, records)
        self.assertEqual(self.store.read(self.path), (records[1], records[0]))

    def test_unordered_records_and_json_keys_are_accepted_then_sorted(self):
        """Canonical values are required, but input indentation/key order is not fixed."""
        document = {
            "records": [
                {"text": "中", "type": "PLAIN_TEXT", "id": 10},
                {"id": 2, "type": "PLAIN_TEXT", "text": "other"},
            ],
            "version": 1, "format": "PIM",
        }
        self.path.write_text(json.dumps(document, ensure_ascii=True), encoding="utf-8")
        self.assertEqual(self.store.read(self.path), (PlainText(2, "other"), PlainText(10, "中")))

    def test_lowercase_extension_is_required_for_read_and_write(self):
        """File extension validation precedes access, even for otherwise valid data."""
        for name in ("records.PIM", "records.json", "records.pim.bak", "records"):
            path = self.directory / name
            path.write_text(json.dumps(self._document()), encoding="utf-8")
            original = path.read_bytes()
            with self.subTest(path=name):
                with self.assertRaises(PersistenceError):
                    self.store.read(path)
                with self.assertRaises(PersistenceError):
                    self.store.write(path, self.records, overwrite=True)
                self.assertEqual(path.read_bytes(), original)

    def test_invalid_path_argument_and_null_byte_are_domain_errors(self):
        """Wrong API/path inputs must not leak incidental file exceptions."""
        for path in (None, "records.pim", 1, Path("bad\0.pim")):
            with self.subTest(path=path):
                with self.assertRaises(PersistenceError):
                    self.store.read(path)
                with self.assertRaises(PersistenceError):
                    self.store.write(path, ())

    def test_missing_file_directory_and_permission_errors_are_wrapped(self):
        """Expected open/stat failures become actionable PersistenceError instances."""
        with self.assertRaises(PersistenceError) as caught:
            self.store.read(self.path)
        self.assertIn("Cannot load", caught.exception.reason)
        self.path.mkdir()
        with self.assertRaises(PersistenceError):
            self.store.read(self.path)
        with self.assertRaises(PersistenceError):
            self.store.write(self.path, ())
        with patch.object(Path, "read_text", side_effect=PermissionError("Controlled denial.")):
            with self.assertRaises(PersistenceError) as caught:
                self.store.read(self.directory / "denied.pim")
        self.assertIn("Controlled denial", caught.exception.reason)

    def test_malformed_json_bom_and_invalid_utf8_are_rejected(self):
        """D 9.2-9.3: no BOM, malformed JSON or invalid encoding is accepted."""
        payloads = (
            b"", b"{", b'{"format":"PIM",}', b"not JSON", b"\xff\xfe",
            b"\xef\xbb\xbf" + json.dumps(self._document()).encode(),
            b'{"format":"PIM","version":1,"records":[]} trailing',
        )
        for payload in payloads:
            self.path.write_bytes(payload)
            with self.subTest(payload=payload), self.assertRaises(PersistenceError):
                self.store.read(self.path)

    def test_duplicate_json_keys_at_root_and_record_levels_are_rejected(self):
        """Duplicate keys are rejected before last-value-wins decoding can hide them."""
        payloads = (
            '{"format":"PIM","format":"PIM","version":1,"records":[]}',
            '{"format":"PIM","version":1,"version":2,"records":[]}',
            '{"format":"PIM","version":1,"records":[],"records":[]}',
            '{"format":"PIM","version":1,"records":'
            '[{"id":1,"id":2,"type":"PLAIN_TEXT","text":"note"}]}',
            '{"format":"PIM","version":1,"records":'
            '[{"id":1,"type":"PLAIN_TEXT","text":"a","text":"b"}]}',
            r'{"format":"PIM","\u0066ormat":"PIM","version":1,"records":[]}',
            '{"format":"PIM","version":1,"records":[],'
            '"extra":{"duplicate":1,"duplicate":2}}',
        )
        for payload in payloads:
            self.path.write_text(payload, encoding="utf-8")
            with self.subTest(payload=payload), self.assertRaises(PersistenceError) as caught:
                self.store.read(self.path)
            self.assertIn("Duplicate JSON object key", caught.exception.reason)

    def test_nonstandard_nan_and_infinity_are_rejected(self):
        """Python JSON extensions must not loosen the documented JSON schema."""
        for token in ("NaN", "Infinity", "-Infinity"):
            self.path.write_text(
                '{"format":"PIM","version":' + token + ',"records":[]}', encoding="utf-8"
            )
            with self.subTest(token=token), self.assertRaises(PersistenceError):
                self.store.read(self.path)

    def test_invalid_root_shapes_and_key_sets_are_rejected(self):
        """Root object contains exactly format, version and records."""
        documents = [None, [], True, "PIM", {}, {"format": "PIM"}]
        for key in self._document():
            missing = self._document()
            del missing[key]
            documents.append(missing)
        documents.append(dict(self._document(), criteria=[]))
        documents.append(dict(self._document(), dirty=False))
        documents.append(dict(self._document(), high_water=100))
        for document in documents:
            self._write_document(document)
            with self.subTest(document=document), self.assertRaises(PersistenceError):
                self.store.read(self.path)

    def test_wrong_format_version_and_records_primitive_types_are_rejected(self):
        """Booleans/floats/string 1 are not supported integer schema version 1."""
        for key, values in (
            ("format", ("OTHER", "pim", 1, True, None, [], {})),
            ("version", (0, 2, "1", True, False, 1.0, None, [], {})),
            ("records", (None, {}, "records", True, 1)),
        ):
            for value in values:
                document = self._document()
                document[key] = value
                self._write_document(document)
                with self.subTest(key=key, value=value), self.assertRaises(PersistenceError):
                    self.store.read(self.path)

    def test_invalid_record_objects_ids_and_type_values_are_rejected(self):
        """Record objects require unique positive integer IDs and exact type spellings."""
        entries = [None, [], True, 1, "note", {}, {"id": 1}, {"type": "PLAIN_TEXT"}]
        for value in (True, False, 0, -1, 1.0, "1", None, [], {}):
            entries.append(dict(self._document()["records"][0], id=value))
        for value in ("plain_text", "UNKNOWN", True, 1, None, [], {}):
            entries.append(dict(self._document()["records"][0], type=value))
        for entry in entries:
            document = self._document()
            document["records"] = [entry]
            self._write_document(document)
            with self.subTest(entry=entry), self.assertRaises(PersistenceError):
                self.store.read(self.path)

    def test_duplicate_record_ids_are_rejected(self):
        """FR25: even valid different records cannot share one saved ID."""
        document = self._document()
        document["records"].append({"id": 1, "type": "CONTACT",
                                    "name": "A", "address": "B", "mobile": "00123"})
        self._write_document(document)
        with self.assertRaises(PersistenceError) as caught:
            self.store.read(self.path)
        self.assertIn("Duplicate record ID 1", caught.exception.reason)

    def test_every_record_field_set_and_primitive_value_is_validated(self):
        """D 9.3: required/unknown fields and wrong business-value types all reject."""
        self.store.write(self.path, self.records)
        valid_entries = json.loads(self.path.read_text(encoding="utf-8"))["records"]
        for entry in valid_entries:
            for key in entry:
                candidate = dict(entry)
                del candidate[key]
                self._write_document({"format": "PIM", "version": 1, "records": [candidate]})
                with self.subTest(kind=entry["type"], missing=key):
                    with self.assertRaises(PersistenceError):
                        self.store.read(self.path)
            for name in ("unexpected", "dirty", "criterion"):
                candidate = dict(entry, **{name: "extra"})
                self._write_document({"format": "PIM", "version": 1, "records": [candidate]})
                with self.subTest(kind=entry["type"], extra=name):
                    with self.assertRaises(PersistenceError):
                        self.store.read(self.path)
            for key in set(entry) - {"id", "type"}:
                for value in (None, True, 123, [], {}):
                    candidate = dict(entry, **{key: value})
                    self._write_document({"format": "PIM", "version": 1, "records": [candidate]})
                    with self.subTest(kind=entry["type"], field=key, value=value):
                        with self.assertRaises(PersistenceError):
                            self.store.read(self.path)

    def test_invalid_and_noncanonical_business_values_are_not_repaired(self):
        """Do not silently trim stored text/mobile or accept bad time/calendar relations."""
        entries = (
            {"id": 1, "type": "PLAIN_TEXT", "text": " note "},
            {"id": 1, "type": "PLAIN_TEXT", "text": "___"},
            {"id": 1, "type": "PLAIN_TEXT", "text": "line\nbreak"},
            {"id": 1, "type": "TASK", "description": "task", "deadline": "2026-02-29 00:00"},
            {"id": 1, "type": "TASK", "description": "task", "deadline": "1-01-01 00:00"},
            {"id": 1, "type": "TASK", "description": "task", "deadline": "2026-01-01 00:00Z"},
            {"id": 1, "type": "CONTACT", "name": "A", "address": "B", "mobile": " 00123 "},
            {"id": 1, "type": "CONTACT", "name": "A", "address": "B", "mobile": "１２３"},
            {"id": 1, "type": "EVENT", "description": "event",
             "start": "2026-01-01 00:00", "alarm": "2026-01-01 00:01"},
        )
        for entry in entries:
            self._write_document({"format": "PIM", "version": 1, "records": [entry]})
            before = self.path.read_bytes()
            with self.subTest(entry=entry), self.assertRaises(PersistenceError):
                self.store.read(self.path)
            self.assertEqual(self.path.read_bytes(), before)

    def test_escaped_unpaired_surrogate_cannot_enter_utf8_record_data(self):
        """UTF-8 record strings cannot contain an unpaired Unicode surrogate."""
        self.path.write_text(
            r'{"format":"PIM","version":1,"records":'
            r'[{"id":1,"type":"PLAIN_TEXT","text":"\ud800"}]}',
            encoding="utf-8",
        )
        with self.assertRaises(PersistenceError):
            self.store.read(self.path)

    def test_existing_file_requires_explicit_overwrite(self):
        """FR33: refusal (no retry) leaves bytes unchanged and creates no temporary file."""
        self.path.write_bytes(b"existing target")
        before = set(self.directory.iterdir())
        with self.assertRaises(OverwriteRequiredError):
            self.store.write(self.path, self.records)
        self.assertEqual(self.path.read_bytes(), b"existing target")
        self.assertEqual(set(self.directory.iterdir()), before)
        self.assertIsNone(self.store.write(self.path, self.records, overwrite=True))
        self.assertEqual(len(self.store.read(self.path)), 4)

    def test_invalid_overwrite_flags_do_not_grant_consent(self):
        """The documented Boolean flag must not treat truthy strings/integers as consent."""
        self.path.write_bytes(b"existing")
        for flag in ("y", 1, 0, None, []):
            with self.subTest(flag=flag), self.assertRaises(PersistenceError):
                self.store.write(self.path, (), overwrite=flag)
            self.assertEqual(self.path.read_bytes(), b"existing")

    def test_invalid_snapshot_is_rejected_before_writing(self):
        """Expected write validation errors preserve the target and leave no staged file."""
        self.path.write_bytes(b"existing")
        invalid_snapshots = (None, [], (object(),), (PlainText(1, "a"), PlainText(1, "b")))
        for records in invalid_snapshots:
            with self.subTest(records=records), self.assertRaises(PersistenceError):
                self.store.write(self.path, records, overwrite=True)
            self.assertEqual(self.path.read_bytes(), b"existing")
            self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_missing_parent_is_not_created_automatically(self):
        """Invalid destinations fail rather than introducing extra filesystem behaviour."""
        target = self.directory / "missing" / "records.pim"
        with self.assertRaises(PersistenceError):
            self.store.write(target, ())
        self.assertFalse(target.parent.exists())

    def test_encode_and_temporary_creation_fail_before_target_change(self):
        """Encoding/creation failures cannot truncate an existing target."""
        self.path.write_bytes(b"existing")
        for target, error in (
            ("model.persistence.json.dumps", ValueError("Controlled encoding failure.")),
            ("model.persistence.tempfile.NamedTemporaryFile", PermissionError("No temp access.")),
        ):
            with self.subTest(target=target), patch(target, side_effect=error):
                with self.assertRaises(PersistenceError):
                    self.store.write(self.path, self.records, overwrite=True)
            self.assertEqual(self.path.read_bytes(), b"existing")
            self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_write_flush_close_and_short_write_failures_cleanup_without_replacement(self):
        """A real staged file may contain bytes on failure; it must not replace the target."""
        original_factory = tempfile.NamedTemporaryFile
        for phase in ("write", "short", "flush", "close"):
            self.path.write_bytes(b"existing")
            staged = []

            def factory(**kwargs):
                actual = original_factory(**kwargs)
                staged.append(Path(actual.name))
                return _FaultyTemporary(actual, phase)

            with self.subTest(phase=phase), patch(
                "model.persistence.tempfile.NamedTemporaryFile", side_effect=factory
            ), patch("model.persistence.os.replace") as replace:
                with self.assertRaises(PersistenceError):
                    self.store.write(self.path, self.records, overwrite=True)
                replace.assert_not_called()
            self.assertTrue(staged)
            self.assertTrue(all(path.parent == self.directory for path in staged))
            self.assertTrue(all(not path.exists() for path in staged))
            self.assertEqual(self.path.read_bytes(), b"existing")
            self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_replace_failure_preserves_existing_or_absent_target_and_cleans_temp(self):
        """D 9.3: replacement is the only target commit point."""
        for exists in (False, True):
            if exists:
                self.path.write_bytes(b"existing")
            with self.subTest(exists=exists), patch(
                "model.persistence.os.replace", side_effect=PermissionError("Replace denied.")
            ):
                with self.assertRaises(PersistenceError):
                    self.store.write(self.path, self.records, overwrite=True)
            if exists:
                self.assertEqual(self.path.read_bytes(), b"existing")
            else:
                self.assertFalse(self.path.exists())
            self.assertEqual(list(self.directory.iterdir()), [self.path] if exists else [])

    def test_success_replaces_only_after_same_directory_temp_is_flushed_and_closed(self):
        """Observe the real replace call: complete staged bytes, closed handle, old target."""
        self.path.write_bytes(b"existing")
        original_factory = tempfile.NamedTemporaryFile
        original_replace = os.replace
        staged_files = []

        def factory(**kwargs):
            actual = original_factory(**kwargs)
            staged_files.append(actual)
            return actual

        def replace(source, destination):
            self.assertEqual(Path(source).parent, self.directory)
            self.assertEqual(destination, self.path)
            self.assertTrue(staged_files[-1].closed)
            self.assertEqual(self.path.read_bytes(), b"existing")
            self.assertEqual(len(json.loads(Path(source).read_bytes())["records"]), 4)
            original_replace(source, destination)

        with patch("model.persistence.tempfile.NamedTemporaryFile", side_effect=factory), patch(
            "model.persistence.os.replace", side_effect=replace
        ):
            self.store.write(self.path, self.records, overwrite=True)
        self.assertEqual(len(self.store.read(self.path)), 4)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_cleanup_failure_does_not_hide_the_original_replace_error(self):
        """Cleanup is best-effort; retain the useful original operation failure."""
        self.path.write_bytes(b"existing")
        with patch(
            "model.persistence.os.replace", side_effect=OSError("Original replace error.")
        ), patch(
            "model.persistence.Path.unlink", side_effect=PermissionError("Cleanup denied.")
        ):
            with self.assertRaises(PersistenceError) as caught:
                self.store.write(self.path, self.records, overwrite=True)
        self.assertIn("Original replace error", caught.exception.reason)
        self.assertEqual(self.path.read_bytes(), b"existing")
        # TemporaryDirectory cleanup runs after the mock is removed.


class ServicePersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "current.pim"
        parser = ExpressionParser()
        self.service = PIMService(PIMFileStorage(), CriteriaRegistry(parser), parser)
        self.store = PIMFileStorage()

    def _create(self, text="note"):
        return self.service.create(RecordType.PLAIN_TEXT, {"text": text})

    def _snapshot(self):
        return (
            self.service.all_records(), self.service._high_water,
            self.service.dirty, self.service.list_criteria(),
        )

    def test_service_round_trip_preserves_all_types_and_criteria_stay_session_only(self):
        """FR22/FR26/FR31: save only records, and reload equal complete values."""
        self._create("中 😀")
        self.service.create(
            RecordType.TASK, {"description": "report", "deadline": "0001-01-01 00:00"}
        )
        self.service.create(
            RecordType.EVENT,
            {"description": "event", "start": "2026-11-20 20:00", "alarm": "2026-11-20 19:00"},
        )
        self.service.create(
            RecordType.CONTACT, {"name": "王", "address": "香港", "mobile": "+00123"}
        )
        item = self.service.define_criterion('text~"中"')
        original = self.service.all_records()
        self.assertIsNone(self.service.save(self.path))
        self.assertFalse(self.service.dirty)
        document = json.loads(self.path.read_bytes())
        self.assertEqual(set(document), {"format", "version", "records"})
        self.service.delete(1)
        self.assertTrue(self.service.dirty)
        self.assertIsNone(self.service.load(self.path))
        self.assertEqual(self.service.all_records(), original)
        self.assertFalse(self.service.dirty)
        self.assertEqual(self.service.list_criteria(), (item,))
        self.assertEqual(self.service.search_saved(item.id), (original[0],))

    def test_empty_save_and_load_replace_all_current_records(self):
        """FR22/FR24: successful empty load replaces, never merges or keeps old data."""
        self.service.save(self.path)
        self.assertFalse(self.service.dirty)
        created = self._create()
        item = self.service.define_criterion('text~"note"')
        self.service.load(self.path)
        self.assertEqual(self.service.all_records(), ())
        self.assertFalse(self.service.dirty)
        self.assertEqual(self.service._high_water, created.id)
        self.assertEqual(self.service.list_criteria(), (item,))
        self.assertEqual(self.service.search_saved(item.id), ())

    def test_load_replaces_ids_without_merging_or_reallocation(self):
        """FR24: exact file IDs replace the previous collection."""
        old = self._create("old")
        records = (PlainText(10, "ten"), PlainText(2, "two"))
        self.store.write(self.path, records)
        self.service.load(self.path)
        self.assertEqual(self.service.all_records(), (records[1], records[0]))
        self.assertNotIn(old.id, [record.id for record in self.service.all_records()])
        self.assertEqual(self._create("next").id, 11)

    def test_load_higher_lower_and_empty_ids_never_lowers_session_high_water(self):
        """FR2: high-water includes deleted/loaded IDs throughout the current session."""
        self._create("original")
        for records, expected_high, expected_next in (
            ((PlainText(50, "high"),), 50, 51),
            ((PlainText(2, "low"),), 51, 52),
            ((), 52, 53),
        ):
            self.store.write(self.path, records, overwrite=True)
            with self.subTest(records=records):
                self.service.load(self.path)
                self.assertEqual(self.service._high_water, expected_high)
                self.assertFalse(self.service.dirty)
                new = self._create(f"new {expected_next}")
                self.assertEqual(new.id, expected_next)
                self.service.delete(new.id)
                self.assertEqual(self.service._high_water, expected_next)

    def test_load_can_restore_deleted_saved_id_without_reusing_it_for_new_creation(self):
        """A restored saved identity is valid; the next creation still exceeds history."""
        original = self._create()
        self.service.save(self.path)
        self.service.delete(original.id)
        self.service.load(self.path)
        self.assertEqual(self.service.get(original.id), original)
        self.assertEqual(self._create("another").id, 2)

    def test_invalid_last_record_preserves_all_state_in_clean_and_dirty_cases(self):
        """FR25: validating an earlier record never commits a partial collection."""
        self._create("original")
        self.service.define_criterion('text~"original"')
        good = self.directory / "good.pim"
        bad = self.directory / "bad.pim"
        bad.write_text(json.dumps({
            "format": "PIM", "version": 1,
            "records": [
                {"id": 999, "type": "PLAIN_TEXT", "text": "valid first"},
                {"id": 1000, "type": "TASK", "description": "bad", "deadline": "invalid"},
            ],
        }), encoding="utf-8")
        for dirty in (False, True):
            self.service.save(good, overwrite=True)
            if dirty:
                self.service.update(1, "text", "changed")
            before = self._snapshot()
            with self.subTest(dirty=dirty), self.assertRaises(PersistenceError):
                self.service.load(bad)
            self.assertEqual(self._snapshot(), before)
        self.assertEqual(self._create("next").id, 2)

    def test_missing_or_unreadable_load_preserves_live_state(self):
        """Expected read errors leave records, ID history, criteria and dirty untouched."""
        self._create()
        self.service.define_criterion('text~"note"')
        before = self._snapshot()
        with self.assertRaises(PersistenceError):
            self.service.load(self.directory / "missing.pim")
        self.assertEqual(self._snapshot(), before)
        with patch(
            "model.persistence.Path.read_text", side_effect=PermissionError("Read denied.")
        ):
            with self.assertRaises(PersistenceError):
                self.service.load(self.path)
        self.assertEqual(self._snapshot(), before)

    def test_failed_save_preserves_dirty_and_all_other_state(self):
        """FR23: a denied replace leaves unsaved data and existing target bytes intact."""
        self._create()
        self.service.define_criterion('text~"note"')
        self.path.write_bytes(b"original target")
        before = self._snapshot()
        with patch("model.persistence.os.replace", side_effect=PermissionError("Replace denied.")):
            with self.assertRaises(PersistenceError):
                self.service.save(self.path, overwrite=True)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.path.read_bytes(), b"original target")
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_every_expected_save_failure_phase_preserves_service_state(self):
        """Encoding/temp creation/write/flush/close failures cannot clear dirty."""
        self._create()
        self.service.define_criterion('text~"note"')
        before = self._snapshot()
        original_factory = tempfile.NamedTemporaryFile
        for phase in ("encode", "create", "write", "short", "flush", "close"):
            if phase == "encode":
                failure = patch("model.persistence.json.dumps", side_effect=ValueError("Encode."))
            elif phase == "create":
                failure = patch(
                    "model.persistence.tempfile.NamedTemporaryFile",
                    side_effect=PermissionError("Create denied."),
                )
            else:
                failure = patch(
                    "model.persistence.tempfile.NamedTemporaryFile",
                    side_effect=lambda **kwargs: _FaultyTemporary(
                        original_factory(**kwargs), phase
                    ),
                )
            with self.subTest(phase=phase), failure:
                with self.assertRaises(PersistenceError):
                    self.service.save(self.path)
            self.assertEqual(self._snapshot(), before)
            self.assertFalse(self.path.exists())
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_failed_save_of_clean_collection_does_not_introduce_dirty(self):
        """FR34: failure preserves False as well as True."""
        before = self._snapshot()
        with self.assertRaises(PersistenceError):
            self.service.save(self.directory / "missing" / "records.pim")
        self.assertEqual(self._snapshot(), before)
        self.assertFalse(self.service.dirty)

    def test_declined_overwrite_preserves_target_and_dirty_until_confirmed_retry(self):
        """FR33: OverwriteRequiredError is not a successful save or an implicit retry."""
        self._create("original")
        self.service.save(self.path)
        original_bytes = self.path.read_bytes()
        self.service.update(1, "text", "changed")
        before = self._snapshot()
        with self.assertRaises(OverwriteRequiredError):
            self.service.save(self.path)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.service.save(self.path, overwrite=True)
        self.assertFalse(self.service.dirty)
        self.assertEqual(self.store.read(self.path)[0].text, "changed")

    def test_successful_save_changes_only_dirty(self):
        """FR22/FR34: saving never changes records, allocation or saved definitions."""
        record = self._create()
        item = self.service.define_criterion('text~"note"')
        before = self._snapshot()
        self.service.save(self.path)
        after = self._snapshot()
        self.assertEqual(after[0], before[0])
        self.assertIs(self.service.get(record.id), record)
        self.assertEqual(after[1], before[1])
        self.assertEqual(after[3], (item,))
        self.assertFalse(after[2])

    def test_save_then_failed_load_keeps_saved_collection_clean(self):
        """FR25/FR36 model boundary: successful save is not rolled back by later bad load."""
        self._create()
        self.service.save(self.path)
        before = self._snapshot()
        bad = self.directory / "bad.pim"
        bad.write_bytes(b"bad file")
        with self.assertRaises(PersistenceError):
            self.service.load(bad)
        self.assertEqual(self._snapshot(), before)
        self.assertFalse(self.service.dirty)

    def test_saved_criteria_survive_load_and_reevaluate_loaded_values(self):
        """FR31: registry/root identity survives while results reflect replacement records."""
        self._create("old report")
        item = self.service.define_criterion('text~"report"')
        self.assertEqual([r.id for r in self.service.search_saved(item.id)], [1])
        self.store.write(self.path, (PlainText(8, "exam"), PlainText(12, "new report")))
        self.service.load(self.path)
        self.assertIs(self.service.list_criteria()[0], item)
        self.assertEqual([r.id for r in self.service.search_saved(item.id)], [12])
        self.assertEqual(self.service.define_criterion("type=TASK").id, "C2")

    def test_duplicate_contents_load_without_creation_confirmation(self):
        """FR26/FR32: loading equal business values under separate IDs retains both."""
        self.store.write(self.path, (PlainText(2, "same"), PlainText(7, "same")))
        self.service.load(self.path)
        self.assertEqual([record.id for record in self.service.all_records()], [2, 7])
        self.assertFalse(self.service.dirty)

    def test_new_session_reconstructs_counter_only_from_loaded_ids(self):
        """D 9.2: a prior session's deleted high-water counter is not persisted."""
        for number in range(3):
            self._create(f"record {number}")
        self.service.delete(3)
        self.service.save(self.path)
        parser = ExpressionParser()
        fresh = PIMService(PIMFileStorage(), CriteriaRegistry(parser), parser)
        fresh.load(self.path)
        self.assertEqual(fresh.create(RecordType.PLAIN_TEXT, {"text": "new"}).id, 3)
        self.assertEqual(self._create("same session new").id, 4)

    def test_real_save_load_do_not_use_terminal_io(self):
        """NFR3: actual temporary-directory file operations need neither input nor print."""
        with patch("builtins.input", side_effect=AssertionError("Unexpected input")), patch(
            "builtins.print", side_effect=AssertionError("Unexpected output")
        ):
            original = self._create("中")
            self.service.save(self.path)
            self.service.update(original.id, "text", "changed")
            self.service.load(self.path)
            self.assertEqual(self.service.get(original.id), original)
            self.assertFalse(self.service.dirty)


if __name__ == "__main__":
    unittest.main()
