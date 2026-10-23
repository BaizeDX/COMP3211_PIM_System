"""Portable process/terminal regressions, including Windows path and filename cases."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

from cli.parser import CommandParser
from cli.view import PIMView, _configure_stdio
from model.persistence import PIMFileStorage


_ROOT = Path(__file__).resolve().parents[1]


def _quoted(path):
    return json.dumps(str(path), ensure_ascii=False)


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pim-portable-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.working = self.directory / "工作 目录"
        self.working.mkdir()
        (self.working / "数据 文件").mkdir()

    def _run(self, lines, *, main=None, crlf=False, encoding="cp1252:strict"):
        environment = dict(os.environ, PYTHONIOENCODING=encoding,
                           PYTHONUTF8="0", PYTHONDONTWRITEBYTECODE="1")
        separator = "\r\n" if crlf else "\n"
        payload = separator.join(lines) + (separator if lines else "")
        result = subprocess.run(
            [sys.executable, "-B", str(main or _ROOT / "main.py")],
            cwd=self.working, input=payload.encode("utf-8"), capture_output=True,
            timeout=15, env=environment,
        )
        # Native stdout newlines may be CRLF; the wire encoding must be UTF-8.
        result.stdout = result.stdout.decode("utf-8").replace("\r\n", "\n")
        result.stderr = result.stderr.decode("utf-8").replace("\r\n", "\n")
        return result

    def test_legacy_stream_encoding_full_unicode_workflow_and_native_paths(self):
        """UTF-8 pipes preserve four types, native/forward paths and live saved criteria."""
        target = self.working / "数据 文件" / "会话 中文.pim"
        forward = "数据 文件/会话 中文.pim"
        result = self._run([
            'create PLAIN_TEXT text="中文 😀 note"',
            'create TASK description="COMP3211 报告" deadline="0001-01-01 00:00"',
            'create EVENT description="会议" start="2026-11-20 20:00" '
            'alarm="2026-11-20 19:00"',
            'create CONTACT name="王" address="香港" mobile="+00123"',
            'define type=TASK && description~"报告"', "search @C1",
            f"save {_quoted(forward)}",
            'update 2 description="已完成"', "search @C1", "delete 4", "n",
            "delete 4", "y", f"load {_quoted(target)}", "d", "search @C1",
            "show all", "exit",
        ], crlf=True)
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertNotIn("ERROR ", result.stdout)
        for text in ("中文 😀 note", "description: COMP3211 报告", "name: 王", "address: 香港",
                     "mobile: +00123", "deadline: 0001-01-01 00:00", "Zero matches",
                     "Deletion cancelled", "Deleted record 4."):
            self.assertIn(text, result.stdout)
        saved = PIMFileStorage().read(target)
        self.assertEqual([r.id for r in saved], [1, 2, 3, 4])
        self.assertEqual(saved[0].text, "中文 😀 note")
        self.assertEqual(saved[1].description, "COMP3211 报告")
        self.assertEqual(saved[3].mobile, "+00123")
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_unicode_source_path_and_unrelated_working_directory(self):
        """Absolute launch imports from the source folder; relative data paths use cwd."""
        source = self.directory / "项目 source with spaces"
        source.mkdir()
        shutil.copyfile(_ROOT / "main.py", source / "main.py")
        for name in ("cli", "model"):
            shutil.copytree(_ROOT / name, source / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        result = self._run([
            "show all", 'create PLAIN_TEXT text="目录独立"',
            'save "数据 文件/relative.pim"', "exit",
        ], main=source / "main.py")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn("Collection is empty", result.stdout)
        self.assertIn("目录独立", result.stdout)
        self.assertTrue((self.working / "数据 文件/relative.pim").is_file())
        self.assertFalse((source / "数据 文件").exists())

    def test_crlf_input_and_escaped_quotes_backslashes_round_trip(self):
        """CRLF is a transport newline; literal backslashes/quotes are decoded only once."""
        target = self.working / "数据 文件" / "转义.pim"
        result = self._run([
            r'create PLAIN_TEXT text="路径 C:\\资料\\note \"quoted\""',
            r'search text ~ "\\资料\\"', f"save {_quoted(target)}",
            f"load {_quoted(target)}", "show 1", "exit",
        ], crlf=True)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertNotIn("ERROR ", result.stdout)
        self.assertEqual(PIMFileStorage().read(target)[0].text, '路径 C:\\资料\\note "quoted"')
        self.assertEqual(result.stdout.count('text: 路径 C:\\资料\\note "quoted"'), 3)

    def test_unicode_file_failures_and_overwrite_refusal_preserve_dirty_data(self):
        """Refused overwrite, failed save/load and s/d/c leave current data usable."""
        target = self.working / "数据 文件" / "保留.pim"
        target.write_bytes(b"existing bytes")
        invalid = self.working / "损坏 文件.pim"
        invalid.write_bytes(b"invalid JSON")
        result = self._run([
            'create PLAIN_TEXT text="未保存 中文"',
            f"save {_quoted(target)}", "n", 'save "不存在/数据.pim"',
            f"load {_quoted(invalid)}", "d", "show 1", "exit", "c", "show 1",
            f"save {_quoted(target)}", "y", f"load {_quoted(target)}", "exit",
        ])
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.count("ERROR "), 2)
        self.assertIn("Save cancelled", result.stdout)
        self.assertIn("Action cancelled", result.stdout)
        self.assertEqual(result.stdout.count("text: 未保存 中文"), 3)
        self.assertEqual(PIMFileStorage().read(target)[0].text, "未保存 中文")
        self.assertEqual(invalid.read_bytes(), b"invalid JSON")
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_legacy_stream_dirty_eof_is_nonzero_and_preserves_target(self):
        """UTF-8 redirected sessions retain the exceptional stderr/no-save EOF contract."""
        target = self.working / "数据 文件" / "保留.pim"
        target.write_bytes(b"original")
        result = self._run([
            'create PLAIN_TEXT text="未保存"', f"save {_quoted(target)}", "n",
        ])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "ERROR Standard input is closed; terminating the "
                         "session with unsaved changes.\n")
        self.assertIn("text: 未保存", result.stdout)
        self.assertNotIn("Saved collection", result.stdout)
        self.assertEqual(target.read_bytes(), b"original")
        clean = self._run([])
        self.assertEqual((clean.returncode, clean.stderr), (0, ""))

    def test_ascii_locale_pipe_can_display_unicode_loaded_from_file(self):
        """Loading valid UTF-8 data cannot crash show because of an ASCII stdout encoding."""
        path = _ROOT / "samples" / "mixed.pim"
        result = self._run([f"load {_quoted(path)}", "show all", "exit"], encoding="ascii:strict")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertNotIn("ERROR ", result.stdout)
        self.assertIn("中文 note", result.stdout)

    def test_windows_path_literals_keep_documented_escaping(self):
        """Parsing is literal; native pathlib interpretation is left to the running OS."""
        for native in (r"C:\Work\资料 文件\records.pim", r"\\server\共享\资料 文件\records.pim"):
            with self.subTest(path=native):
                decoded = CommandParser().parse("save " + _quoted(native)).arguments["path"]
                self.assertEqual(PureWindowsPath(str(decoded)), PureWindowsPath(native))
        self.assertEqual(CommandParser().parse('save "资料 文件/a.pim"').arguments["path"],
                         Path("资料 文件/a.pim"))
        # No textual/escape alias is introduced for Windows paths.
        from cli.errors import CommandError
        with self.assertRaises(CommandError):
            CommandParser().parse(r'save "C:\Work\bad.pim"')

    def test_stdio_setup_preserves_in_memory_embedding_streams(self):
        """Embedding/test adapters need no .buffer or reconfigure attribute to keep working."""
        incoming, outgoing, error = io.StringIO("中文\n"), io.StringIO(), io.StringIO()
        with patch("sys.stdin", incoming), redirect_stdout(outgoing), redirect_stderr(error):
            _configure_stdio()
            view = PIMView()
            self.assertEqual(view.read_line(), "中文")
            view.message("中文 😀")
            view.report_closed_input_with_unsaved_changes()
        self.assertIn("中文 😀", outgoing.getvalue())
        self.assertIn("unsaved changes", error.getvalue())
        self.assertFalse(incoming.closed or outgoing.closed or error.closed)

    def test_debugger_consumed_stdin_keeps_buffered_input(self):
        """Startup cannot replace a debugger's consumed decoder or lose unread commands."""
        for encoding in ("utf-8", "cp1252"):
            with self.subTest(encoding=encoding):
                incoming = io.TextIOWrapper(io.BytesIO(b"debugger command\nshow all\r\n"),
                                            encoding=encoding, newline="")
                outgoing, error = io.StringIO(), io.StringIO()
                self.assertEqual(incoming.readline(), "debugger command\n")
                with patch("sys.stdin", incoming), redirect_stdout(outgoing), redirect_stderr(error):
                    _configure_stdio()
                    self.assertIs(sys.stdin, incoming)
                    self.assertEqual(PIMView().read_line(), "show all")
                incoming.close()

    def test_real_pdb_launch_keeps_input_and_record_creation_working(self):
        """The documented debugger route must run the application, not enter post mortem."""
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", "-m", "pdb", str(_ROOT / "main.py")],
            input='c\ncreate PLAIN_TEXT text="中文 debug"\nexit\nd\nq\n'.encode("utf-8"),
            cwd=self.working, capture_output=True, timeout=15,
            env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1"),
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        output = result.stdout.decode("utf-8")
        self.assertIn("text: 中文 debug", output)
        self.assertIn("Session ended.", output)
        self.assertNotIn("post mortem", output)
        self.assertNotIn("Traceback", result.stderr.decode("utf-8"))

    @unittest.skipUnless(os.name == "nt", "Requires a real Windows filesystem")
    def test_windows_invalid_filename_recovers_without_mutation(self):
        """Native Windows rejects '?' in filenames; the next command retains unsaved data."""
        result = self._run([
            'create PLAIN_TEXT text="保留"', 'save "数据 文件/bad?.pim"',
            "show 1", "exit", "d",
        ])
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.count("ERROR Cannot save"), 1)
        self.assertEqual(result.stdout.count("text: 保留"), 2)
        self.assertIn("Unsaved changes:", result.stdout)
        self.assertEqual(list((self.working / "数据 文件").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
