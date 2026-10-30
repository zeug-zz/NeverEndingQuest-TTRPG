# Task 4.3 Implementation Report

## Result

Task 4.3 is complete for primary-scoped software verification. `get_ai_npc_movement_decision` routes through `llm.call(task="updates", json_output=False)` while preserving `attempt`, prompt construction, parsing, and the result shape. Terminal outcomes bypass generic catches and fallbacks and cannot produce or apply a movement decision.

Primary review confirmed the actual facade implementation: `STR` is retained, `updates/temp=0.7/attempt/parser/nonterminal=None` are passed through, both typed terminal guards are in place, the receipt adapter is called once, and the source-helper assertion covers the facade route.

## Verification

Fresh primary-scoped result: **217 tests passed across 12 separate processes**.

| Suite | Tests |
| --- | ---: |
| NPC movement | 6 |
| Transition | 5 |
| Starting location | 7 |
| Semantic operation inventory | 13 |
| Requests | 17 |
| Receipt adapter | 15 |
| Launch reset | 3 |
| Router | 88 |
| Benchmark model profiles | 6 |
| GPT-5.4 chat contract | 10 |
| GPT-5.4 mini shim | 6 |
| GPT-5.6 Luna direct OpenAI contract | 41 |
| **Total** | **217** |

Strict OpenSpec validation, scoped diff/whitespace validation, and no-ignored-cleanup validation passed. The task status is 18/25 change tasks checked; the 15-operation semantic inventory is 15/15 routed with zero legacy operations within that inventory.

## Follow-ups and scope boundaries

- An auxiliary 13-test unguarded incident remains recorded; its required guarded rerun is outstanding. It is not represented as a guarded pass or as part of the 217-test result.
- The old-format source assertion follow-up remains assigned to task 5.1.
- G4 remains pending. No live verification, full-goal completion, or G4 pass is claimed.
- No other task checkbox, golden, incident record, or unrelated artifact is changed by this task report.
