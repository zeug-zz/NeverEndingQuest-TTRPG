# Tasks

## 1. Durable Turn Identity and Receipt Model

- [x] 1.1 Add persisted `turn_id` metadata, exact encounter receipt fields (including an optional reserved `position_deltas` slot), character applied-ID markers, backward-compatible readers/writers, and initial identity/receipt tests in `scripts/test_combat_turn_commit.py`; verify with `.venv/bin/python -m unittest -q scripts.test_combat_turn_commit scripts.test_combat_persistence_phase_stages`.
  Evidence (primary, 2026-10-27): `core/combat/turn_commit.py` assigns UUID `turn_id` on accepted input and computes `applied_id` from the SHA-256 v1 vector; exact receipt schema includes optional reserved `position_deltas`; character `last_combat_applied_id` and legacy readers are covered. Schema updates are present; provider-bound projection allowlists standard message keys so `turn_id`/manifest never reach providers, with an end-to-end recording test; prompt hashes pass 9/9. Tier: sonnet.

## 2. Authoritative Commit and Post-Commit Phase Flow

- [x] 2.1 Stage validated turn effects and route normal and enemy-batch paths through atomic character-first writes followed by one encounter-last receipt write; verify write ordering and failure handling with `.venv/bin/python -m unittest -q scripts.test_combat_turn_commit scripts.test_combat_persistence_phase_stages`.
  Evidence (primary, 2026-10-27): A single character-first/encounter-last commit coordinator serves normal and enemy-batch paths; write budget is unchanged and partial/complete replay tests pass. `utils/xp.main` accepts a staged encounter backward-compatibly. Tier: sonnet.
- [x] 2.2 Derive rounds in Python, commit the final phase/round snapshot with the receipt, then synchronize managers/queues and publish success internally correlated with the same `applied_id` without changing the external payload; verify 1-PC/4-PC transitions, restart handoff, and no pre-commit success with `.venv/bin/python -m unittest -q scripts.test_combat_turn_commit scripts.test_combat_resume_replay_guards scripts.test_combat_manager_decomposition_contract`.
  Evidence (primary, 2026-10-27): Python-derived round/phase is committed in the receipt-bearing write, followed by post-commit sync; success publication is gated after commit and correlated with `applied_id`, with external payload unchanged. C5 contracts are restored with behavioral assertions and byte-identical marker text; combined 2.2 command: 62 OK. Tier: sonnet.
- [x] 2.3 Persist the commit manifest in the existing pre-commit history write for normal and enemy-batch paths and complete pending manifests at combat bootstrap (no provider call, no re-plan), publishing the stored narration under the original `applied_id`; verify with provider-free start_game-level restart tests for every pre-receipt boundary (1-PC/4-PC) plus unchanged write budgets, prompt hashes and G5T write counts using `.venv/bin/python -m unittest -q scripts.test_combat_turn_commit scripts.test_combat_bootstrap scripts.test_combat_g5t_report`.
  Evidence (primary, 2026-10-27): D7 commit manifest is persisted in the existing pre-commit history write; combat bootstrap completes pending manifests without provider calls or re-planning and publishes stored narration under the original `applied_id`. Combined 2.3 command: 80 OK. Tier: sonnet.

## 3. Provider-Free Interruption and Recovery Tests

- [x] 3.1 Add default-off sandbox-only fault injection and provider-free restart tests before the first character write, after each character write, after the encounter write, after phase synchronization, and during/after success publication; verify each pre-/post-restart state, duplicate-effect rejection, 1-PC/4-PC parity, and provider tripwires. Every pre-receipt restart SHALL exercise persisted-manifest recovery through the real `start_game` bootstrap path, not manual `turn_id` reuse; verify with `.venv/bin/python -m unittest -q scripts.test_combat_turn_commit`.
  Evidence (primary, 2026-10-27): `COMBAT_TURN_COMMIT_FAULT_INJECTION_ENABLED=False` by default; `NEQ_COMBAT_FAULT_POINT` is honored only with the flag enabled inside `tmp/combat_capture`. Restart tests at every boundary use real bootstrap recovery, cover 1-PC/4-PC, and make zero provider calls. Tier: sonnet.

## 4. Compatibility and Prompt-Golden Guards

- [x] 4.1 Preserve the existing G1/G3/G4/G5R goldens, compat33 parity, and all nine legacy combat prompt hashes; verify by running each listed module in a separate process (`.venv/bin/python -B -m unittest -q scripts.<module>`). A pre-existing test-isolation issue requires separate processes: `scripts/test_capture_drive.py` installs a permanent fake `updates.update_character_info` module imported by `scripts/test_combat_g5_trace.py`; `core/managers/combat_manager.py` imported `update_character_info` at HEAD line 157.
  Evidence (primary, 2026-10-27): G1 4/4 byte-identical, G3 50/50, G4 pinned identical, prompt hashes 9/9, and gate10 G5T offline re-evaluation byte-identical. The six named suites pass in separate processes; the combined single-process invocation is blocked by the pre-existing isolation issue described above. The 75-process regression baseline is 1432 tests, 0 skipped (`tmp/router-rollout/g7/g7-baseline-results.json`). Tier: primary.

## 5. Primary-Owned G7 Live Gate

- [x] 5.1 After Tasks 1-4 pass, the primary orchestrator SHALL capture both party shapes for completed-turn replay and every approved interruption boundary in a real copy under `tmp/combat_capture/`, using port 8360, `NEQ_OPEN_BROWSER=0`, and the repository venv; restart without reseeding, preserve expected/observed state and receipt evidence under `tmp/router-rollout/g7/<run-id>/`, and verify no duplicate effects before recording the primary `PASS`, `FAIL`, or `BLOCKED` verdict in the owning change.
  Evidence (primary): See `reports/g7-verdict.md` for the adjudicated PASS and review evidence.
