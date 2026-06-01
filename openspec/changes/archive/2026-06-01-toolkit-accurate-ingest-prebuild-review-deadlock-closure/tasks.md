## 1. Pipeline Boundary

- [x] 1.1 Audit accurate-ingest GUI job states and identify the exact branch that converts pre-build fidelity diagnostics into mandatory `awaiting_review` / `blocked_by_fidelity` before blueprint generation.
  - Root cause: `evaluate_blueprint_fidelity_precheck()` in `utils/toolkit_builder_blueprint.py` refused blueprint generation when fidelity was "degraded" with blocking findings. In `web/extensions/toolkit_homebrew_fidelity_review.py`, `_summarize_blueprint()` marked degraded blueprints as not-ready and `can_approve_fidelity_review()` rejected non-"ready" blueprint status.
- [x] 1.2 Change the default accurate-ingest flow so readable source/packet artifacts proceed to bounded blueprint generation even when pre-build fidelity diagnostics are degraded.
  - `evaluate_blueprint_fidelity_precheck()`: removed the degraded-with-blockers refusal branch. Degraded, clean, repaired, and unknown fidelity all allow blueprint generation now. Only "blocked" and "failed" fidelity blocks.
  - `_summarize_blueprint()`: "ready" now accepts both "ready" and "degraded" blueprint status.
  - `can_approve_fidelity_review()`: accepts "ready" and "degraded" blueprint status.
- [x] 1.3 Preserve strict required-review behavior for explicitly required review states, stale signatures, non-approvable reviews, user rejection, and malformed/missing source artifacts.
  - Missing artifacts (`source_graph` or `normalized_packet` is None) still refuse with `STATUS_MISSING_ARTIFACTS`.
  - Blocked/failed fidelity still refuses with `STATUS_BLOCKED_BY_FIDELITY`.
  - `_fidelity_review_requires_decision()` unchanged - still checks can_approve and blockers.
  - `can_approve_fidelity_review()` unchanged for missing/failed/blocked status and blockers.
- [x] 1.4 Ensure missing or malformed blueprint prerequisites fail with explicit `missing_artifacts` or malformed-artifact diagnostics instead of false success.
  - No change needed - existing checks for missing `source_graph` and `normalized_packet` produce `STATUS_MISSING_ARTIFACTS` with explicit detail.

## 2. Source Atom Classification

- [x] 2.1 Extend deterministic source atom extraction/classification to recognize markdown heading locations and escaped numbered room headings.
  - `_extract_location_candidates()`: added heading-based location extraction for level 2-4 headings that pass `_is_heading_location_name()`.
  - `_MAP_KEY_PATTERN`: now matches escaped numbering (`\?` before separator) and captures full "number + title" string.
  - `_normalize_heading_text()`: strips backslash escapes and is applied during heading extraction and map-key name capture.
  - `_is_map_key_style_heading()`: normalizes text before checking.
- [x] 2.2 Classify appendix/section headings separately from entity/location requirements.
  - Added `_APPENDIX_PATTERN` regex matching Appendix/Appendices/Credits/Changelog/etc.
  - `_is_heading_location_name()` rejects appendix matches.
  - Heading-based location extraction skips appendix headings.
- [x] 2.3 Prevent prose fragments from becoming required NPC/location/monster blockers.
  - `_is_likely_name()`: added prefix-word check rejecting phrases where >=50% of words are function words.
  - `_proper_noun_candidates()`: added same prefix-word rejection.
  - `_HEADING_PREFIX_WORDS`: expanded with articles, filler words, and prose-fragment words.
  - `_is_heading_location_name()`: rejects phrases dominated by prefix/function words.
- [x] 2.4 Keep NPC-like and creature/monster-like names available as source context without forcing pre-build human approval.
  - `_ENCOUNTER_PATTERN`: extended with creature descriptors (assassin, knight, guard dog, lion, etc.).
  - Entity candidates from bold spans/table cells/quoted names continue to be captured.
  - The pre-build continuation change ensures these are source context, not mandatory blockers.

## 3. GUI Status and Guidance

- [x] 3.1 Fix status rendering so `rejected`, `blocked`, `failed`, `quarantined`, and no-module states are terminal or blocked, not successful.
  - `pollToolkitHomebrewJob()`: `rejected` status now shows as 'error' type with terminal message.
  - `blocked` status now stops polling and disables the upload button.
  - `_get_canonical_accurate_ingest_phase()`: added "blocked" to terminal statuses.
- [x] 3.2 Gate MMG guidance on actual module folder existence and an MMG-eligible build state.
  - `getHomebrewStatusWithGuidance()`: removed unconditional "Next: open the MMG tab..." for all success messages.
  - MMG guidance is now only implied by the caller when appropriate (completed + playable state).
- [x] 3.3 Surface diagnostics as warnings/blockers/next actions without implying successful build completion.
  - Status messages for blocked/not_publishable states use 'error'/'warning' types.
  - `rejected` state explicitly says "terminally blocked."

## 4. Regression Tests

- [x] 4.1 Add provider-free tests proving degraded pre-build fidelity diagnostics do not prevent `builder_blueprint.json` generation when source/packet artifacts are readable.
  - `test_degraded_with_blocking_findings_allows`: degraded with blocking findings now returns "allowed".
  - All existing `TestBlueprintFidelityPrecheck` tests still pass.
- [x] 4.2 Add tests proving strict review approval remains strict for explicit required-review states.
  - Existing `test_blocked_fidelity_refuses_generation`, `test_failed_fidelity_refuses_generation` still pass.
  - Existing `test_missing_source_graph_refuses_generation`, `test_missing_packet_refuses_generation` still pass.
  - Fidelity review tests (11 tests) all pass unchanged.
- [x] 4.3 Add source classification tests for heading locations, escaped numbered rooms, appendices, prose fragments, NPC-like names, and creature/monster-like names.
  - `TestSourceAtomClassification` (11 tests): heading locations, escaped rooms, appendix filtering, prose fragment rejection, NPC/creature name detection.
  - `TestHeadingClassificationHelpers` (15 tests): unit tests for `_is_heading_location_name`, `_is_map_key_style_heading`, `_is_likely_name`, `_APPENDIX_PATTERN`, `_normalize_heading_text`, `_HEADING_PREFIX_WORDS`.
- [x] 4.4 Add GUI/source-contract tests proving rejected/no-module states do not show success or MMG guidance.
  - `TestGuiStatusGuidanceContracts` (5 tests): blocked, rejected, quarantined, not_publishable, and awaiting_review map to correct non-success phases.
- [x] 4.5 Add regression coverage for the Elden Ring-like source pattern without requiring live provider calls.
  - `_ELDEN_LIKE_SOURCE` fixture provides realistic markdown with: heading locations, escaped rooms, appendix sections, prose fragments, NPC names, and creature names. All tests provider-free.

## 5. Verification

- [x] 5.1 Run targeted Python compile checks for modified files. (PASS)
- [x] 5.2 Run targeted accurate-ingest GUI/unified-flow tests. (233 tests PASS)
- [x] 5.3 Run source classification/fidelity tests. (45 tests PASS in test_builder_blueprint_fidelity_gate.py; 11 tests PASS in test_toolkit_homebrew_fidelity_review.py)
- [x] 5.4 Run publishability/report-agreement tests touched by this flow to prove final gates remain strict. (test_accurate_ingest_numillian_benchmark.py PASS)
- [x] 5.5 Run `openspec validate toolkit-accurate-ingest-prebuild-review-deadlock-closure`. (VALID)

## Files Modified

- `utils/toolkit_builder_blueprint.py` — Changed `evaluate_blueprint_fidelity_precheck()` to allow degraded fidelity through
- `utils/toolkit_source_manifest.py` — Added heading-based locations, escaped heading support, appendix filtering, prose fragment detection, creature name patterns
- `web/extensions/toolkit_homebrew_fidelity_review.py` — Updated `_summarize_blueprint()` and `can_approve_fidelity_review()` to treat degraded blueprints as acceptable
- `web/templates/module_toolkit.html` — Fixed status rendering, MMG guidance gating, rejected/blocked state handling
- `web/routes/toolkit_homebrew_routes.py` — Added "blocked" to terminal status phases
- `scripts/test_builder_blueprint_fidelity_gate.py` — Added 4 regression tests (45 tests total) including blocked terminal/canonical phase, rejected review decision, and blocked build status. Updated existing degraded->refuses test.
