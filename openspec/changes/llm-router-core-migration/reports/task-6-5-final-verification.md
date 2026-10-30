# Task 6.5 - Final Verification (2026-10-23)

Primary-run results are recorded in `tmp/router-rollout/g4/final-6-5-results.json`. This report records those results; this documentation task ran no tests or live work.

## Commands

Module suites used one process per module with the pattern:

```text
PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g4/final65-pycache .venv/bin/python -B -m unittest -q <module>
```

The script-form facade run used:

```text
.venv/bin/python -B scripts/test_llm_router.py
```

## Results

Each listed process returned status 0 and `OK`.

| Group | Module or command | Tests | Status |
|---|---|---:|---|
| facade-script | scripts/test_llm_router.py (script form) | 88 | PASS |
| baseline | scripts.c5_regression_combat | 60 | PASS |
| baseline | scripts.test_action_predictor_params_contract | 5 | PASS |
| baseline | scripts.test_benchmark_model_profiles | 6 | PASS |
| baseline | scripts.test_capture_drive | 63 | PASS |
| baseline | scripts.test_character_update_model_params | 3 | PASS |
| baseline | scripts.test_character_validator_params | 2 | PASS |
| baseline | scripts.test_combat_bootstrap | 29 | PASS |
| baseline | scripts.test_combat_canonical_validation_facts | 3 | PASS |
| baseline | scripts.test_combat_compression_params | 5 | PASS |
| baseline | scripts.test_combat_decisions | 10 | PASS |
| baseline | scripts.test_combat_decomposition_contract | 9 | PASS |
| baseline | scripts.test_combat_encounter_ops_contract | 27 | PASS |
| baseline | scripts.test_combat_expanded_deterministic_guards_contract | 16 | PASS |
| baseline | scripts.test_combat_latency_baseline | 24 | PASS |
| baseline | scripts.test_combat_manager_decomposition_contract | 36 | PASS |
| baseline | scripts.test_combat_narration | 7 | PASS |
| baseline | scripts.test_combat_narration_consistency_precheck | 13 | PASS |
| baseline | scripts.test_combat_payload_hygiene | 4 | PASS |
| baseline | scripts.test_combat_pc_action_parser | 29 | PASS |
| baseline | scripts.test_combat_persistence_phase_stages | 12 | PASS |
| baseline | scripts.test_combat_phase_integrity_precheck | 23 | PASS |
| baseline | scripts.test_combat_resume_replay_guards | 8 | PASS |
| baseline | scripts.test_combat_retry_hygiene | 3 | PASS |
| baseline | scripts.test_combat_retry_stage | 15 | PASS |
| baseline | scripts.test_combat_runtime_prompt_authority | 7 | PASS |
| baseline | scripts.test_combat_save_concentration_contract | 20 | PASS |
| baseline | scripts.test_combat_state_coherence_repair | 10 | PASS |
| baseline | scripts.test_combat_structured_ops_contract | 16 | PASS |
| baseline | scripts.test_combat_surrender_exit_flow | 4 | PASS |
| baseline | scripts.test_combat_trace_observation_writer | 3 | PASS |
| baseline | scripts.test_combat_truth_pack | 8 | PASS |
| baseline | scripts.test_combat_validation_routing | 11 | PASS |
| baseline | scripts.test_combat_validation_stage | 17 | PASS |
| baseline | scripts.test_gpt54_chat_params_contract | 10 | PASS |
| baseline | scripts.test_gpt54_mini_chat_params_shim | 6 | PASS |
| baseline | scripts.test_gpt56_luna_direct_openai_contract | 41 | PASS |
| baseline | scripts.test_llm_router | 88 | PASS |
| baseline | scripts.test_multi_pc_combat | 74 | PASS |
| baseline | scripts.test_update_character_ops_contract | 21 | PASS |
| baseline | scripts.test_update_encounter_ops_runtime | 5 | PASS |
| baseline | scripts.test_validator_truth_pack | 5 | PASS |
| affected | scripts.test_llm_runtime_receipt_adapter | 15 | PASS |
| affected | scripts.test_llm_runtime_launch_reset | 3 | PASS |
| affected | scripts.test_core_chat_inventory_contract | 14 | PASS |
| affected | scripts.test_core_chat_request_contracts | 17 | PASS |
| affected | scripts.test_initiative_tracker_router_migration | 7 | PASS |
| affected | scripts.test_starting_location_router_migration | 7 | PASS |
| affected | scripts.test_transition_router_migration | 5 | PASS |
| affected | scripts.test_npc_movement_router_migration | 6 | PASS |
| affected | scripts.test_combat_summary_router_migration | 6 | PASS |
| affected | scripts.test_runtime_area_hydration | 14 | PASS |
| affected | scripts.test_scene_follower_transition_sync | 14 | PASS |
| affected | scripts.test_authoritative_transition_inventory_runtime_reset | 9 | PASS |

The five facade suites are explicitly accounted for: `test_llm_router.py` passed in both script and module forms (88 tests each); `test_benchmark_model_profiles` passed (6); `test_gpt54_chat_params_contract` passed (10); `test_gpt54_mini_chat_params_shim` passed (6); and `test_gpt56_luna_direct_openai_contract` passed (41). The module-form router run is part of the baseline group.

Totals: 54 separate processes, all status 0 / OK; 88 tests in facade-script, 758 in baseline, and 117 in affected suites. The 41 baseline processes include the historical 705-test set plus later-added suites; module counts are identical to prelive, with zero drift.

## Static checks

| Check | Result |
|---|---|
| `python3 scripts/check_ascii_compliance.py --summary-only` | PASS, 773 files scanned, 0 violations |
| `git diff --check` | PASS |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` | PASS |

## Side-effect observations

- The gitignored `scripts/__pycache__/capture_evidence.cpython-313.pyc` was regenerated by the documented seeder/driver run at 22:57.
- Gitignored `modules/logs/game_debug.log` received one DEBUG line from a test process, the same pattern as prior baseline runs.
- Installed `party_tracker.json` is unchanged since 2026-09-22.
- No other files outside `tmp/` were modified except the OpenSpec ledger/report documentation.

## Scope

Task 6.5 is complete and, with task 6.4, the G4 gate for `llm-router-core-migration` is complete. Historical baselines, incidents, and goldens remain unchanged. No live work was performed in this task. Retained phase-5 HTTP 400 temperature diagnostics remain out of scope for this change.
