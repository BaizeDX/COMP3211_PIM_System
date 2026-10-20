# Implementation Demonstration and Recording Guide

COMP3211 Group 149 PIM | 20 October 2026

**Actual implementation MP4: outstanding.** This guide and the tested command
script are preparation materials, not a recording. A student must record the
real application in use and supply an MP4 no longer than four minutes, as
required by Project Description page 2, Deliverable 3.d.

## Recording plan

Target 3 minutes 40 seconds, leaving 20 seconds below the four-minute maximum.
The timings below are a planned budget, not a measured recording duration.
Rehearse and trim narration or pauses; verify the actual exported MP4 duration.

| Time budget | Visible actions | Suggested explanation |
| --- | --- | --- |
| 0:00-0:20 | Launch empty; show all; load mixed sample; show all | One offline collection, four record types and explicit loading |
| 0:20-0:50 | Create Demo note; repeat creation and refuse duplicate | Normalized duplicate warning; refusal adds no record or ID |
| 0:50-1:45 | Define/use C1; update Task 2; reuse C1; invalid skipped branch | Result changes from 2,7 to 7; saved criteria reevaluate current records; whole expression is validated |
| 1:45-2:25 | Refuse then confirm deletion of 12; save; refuse overwrite | Show-before-delete, real saving and overwrite protection |
| 2:25-3:05 | Change note 1; load missing file and choose discard; show 1 | Failed validation preserves original dirty records despite discard choice |
| 3:05-3:40 | Exit/cancel; exit/save to demo_final.pim | A cancelled exit keeps the session; successful save permits exit |

## Preconditions

Use a fresh disposable copy of the source root with supplied samples. Ensure
demo_session.pim, demo_final.pim and missing_demo.pim do not exist in that copy.
Do not delete or overwrite personal files to satisfy these conditions.
Start Python 3.12 in that folder; use the appropriate platform command from
the Developer Manual. Do not claim Windows verification if recording on macOS.

The exact input is docs/demo_commands.txt. Feed or paste short sections so the
viewer can see important output. The y/n/s/d/c lines and quoted save path are
responses to later prompts, not main commands. Do not paste the whole script
into a live terminal so quickly that results cannot be read.

The full script has been executed through the real CLI in a temporary folder.
It exited 0, produced the two intended ERROR messages (unknown search field
and missing load file), and saved five records to demo_final.pim. Its final
record IDs are 1,2,7,10,11; note 1 contains Unsaved demo change. This is script
verification evidence, not proof that any video has been recorded.

<!-- pagebreak -->
## Exact command and response sequence

Start the application first. Enter these lines in order:

```text
show all
load "samples/mixed.pim"
show all
create PLAIN_TEXT text="Demo note"
create PLAIN_TEXT text="Demo note"
n
define type = TASK && description ~ "COMP3211" && deadline < "2026-11-22 00:00"
search @C1
update 2 deadline="2026-11-25 23:59"
search @C1
search type = TASK || unknown ~ "x"
delete 12
n
delete 12
y
save "demo_session.pim"
save "demo_session.pim"
n
update 1 text="Unsaved demo change"
load "missing_demo.pim"
d
show 1
exit
c
exit
s
"demo_final.pim"
```

Explain only what is visible. Alarms are stored/searchable times, with no
automatic notifications; instructor scope confirmation is still outstanding.
Do not imply the application catches forced process termination or auto-saves.

## Recording and export checklist

- Record the actual terminal with readable font size and an uncluttered screen.
- State the real OS/Python used. Keep Windows claims pending unless tested there.
- Show both before/after search outputs and unchanged Task 7 where useful.
- Keep confirmations, intended errors and final successful save visible.
- Avoid exposing private paths, real personal information or other students' IDs.
- Export MP4 and measure its real duration; it must be <=4:00.
- Play the exported file and check legibility, audio if used, and complete ending.
- Name the final implementation recording demo.mp4 and add it to the handoff.
- Do not submit this guide or a simulated terminal animation as the required video.

The separate presentation has different rules: PDF slides, MP4 <=5 minutes,
at least one minute per member, required face/student-ID visibility and
prescribed contents. It is not replaced by this implementation demonstration.
