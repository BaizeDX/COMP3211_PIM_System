# Group 149 Personal Information Management

Offline Python command-line PIM using MVC and Python standard libraries only.
The program starts empty. It never automatically loads the supplied samples.

Verified locally: **CPython 3.12.6, macOS 15.7.3, arm64**.
Windows is the SRS target; **a real Windows run remains outstanding**.

From the source-code root:

```text
python3.12 -X utf8 -B main.py
python3.12 -B -m unittest discover -s tests -p "test_*.py" -v
python3.12 -B tools/report_model_coverage.py
```

Windows commands (provided for verification, not yet executed on Windows):

```text
py -3.12 -X utf8 -B main.py
py -3.12 -B -m unittest discover -s tests -p "test_*.py" -v
py -3.12 -B tools/report_model_coverage.py --output "docs/evidence/windows_model_line_coverage.md"
```

No compilation, package installation or network service is required. Select
Python 3.12 and check its actual patch version before running. The `-B` option
avoids bytecode cache files.

At `pim>`, enter one command per line:

```text
load "samples/mixed.pim"
show all
define type = TASK && description ~ "COMP3211" && deadline < "2026-11-22 00:00"
search @C1
update 2 deadline="2026-11-25 23:59"
search @C1
exit
```

The searches return IDs **2, 7**, then **7**. At a dirty exit, choose `s` to save,
`d` to discard and exit, or `c` to stay. Save paths must be quoted.

## Documents and evidence

- [Developer Manual](docs/DEVELOPER_MANUAL.pdf): environment, architecture,
  launch/tests/debugging and platform verification.
- [User Manual](docs/USER_MANUAL.pdf): all commands, data rules, errors and guards.
- [Requirements Coverage Report](REQUIREMENTS_COVERAGE.pdf): actual US/UR/FR/NFR
  status, code/test references and qualified gaps.
- [Model Line Coverage Report](MODEL_LINE_COVERAGE.pdf): separate formal Testing
  evidence; measured source: [MODEL_LINE_COVERAGE.md](MODEL_LINE_COVERAGE.md).
- [Demonstration guide](docs/DEMO_RECORDING_GUIDE.pdf) and
  [command script](docs/demo_commands.txt). The script is not the MP4.
- [AI assistance summary](docs/AI_ASSISTANCE_SUMMARY.pdf): supporting information
  for the official declaration, not a completed or signed declaration.
- [Windows checklist](docs/WINDOWS_VERIFICATION_CHECKLIST.md) and
  [handoff status](docs/HANDOFF_STATUS.md): outstanding actions and inventory.
- [Specification copy changes](docs/specifications/CHANGE_LOG.md): the approved
  permanent-EOF clarification is explicit; original sources are preserved.

## Structure and limitations

`main.py` constructs dependencies. `cli/` contains syntax, terminal formatting
and confirmation coordination. `model/` owns immutable records, validation,
criteria/parser, collection state and transactional file persistence.
`tests/` contains assertions; `tools/` contains development measurement.

Event alarms are stored/searchable times with `alarm <= start`; there are no
notifications. Instructor confirmation of that scope is still required.
There is no autosave, GUI, online integration or database server.

Student work still includes the real implementation MP4 (maximum four minutes),
Windows verification and the official Honour Declaration with genuine agreed
contributions/signatures. Separate presentation deliverables also remain.
**This handoff is not a complete submission.** README supplements the required
manuals; it does not replace them.
