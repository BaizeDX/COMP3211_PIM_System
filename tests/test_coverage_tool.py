"""Verify coverage accounting independently of production model implementation."""

import os
import shutil
import subprocess
import sys
import tempfile
import trace
import unittest
from pathlib import Path

from tools.report_model_coverage import _MODEL_TEST_MODULES, _inventory, _report


class CoverageToolTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.model = self.root / "model"
        self.model.mkdir()

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
            exec(compile(used.read_text(), str(used), "exec"), namespace)
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
        report = self.root / "MODEL_LINE_COVERAGE.md"
        report.write_text("earlier evidence", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(tools / source.name)], cwd=self.root,
            text=True, capture_output=True, timeout=5,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAILED", result.stderr)
        self.assertNotIn("coverage written", result.stdout)
        self.assertEqual(report.read_text(), "earlier evidence")

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
            text=True, capture_output=True, timeout=5,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = (self.root / "MODEL_LINE_COVERAGE.md").read_text()
        self.assertIn("model/sample.py | 2 | 2 | 100.00% | None", report)


if __name__ == "__main__":
    unittest.main()
