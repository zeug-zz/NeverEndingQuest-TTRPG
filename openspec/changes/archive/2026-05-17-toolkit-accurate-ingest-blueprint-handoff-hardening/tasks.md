## 1. Normalizer Narrative Persistence

- [x] 1.1 Inspect `utils/toolkit_homebrew_normalizer.py` final artifact persistence order around blueprint generation and legacy `_build_builder_narrative(...)`.
- [x] 1.2 Refactor narrative selection so the final `builder_narrative` variable is blueprint-derived when blueprint status is `ready`.
- [x] 1.3 Ensure `persist_builder_narrative_artifact(...)` writes the selected narrative once on the success path.
- [x] 1.4 Ensure the normalizer result payload returns the selected narrative and, if practical, a compact narrative source marker.
- [x] 1.5 Add/extend tests proving ready blueprint mode persists a `builder_narrative.md` containing `SOURCE-FAITHFUL BUILD LOCK` and does not overwrite it with legacy prose.

## 2. Required Blueprint vs Legacy Handoff

- [x] 2.1 Add a small helper in `web/extensions/toolkit_homebrew_packet_builder.py` to classify blueprint handoff as `source_blueprint_ready`, `blueprint_required_not_ready`, or `legacy_allowed`.
- [x] 2.2 Treat non-ready `builder_blueprint_report.json` as fail-closed before executor invocation.
- [x] 2.3 Treat missing blueprint artifacts as fail-closed when accurate-ingest source/fidelity artifacts are present and blueprint handoff is enabled.
- [x] 2.4 Preserve legacy packet-builder behavior when blueprint handoff is disabled or no accurate-ingest source/fidelity artifacts exist.
- [x] 2.5 Ensure `builder_input.json` still includes source-blueprint metadata when ready and excludes false source-blueprint readiness for legacy mode.

## 3. Packet Builder Test Isolation

- [x] 3.1 Update `scripts/test_packet_builder_blueprint_handoff.py` so every success-path build passes an injected mock executor.
- [x] 3.2 Update fail-closed tests to pass a raising/no-call executor and assert it is not invoked.
- [x] 3.3 Add a regression proving a missing blueprint in an accurate-ingest workspace fails closed without calling the executor.
- [x] 3.4 Add a regression proving a legacy workspace without accurate-ingest artifacts succeeds with a mock executor.
- [x] 3.5 Add a source-contract assertion or mock guard proving tests cannot accidentally invoke real `ModuleBuilder.build_module(...)`.

## 4. Verification

- [x] 4.1 Run `.venv/bin/python -m py_compile utils/toolkit_homebrew_normalizer.py web/extensions/toolkit_homebrew_packet_builder.py scripts/test_packet_builder_blueprint_handoff.py`.
- [x] 4.2 Run `.venv/bin/python -m unittest scripts.test_packet_builder_blueprint_handoff`.
- [x] 4.3 Run the Phase 4 blueprint suites: `scripts.test_builder_blueprint_fidelity_gate`, `scripts.test_builder_blueprint_generation`, and `scripts.test_builder_narrative_source_lock`.
- [x] 4.4 Run existing impacted regressions: `scripts.test_accurate_ingest_source_graph` and `scripts.test_toolkit_normalization_fidelity`.
- [x] 4.5 Run `openspec validate toolkit-accurate-ingest-blueprint-handoff-hardening`.
- [x] 4.6 Re-run `openspec validate toolkit-accurate-ingest-blueprint-builder-handoff` to confirm the base Phase 4 change remains valid.

## 5. Phase Boundary

- [x] 5.1 Confirm this slice does not add Phase 5 build-time fidelity gates.
- [x] 5.2 Confirm this slice does not add review UI fidelity panel behavior.
- [x] 5.3 Confirm this slice does not add narrative enrichment application.
