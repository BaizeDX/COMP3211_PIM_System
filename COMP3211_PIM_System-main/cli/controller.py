"""Serial command coordination and confirmation policies (Design sections 7-8/11)."""

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from cli.errors import CommandError
from cli.parser import Command, CommandParser
from cli.view import PIMView
from model.errors import (
    DuplicateRecordError,
    ExpressionError,
    NotFoundError,
    OverwriteRequiredError,
    PersistenceError,
    PIMError,
    UnknownCriterionError,
)
from model.service import PIMService


_T = TypeVar("_T")


class _InputInterrupted(Exception):
    """A recoverable interruption raised only by a terminal input boundary."""


class PIMController:
    """Coordinate the service without directly changing domain/session state."""

    def __init__(self, service: PIMService, parser: CommandParser, view: PIMView) -> None:
        self._service = service
        self._parser = parser
        self._view = view
        self._running = True

    def _read(self, reader: Callable[..., _T], *args: object) -> _T:
        # Never wrap service calls/commits in this catch-and-recover boundary.
        try:
            return reader(*args)
        except KeyboardInterrupt:
            raise _InputInterrupted from None
        except EOFError:
            self._running = False
            if self._service.dirty:
                self._view.report_closed_input_with_unsaved_changes()
                raise SystemExit(1) from None
            raise SystemExit(0) from None

    def run(self) -> None:
        while self._running:
            try:
                line = self._read(self._view.read_line)
                if not self.execute(self._parser.parse(line)):
                    break
            except _InputInterrupted:
                self._view.error(
                    "Input interrupted; pending action cancelled. Use exit to leave the session."
                )
            except (CommandError, PIMError) as error:
                reason = error.reason
                if isinstance(error, NotFoundError):
                    reason += " Use show all to list current record IDs."
                elif isinstance(error, UnknownCriterionError):
                    reason += " Use criteria to list saved definitions."
                elif isinstance(error, ExpressionError):
                    reason += (
                        ' Expected type = TASK, text ~ "word", or deadline < "YYYY-MM-DD HH:MM";'
                        " combine conditions with !, &&, || and parentheses."
                    )
                elif isinstance(error, OverwriteRequiredError):
                    # Confirmation belongs in _save; do not append generic path advice.
                    pass
                elif isinstance(error, PersistenceError):
                    reason += (
                        " Use a lowercase .pim path and a readable file for load "
                        "or a writable destination directory for save."
                    )
                self._view.error(reason)

    def _save(self, path: Path) -> bool:
        try:
            self._service.save(path)
        except OverwriteRequiredError:
            if not self._read(self._view.confirm, f"Overwrite {str(path)!r}?"):
                self._view.message("Save cancelled; existing file retained.")
                return False
            self._service.save(path, overwrite=True)
        self._view.message(f"Saved collection to {path}.")
        return True

    def _allow_unsaved(self) -> bool:
        if not self._service.dirty:
            return True
        choice = self._read(self._view.choose_unsaved)
        if choice == "c":
            self._view.message("Action cancelled.")
            return False
        if choice == "s":
            return self._save(self._read(self._view.read_path))
        # Discard permits the action; it does not pre-clear model records/dirty.
        return True

    def execute(self, command: Command) -> bool:
        """Dispatch a well-formed command; return False after an approved exit."""
        args = command.arguments
        verb = command.verb
        if verb == "create":
            try:
                record = self._service.create(args["kind"], dict(args["fields"]))
            except DuplicateRecordError as error:
                ids = ", ".join(map(str, error.matching_ids))
                self._view.message(f"Duplicate records: {ids}.")
                if not self._read(self._view.confirm, "Create another record with this content?"):
                    self._view.message("Creation cancelled.")
                    return True
                record = self._service.create(
                    args["kind"], dict(args["fields"]), allow_duplicate=True
                )
            self._view.message("Created record.")
            self._view.show_records((record,))
        elif verb == "update":
            record = self._service.update(args["record_id"], args["field"], args["value"])
            self._view.message("Record after update:")
            self._view.show_records((record,))
        elif verb == "show":
            records = (
                (self._service.get(args["record_id"]),)
                if "record_id" in args else self._service.all_records()
            )
            if records:
                self._view.show_records(records)
            else:
                self._view.message("Collection is empty")
        elif verb == "delete":
            record = self._service.get(args["record_id"])
            self._view.show_records((record,))
            if self._read(self._view.confirm, f"Delete record {record.id}?"):
                self._service.delete(record.id)
                self._view.message(f"Deleted record {record.id}.")
            else:
                self._view.message("Deletion cancelled.")
        elif verb == "define":
            self._view.show_criteria((self._service.define_criterion(args["expression"]),))
        elif verb == "criteria":
            self._view.show_criteria(self._service.list_criteria())
        elif verb == "search":
            records = (
                self._service.search_saved(args["criterion_id"])
                if "criterion_id" in args else self._service.search(args["expression"])
            )
            if records:
                self._view.show_records(records)
            else:
                self._view.message("Zero matches")
        elif verb == "save":
            self._save(args["path"])
        elif verb == "load":
            if self._allow_unsaved():
                self._service.load(args["path"])
                self._view.message(f"Loaded collection from {args['path']}.")
        elif verb == "exit":
            if self._allow_unsaved():
                self._running = False
                self._view.message("Session ended.")
        else:
            raise CommandError("Unknown command carrier. Expected a CommandParser result.")
        return self._running
