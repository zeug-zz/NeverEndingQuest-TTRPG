# Task 5.2 - Combat Function and Compatibility Shim Size Audit

Status: primary-reviewed scoped size audit PASS. This records the primary's
already-completed source and contract verification; no additional test suite or
runtime execution is claimed here.

## Audit result

The primary used Python's standard-library AST parser, without runtime imports,
on every `core/combat/**/*.py` source file. The audit covered 18 files and 272
functions, including nested and async functions. Zero functions exceed the
600-line maximum.

Largest functions reported by the audit:

| Function | Source | Lines |
|---|---|---:|
| `validate_combat_response` | `core/combat/validation.py:62` | 480 |
| `_run_combat_simulation_internal` | `core/combat/combat_manager.py:2977` | 479 |
| `assemble_combat_context` | `core/combat/prompts.py:352` | 416 |
| `handle_combat_command` | `core/combat/multi_pc/manager.py:653` | 343 |
| `run_combat_provider_retry_stage` | `core/combat/turn.py:719` | 236 |
| `_build_compact_combat_truth_pack` | `core/combat/combat_manager.py:985` | 212 |

The compatibility shim `core/managers/combat_manager.py` is 17 lines, below its
100-line maximum.

## Relevant source-contract verification

The primary separately ran these focused suites, each in its own process:

| Suite | Tests passed |
|---|---:|
| `scripts.test_combat_decomposition_contract` | 9 |
| `scripts.test_combat_manager_decomposition_contract` | 35 |
| `scripts.test_combat_runtime_prompt_authority` | 7 |
| **Total** | **51 across 3 processes** |

Primary reports strict validation PASS and confirms no ignored cleanup was
performed. No claim is made here that this audit ran a 705-test combat baseline,
compile-count check, or additional AST rerun.

## Scope and status

No `main.py` or `process_action` refactor was made or claimed. This report does
not claim live G4, server/campaign, or full-goal verification. Previously
documented incidents remain in their existing reports and are not reclassified
by this audit.

Task accounting after this primary PASS: 20/25 tasks checked, all 15/15
inventoried semantic operations routed, and only tasks 6.1-6.5 pending. This is
scoped task evidence, not a full-goal completion claim.
