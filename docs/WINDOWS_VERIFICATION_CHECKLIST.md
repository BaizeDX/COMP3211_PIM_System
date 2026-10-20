# Windows release verification checklist

**Status: not executed.** A student or real Windows runner must record actual
results. macOS tests and this checklist do not establish Windows compatibility.
Use a disposable source copy and scratch files, without third-party runtime
packages and with networking unavailable.

## Environment and automated checks

- [ ] Record tester, date, Windows edition/build and source snapshot.
- [ ] Extract into a writable folder and change to its source root:

```powershell
Set-Location "C:\Work\Group149_PIM"
py -0p
py -3.12 --version
py -3.12 -B -m unittest discover -s tests -p "test_*.py" -v
py -3.12 -B tools/report_model_coverage.py --output "docs/evidence/windows_model_line_coverage.md"
py -3.12 -X utf8 -B main.py
```

- [ ] Record the actual Python patch; 3.12.6 is verified on macOS only.
  If py is absent, use the installed interpreter's full path.
- [ ] Retain stdout/stderr, exit status and counts; repair failures before
  marking a pass. Preserve Windows coverage separately from macOS evidence.
- [ ] Confirm fresh startup is empty despite supplied sample files.

## Record search and persistence checks

- [ ] Load samples/mixed.pim and display complete records in numerical order.
- [ ] Create every type, checking Unicode, mobile +/leading zeroes, year 0001,
  exact dates and Event alarm <= start.
- [ ] Define the Task/COMP3211/deadline criterion from the User Manual.
  Observe [2,7], update only Task 2 to 2026-11-25 23:59, then observe [7].
  Verify Task 7 remains unchanged.
- [ ] Exercise ~, time < > =, !, &&, disjunction and parentheses.
  Reject textual aliases, unknown fields even in skipped branches, malformed
  quotes/escapes and bad dates; a later valid command must still work.
- [ ] Verify normalized no-op and failed updates preserve the applicable dirty
  state; ID/type cannot be edited.
- [ ] Refuse/confirm duplicates and deletion; refusals do not consume IDs.
  Updating/loading equal business contents does not request duplicate consent.
- [ ] Delete the highest ID, load lower IDs or an empty collection, then create;
  the new ID exceeds session history.
- [ ] Save/reload all types and empty collections. Check UTF-8 JSON, lowercase
  .pim, all values/IDs and no persisted criteria/dirty/counter.
- [ ] Check Unicode/space paths using forward slashes and escaped backslashes:

```text
save "C:/Work/PIM data/test.pim"
save "C:\\Work\\PIM data\\test.pim"
```

- [ ] Use an existing scratch directory. Refuse overwrite and compare bytes.
- [ ] Check actual read/write permission errors and closed-handle replacement.
- [ ] Reject duplicate JSON keys/IDs, unsupported versions, corrupt/invalid
  files without partial replacement, counter change or criterion loss.

## Guards interruption and IDE

- [ ] Exercise s/d/c and invalid responses before dirty exit/load.
- [ ] Failed save or refused overwrite stops the pending action.
- [ ] Discard + failed load preserves original dirty records.
- [ ] Successful preliminary save + failed load preserves original clean records.
- [ ] Ctrl-C at input/confirmation/path boundaries cancels pending input without
  granting consent or silently discarding changes.
- [ ] Close piped stdin after creation; observe stderr warning, status 1,
  bounded termination and no auto-save. PowerShell example:

```powershell
'create PLAIN_TEXT text="unsaved"' | py -3.12 -X utf8 -B main.py
$LASTEXITCODE
```

- [ ] Expect status 1; distinguish clean EOF/status 0 and ordinary guarded exit.
- [ ] Run the Developer Manual's pdb procedure with py -3.12 -B -m pdb main.py.
- [ ] Open the folder in VS Code, select Python 3.12 and test the supplied
  PIM terminal debugger configuration using the integrated terminal.
- [ ] Update platform claims only after retaining genuine evidence. Leave every
  failed/unexecuted item pending.
