# Tasks: Accurate-Ingest GUI State And Overwrite Safety

## 1. Baseline Review

- [x] 1.1 Review current job state payload construction in `web/routes/toolkit_homebrew_routes.py`.
- [x] 1.2 Review packet build write boundary in `web/extensions/toolkit_homebrew_packet_builder.py`.
- [x] 1.3 Review existing overwrite confirmation and clean rebuild helpers in `web/extensions/toolkit_homebrew_rebuild_guard.py`.
- [x] 1.4 Review GUI status tests and upload/rebuild route tests for existing coverage.

## 2. Canonical Phase Surfacing

- [x] 2.1 Define a canonical accurate-ingest phase map for upload/build/fidelity/readiness/finisher states.
- [x] 2.2 Ensure job polling payloads include a stable accurate-ingest phase field.
- [x] 2.3 Preserve existing `status`, `stage`, `pipeline_status`, `progress_stage`, and `progress_message` fields.
- [x] 2.4 Include phase values for `extracting_source_truth`, `building_blueprint`, `awaiting_review`, `seeding_module`, `enriching_module`, `build_fidelity`, `readiness`, `finishing`, and `publishability_audit`.

## 3. Accurate-Ingest Summary Payload

- [x] 3.1 Add compact grouped accurate-ingest summary to job payloads.
- [x] 3.2 Include source counts when available: locations, NPCs, plot beats, and areas.
- [x] 3.3 Include blueprint status, seed status, enrichment status, build fidelity status, readiness status, publishability status, and source-fidelity status when available.
- [x] 3.4 Ensure legacy/non-accurate-ingest jobs do not break and may omit or mark the grouped summary disabled.

## 4. Overwrite Authorization Guard

- [x] 4.1 Add shared overwrite authorization check at packet-build write boundary.
- [x] 4.2 Refuse packet build before module writes when output module directory exists and no confirmation token/rebuild plan is present.
- [x] 4.3 Permit first build when output module directory is absent.
- [x] 4.4 Permit confirmed clean rebuild only when route-level confirmation or rebuild plan artifact is valid for the same workspace/module slug.
- [x] 4.5 Keep finishing-only retry allowed without packet rebuild overwrite authorization.

## 5. Tests

- [x] 5.1 Add payload test: accurate-ingest phase appears for source extraction / blueprint / review / seeding / fidelity / readiness / finishing states.
- [x] 5.2 Add payload test: grouped accurate-ingest summary includes source counts and status fields when artifacts exist.
- [x] 5.3 Add overwrite test: first build into absent module directory succeeds.
- [x] 5.4 Add overwrite test: existing module without confirmation is refused before seed writer or ModuleBuilder execution.
- [x] 5.5 Add overwrite test: confirmed rebuild path proceeds and references backup-clean rebuild artifact/plan.
- [x] 5.6 Add retry test: retry-from-packet refuses overwrite without confirmation.
- [x] 5.7 Add retry test: finishing-only retry remains allowed.
- [x] 5.8 Add regression test: existing fidelity review approval requirement still blocks unapproved builds before module files are written.

## 6. Verification

- [x] 6.1 Run `.venv/bin/python -m py_compile web/routes/toolkit_homebrew_routes.py web/extensions/toolkit_homebrew_packet_builder.py web/extensions/toolkit_homebrew_rebuild_guard.py`.
- [x] 6.2 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`.
- [x] 6.3 Run `.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity`.
- [x] 6.4 Run related route/rebuild tests if modified.
- [x] 6.5 Run `openspec validate toolkit-accurate-ingest-gui-state-overwrite-safety`.
- [x] 6.6 Run targeted ASCII compliance on changed Python/test/template files.

## Builder Guidance

Use micro-edits. Start with tests for status payload and overwrite refusal, then implement the smallest shared helper changes needed. Do not rebuild or edit production modules. Avoid frontend template edits unless a payload/rendering source-contract test requires them.
