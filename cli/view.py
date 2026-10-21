"""Terminal input/output and complete record formatting (Design section 8)."""

import io
import re
import sys
from datetime import datetime
from pathlib import Path

from cli.errors import CommandError
from cli.literals import _parse_path
from model.records import PIR
from model.search import SavedCriterion


def _configure_stdio() -> None:
    """Use UTF-8 before the first input read, without replacing embedded streams.

    Windows console streams already support Unicode, but redirected streams
    can otherwise inherit an ANSI code page. Retain native newlines/error policies.
    A debugger may already have read stdin; never replace its buffered stream.
    Such hosts must select UTF-8 before reading (for example, -X utf8 with pdb).
    """
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, name)
        if isinstance(stream, io.TextIOWrapper) and (
            stream.encoding.lower().replace("-", "").replace("_", "") != "utf8"
        ):
            try:
                stream.reconfigure(encoding="utf-8", errors=stream.errors)
            except io.UnsupportedOperation:
                if name != "stdin":
                    raise
                # Reconfiguring consumed input is forbidden. Keep decoder/buffer
                # ownership with the debugger rather than losing pending input.


class PIMView:
    """Stateless terminal adapter; input interruptions propagate to the controller."""

    def read_line(self, prompt: str = "pim> ") -> str:
        # input() removes LF; a redirected CRLF stream can retain its final CR.
        # Remove only that transport suffix, never whitespace within literals.
        return input(prompt).removesuffix("\r")

    def confirm(self, message: str) -> bool:
        while True:
            choice = self.read_line(f"{message} [y/n] ").strip()
            if choice in ("y", "n"):
                return choice == "y"
            self.error("Invalid confirmation. Expected y or n.")

    def choose_unsaved(self) -> str:
        while True:
            choice = self.read_line(
                "Unsaved changes: save and continue, discard and continue, or cancel? [s/d/c] "
            ).strip()
            if choice in ("s", "d", "c"):
                return choice
            self.error("Invalid choice. Expected s (save), d (discard), or c (cancel).")

    def read_path(self) -> Path:
        while True:
            try:
                return _parse_path(self.read_line('Save path (double-quoted): '))
            except CommandError as error:
                self.error(error.reason)

    def show_records(self, records: tuple[PIR, ...]) -> None:
        for index, record in enumerate(sorted(records, key=lambda item: item.id)):
            if index:
                self.message("")
            self.message(f"ID: {record.id}")
            self.message(f"Type: {record.type.value}")
            for name, value in record.business_fields().items():
                if isinstance(value, datetime):
                    value = (
                        f"{value.year:04d}-{value.month:02d}-{value.day:02d} "
                        f"{value.hour:02d}:{value.minute:02d}"
                    )
                self.message(f"{name}: {value}")

    def show_criteria(self, items: tuple[SavedCriterion, ...]) -> None:
        if not items:
            self.message("No criteria defined")
        for item in sorted(items, key=lambda value: int(value.id[1:])):
            self.message(f"{item.id}: {item.expression}")

    def message(self, text: str) -> None:
        print(text)

    def error(self, reason: str) -> None:
        reason = re.sub(r"^(?:ERROR\b\s*:?\s*)+", "", reason)
        self.message(f"ERROR {reason}")

    def _closed_input(self) -> None:
        """Exceptional dirty-EOF diagnostic from the user-approved clarification."""
        print(
            "ERROR Standard input is closed; terminating the session with unsaved changes.",
            file=sys.stderr,
        )
