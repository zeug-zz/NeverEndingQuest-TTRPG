# Design

## Context

See `proposal.md` for the motivation and scope. G6 routes production chat through the router. The router already records response-derived actual/estimated/unpriced provenance and task/model totals; the session/week tracker owns time-window rollups and existing image cost-only events, while Debug `token_update` currently reads that tracker. The current tracker can apply a blended estimate to chat with no reported cost, so G10 must pass router provenance into the existing session/week aggregation without creating a second ledger. Capture tooling currently defines G7 and G9 but no G10 profile/evaluator.

### Current-source removal audit

The following inventory was checked against current Python source before any removal was listed:

| Candidate | Current reference evidence | Design decision |
|---|---|---|
| `model_config.AVAILABLE_MODELS` | Repository grep finds only its definition at `model_config.py:313`. | Remove as unused selection data. |
| `ai_client_factory.is_thinking_enabled`, `get_task_complexity`, `get_model_for_task` | Repository grep finds only the three definitions in `utils/ai_client_factory.py`; there are no imports or calls. | Remove these unused selector helpers. |
| `scripts/migrate_to_openrouter.py` | No active source import or invocation exists outside the script itself; other matches are historical documentation. | Remove the retired migration script. |
| `main.py` import of `get_chat_model_name` | In `main.py`, the only match is the import at line 210. | Remove this stale import only. Keep the helper because other current modules call it. |
| `model_config.THINKING_ENABLED_TASKS` | It aliases `COMPLEX_TASKS` at `model_config.py:292`; active references are in the old factory selector, the router's compatibility fallback, and an alias assertion in `scripts/test_llm_router.py`. One archived fixture also references it. | Replace the active references with `COMPLEX_TASKS`, then remove the alias after a fresh active-source reference search is empty. Do not describe it as currently unused; do not edit archived artifacts. |
| `OPENROUTER_STRATEGY`, `OPENROUTER_CHAT_MODEL`, `OPENROUTER_FULL_MODEL`, `OPENROUTER_MINI_MODEL`, and `get_model_config` | The old factory selector uses these constants; `OPENROUTER_CHAT_MODEL` also feeds `get_chat_model_name`. Production callers still use `get_model_config` in `core/memory/session_diary.py`, `core/memory/players_diary.py`, `core/memory/story_so_far_compiler.py`, `utils/character_creation_audit.py`, and `utils/toolkit_homebrew_normalizer.py`. | Do not remove or rename these live symbols in this change based on the present inventory. A new audit is required before any future deletion. |
| `core/validation/character_validator_backup.py` | The current worktree records it as deleted, consistent with the G6 removal. | Excluded; do not re-plan it. |

The audit prevents dead-code cleanup from silently expanding into active model-selection migration. Archived artifacts and frozen history are not updated to preserve a retired alias or migration tool.

## Goals / Non-Goals

**Goals:**

- Keep response-level provenance owned by the router and session/week aggregation owned by the existing tracker.
- Present one reconciled view through `/usage` and Debug without double-counting chat or dropping media cost events.
- Extend the existing Capture_Arena tooling only enough to evaluate the G10 full-session evidence contract.

**Non-Goals:**

- Replacing the existing tracker, adding a new router or capture runner, or changing provider activation/configuration.
- Changing image/audio transport, game mechanics, prompt content, Titan runtime, Jev, or party-size gates.

## Decisions

### Preserve the router/factory ownership boundary

Use the router receipt as the authoritative source for each chat response's requested/resolved model, token usage, cost amount, provenance, and completeness. Keep client construction, actual-provider detection, request-parameter finalization, and fallback-notification state in the existing factory. Remove only the audited dead selector helpers/data and stale import. The alias is replaced by its identical canonical list before deletion so task-tier behavior is unchanged.

The simplest alternative, deleting the entire legacy model-selection family, is rejected: current production callers still invoke `get_model_config`, so its constants and helper are not unused. Migrating those live call sites would exceed the evidence-based cleanup scope and risks changing request/model behavior.

### Reconcile chat events through the existing session/week tracker

Extend the existing receipt-to-tracker path so chat events carry the router's trusted actual/estimated/unpriced facts. A chat response with an actual cost is recorded once; only a verified estimate from the matching concrete response model contributes an estimated amount; an unpriced response retains tokens and increments incompleteness without adding a fabricated amount. Session/week known-cost totals are the sum of actual and estimated amounts. Existing media cost-only tracking remains intact and continues to contribute cost without chat tokens.

Do not add the router's aggregate totals on top of already-forwarded chat events. The router snapshot supplies router-local counts and breakdowns to `/usage`; the existing tracker supplies session/week windows to `/usage` and Debug.

The simpler alternative, leaving chat on the legacy blended estimator and displaying only a dominant source label, is rejected because it hides unpriced calls and can disagree with router receipts. A separate accounting ledger is also rejected because it would duplicate session/week and media aggregation.

### Keep `/usage` and Debug read-only projections

Implement `/usage` as a read-only game command that snapshots router statistics and tracker rollups. It does not call a provider, mutate campaign state, or reset counters. Extend the current Debug `token_update` payload additively with the provenance subtotals, unpriced counts, and completeness required by the specs; keep existing token fields and rendering defaults.

### Extend the existing G9 capture path for G10

The `llm-router-g10-verification` delta defines the evidence and ownership contract. Add G10 profiles and offline evidence checks to the existing fixture registry, seeder, socket driver, and evaluator; do not create a new runner. The required live matrix is one bounded full-session run per party shape (1-PC and 4-PC), covering narration, combat, save, restart/resume, `/usage`, and Debug accounting. Each run uses a real copy under `tmp/combat_capture/`, port 8360, `NEQ_OPEN_BROWSER=0`, and the repository venv, with its complete bundle under `tmp/router-rollout/g10/<run-id>/`.

The offline evaluator may report readiness only. The primary orchestrator reviews expected versus observed session state, usage provenance, transcript, owned-server log, and save/resume evidence, then records PASS, FAIL, or BLOCKED. Exit status, degraded output, fake transport, or builder results cannot substitute for the primary verdict.

### Keep implementation verification provider-free

Focused router, tracker, command, UI, and capture-evaluator tests use injected responses and no external provider. Run each `.venv/bin/python -m unittest -q scripts.<module>` command in a separate process. Preserve the G1/G3/G4/G5R golden and nine prompt-hash checks; no cleanup task changes prompt bytes or installed provider defaults.

## Guidance Layer (SHOULD)

- SHOULD reuse the existing receipt observer, session/week tracker, `token_update` contract, and Capture_Arena tools rather than introduce parallel ownership.
- SHOULD keep provider-free readiness checks distinct from primary-owned live evidence review.

## Risks / Trade-offs

- [Legacy chat tracking may apply its blended estimate in addition to router provenance] -> Carry receipt cost provenance into the existing tracker event and assert exactly-once totals for actual, estimated, and unpriced responses.
- [Removing the alias makes historical archived tests that import it non-runnable] -> Update active tests to use `COMPLEX_TASKS`; do not add a compatibility shim or rewrite archived artifacts.
- [G10 evidence may be incomplete or degraded] -> Keep the gate incomplete and let the primary record FAIL or BLOCKED; never infer PASS from process exit or synthetic evidence.

## Migration Plan

1. Before any cleanup implementation, verify that `openspec/changes/llm-router-openrouter-activation` records primary-owned G9 PASS with accepted evidence. If not, stop without starting implementation tasks.
2. Remove only the current-source-audited dead helpers/data, stale import, and retired migration script. Replace the alias's active references with `COMPLEX_TASKS`, then confirm no active reference remains before deleting the alias.
3. Pass response provenance through the existing observer/tracker path, preserve media cost events, and expose the same session/week facts through `/usage` and additive Debug payload fields.
4. Add and provider-free test G10 support in the existing Capture_Arena path; update durable documentation only for the resulting behavior and ownership.
5. Run focused provider-free tests, 1-PC/4-PC save-resume regressions, and golden/hash checks before the primary starts live G10.
6. The primary runs both G10 captures in isolated copies, preserves bundles before teardown, reviews expected/observed evidence, and records the verdict. Rollback is limited to Build 8 changes; do not undo G9 activation or change the installed provider default.

## Open Questions

None. The live-source inventory is explicit; currently referenced selection symbols are retained rather than guessed away.
