# Group 149 Personal Information Management

An offline Python command-line application for managing plain-text notes, tasks,
events and contacts. It uses MVC and Python standard libraries only.

The repository root is this folder, containing main.py, model/, cli/ and tests/.
Run all commands below from this folder. The application starts empty and never
automatically loads sample files or previous sessions.

## Requirements and startup

Verified locally with **CPython 3.12.6 on macOS 15.7.3 arm64**.
Windows is the target platform; **real Windows verification remains pending**.
No third-party runtime packages, database server or network connection is required.

On the verified local environment:

```text
python3.12 -X utf8 -B main.py
```

Windows launch command, not yet verified on Windows:

```text
py -3.12 -X utf8 -B main.py
```

Use Python 3.12 and check the installed patch version. The -B option avoids
creating Python bytecode cache files.

## Example session

Enter one command per line at the pim> prompt:

```text
load "samples/mixed.pim"
show all
define type = TASK && description ~ "COMP3211" && deadline < "2026-11-22 00:00"
search @C1
update 2 deadline="2026-11-25 23:59"
search @C1
exit
```

The searches return records 2 and 7, then only 7 after the update. If exiting
with unsaved changes, choose s to save, d to discard and exit, or c to cancel
exit. Save paths must be double-quoted, for example "records.pim".

Supported commands are create, update, show, delete, define, criteria, search,
save, load and exit. Search operators are ~, =, <, >, !, && and ||, with
parentheses for grouping. Textual operator aliases are not supported.

## Tests and model line coverage

Run the full automated suite:

```text
python3.12 -B -m unittest discover -s tests -p "test_*.py" -v
```

Measure model line coverage separately:

```text
python3.12 -B tools/report_model_coverage.py --output "coverage/model_line_coverage.md"
```

The coverage command creates its output directory and measures model unit tests
only. It inventories every model module, including completely unexecuted ones.
Line coverage and requirements coverage are different measures.

Equivalent Windows commands, provided for verification:

```text
py -3.12 -B -m unittest discover -s tests -p "test_*.py" -v
py -3.12 -B tools/report_model_coverage.py --output "coverage/model_line_coverage.md"
```

Latest completed local verification on 20 October 2026: **258 tests passed**.
The separate **181-model-test** run covered **664/666 executable model lines
(99.70%)**. Uncovered lines were model/search.py:189 and model/validation.py:16.
These results were obtained on macOS and do not establish Windows compatibility.

## Repository structure

```text
main.py       Dependency construction and application entry point
model/        Immutable records, validation, search, service and persistence
cli/          Command parsing, terminal input/output and controller coordination
tests/        Unit, controller, real-process and coverage-tool tests
tools/        Development tools for measuring model line coverage
samples/      Valid example .pim files loaded only on explicit request
README.md     Startup, examples, tests and project overview
```

Model code has no terminal input/output. The controller coordinates operations
and confirmations; the view handles terminal interaction. Search expressions
are parsed and validated in the model without eval.

The samples include mixed.pim for all four record types, design_scenario.pim
for the search-and-update example, and empty.pim for a valid empty collection.

## Behaviour and limitations

- Record IDs range from 1 through 9223372036854775807. Allocation follows the
  session high-water mark; deletion and loading lower IDs never reset it.
  Exhausted creation fails before changing records, the counter or dirty state.
  Existing records remain usable.
- Saved criteria reevaluate current records, survive loads and remain
  session-only. They are not persisted in .pim files.
- Saving uses UTF-8 JSON and a lowercase .pim extension. Loading validates the
  entire file before replacing the collection. Existing files require overwrite
  confirmation; failed saves and loads preserve the applicable in-memory state.
- Duplicate creation and deletion require confirmation. Unsaved changes before
  load or normal exit use save/discard/cancel.
- Permanent EOF does not auto-save or imply discard. With unsaved changes, it
  reports an ERROR on stderr and exits with status 1 without repeated prompts.
- Event alarms are stored/searchable times with alarm <= start. Automatic
  notifications are excluded; instructor confirmation of this scope is pending.
- There is no GUI, autosave, online integration or database server.

## Repository hygiene

Exclude __pycache__/, *.pyc, .DS_Store, unrelated .Rhistory, generated coverage
output and temporary test/demo files from version control. Keep the supplied
samples/ files; do not ignore every .pim file indiscriminately.
