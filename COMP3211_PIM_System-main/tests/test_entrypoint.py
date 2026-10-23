"""Actual main.py subprocess checks: representative commands, guards and bounded EOF exit."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from model.persistence import PIMFileStorage
from model.records import PlainText, Task
from model.validation import MAX_RECORD_ID


_MAIN = Path(__file__).resolve().parents[1] / "main.py"


def _quoted(value):
    """Test command literals: JSON quoting overlaps for these quote/backslash-only paths."""
    return json.dumps(str(value), ensure_ascii=False)


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "中 文 records.pim"

    def _run(self, lines, block_network=False):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        command = [sys.executable, str(_MAIN)]
        if block_network:
            bootstrap = (
                "import runpy, sys\nfrom unittest.mock import patch\n"
                f"sys.path.insert(0, {str(_MAIN.parent)!r})\n"
                "with patch('socket.socket', side_effect=AssertionError('Network access')):\n"
                f"    runpy.run_path({str(_MAIN)!r}, run_name='__main__')\n"
            )
            command = [sys.executable, "-c", bootstrap]
        return subprocess.run(
            command, cwd=self.directory,
            input="\n".join(lines) + ("\n" if lines else ""), text=True, encoding="utf-8",
            capture_output=True, timeout=15, env=environment,
        )

    def test_representative_script_uses_all_commands_and_all_record_types(self):
        """Real CLI: CRUD/search/criteria/save/load, quotes/Unicode and both empty outcomes."""
        result = self._run([
            "show all", "criteria",
            r'create PLAIN_TEXT text="中文 a\\b\"c _"',
            'create TASK description="COMP3211 report" deadline="2026-11-20 20:00"',
            'create EVENT description="Meeting" start="2026-11-21 12:00" '
            'alarm="2026-11-21 11:00"',
            'create CONTACT name="王" address="香港" mobile="+00123"',
            'define type=TASK && deadline < "2026-11-22 00:00"',
            "criteria", "search @C1", r'search text~"a\\b\"c"',
            'update 2 deadline="2026-11-25 23:59"', "search @C1", "show all",
            f"save {_quoted(self.path)}",
            r'create PLAIN_TEXT text="中文 a\\b\"c _"', "n",
            r'create PLAIN_TEXT text="中文 a\\b\"c _"', "y",
            "delete 5", "y", f"load {_quoted(self.path)}", "d", "search @C1", "exit",
        ])
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("ERROR ", result.stdout)
        for expected in ("Collection is empty", "No criteria defined", "Zero matches",
                         "Duplicate records: 1.", "Deleted record 5.", "Session ended.",
                         "Type: PLAIN_TEXT", "Type: TASK", "Type: EVENT", "Type: CONTACT",
                         'text: 中文 a\\b"c _', "mobile: +00123", "address: 香港",
                         "alarm: 2026-11-21 11:00", "deadline: 2026-11-25 23:59"):
            self.assertIn(expected, result.stdout)
        saved = PIMFileStorage().read(self.path)
        self.assertEqual([record.id for record in saved], [1, 2, 3, 4])
        self.assertEqual(saved[0].text, '中文 a\\b"c _')
        self.assertEqual(saved[3].mobile, "+00123")
        self.assertEqual(set(json.loads(self.path.read_bytes())), {"format", "version", "records"})

    def test_startup_never_loads_existing_sample_or_previous_files(self):
        """FR1: working-directory record files have no startup side effects."""
        PIMFileStorage().write(self.directory / "records.pim", (PlainText(90, "previous"),))
        result = self._run(["show all", "criteria", "exit"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertIn("Collection is empty", result.stdout)
        self.assertIn("No criteria defined", result.stdout)
        self.assertNotIn("ID: 90", result.stdout)

    def test_boundary_id_show_search_update_save_load_and_exhaustion_remain_usable(self):
        """Real CLI supports MAX; rejected create stays clean, with later commands usable."""
        PIMFileStorage().write(self.path, (PlainText(MAX_RECORD_ID - 1, "previous"),))
        output_path = self.directory / "boundary result.pim"
        result = self._run([
            f"load {_quoted(self.path)}", 'create PLAIN_TEXT text="last"',
            f"show {MAX_RECORD_ID}", 'define text~"last"', "search @C1",
            f'update {MAX_RECORD_ID} text="last changed"', f"save {_quoted(output_path)}",
            'create PLAIN_TEXT text="must fail"', f"show {MAX_RECORD_ID}",
            f"load {_quoted(output_path)}", "search @C1", f"delete {MAX_RECORD_ID}", "y",
            f"save {_quoted(output_path)}", "n", f"save {_quoted(output_path)}", "y", "exit",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.count("ERROR "), 1)
        self.assertIn("exhausted", result.stdout)
        self.assertIn(f"ID: {MAX_RECORD_ID}", result.stdout)
        self.assertIn("text: last changed", result.stdout)
        self.assertNotIn("Unsaved changes:", result.stdout)
        self.assertEqual(PIMFileStorage().read(output_path),
                         (PlainText(MAX_RECORD_ID - 1, "previous"),))

    def test_huge_cli_ids_and_original_giant_file_recover_without_tracebacks(self):
        """Reject huge command IDs and the original file; later valid show/create succeeds."""
        oversized = self.directory / "original huge.pim"
        oversized.write_text(
            '{"format":"PIM","version":1,"records":[{"id":' + "9" * 4300 +
            ',"type":"PLAIN_TEXT","text":"old"}]}', encoding="utf-8",
        )
        result = self._run([
            f"load {_quoted(oversized)}", 'create PLAIN_TEXT text="safe"',
            "show " + "9" * 4300, 'update ' + "9" * 5000 + ' text="bad"',
            "delete " + str(MAX_RECORD_ID + 1), "show 1", "exit", "d",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.count("ERROR "), 4)
        self.assertNotIn("Traceback", result.stdout)
        self.assertIn("ID: 1\nType: PLAIN_TEXT\ntext: safe", result.stdout)

    def test_invalid_input_recovers_without_traceback(self):
        """FR28/NFR2: representative command/field/search/file failures remain usable."""
        result = self._run([
            "edit 1", 'create TASK description="bad" deadline="invalid"',
            'search type=TASK OR type=EVENT', 'load "missing.pim"',
            'create PLAIN_TEXT text="valid"', 'update 1 id="2"', "show 1", "exit", "d",
        ])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.count("ERROR "), 5)
        self.assertNotIn("Traceback", result.stdout)
        self.assertIn("text: valid", result.stdout)
        self.assertIn("Expected", result.stdout)
        self.assertNotIn("Saved collection", result.stdout)

    def test_save_guard_failure_blocks_load_then_user_can_retry(self):
        """FR36: save-path failure stops the pending load and supports later explicit saving."""
        incoming = self.directory / "incoming.pim"
        PIMFileStorage().write(incoming, (PlainText(8, "incoming"),))
        result = self._run([
            'create PLAIN_TEXT text="original"', f"load {_quoted(incoming)}", "s",
            '"missing/destination.pim"', "show all", f"save {_quoted(self.path)}", "exit",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ERROR Cannot save", result.stdout)
        self.assertNotIn("Loaded collection", result.stdout)
        self.assertNotIn("ID: 8", result.stdout)
        self.assertEqual(PIMFileStorage().read(self.path), (PlainText(1, "original"),))

    def test_failed_load_after_discard_keeps_dirty_until_user_chooses_discard_again(self):
        """FR36: actual main loop retains original data after discard plus invalid file."""
        self.path.write_bytes(b"invalid collection")
        result = self._run([
            'create PLAIN_TEXT text="original"', f"load {_quoted(self.path)}", "d",
            "show all", "exit", "c", "show all", "exit", "d",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ERROR Cannot load", result.stdout)
        self.assertEqual(result.stdout.count("text: original"), 3)
        self.assertEqual(result.stdout.count("Unsaved changes:"), 3)
        self.assertEqual(self.path.read_bytes(), b"invalid collection")

    def test_dirty_eof_at_command_and_all_confirmation_boundaries_is_nonzero(self):
        """Q6: subprocess timeout proves no prompt loop, no overwrite or implicit save."""
        prefixes = (
            [],
            ['create PLAIN_TEXT text="original"'],
            ["delete 1"],
            [f"save {_quoted(self.path)}"],
            ["exit"],
            ["exit", "s"],
            ["exit", "s", _quoted(self.path)],
            ['load "missing.pim"'],
        )
        for prefix in prefixes:
            self.path.write_bytes(b"existing file")
            with self.subTest(prefix=prefix):
                result = self._run(['create PLAIN_TEXT text="original"'] + prefix)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr,
                                 "ERROR Standard input is closed; terminating the session "
                                 "with unsaved changes.\n")
                self.assertNotIn("Saved collection", result.stdout)
                self.assertNotIn("Session ended.", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertLessEqual(result.stdout.count("pim> "), len(prefix) + 2)
                self.assertEqual(self.path.read_bytes(), b"existing file")

    def test_clean_eof_status_and_eof_after_successful_save(self):
        """Q6: clean EOF status is zero with no fabricated save; completed save stays true."""
        result = self._run([])
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertNotIn("Saved collection", result.stdout)
        result = self._run([
            'create PLAIN_TEXT text="saved"', f"save {_quoted(self.path)}",
        ])
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.count("Saved collection"), 1)
        self.assertEqual(PIMFileStorage().read(self.path), (PlainText(1, "saved"),))

    def test_declined_exit_overwrite_then_eof_is_not_a_successful_save(self):
        """FR33/Q6: n stops pending exit; later permanent EOF reports unsaved data."""
        self.path.write_bytes(b"existing")
        result = self._run([
            'create PLAIN_TEXT text="unsaved"', "exit", "s", _quoted(self.path), "n",
        ])
        self.assertEqual(result.returncode, 1)
        self.assertIn("unsaved changes", result.stderr)
        self.assertIn("Save cancelled", result.stdout)
        self.assertNotIn("Saved collection", result.stdout)
        self.assertNotIn("Session ended.", result.stdout)
        self.assertEqual(self.path.read_bytes(), b"existing")

    def test_failed_load_after_preliminary_save_then_eof_is_clean(self):
        """FR36/Q6: actual process status reflects the independently completed save."""
        incoming = self.directory / "bad.pim"
        incoming.write_bytes(b"bad")
        result = self._run([
            'create PLAIN_TEXT text="saved"', f"load {_quoted(incoming)}", "s",
            _quoted(self.path),
        ])
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn("ERROR Cannot load", result.stdout)
        self.assertEqual(result.stdout.count("Saved collection"), 1)
        self.assertEqual(PIMFileStorage().read(self.path), (PlainText(1, "saved"),))

    def test_exact_design_figure5_search_update_and_next_search(self):
        """D 10/Figure 5: CLI direct/saved results [2,7] become [7], preserving Task 7."""
        task2 = Task(2, "COMP3211 report", datetime(2026, 11, 20, 20))
        task7 = Task(7, "COMP3211 tests", datetime(2026, 11, 21, 18))
        PIMFileStorage().write(self.path, (task7, task2))
        changed = self.directory / "updated.pim"
        expression = (
            'type = TASK && description ~ "COMP3211" && deadline < "2026-11-22 00:00"'
        )
        result = self._run([
            f"load {_quoted(self.path)}", f"define {expression}", f"search {expression}",
            "search @C1", 'update 2 deadline="2026-11-25 23:59"',
            f"search {expression}", "search @C1", "show 7", f"save {_quoted(changed)}", "exit",
        ])
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertNotIn("ERROR ", result.stdout)
        outputs = result.stdout.split("pim> ")
        def ids(section):
            return re.findall(r"^ID: ([0-9]+)$", section, re.MULTILINE)

        self.assertEqual(ids(outputs[3]), ["2", "7"])
        self.assertEqual(ids(outputs[4]), ["2", "7"])
        self.assertEqual(ids(outputs[5]), ["2"])
        self.assertEqual(ids(outputs[6]), ["7"])
        self.assertEqual(ids(outputs[7]), ["7"])
        self.assertEqual(ids(outputs[8]), ["7"])
        loaded = PIMFileStorage().read(changed)
        self.assertEqual(loaded[0].deadline, datetime(2026, 11, 25, 23, 59))
        self.assertEqual(loaded[1], task7)
        self.assertEqual(PIMFileStorage().read(self.path), (task2, task7))

    def test_long_valid_expression_and_invalid_branch_keep_cli_usable(self):
        """Regression: valid flat chains cannot crash; a bad skipped branch reports ERROR."""
        expression = " && ".join(["type=PLAIN_TEXT"] * 1500)
        result = self._run([
            'create PLAIN_TEXT text="note"', f"define {expression}", "search @C1",
            f'search type=PLAIN_TEXT || ({expression}) || unknown~"x"',
            "show all", "exit", "d",
        ])
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.count("ID: 1"), 3)
        self.assertIn("ERROR Unknown search field", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertIn("Session ended.", result.stdout)

    def test_complete_cli_workflow_with_socket_creation_blocked(self):
        """NFR5 local evidence: all record types and operations work with sockets forbidden."""
        result = self._run([
            'create PLAIN_TEXT text="offline note"',
            'create TASK description="offline task" deadline="2026-11-20 20:00"',
            'create EVENT description="offline event" start="2026-11-20 20:00" '
            'alarm="2026-11-20 19:00"',
            'create CONTACT name="A" address="B" mobile="+001"',
            "define type=TASK || type=EVENT", "criteria", "search @C1",
            'update 1 text="offline changed"', "show all", f"save {_quoted(self.path)}",
            "delete 1", "y", f"load {_quoted(self.path)}", "d", "show 1", "exit",
        ], block_network=True)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertNotIn("ERROR ", result.stdout)
        self.assertIn("text: offline changed", result.stdout)
        self.assertEqual(len(PIMFileStorage().read(self.path)), 4)


if __name__ == "__main__":
    unittest.main()
