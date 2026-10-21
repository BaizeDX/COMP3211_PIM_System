"""Measure model-only unittest line coverage, including completely unexecuted modules."""

import argparse
import dis
import hashlib
import io
import os
import platform
import shlex
import subprocess
import sys
import trace
import unittest
from pathlib import Path
from types import CodeType


_MODEL_TEST_MODULES = (
    "test_errors", "test_validation", "test_records", "test_criteria",
    "test_search", "test_service", "test_persistence", "test_model_regressions",
)


def _executable_lines(code: CodeType) -> set[int]:
    """Count distinct positive bytecode source lines recursively, not comments/blank lines."""
    lines = {line for _, line in dis.findlinestarts(code) if line > 0}
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            lines.update(_executable_lines(constant))
    return lines


def _inventory(model: Path, counts: dict) -> list[dict]:
    """Discover all model files independently of trace hits or imported modules."""
    hits = {}
    for (filename, line), count in counts.items():
        if count > 0:
            hits.setdefault(Path(filename).resolve(), set()).add(line)
    rows = []
    for path in sorted(model.rglob("*.py")):
        source = path.read_bytes()
        executable = _executable_lines(compile(source, str(path.resolve()), "exec"))
        covered = executable & hits.get(path.resolve(), set())
        rows.append({
            "path": path.relative_to(model.parent).as_posix(),
            "covered": len(covered), "total": len(executable),
            "missing": sorted(executable - covered),
            "sha256": hashlib.sha256(source).hexdigest(),
        })
    return rows


def _run_model_tests(tracer: trace.Trace) -> unittest.TestResult:
    # Loading occurs inside tracing, so import/class/function-definition lines count.
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        [f"tests.{name}" for name in _MODEL_TEST_MODULES]
    )
    class MeasuredResult(unittest.TextTestResult):
        def startTest(self, test):
            # Deliberate recursion-limit tests can disable CPython's trace hook.
            # Restore it for the next test rather than silently losing later hits.
            sys.settrace(tracer.globaltrace)
            super().startTest(test)

    return unittest.TextTestRunner(verbosity=1, resultclass=MeasuredResult).run(suite)


def _report(rows: list[dict], tests: int, command: str) -> str:
    covered = sum(row["covered"] for row in rows)
    total = sum(row["total"] for row in rows)
    percentage = f"{100 * covered / total:.2f}%" if total else "N/A"
    lines = [
        "# Model line coverage verification", "",
        f"Command: {command}", "",
        f"Runtime: Python {platform.python_version()}, {platform.platform()}.", "",
        f"Measured model unit tests: {tests}; all passed.",
        f"Covered executable model lines: **{covered}/{total} ({percentage})**.", "",
        "Method: standard-library trace line events, intersected with recursively compiled",
        "bytecode source-line tables (dis.findlinestarts). Each positive physical source",
        "line counts once. Blank/comment/function-docstring-only lines have no executable",
        "bytecode; module/class docstring assignments count when compiled as instructions.",
        "Imports are traced from a cold process. Every model .py file is inventoried,",
        "including completely unimported/unexecuted modules. No CLI/process/tool tests",
        "or CLI/tests/tools/standard-library source lines enter this measurement.",
        "Tracing is restored at each test boundary if an intentional recursion-limit",
        "test disabled the hook. Any missed lines within that test remain uncovered.",
        "This is line coverage, not branch coverage or requirements coverage.", "",
        "| Model file | Covered | Executable | Line coverage | Uncovered lines |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        ratio = f'{100 * row["covered"] / row["total"]:.2f}%' if row["total"] else "N/A"
        missing = ", ".join(map(str, row["missing"])) or "None"
        lines.append(
            f'| {row["path"]} | {row["covered"]} | {row["total"]} | {ratio} | {missing} |'
        )
    lines.extend([
        "", "Working verification evidence only. The required-format formal Testing",
        "report remains a separate handoff artifact. No Windows execution is claimed.",
        "", "## Source snapshot", "",
    ])
    lines.extend(f'- {row["path"]}: {row["sha256"]}' for row in rows)
    return "\n".join(lines) + "\n"


def main() -> int:
    # Report paths/test failures can contain Unicode even with ANSI redirection.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors=stream.errors)
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=root / "supporting" / "evidence" / "MODEL_LINE_COVERAGE.md",
    )
    args = parser.parse_args()
    if any(name == "model" or name.startswith("model.") for name in sys.modules):
        raise RuntimeError("Coverage must start in a cold process, before importing model.")
    sys.path.insert(0, str(root))
    tracer = trace.Trace(count=True, trace=False)
    result = tracer.runfunc(_run_model_tests, tracer)
    if not result.wasSuccessful():
        return 1  # Never publish successful coverage over failing tests.
    rows = _inventory(root / "model", tracer.results().counts)
    arguments = [sys.executable, *sys.argv]
    command = subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_report(rows, result.testsRun, command), encoding="utf-8")
    print(f"Model line coverage written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
