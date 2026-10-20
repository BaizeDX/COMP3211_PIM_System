"""Collection and persistence operations (SRS 5.1; Design sections 4-5 and 9).

The service is the collection's mutation boundary. Validation and duplicate
checks finish before a candidate is committed. Confirmations belong to the
caller, never the model. File validation/replacement is delegated to storage.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from model.criteria import SearchCriterion
from model.errors import DuplicateRecordError, NotFoundError, ValidationError
from model.persistence import PIMFileStorage
from model.records import PIR, RecordType
from model.search import CriteriaRegistry, ExpressionParser, SavedCriterion
from model.validation import MAX_RECORD_ID, _validate_record_id, build_record, parse_time


class PIMService:
    """Own one record collection, session ID history, dirty state and criteria.

    Supply the same ExpressionParser to this service and its CriteriaRegistry.
    The injected store is accessed only for explicit save/load operations.
    Construction always starts with no records and dirty False, without file access.
    """

    def __init__(
        self, store: PIMFileStorage, criteria: CriteriaRegistry, parser: ExpressionParser
    ) -> None:
        self._store = store
        self._criteria = criteria
        self._parser = parser
        self._records: dict[int, PIR] = {}
        self._high_water = 0
        self._dirty = False

    @property
    def dirty(self) -> bool:
        """Whether record changes are unsaved; callers cannot set this property."""
        return self._dirty

    def create(
        self, kind: RecordType, fields: dict[str, str], allow_duplicate: bool = False
    ) -> PIR:
        """Validate, then insert a new ID; raise ValidationError/DuplicateRecordError.

        A duplicate error carries numerically sorted matching IDs and changes no
        state. Only a caller-confirmed retry should set allow_duplicate=True.
        """
        if type(allow_duplicate) is not bool:
            raise ValidationError("allow_duplicate must be a Boolean value.")
        if self._high_water >= MAX_RECORD_ID:
            raise ValidationError(
                f"Record ID range is exhausted at {MAX_RECORD_ID}. "
                "Cannot create another record; existing records remain usable."
            )
        candidate = build_record(self._high_water + 1, kind, fields)
        if not allow_duplicate:
            key = candidate.duplicate_key()
            matching_ids = tuple(sorted(
                record.id for record in self._records.values() if record.duplicate_key() == key
            ))
            if matching_ids:
                raise DuplicateRecordError(
                    "Records with identical normalized business fields already exist.",
                    matching_ids,
                )

        self._records[candidate.id] = candidate
        self._high_water = candidate.id
        self._dirty = True
        return candidate

    def get(self, record_id: int) -> PIR:
        """Return an immutable PIR; raise ValidationError or NotFoundError for bad IDs."""
        _validate_record_id(record_id)
        try:
            return self._records[record_id]
        except KeyError:
            raise NotFoundError(f"Record {record_id} does not exist.") from None

    def all_records(self) -> tuple[PIR, ...]:
        """Return a detached immutable snapshot ordered by numeric record ID."""
        return tuple(self._records[record_id] for record_id in sorted(self._records))

    def update(self, record_id: int, field: str, value: str) -> PIR:
        """Validate one field's complete replacement before committing any change.

        ID/type cannot be edited. A normalized no-op returns the original PIR
        without changing dirty. Raises NotFoundError or ValidationError.
        """
        original = self.get(record_id)
        fields = original.business_fields()
        if not isinstance(field, str) or field not in fields:
            raise ValidationError(
                f"Field {field!r} is not editable for {original.type.value}. "
                f"Expected one of: {', '.join(fields)}."
            )
        replacement_value: str | datetime = value
        if isinstance(fields[field], datetime):
            try:
                replacement_value = parse_time(value)
            except ValidationError as error:
                raise ValidationError(f"Invalid {field}. {error.reason}") from error

        # replace calls the concrete constructor, revalidating every field and
        # the Event alarm/start relationship while retaining the original ID/type.
        candidate = replace(original, **{field: replacement_value})
        if candidate == original:
            return original
        self._records[record_id] = candidate
        self._dirty = True
        return candidate

    def delete(self, record_id: int) -> PIR:
        """Remove/return one PIR after caller confirmation; retain the high-water mark.

        Raises ValidationError or NotFoundError without changing state.
        """
        record = self.get(record_id)
        del self._records[record_id]
        self._dirty = True
        return record

    def _matching_records(self, criterion: SearchCriterion) -> tuple[PIR, ...]:
        return tuple(record for record in self.all_records() if criterion.matches(record))

    def search(self, expression: str) -> tuple[PIR, ...]:
        """Parse completely, then return current matches in ID order without mutation.

        Raises ExpressionError, even for invalid expressions over an empty collection.
        """
        criterion = self._parser.parse(expression)
        return self._matching_records(criterion)

    def search_saved(self, criterion_id: str) -> tuple[PIR, ...]:
        """Reevaluate an existing root against current records; never cache results.

        Raises UnknownCriterionError for an unknown or malformed criterion ID.
        """
        criterion = self._criteria.get(criterion_id)
        return self._matching_records(criterion.root)

    def define_criterion(self, expression: str) -> SavedCriterion:
        """Define a session criterion without changing record state; raises ExpressionError."""
        return self._criteria.define(expression)

    def list_criteria(self) -> tuple[SavedCriterion, ...]:
        """List immutable session definitions in numeric C-ID order without mutation."""
        return self._criteria.all()

    def save(self, path: Path, overwrite: bool = False) -> None:
        """Write the sorted snapshot; clear dirty only after storage confirms success.

        PersistenceError/OverwriteRequiredError leave all service state unchanged.
        The caller, never the model, obtains any required overwrite consent.
        """
        self._store.write(path, self.all_records(), overwrite=overwrite)
        self._dirty = False

    def load(self, path: Path) -> None:
        """Replace records after full storage validation; retain criteria and ID history.

        The caller resolves unsaved changes first. PersistenceError leaves records,
        high-water and dirty unchanged, including after an earlier successful save.
        """
        records = self._store.read(path)
        replacement = {record.id: record for record in records}
        high_water = max(self._high_water, max(replacement, default=0))
        self._records = replacement
        self._high_water = high_water
        self._dirty = False
