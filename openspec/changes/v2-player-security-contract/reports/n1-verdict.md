# N1 verdict
**Overall: PASS** (orchestrator-owned, 2026-11-06). Gate N1: unauthenticated and authenticated player negative tests cannot invoke host operations or receive privileged payloads; 1-PC and 4-PC projections and input validation pass. No tunnel, public listener, live gameplay, provider call, or gameplay tester was used; ports 8357 and 8370 had no listener after tests.

## Build identity
- Branch `feature/v2-network`, base HEAD `8a464e0b583d1c38c4c01eb66f10ae118d247587`, worktree dirty (uncommitted N1 change plus N0 archive).
- Python 3.13.18; uvicorn 0.54.0, websockets 17.4, python-socketio 5.18.1, python-engineio 4.15.1. Provider: none.
- Evidence directory: `tmp/router-rollout/v2-network/n1/n1-20261105t161344z/`; Semgrep artifacts: `tmp/router-rollout/v2-network/n1/semgrep/`.

## Focused tests (task 5.1)
- `PYTHONPATH=. .venv/bin/python -m unittest -q scripts.test_player_access scripts.test_player_route_inventory scripts.test_player_capabilities scripts.test_gameplay_sync scripts.test_player_active_pc_revision scripts.test_player_runtime_integration` -> 76 tests OK (rerun after the B101 fix: 76 OK).
- Coverage: credential/session/CSRF/limit negatives (access); positive route/event allowlist equals registrations and every host surface is classified (route inventory); canary privileged values absent from snapshots, events, media and login shell, safe Markdown and image-only bounded media (capabilities); monotonic events, contiguous replay or resync, atomic deduplication, bounded receipts (gameplay sync); revisioned active-PC selection, stale/invalid rejection (active PC revision); at most one enqueue, exact character binding, no cross-PC retarget, echo-before-enqueue, provider/network tripwires (runtime integration).
- 1-PC and 4-PC coverage: `test_projection_allowlists_support_one_and_four_pc_parties`, `test_one_pc_and_four_pc_snapshot_shapes_share_the_same_contract`, `test_single_and_four_pc_party_selection`, `test_accepted_input_is_character_tagged_for_one_and_four_pc_parties`, `test_party_schema_accepts_legacy_and_revisioned_files`.
- `python3 scripts/check_ascii_compliance.py --summary-only` -> 0 violations; `openspec validate v2-player-security-contract --strict` -> valid; `openspec validate --specs` -> 468 passed, 0 failed.

## Host regression (task 4.2 shared paths)
- 64 suites touching changed host paths (1,025 tests) compared against a clean HEAD export at `tmp/n1/baseline/`: 56 pass; the 8 others fail identically at HEAD (no new failures). `test_multi_pc_combat` (75), `test_combat_turn_commit` (26), `test_turn_time_sync` (7) pass individually; their combined-process failures (10 failures, 5 errors) reproduce identically at HEAD (pre-existing test interference).
- Pre-existing failures outside this change: `test_character_sheet_edit::test_edit_button_appears_before_download_pdf`, `test_authoritative_transition_inventory_runtime_reset::test_nig04_to_nig05_validates_from_fresh_module_topology`.

## Security checks (task 5.2)
- `pre-commit run --files` on the player package, tests and changed host files -> ASCII, Gitleaks, Bandit passed.
- `gitleaks dir web/extensions/player` -> no leaks.
- `pip-audit -r requirements-lock.txt --strict` with the three SECURITY.md tornado exceptions (CVE-2026-115927, CVE-2026-116577, CVE-2026-116578) -> no known vulnerabilities, 3 ignored.
- Semgrep (CI packs p/flask, p/bandit, p/python, p/secrets; `--metrics=off --timeout 0`; state under tmp/): scoped to the player package, player tests and changed host files rather than the whole repository (impractical locally with no per-rule timeout; CI full-repo scan remains authoritative). Exit 0, 0 errors, 3 findings: B404 subprocess import in `scripts/test_player_access.py` (test-only, accepted); B101 asserts at `web/extensions/player/app.py:143` and `web/extensions/player/sync.py:156` -> replaced with explicit fail-closed checks (400 invalid_request; resync `invalid_cursor`); recheck of both files: 0 findings, 0 errors.

## Residual risks handed forward
- In-memory active-PC writers (combat) can still overwrite a concurrent locked selection between read and write; pre-existing, recorded for 4.x follow-up in N2.
- Listener startup remains explicit and off by default; no host startup path starts it.
