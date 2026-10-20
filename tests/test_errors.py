"""Design 8.1: domain errors expose reasons and support the documented catches."""

import unittest

from model.errors import (
    DuplicateRecordError,
    ExpressionError,
    NotFoundError,
    OverwriteRequiredError,
    PersistenceError,
    PIMError,
    UnknownCriterionError,
    ValidationError,
)


class ErrorTests(unittest.TestCase):
    def test_reason_and_exception_message(self):
        """All ordinary model errors retain the supplied actionable reason."""
        for error_type in (
            PIMError, ValidationError, NotFoundError, ExpressionError,
            UnknownCriterionError, PersistenceError, OverwriteRequiredError,
        ):
            with self.subTest(error=error_type.__name__):
                error = error_type("Invalid field: description.")
                self.assertEqual(error.reason, "Invalid field: description.")
                self.assertEqual(str(error), error.reason)
                self.assertEqual(error.args, (error.reason,))

    def test_domain_errors_can_be_caught_as_pim_errors(self):
        """The later controller can catch every expected model error once."""
        errors = (
            ValidationError("invalid"), NotFoundError("missing"),
            ExpressionError("expression"), UnknownCriterionError("criterion"),
            PersistenceError("file"), OverwriteRequiredError("overwrite"),
            DuplicateRecordError("duplicate", (2, 7)),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(PIMError):
                    raise error

    def test_overwrite_is_a_persistence_error(self):
        """Overwrite consent is distinguishable while remaining a file error."""
        with self.assertRaises(PersistenceError):
            raise OverwriteRequiredError("Destination exists.")
        self.assertNotIsInstance(DuplicateRecordError("Duplicate.", (1,)), PersistenceError)

    def test_duplicate_retains_reason_and_matching_ids(self):
        """FR32 support: callers can identify all duplicate IDs without parsing text."""
        error = DuplicateRecordError("Matching records exist.", (2, 7))
        self.assertEqual(error.reason, "Matching records exist.")
        self.assertEqual(str(error), error.reason)
        self.assertEqual(error.matching_ids, (2, 7))
        self.assertIsInstance(error.matching_ids, tuple)


if __name__ == "__main__":
    unittest.main()
