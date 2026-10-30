# Task 3.6 Narration/Output and Shared Template Selection

Status: **Parent-primary verification recorded; Task 3.6 checked. No G3/live verdict.**

## Ownership changes

- Added `core/combat/narration.py`, a provider-free owner for the legacy SHA-1 deterministic template selector and immediate output publication.
- Retained `multi_pc.manager._select_deterministic_template` and `combat_pc_action_parser._pick_template` as runtime wrappers, preserving private patch points while delegating both callers to the one selector. The original falsey-value conversion, UTF-8 encoding, template ordering, modulo selection, and empty-list result are unchanged.
- Routed validated turn narration through `publish_combat_narration` at the existing point after round preparation and before `process_combat_action_batch`; helper emits the exact legacy `Dungeon Master: {narration}` line and flushes immediately. Initial-scene and re-engagement output also use the owner; raw initial-response fallback retains its original prefix and content.
- No prompts, model/provider policy, mechanics, persistence, or action publication ordering were changed. No final narration shim was introduced.

## Deterministic parity matrix

`scripts.test_combat_narration` locks expected pre-extraction output for:

| Path | Expected selected output | Result |
|---|---|---|
| Multi-PC attack miss | `Acheron's axe cuts empty air as Goblin slips just outside the strike.` | PASS |
| Multi-PC damage/bloodied | `Goblin reels under Acheron's blow, its defense breaking for a dangerous moment.` | PASS |
| Parser attack miss | `Dungeon Master: Acheron's attack cuts empty air as Goblin slips just outside the strike.` | PASS |
| Parser Magic Missile | `Dungeon Master: Acheron speaks the incantation, and shimmering missiles race unerringly home.` | PASS |
| Parser healing | `Dungeon Master: A warm radiance flows from Acheron into Merisiel, mending injuries.` | PASS |
| Parser movement | `Dungeon Master: Acheron move north.` | PASS |
| Output publication | Same prefixed line; emit precedes flush | PASS |

The focused tests use fake emit/flush callbacks, network tripwires, and `BaseException`-derived write guards. They do not enter the combat owner loop or call the provider SDK.

## Verification

- `scripts.test_combat_narration`: 7/7 PASS.
- Affected suite set: **17 separate processes, 291 tests, 0 failures**. This was rerun for the focused verification repair. It includes parser 28, multi-PC 73, C5 59, lifecycle 27, and persistence 10. The `scripts.test_combat_decomposition_contract` process passed its 9 static prompt hash/dynamic contract checks. `scripts.test_update_encounter_ops_runtime` ran as its own process through an inline isolated runner that mapped only its fixture encounter to `tmp/`, supplied party-tracker state, stubbed unrelated character synchronization/logging, and guarded provider/network/outside I/O; 4/4 passed.
- Added two separate focused processes: narration parity 7/7 and full surrender/exit 4/4 (the 3 existing gameplay assertions plus one import-tripwire regression test). Combined verification: **19 processes, 302 tests, 0 failures**.
- `py_compile` on narration owner, call sites and focused tests: PASS.
- `python3 scripts/check_ascii_compliance.py --summary-only`: PASS, 751 files, 0 violations.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate combat-manager-decomposition --strict`: PASS.
- `git diff --check`: PASS.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest -q scripts.test_combat_surrender_exit_flow`: 4/4 PASS, including all 3 original gameplay cases plus an import-tripwire self-test. Its fixture uses `TemporaryDirectory(dir="tmp")`; the legacy encounter filename is redirected to that one scratch fixture. Optional dependencies are preloaded, then `update_encounter` is lazily imported while the actual factory is patched to return an explicit fake whose `completions.create` raises `ForbiddenSideEffect`. Bytecode writes are disabled for the process and temporarily disabled during guarded import.
- Import-guard regression probes independently show fatal `BaseException` interception for factory invocation, SDK constructor invocation, network socket creation, and file write. Actual module import counters: fake constructors=1; provider attempts=0; network attempts=0; outside writes/campaign reads=0. During surrender operations: provider attempts=0; network attempts=0; outside-scratch file reads/writes=0. The actual `set_status` and `condition_add` operation preparation, application, defeat normalization, schema validation and fixture persistence execute unchanged. Party-tracker read returns only fixture state; non-player character synchronization and module logging are patched, and the sync seam is asserted called.
- The normal-turn source anchor now locates the `while True` that contains `run_combat_provider_retry_stage`, requires exactly one normal validated narration publication inside that loop, checks `narration`/`emit=print`/`flush=sys.stdout.flush` bindings, and checks round metadata -> publication/flush -> action batch -> opening-phase completion -> consolidated updates by AST line order. This excludes initial-scene and resume publications from satisfying the normal-turn assertion. The emit-then-flush unit test remains.
- Incident note: an early full-suite attempt failed with `NameError` after the old setup wrote the root fixture `modules/encounters/encounter_UNITTEST_SURRENDER_EXIT.json`; the old teardown deleted it. Its prior existence was not checked. Whether it existed beforehand is unknown; no restoration is claimed. The final harness used only a unique fixture under project-local `tmp/`, and no later test used the root fixture path.

## Parent-primary bookkeeping

The parent-primary supplied **19 separate processes, 302 tests, 0 failures**, including narration parity (7/7) and surrender/exit (4/4). This evidence closes Task 3.6 only. G3/live acceptance remains incomplete.

## Remaining size gate

AST inspection found one existing owner exception to the package function limit: `core/combat/combat_manager.py::_run_combat_simulation_internal` is 1,531 lines, and its largest `while` body spans 713 lines. All other combat-package functions are at most 600 lines. This task extracted narration publication, not the full initial/re-engagement provider-generation block. A later scoped size-correction task is still needed before the package-wide `<=600` gate can pass; this report does not claim that gate.
