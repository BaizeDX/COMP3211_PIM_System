# Handoff specification clarification

Prepared 20 October 2026. These are versioned handoff copies. The original
selected SRS v1.3 and approved merged Design v1.1 in Downloads are unchanged.
No new application feature or architecture is introduced.

| Copy | Changes from the approved source |
| --- | --- |
| Group149_PIM_SRS_v1.4_Handoff.docx | Version metadata/history; section 5.3 explicitly records the user's permanent-EOF and input-boundary interruption clarification; ordinary output remains stdout and exceptional dirty EOF uses stderr/status 1. The footer uses a dynamic page field. |
| Group149_PIM_Design_v1.2_Handoff.docx | Version metadata/footer; sections 1.1/13 refer to the user-selected Word SRS and its clarified copy rather than the unavailable PDF; section 8 documents the exceptional lifecycle outcome/private stderr helper and points to new section 14; section 13.2 records the revision and private iterative Composite evaluation detail. |

Normal load/exit keeps save/discard/cancel. Recoverable Ctrl-C cancels pending
uncommitted input only; an already completed save stays completed. Permanent
stdin closure never repeatedly prompts, implicitly saves/overwrites, claims a
successful save or becomes user-confirmed discard. If dirty, it warns on stderr
and exits with status 1; clean EOF may exit with status 0. Recovery does not
broadly catch-and-continue across record, ID, dirty-state or file commits.

This is the explicit user-approved clarification requested after the original
documents, not a claim that the original SRS/design specified permanent EOF.
The original FR1-FR36/NFR1-NFR5 identifiers and paragraphs, all five design
diagrams, public ordinary signatures, symbolic grammar and file schema are
retained. The existing provisional stored-alarm assumption still needs
instructor confirmation; no notification requirement is silently added.

The final copies were rendered and visually reviewed. Students should review
and use consistent SRS/design versions in the final ZIP; these copies do not
create student approval signatures or instructor confirmation.

Original source identities and local paths remain in Implementation Plan
Appendix A. Actual handoff file identities are recorded in
../evidence/SOURCE_SNAPSHOT.json.
