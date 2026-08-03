# Step 1.1 Baseline Evidence: `final_reconciliation_required` Boundary And Well Of Ruin Blocker Terms

Date: 2026-06-04
Source archive: `openspec/changes/archive/2026-06-04-toolkit-accurate-ingest-final-reconciliation-boundary/`

## 1. Archived Boundary Already Classifies Well Of Ruin Blockers As Editorial

The archived `toolkit-accurate-ingest-final-reconciliation-boundary` change (referenced via
`archive/2026-06-04-toolkit-accurate-ingest-final-reconciliation-boundary/`) provides:

- A provider-free final blocker classifier
  (`utils/toolkit_final_blocker_classifier.py`) that separates blockers into
  `fatal`, `editorial`, `mixed`, `unknown`, and `no_blockers`.
- A final reconciliation brief/report helper
  (`utils/toolkit_final_reconciliation.py`) that persists
  `final_reconciliation_brief.json` and `final_reconciliation_report.json`.
- Packet-builder integration in
  `web/extensions/toolkit_homebrew_packet_builder.py` that routes editorial-only
  classifications to `final_reconciliation_required: true` with persisted
  `final_reconciliation_brief.json` instead of immediate terminal build failure.
- Report-agreement logic in `utils/toolkit_report_agreement.py` that consumes
  `source_fidelity_effective_status` and allows playable publication when an
  accepted final reconciliation is present, while preserving original
  `source_fidelity_status`.
- GUI surfacing in `web/templates/module_toolkit.html` and
  `web/routes/toolkit_homebrew_routes.py` (canonical phase + terminal job
  state) for the `final_reconciliation_required` branch.

The classifier test matrix confirms Well-like bogus headings are classified as
`editorial`:

- `test_well_like_bogus_heading_boundary_contract` (scripts/test_toolkit_final_blocker_classifier.py)
  - Trigger, Passive Element, Active Element -> status: editorial
  - editorial_count: 3
  - refs/messages/report_paths all preserved
- `test_editorial_boundary_contract_required_location` covers
  editorial-only classifications yielding
  `can_attempt_final_reconciliation: True`.

So the front and middle of the accurate-ingest pipeline (source graph,
normalized packet, blueprint, backstage audit, source-enhanced ModuleBuilder)
are unchanged. The archived boundary already handles classification and brief
plumbing. The remaining gap is a live LLM Builder final editor that consumes
the brief and produces validated module changes plus an accepted report.

## 2. Well Of Ruin Blocker Terms (Recorded Exactly)

The 12 build-fidelity blockers observed on
`user_uploads/toolkit/homebrew_md/89c5a083-ad1c-4059-9994-2a3659d6174c/`
(archived baseline) are:

1. `Trigger`
2. `Passive Element`
3. `Active Element`
4. `Echoes of Calamity`
5. `Deciphering Ruin`
6. `**Well**spring of Legend`
7. `Celestial`
8. `Draconic`
9. `Orcish`
10. `Infernal`
11. `Primordial`
12. `Abyssal`

These are the canonical `final_reconciliation_brief` blocker-message strings
this change will use as test inputs and contract fixtures.

## 3. Trap/Mechanics Heading Classification (Source Markdown Context)

`Trigger`, `Passive Element`, and `Active Element` are **trap mechanics
sub-headings** in the source markdown, not playable module locations.

From the archived baseline (`evidence/well-of-ruin-baseline.md`):

- `### Trigger` (source line 17) - H3 sub-heading under the
  `# Well of Ruin` complex trap encounter.
- `### Passive Element` (source line 22) - H3 sub-heading for the trap's
  passive complication phase.
- `### Active Element` (source line 41) - H3 sub-heading for the trap's
  active rune activation phase.

The actual playable location is the trap room itself. The remaining 9 blockers
(`Echoes of Calamity`, `Deciphering Ruin`, `**Well**spring of Legend`,
`Celestial`, `Draconic`, `Orcish`, `Infernal`, `Primordial`, `Abyssal`) are
heading-derived (H3/H4 sub-headings for trap phases, lore sub-sections, and
rune variant table column headers) and are likewise not playable locations.

## 4. Implication For This Change

The presence of the editorial classification path, brief persistence, and
report agreement surface in the archived boundary confirms that the new
change must implement the **final LLM Builder editorial reconciliation** step,
not alter the front/middle accurate-ingest pipeline. Specifically:

- Source graph extraction, source manifest generation, normalized packet
  generation, blueprint generation, backstage audit briefing, and
  source-enhanced ModuleBuilder handoff all remain unchanged.
- The final editor consumes `final_reconciliation_brief.json`, emits a strict
  patch plan, applies only safe canonical JSON changes, and persists
  `final_reconciliation_report.json` with
  `source_fidelity_effective_status: reconciled_degraded` when accepted.
- Patch decisions for the 12 Well of Ruin blocker terms SHOULD classify them
  as bogus source atoms (e.g. `decision: delete_bogus_atom` or
  `decision: reclassify_atom`) rather than as missing playable locations.

## 5. Local Module Presence

`modules/Well_of_Ruin` is present locally (24 entries listed under
`ls modules/Well_of_Ruin/`). This Step 1.1 records presence only; no module
validation was run. Subsequent steps may reuse the artifact for fixture and
verification work, but live validator runs are deferred to Step 7.3 / 7.4
per `tasks.md`.

## 6. No Production Code Changed

This evidence file is read-only baseline documentation. No production code,
source graph, normalized packet, blueprint, backstage audit, module artifacts,
or archived boundary artifacts were modified.
