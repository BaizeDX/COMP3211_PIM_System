# Model line coverage verification

Command: /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 tools/report_model_coverage.py

Runtime: Python 3.12.6, macOS-15.7.3-arm64-arm-64bit.

Measured model unit tests: 175; all passed.
Covered executable model lines: **659/661 (99.70%)**.

Method: standard-library trace line events, intersected with recursively compiled
bytecode source-line tables (dis.findlinestarts). Each positive physical source
line counts once. Blank/comment/function-docstring-only lines have no executable
bytecode; module/class docstring assignments count when compiled as instructions.
Imports are traced from a cold process. Every model .py file is inventoried,
including completely unimported/unexecuted modules. No CLI/process/tool tests
or CLI/tests/tools/standard-library source lines enter this measurement.
Tracing is restored at each test boundary if an intentional recursion-limit
test disabled the hook. Any missed lines within that test remain uncovered.
This is line coverage, not branch coverage or requirements coverage.

| Model file | Covered | Executable | Line coverage | Uncovered lines |
| --- | --- | --- | --- | --- |
| model/__init__.py | 1 | 1 | 100.00% | None |
| model/criteria.py | 115 | 115 | 100.00% | None |
| model/errors.py | 23 | 23 | 100.00% | None |
| model/persistence.py | 117 | 117 | 100.00% | None |
| model/records.py | 70 | 70 | 100.00% | None |
| model/search.py | 158 | 159 | 99.37% | 189 |
| model/service.py | 97 | 97 | 100.00% | None |
| model/validation.py | 78 | 79 | 98.73% | 16 |

Working verification evidence only. The required-format formal Testing
report remains a separate handoff artifact. No Windows execution is claimed.

## Source snapshot

- model/__init__.py: 81c189af13eb429d1fb802e3b185e08ad37b1b4de0a53c4f52c535b621bdfd98
- model/criteria.py: 4d3a9b181ab6726ff101b9fc738382b070ad88d9e91ca941b826fee49f1fecfc
- model/errors.py: 0cd3009c9412913940685531bfc89d2c025c215caaa548939e76ca21a1941b96
- model/persistence.py: 3b3bf96654f191f4a41470cca9ff8d390af00ebc6a151a3dcc67c8150fc519b6
- model/records.py: c9ff9029ddda1883378e19ea5130d9583e999a1cd0f097a10560d4ce6eb61b51
- model/search.py: dc395ed5d255bc6c5765b4ce957968786290000a9df09be492c75d02eedbf6b0
- model/service.py: b57f479884b34b5e6ad6e952ac491b5d10693921159d130f1e64067337a7f521
- model/validation.py: cfbaab2471b97b9f1ff95a86e1f787ec6813032cd0de22ebe8e8aa5352a85070
