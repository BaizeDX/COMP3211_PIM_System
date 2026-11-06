"""Verify coverage accounting independently of production model implementation."""

import dis
import os
import shutil
import subprocess
import sys
import tempfile
import trace
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.report_model_coverage import (
    _MODEL_TEST_MODULES, _executable_lines, _inventory, _report,
)


class CoverageToolTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.model = self.root / "model"
        self.model.mkdir()

    def test_unicode_project_and_output_paths_with_legacy_stream_encoding(self):
        """A completed measurement must not crash while printing a Unicode report path."""
        project = self.root / "项目 source"
        tools, tests, model = (project / name for name in ("tools", "tests", "model"))
        for directory in (tools, tests, model):
            directory.mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / "tools/report_model_coverage.py"
        shutil.copyfile(source, tools / source.name)
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (model / "__init__.py").write_text("", encoding="utf-8")
        (model / "sample.py").write_text("def result():\n    return '中文'\n", encoding="utf-8")
        for name in _MODEL_TEST_MODULES:
            (tests / f"{name}.py").write_text("", encoding="utf-8")
        (tests / "test_errors.py").write_text(
            "import unittest\nclass Example(unittest.TestCase):\n"
            "    def test_example(self):\n"
            "        from model.sample import result\n"
            "        self.assertEqual(result(), '中文')\n", encoding="utf-8"
        )
        report = self.root / "结果 reports" / "覆盖.md"
        result = subprocess.run(
            [sys.executable, "-B", str(tools / source.name), "--output", str(report)],
            cwd=self.root, capture_output=True, timeout=15,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="0",
                     PYTHONIOENCODING="cp1252:strict"),
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertIn(str(report), result.stdout.decode("utf-8"))
        text = report.read_text(encoding="utf-8")
        self.assertIn("model/sample.py | 2 | 2 | 100.00% | None", text)
        self.assertIn("Measured model unit tests: 1; all passed.", text)

    def test_executed_partial_and_completely_unexecuted_modules(self):
        """A never-imported file still contributes all executable lines to the denominator."""
        used = self.model / "used.py"
        used.write_text(
            '# comment\n'
            'def choose(flag):\n'
            '    """Function docstring is not an executable body line."""\n'
            '    if flag:\n'
            '        return 10\n'
            '    return 20\n', encoding="utf-8",
        )
        (self.model / "never.py").write_text("def never():\n    return 99\n", encoding="utf-8")
        (self.model / "__init__.py").write_text("", encoding="utf-8")
        tracer = trace.Trace(count=True, trace=False)
        namespace = {"__file__": str(used)}

        def run():
            exec(compile(used.read_text(encoding="utf-8"), str(used), "exec"), namespace)
            self.assertEqual(namespace["choose"](True), 10)

        tracer.runfunc(run)
        rows = {row["path"]: row for row in _inventory(self.model, tracer.results().counts)}
        self.assertEqual((rows["model/used.py"]["covered"], rows["model/used.py"]["total"]),
                         (3, 4))
        self.assertEqual(rows["model/used.py"]["missing"], [6])
        self.assertEqual((rows["model/never.py"]["covered"], rows["model/never.py"]["total"]),
                         (0, 2))
        self.assertEqual(rows["model/never.py"]["missing"], [1, 2])
        self.assertEqual(rows["model/__init__.py"]["total"], 0)

    def test_non_model_hits_and_impossible_line_numbers_cannot_inflate_coverage(self):
        """Hit counts are not covered-line counts; unrelated and nonexecutable lines excluded."""
        path = self.model / "single.py"
        path.write_text("# comment\nvalue = 1\n", encoding="utf-8")
        rows = _inventory(self.model, {
            (str(path), 1): 100, (str(path), 2): 100, (str(path), 999): 100,
            (str(self.root / "cli.py"), 2): 100,
        })
        self.assertEqual((rows[0]["covered"], rows[0]["total"], rows[0]["missing"]), (1, 1, []))

    def test_annotate_child_code_objects_are_excluded_by_policy(self):
        """Lazy annotation functions (PEP 649) are excluded as a measurement policy; they
        evaluate type annotations, not model behaviour. Sibling code still counts."""
        code = compile(
            'value = 1\n'
            'def __annotate__(format):\n'
            '    return {"value": int}\n'
            'def kept():\n'
            '    return value\n', "sample.py", "exec",
        )
        children = {c.co_name for c in code.co_consts if isinstance(c, type(code))}
        self.assertEqual(children, {"__annotate__", "kept"})
        self.assertEqual(_executable_lines(code), {1, 2, 4, 5})

    def test_only_positive_line_starts_are_counted(self):
        """None (Python 3.13+) and 0 line starts are ignored; normal line numbers count."""
        code = types.SimpleNamespace(co_consts=())
        starts = [(0, None), (2, 0), (4, 7), (6, None), (8, 9)]
        with patch("tools.report_model_coverage.dis.findlinestarts", return_value=starts):
            self.assertEqual(_executable_lines(code), {7, 9})

    @unittest.skipUnless(sys.version_info >= (3, 14), "Requires PEP 649 lazy annotations")
    def test_compiler_generated_annotate_is_excluded_but_shared_lines_still_count(self):
        """Real __annotate__ lines drop out; a line shared with normal code counts once."""
        code = compile(
            'def spread(\n'
            '    value: int,\n'
            ') -> int:\n'
            '    return value\n'
            'def shared(value: int) -> int: return value\n', "sample.py", "exec",
        )

        def walk(node):
            yield node
            for constant in node.co_consts:
                if isinstance(constant, types.CodeType):
                    yield from walk(constant)

        annotate_lines = {
            line for node in walk(code) if node.co_name == "__annotate__"
            for _, line in dis.findlinestarts(node) if line
        }
        self.assertIn(2, annotate_lines)
        self.assertIn(5, annotate_lines)
        lines = _executable_lines(code)
        self.assertNotIn(2, lines)
        self.assertIn(5, lines)
        self.assertEqual(lines, {1, 4, 5})

    def test_report_aggregate_uses_line_totals_instead_of_average_percentages(self):
        """Two modules with 1/1 and 0/3 coverage total 1/4 (25%), not 50%."""
        rows = [
            {"path": "model/a.py", "covered": 1, "total": 1, "missing": [], "sha256": "a"},
            {"path": "model/b.py", "covered": 0, "total": 3,
             "missing": [1, 2, 3], "sha256": "b"},
        ]
        report = _report(rows, 2, "example command")
        self.assertIn("1/4 (25.00%)", report)
        self.assertIn("model/b.py | 0 | 3 | 0.00% | 1, 2, 3", report)
        self.assertIn("not branch coverage or requirements coverage", report)

    def test_failing_model_suite_does_not_publish_or_replace_a_success_report(self):
        """Actual tool process exits nonzero and retains earlier evidence when tests fail."""
        tools = self.root / "tools"
        tests = self.root / "tests"
        tools.mkdir()
        tests.mkdir()
        source = Path(__file__).resolve().parents[1] / "tools" / "report_model_coverage.py"
        shutil.copyfile(source, tools / source.name)
        (tests / "__init__.py").write_text("", encoding="utf-8")
        for name in _MODEL_TEST_MODULES:
            (tests / f"{name}.py").write_text("", encoding="utf-8")
        (tests / "test_errors.py").write_text(
            "import unittest\nclass Failure(unittest.TestCase):\n"
            "    def test_failure(self):\n        self.assertEqual(1, 2)\n", encoding="utf-8"
        )
        report = self.root / "supporting" / "evidence" / "MODEL_LINE_COVERAGE.md"
        report.parent.mkdir(parents=True)
        report.write_text("earlier evidence", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(tools / source.name)], cwd=self.root,
            text=True, encoding="utf-8", capture_output=True, timeout=15,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAILED", result.stderr)
        self.assertNotIn("coverage written", result.stdout)
        self.assertEqual(report.read_text(encoding="utf-8"), "earlier evidence")

    def test_tracing_resumes_for_next_test_after_trace_hook_is_disabled(self):
        """A test disabling tracing must not silently remove later modules from measured hits."""
        tools = self.root / "tools"
        tests = self.root / "tests"
        tools.mkdir()
        tests.mkdir()
        source = Path(__file__).resolve().parents[1] / "tools" / "report_model_coverage.py"
        shutil.copyfile(source, tools / source.name)
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (self.model / "__init__.py").write_text("", encoding="utf-8")
        (self.model / "sample.py").write_text("def calculate():\n    return 3\n", encoding="utf-8")
        for name in _MODEL_TEST_MODULES:
            (tests / f"{name}.py").write_text("", encoding="utf-8")
        (tests / "test_errors.py").write_text(
            "import sys, unittest\nclass Recovery(unittest.TestCase):\n"
            "    def test_a_disables_tracing(self):\n        sys.settrace(None)\n"
            "    def test_b_measures_afterwards(self):\n"
            "        from model.sample import calculate\n"
            "        self.assertEqual(calculate(), 3)\n", encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(tools / source.name)], cwd=self.root,
            text=True, encoding="utf-8", capture_output=True, timeout=15,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = (self.root / "supporting" / "evidence" / "MODEL_LINE_COVERAGE.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("model/sample.py | 2 | 2 | 100.00% | None", report)


if __name__ == "__main__":
    unittest.main()
