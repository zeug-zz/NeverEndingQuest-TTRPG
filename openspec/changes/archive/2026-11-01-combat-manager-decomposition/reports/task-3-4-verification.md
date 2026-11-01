# Task 3.4 Provider Retry and Validation Verification

Status: **Parent-primary static verification recorded. Task 3.4 is checked; this is not a G3/live verdict.**

## Scope

Task 3.4 extracts provider retry and validation stages while preserving retry policy, validation order, retry context, and provider-call decisions. The implementation owner is `core/combat/turn.py`; the combat loop hands off to the retry stage in `core/combat/combat_manager.py`.

## Parent-primary verification

The primary reports 14 provider-free suites run as separate processes, with 270 tests passing, and nine SHA/diff checks passing:

| Suite | Tests |
|---|---:|
| Retry | 11 |
| Validation | 8 |
| Routing | 11 |
| Phase integrity | 14 |
| Retry hygiene | 3 |
| Truth pack | 6 |
| Prompt authority | 9 |
| Authority | 7 |
| Payload | 4 |
| Lifecycle | 27 |
| Multi-PC | 73 |
| C5 regression | 59 |
| PC-action parser | 28 |
| Decision seam | 10 |
| **Total** | **270** |

The primary verified the retry/validation extraction and handoffs, including preservation of retry policy, validation ordering/context, provider-call decisions, HP and temperature handoffs, and the initial-scene path. No product-code or prompt changes are part of this documentation checkpoint. Static tests do not establish live G3 acceptance.

## Scope note

The current `tasks.md` has Task 3.3 unchecked at line 21, despite the supplied checkpoint instruction describing it as already checked. This report-only checkpoint leaves Task 3.3 unchanged; only Task 3.4 was marked checked.
