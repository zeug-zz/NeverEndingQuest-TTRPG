# Task 1.5 Implementation Report

## Scope

Added `utils.llm_runtime.begin_llm_session()`. It lazily imports `utils.llm_router` and `utils.ai_client_factory.reset_fallback_status`, then resets router-local usage stats followed by factory fallback-notification state. It does not construct clients or touch usage trackers, callbacks, or rolling-week history.

The helper is called once at CLI `main.main()` entry, before `setup_utf8_console()` or startup setup, and once at web `web.web_interface.run_game_loop()` entry, before hydration or the first core call. Removed the old import-time `reset_fallback_status()` invocation from `main.py`; the compatibility import remains.

No call was added to `main_game_loop()` or restore recursion. No campaign, turn, validator, save/load, resume, or rolling-week reset was introduced. Function signatures and existing callbacks were not changed.

## Focused Evidence

`scripts/test_llm_runtime_launch_reset.py` arms `scripts.core_chat_test_safety.arm_process_tripwires()` before importing `utils.llm_runtime`. It uses fake router/factory/tracker modules (and patches/restores the parent `utils.llm_router` attribute) to assert lazy import behavior, exact reset call order/count, no tracker reset, and unchanged SHA-256 for a unique week-ledger fixture in a `TemporaryDirectory` under `tmp/`. AST/source assertions cover both launch ordering and restore-loop exclusion. It does not rely on a pre-existing ignored tmp file. The tests never invoke `main()`, `main_game_loop()`, `run_game_loop()`, or a server.

Primary review confirmed the minimal shared begin helper, exactly two launch-entry calls, no import-time reset, restore-recursion exclusion, and the self-contained guarded weekly-ledger fixture. No ignored-file cleanup errors were reported.

## Verification

Primary focused software checks passed in nine separate processes: launch-reset tests (3), runtime-area-hydration tests (14), router tests (88), benchmark profiles (6), GPT-5.4 chat contract (10), GPT-5.4 mini shim (6), GPT-5.6 Luna direct OpenAI contract (41), inventory (9), and request contract (11), totaling 188 tests. Strict OpenSpec validation and the scoped whitespace/diff check passed. Earlier recorded checks also include Python compilation and ASCII compliance (`1140` files scanned, zero violations).

Primary software verification is PASS and task 1.5 is checked in `tasks.md`. No CLI/web/game-loop/server was run, and no live G4 execution or verdict is claimed. Task 1.6, all caller migrations, and G4 work remain pending; planner review remains required.
