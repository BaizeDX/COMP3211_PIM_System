# Qualified local handoff status

Prepared 20 October 2026. **This is not a complete course submission or a
Windows-verified release.** The runnable implementation, local evidence and
required-format documents are prepared. Actual recordings, platform acceptance
and the official declaration still need genuine student input.

## Prepared artifacts

| Requirement/item | Files and actual status |
| --- | --- |
| Implementation 3.a: source | main.py, model/, cli/; complete approved MVC implementation, standard-library runtime only |
| Implementation 3.b: Developer Manual | DEVELOPER_MANUAL.pdf (4 pages); actual CPython 3.12.6/macOS 15.7.3 arm64; launch/test/pdb verified; optional VS Code and all Windows instructions unverified |
| Implementation 3.c: User Manual | USER_MANUAL.pdf (6 pages); commands, escaping, validation, confirmations, guards, stored-alarm scope and exceptional EOF |
| Implementation 3.d: actual MP4 <=4 minutes | **Not provided.** DEMO_RECORDING_GUIDE.pdf (2 pages) and demo_commands.txt are preparation only |
| Implementation 3.e: root requirements table | ../REQUIREMENTS_COVERAGE.pdf (8 pages); all US1-US11/UR1-UR11, FR1-FR36, NFR1-NFR5 and common rules; local evidence and qualified gaps |
| Separate Testing 4.a | ../tests/; full 249 methods passed locally, including 175 model methods, 69 CLI/process methods and 5 coverage-tool methods |
| Separate Testing 4.b | ../MODEL_LINE_COVERAGE.pdf (2 pages), ../MODEL_LINE_COVERAGE.md and ../tools/report_model_coverage.py; measured 659/661 model executable lines (99.70%) |
| Supporting AI acknowledgement | AI_ASSISTANCE_SUMMARY.pdf (1 page); **not the official declaration** and contains no invented contribution percentages or signatures |
| Supplementary startup guide | ../README.md; verified local commands and links; does not replace either manual |
| Valid samples | ../samples/empty.pim, design_scenario.pim, mixed.pim; parsed using the actual storage class; no automatic startup loading |
| Clarified SRS/design copies | specifications/Group149_PIM_SRS_v1.4_Handoff.docx (9 pages) and Group149_PIM_Design_v1.2_Handoff.docx (18 pages); CHANGE_LOG.md records the narrow user-approved lifecycle/reference changes |
| Reproducible evidence | evidence/LOCAL_VERIFICATION.txt, evidence/SOURCE_SNAPSHOT.json, source/ editable document drafts and source/REQUIREMENTS_EVIDENCE.json |
| Windows release procedure | WINDOWS_VERIFICATION_CHECKLIST.md; every real Windows checkbox remains outstanding |

All six final PDFs and both final DOCX copies have been rendered and visually
reviewed page by page. Original source documents, existing runtime/test/tool
code and .Rhistory are preserved. No commit, push, publication, MP4 or final
submission ZIP was produced.

## Actual local verification

The transcript records commands, outputs and exit statuses. The full suite
passed 249 methods. The separately measured model-only suite passed 175.
The standard-library trace/compiled-line inventory includes every model module,
including unexecuted modules; five accounting tests validate the denominator,
aggregation, filtering, failed-suite publication and trace restoration.
Uncovered lines: model/search.py:189 (recursion-handler trace event unavailable
within the deliberate recursion-limit test) and model/validation.py:16
(TYPE_CHECKING import). No minimum percentage was invented; requirements
coverage and code line coverage remain distinct.

The documented launch command, README search-update workflow, pdb breakpoint
procedure and the complete recording script were executed in real processes.
The script produced the two intended ERROR cases and ended normally, with
five saved records and the expected changes. It is a verified script, not a
recorded video or a measured video duration. Plan Figure 5 checks and saved
criteria searches reflect Task 2's changed deadline: [2,7] becomes [7].

## Remaining student actions and owners

1. Students review the code and documents, including the clearly labelled
   SRS/design clarification copies. Retain the approved MVC/public interfaces.
2. A real Windows runner executes WINDOWS_VERIFICATION_CHECKLIST.md, retains
   actual OS/Python/command/result evidence and repairs any failures. Update
   platform claims only after that run. Local progress is not blocked by its
   present absence.
3. Students record the real implementation MP4, showing important features
   within 4 minutes. Use the planned 3:40 script as rehearsal guidance; inspect
   the actual file's format, duration and visible results before submission.
4. Students obtain/complete the official Honour Declaration for Group Project
   at the ZIP root, truthfully acknowledge assistance, agree actual contribution
   percentages and supply required signatures/attestations themselves.
5. Students confirm the provisional stored-alarm scope with the instructor.
   Automatic notification is not implemented or claimed approved.
6. Students complete the separate presentation deliverables: PDF slides and
   actual MP4, <=5 minutes total, >=1 minute per member and required face/ID
   evidence. The implementation demo does not replace that presentation.
7. Students assemble and check the final single ZIP against the actual course
   requirements and deadline: 20 November 2026, 20:00 Hong Kong time. Include
   complete source/tests, manuals, root reports, consistent SRS/design,
   recordings/presentation and official declaration. Exclude scratch output,
   generated caches and unrelated private files such as .Rhistory.

No student identity, contribution, signature, recording, instructor decision or
Windows pass has been fabricated. The remaining items prevent a truthful claim
that the entire submission is complete.
