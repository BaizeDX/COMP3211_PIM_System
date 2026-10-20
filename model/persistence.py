"""Strict versioned .pim JSON and staged file replacement (Design section 9)."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from model.errors import OverwriteRequiredError, PersistenceError, ValidationError
from model.records import PIR, RecordType
from model.validation import build_record


def _validate_path(path: Path) -> None:
    if not isinstance(path, Path):
        raise ValidationError("Expected a pathlib.Path ending in lowercase .pim.")
    if path.suffix != ".pim" or "\0" in str(path):
        raise ValidationError(
            "File path must have the lowercase .pim extension and no null bytes."
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON object key {key!r}.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValidationError(f"Non-standard JSON constant {value!r} is not supported.")


def _record_data(record: PIR) -> dict[str, object]:
    data = {"id": record.id, "type": record.type.value}
    for name, value in record.business_fields().items():
        if isinstance(value, datetime):
            # strftime's year padding varies by platform for years below 1000.
            value = (
                f"{value.year:04d}-{value.month:02d}-{value.day:02d} "
                f"{value.hour:02d}:{value.minute:02d}"
            )
        data[name] = value
    return data


def _validated_records(document: object) -> tuple[PIR, ...]:
    if not isinstance(document, dict) or set(document) != {"format", "version", "records"}:
        raise ValidationError("Root object must contain exactly format, version and records.")
    if document["format"] != "PIM":
        raise ValidationError("Unsupported file format; expected PIM.")
    if type(document["version"]) is not int or document["version"] != 1:
        raise ValidationError("Unsupported version; expected integer 1.")
    if not isinstance(document["records"], list):
        raise ValidationError("records must be a JSON array.")

    records = []
    seen_ids = set()
    for entry in document["records"]:
        if not isinstance(entry, dict) or "id" not in entry or "type" not in entry:
            raise ValidationError("Every record must be an object containing id and type.")
        if not isinstance(entry["type"], str):
            raise ValidationError("Record type must be text.")
        try:
            kind = RecordType(entry["type"])
        except ValueError as error:
            raise ValidationError(f"Unknown record type {entry['type']!r}.") from error
        fields = {key: value for key, value in entry.items() if key not in ("id", "type")}
        # Escaped lone surrogate code points are not representable in UTF-8.
        for value in fields.values():
            if isinstance(value, str):
                value.encode("utf-8")
        record = build_record(entry["id"], kind, fields)
        if _record_data(record) != entry:
            raise ValidationError(f"Record {record.id} contains non-canonical field values.")
        if record.id in seen_ids:
            raise ValidationError(f"Duplicate record ID {record.id}.")
        seen_ids.add(record.id)
        records.append(record)
    return tuple(sorted(records, key=lambda record: record.id))


class PIMFileStorage:
    """Stateless file adapter; expected input/file failures raise PersistenceError.

    No prompts or model collection mutation occur here. OverwriteRequiredError
    signals that the caller must obtain consent before retrying write.
    """

    def read(self, path: Path) -> tuple[PIR, ...]:
        """Decode and validate the entire UTF-8 file before returning any records."""
        try:
            _validate_path(path)
            document = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
            return _validated_records(document)
        except (OSError, UnicodeError, ValueError, ValidationError, RecursionError) as error:
            raise PersistenceError(f"Cannot load {str(path)!r}: {error}") from error

    def write(
        self, path: Path, records: tuple[PIR, ...], overwrite: bool = False
    ) -> None:
        """Encode fully, write/flush/close a same-directory temporary file, then replace.

        Existing destinations require overwrite=True. Failure leaves the target
        unchanged before replacement and attempts to remove the temporary file.
        Concurrent external writes and power-loss recovery are outside this contract.
        """
        temporary_path = None
        try:
            _validate_path(path)
            if type(overwrite) is not bool:
                raise ValidationError("overwrite must be a Boolean value.")
            if not isinstance(records, tuple) or any(
                not isinstance(item, PIR) for item in records
            ):
                raise ValidationError("Expected a tuple of valid PIR records.")
            document = {
                "format": "PIM",
                "version": 1,
                "records": [_record_data(record) for record in records],
            }
            # Validate the supplied snapshot as well; emit fixed key and numeric ID order.
            document["records"] = [_record_data(record) for record in _validated_records(document)]
            payload = (
                json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            ).encode("utf-8")
            if path.is_dir():
                raise ValidationError("Destination is a directory, not a .pim file.")
            if not overwrite and (path.exists() or path.is_symlink()):
                raise OverwriteRequiredError(
                    f"File {str(path)!r} already exists; confirm overwrite before retrying."
                )

            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                if temporary.write(payload) != len(payload):
                    raise OSError("Incomplete write to the temporary file.")
                temporary.flush()
            os.replace(temporary_path, path)
            temporary_path = None
        except (OSError, UnicodeError, ValueError, ValidationError, RecursionError) as error:
            raise PersistenceError(f"Cannot save {str(path)!r}: {error}") from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    # Cleanup is best-effort; preserve the original operation's error.
                    pass
