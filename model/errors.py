"""Model exceptions from Design section 8.1; presentation belongs to the CLI."""


class PIMError(Exception):
    """Base domain error carrying a reason without terminal formatting."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ValidationError(PIMError):
    """A record ID, field or complete record is invalid."""


class NotFoundError(PIMError):
    """A valid record ID is absent from the current collection."""


class ExpressionError(PIMError):
    """A search expression or criterion is invalid."""


class UnknownCriterionError(PIMError):
    """A requested session criterion does not exist."""


class PersistenceError(PIMError):
    """A file operation or persisted collection is invalid."""


class OverwriteRequiredError(PersistenceError):
    """Saving requires the caller to obtain overwrite confirmation."""


class DuplicateRecordError(PIMError):
    """Creation requires confirmation of identical business content."""

    def __init__(self, reason: str, matching_ids: tuple[int, ...]) -> None:
        super().__init__(reason)
        self.matching_ids = tuple(matching_ids)
