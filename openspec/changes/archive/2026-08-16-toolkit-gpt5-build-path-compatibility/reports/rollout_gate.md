# GPT-5.6 Luna Build-Path Compatibility Rollout Gate

- change: toolkit-gpt5-build-path-compatibility
- recorded_on: 2026-08-04
- compatibility_status: pass
- adaptation_prerequisite: ready
- production_adaptation_enablement: not changed

## Safe compatibility evidence

- priority_sites_migrated: 23/23
- included_adjacent_sites_migrated: 5/5
- aggregate_matrix_sites: 28
- helper_reference_sites: 1
- focused_change_local_suites: 9
- focused_change_local_tests: 111
- focused_change_local_skipped: 0
- direct_gpt5_aggregate: pass, 9 tests
- openrouter_aggregate: pass, 12 tests
- strict_openspec_validation: pass

R1 (`utils/toolkit_llm_final_reconciliation.py`) is deferred/external to this
clean baseline because it belongs to the later adaptation work and is absent
from this isolated target. It is not included in the 23 priority calls or
their task-id assertions; no adaptation-only files are added here.

The focused change-local suites covered the final GPT-5 kwargs, OpenRouter
request shape, forbidden sampling parameters, inventory anchors, fixtures,
normalizer, generator, auxiliary toolkit, and Markdown writer contracts.

## Bounded direct provider smoke

Evidence source: `reports/gpt56_luna_build_smoke.json`.

- provider: openai
- model: gpt-5.6-luna
- status: pass
- elapsed_seconds: 2.78
- timeout_seconds: 25
- max_completion_tokens: 64
- max_retries: 0
- usage_prompt_tokens: 37
- usage_completion_tokens: 8
- usage_total_tokens: 45
- unsupported_parameter_error: false
- diagnostics_persisted_api_credential: false
- diagnostics_persisted_raw_source: false
- diagnostics_persisted_raw_response: false

## Legacy accurate-ingest selection

Legacy accurate-ingest remains explicitly selectable and unchanged. The
provider-free legacy contract suites passed as follows:

- suites_passed: 9
- tests_run: 590
- tests_passed: 587
- tests_skipped: 3
- normalizer: `scripts/test_toolkit_homebrew_normalizer.py`
- route and handoff: `scripts/test_toolkit_homebrew_gui_unified_flow.py`,
  `scripts/test_toolkit_homebrew_packet_builder.py`
- publication: `scripts/test_toolkit_module_build_publication_parity.py`
- accurate-ingest contracts: `scripts/test_toolkit_blueprint_v2_contract.py`,
  `scripts/test_toolkit_homebrew_fidelity_review.py`,
  `scripts/test_accurate_ingest_source_graph.py`,
  `scripts/test_accurate_ingest_numillian_benchmark.py`,
  `scripts/test_accurate_ingest_numillian_end_to_end.py`

The route/config assertions confirm that accurate-ingest build modes remain
recognized, the existing accurate-ingest flags retain their current values,
and the legacy path remains selected when blueprint handoff is disabled or
accurate-ingest evidence is absent. No adaptation feature flag, route, model
assignment, module artifact, schema, or prompt was changed here.

Current legacy flag values are recorded for the handoff:

- ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF: true
- ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD: false
- ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK: false
- ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT: false

## Gate decision

The adaptation-builder prerequisite is READY as a change-local rollout marker
only. It is ready because the focused provider-free suites, strict OpenSpec
validation, bounded direct OpenAI GPT-5.6 Luna smoke, and legacy
accurate-ingest selection checks passed. The separate
`toolkit-llm-adaptation-builder` change remains untouched and must own its
feature flag and rollout behavior.
