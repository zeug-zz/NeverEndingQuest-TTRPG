# Task 4.1 Scoped Combat Hygiene

Status: **Task 4.1 implementation and parent-primary verification complete.**

## Reference audit and removals

- Repository-wide source/importer/test search of the deprecated candidate `update_json_schema` found the function definition, its `core.combat.__all__`/lazy export, and no call sites. It remains exported as a compatibility surface, so it is not a proven-removable private function.
- The callback APIs `temporary_combat_manager`, `temporary_combat_callback`, `reset_combat_state`, and `set_combat_callback` remain. Package exports and compatibility tests reference them; multi-PC tests also exercise manager/callback contexts and reset behavior.
- No function was removed. This is the safe audit result, not a cleanup quota.

## Exception handling and control flow

- Replaced all bare `except:` blocks found in `core/combat/combat_manager.py` and `core/combat/prompts.py`. Module/path fallback failures now log their exception before the existing fallback; usage-tracking failures log and remain non-fatal; malformed round-marker conversion catches only `TypeError`/`ValueError` and emits a debug diagnostic.
- No bare handler or swallowed `BaseException` remains in `core/combat/`. Stable `[COMBAT_LOOP]` diagnostic lines, including the EOF line, are retained verbatim.
- `/quit`, `/exit`, and EOF produce a typed `FastCommandResult` with `control_action`, `status`, `reason`, and `exit_code`. The combat owner returns immediately at that boundary, before any later provider stage. The legacy public `run_combat_simulation(...)` adapter maps the exit result to its existing `(None, None)` tuple shape; its `finally` still releases the encounter claim, while `run_combat_simulation_session(...)` still unwinds its manager context. No process exit callback, `sys.exit`, built-in `exit`/`quit`, or `os._exit` remains in the combat package. Existing encounter-load/init failure paths still return without entering the provider loop; pending encounter state is not cleared by this change.

## Focused verification

Separate processes:

| Suite/check | Result |
|---|---|
| `scripts.test_combat_manager_decomposition_contract` | 31 tests passed; typed command outcome, legacy tuple adapter, claim release, exception propagation, stable diagnostics, no process-exit/bare-handler AST scan, and pre-provider early-return ordering covered |
| `scripts.c5_regression_combat` | 59 tests passed |
| `scripts.test_multi_pc_combat` | 73 tests passed |
| `scripts.test_combat_narration` | 7 tests passed |
| `scripts.test_combat_surrender_exit_flow` | 4 tests passed |
| `py_compile` (commands, owner, prompts, focused test) | PASS |
| ASCII compliance | PASS, 751 files / 0 violations |
| `git diff --check` | PASS |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate combat-manager-decomposition --strict` | PASS |

The focused suites do not call the owner loop or a live provider. No campaign fixture was created. The surrender/exit test uses its existing unique `tmp/` fixture contract. Parent-primary verification for Task 4.1 reports **306 tests across 19 separate processes, all passing**, including lifecycle (31), C5 (59), multi-PC (73), narration (7), and surrender/exit (4). The parent also reviewed the no-bare-handler/no-process-exit audit, structured quit/EOF outcomes, legacy tuple adapter, and finally-based encounter-claim release. This is 4.1 evidence only; it is not G3/live evidence or a size-gate claim. Task 4.2 remains unchecked.

## Remaining boundaries

- Task 4.1 is checked in `tasks.md` with parent-primary verification evidence; Task 4.2 remains unchecked.
- The known `_run_combat_simulation_internal` owner remains 1,531 lines. This task does not claim the pending size gate or decomposition phase is complete.
- No prompt, model/provider, retry policy, schema, `main.py`, `action_handler.py`, mechanics, or unrelated code was changed.
