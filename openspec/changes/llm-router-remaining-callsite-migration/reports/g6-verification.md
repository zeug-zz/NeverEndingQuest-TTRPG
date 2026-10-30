# G6 Verification

G6 gate: PASS. Verification was provider-free; no live gate was required by the design.

## Evidence

- 74-process regression baseline: 1401 tests, 0 skipped, no decreases (`tmp/router-rollout/g6/g6-baseline-results.json`).
- `py_compile` passed for 197 changed Python files.
- ASCII check: 1205 files, 0 violations.
- `git diff --check` clean; strict OpenSpec validation valid.
- G1: 4/4 byte-identical; G3: 50/50 identical; G4 pinned identical; 9/9 prompt hashes; gate10 G5T re-evaluation error/JSON byte-identical.
- Focused integration results: core chat request 17, decomposition 9, validation stage 25, latency hot path 45; 1-PC/4-PC floor: decomposition 9, enemy resolution 16, multi-PC combat 75.
- Shared contract: 64 OK in script and module form; router test 88 OK. Production tripwire scanned 381 production files; only `utils/llm_router.py` and `utils/provider_response_recovery.py` contain raw calls; negative fixture detected, 7 OK.
- Compression evidence tooling accepts router-shaped `combat_compression` traces while legacy bundles remain identical; transition fail-open 8 OK, compression routing 5 OK, compression params 6 tests restored at the router boundary.

## Known HEAD failures excluded from the regression claim

Pre-existing HEAD failures: `test_pc_image_create_mvp` (4F), `test_toolkit_text_description_enabled_failure_guards` (5F), `test_toolkit_text_description_socketio_path` (1F), `test_toolkit_homebrew_gui_unified_flow` (4F), `test_toolkit_homebrew_corpus_quality_gate` (1F), `test_structural_blocker_routing` (2F), `test_character_creation_shared_contract`, `test_toolkit_module_build_publication_parity` (1F), and `test_step_2_1_trigger_integration`.

`test_toolkit_text_description_legacy_contract` times out only because its `tmp/` scan is quadratic over approximately 70,000 scratch files. It passes at HEAD and with a linear equivalent.

## Intentional behavior changes

- The campaign export branch previously referenced nonexistent `DM_SUMMARY_MODEL` and always fell back. It now routes through `summaries`, preserving deterministic fallback.
- Caller temperature is no longer sent; this had no effect on `gpt-6-luna`.
- Phase-7 task policies must define sampling for non-reasoning models.

## Provider-contact incident

No live provider or Capture_Arena call occurred during verification. One builder scratch attempt during task 6.2 reached a provider and returned `BadRequestError`; the detail is unrecoverable, and no state write was evidenced.
