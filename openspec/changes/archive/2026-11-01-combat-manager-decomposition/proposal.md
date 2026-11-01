# Combat Manager Decomposition

## Why

Combat behavior is concentrated in oversized manager modules, including a 2,594-line main combat loop, which makes the approved router migration difficult to review and safely target. This change creates navigable ownership boundaries before combat call sites migrate, while preserving the current combat contract.

## What Changes

- MUST introduce the combat-owned `core/combat/` package and `core/combat/multi_pc/` subpackage, retaining old manager import paths as compatibility shims.
- MUST move the existing implementation into focused modules before extracting it into smaller ownership units; a renamed monolith is not completion.
- MUST make a session object own encounter, multi-PC manager, history, active PC, and phase state, replacing mutable combat globals and literal-index conversation-history rewrites with state-derived payload construction.
- MUST expose nine named responsibility stages, including a single PC-action decision seam whose `declined` and `unavailable` outcomes remain distinct and both continue through the existing LLM path, while preserving the validated legacy execution, mutation, persistence, and publication order.
- MUST preserve existing multi-PC facade, state, turn queue, sync, DM-note, narration, public API, old-path monkeypatch compatibility, and lifecycle-isolation behavior through stable APIs or deliberate shims.
- MUST preserve prompt/static/dynamic text byte-for-byte and make no gameplay, mechanics, persistence protocol, provider, or latency-policy changes.
- MAY make only the separately approved, strictly necessary corrections to the dynamic validation context and its explanatory instructions: committed Python state is distinct from proposed candidate changes/operations, candidate-derived `touchedChanges` are not authoritative truth-pack state, and source-backed canonical non-PC attack/stat facts may be supplied as read-only validation context. This is a narrow extraction byte-parity exception; unrelated prompt bytes, all generation prompt bytes, and all other extraction parity remain mandatory.
- MUST limit each combat-package function to 600 lines or fewer and keep `core/managers/combat_manager.py` below 100 lines after shimming.
- MUST clean only verified dead functions and unsafe library-exit/error/logging paths, retaining diagnostic strings used as regression anchors.
- MUST update source-contract test anchors to the new module ownership without weakening assertions.
- MUST extend the existing Capture_Arena seeder/driver/fixture/report helpers only as needed for bounded named G3 scenarios and evidence checks, with provider-free tooling tests before the primary orchestrator runs the live matrix.
- MUST close G3 only after primary-owned 1-PC/4-PC capture evidence covers initiative outcomes, death saves, roster/enemy batches, surrender/exit and completed-turn resume replay; missing coverage, required timeouts or degraded required evidence cannot PASS.
- MUST retain G3 strict rejection checks for all 18 required cases, keep failed bundles as FAIL, and rerun affected cases as primary-owned evidence. This amendment does not implement G7 or alter schema, public returns, mechanics, order, retries, or fail-open policy.
- MUST add the bounded, evidence-only causal linkage and mechanical reconciliation correction described by Task 4.7 through the existing Capture_Arena rig; preserve default latency inputs/order and do not add runtime gameplay behavior or a second runner.
- MUST add the narrow inventory-container explanation and opt-in bounded enemy-routing rejection diagnostic described by Task 4.8 without changing routing policy, inventory mechanics, or precheck behavior.
- MUST add the narrowly authorized Task 4.9 validation-context authority corrections: clause/recipient-aware rejection of proven non-enemy prose mutations, a code-identified complete enemy-batch handoff path that still requires full semantic validation, and bounded flat operation diagnostics. This does not add mechanics, schema, resolver, or validation framework behavior.
- MUST add the narrow, evidence-only Task 4.10 HP-ledger extension described in `design.md` and the existing hygiene spec: capture bounded read-only HP evidence around the existing encounter updater and use it only for causally complete checker proof. It does not waive missing operation evidence or change gameplay, persistence, callbacks, provider policy, or the 18 live checks.

## Capabilities

### New Capabilities

- `combat-session-package-ownership`: Defines combat package/shim behavior, session ownership, lifecycle isolation, and compatibility of the public and monkeypatch surfaces.
- `combat-turn-stage-contract`: Defines the nine-stage turn boundary, explicit state-derived handoff, and decision seam outcomes.
- `combat-behavior-hygiene-parity`: Defines behavior/prompt parity, cleanup boundaries, and the bounded primary-owned G3 capture coverage/evidence needed to verify decomposition.

### Modified Capabilities

- `tt-combat-manager-gate-isolation`: Update the explicit phase-one normalization ownership requirement to allow implementation ownership to move with the combat package while retaining the old public import/API and all initiative and marker behavior. This is required because the existing spec currently pins the implementation to the legacy shim path.

## Impact

- Affected implementation surfaces: `core/managers/combat_manager.py`, `core/managers/multi_pc_combat.py`, `core/managers/combat_state_sync.py`, `core/managers/initiative_tracker_ai.py`, `utils/combat_pc_action_parser.py`, runtime importers, and combat regression/source-contract tests.
- New package surfaces are under `core/combat/` and `core/combat/multi_pc/`; old paths remain compatible.
- Test-tooling scope also includes `scripts/seed_combat_capture.py`, `scripts/capture_drive.py`, existing `scripts/combat_latency_fixtures.py`/report helpers and focused provider-free `scripts/test_capture_drive.py` coverage. Preserve default fixed latency scripts and extend the existing rig, not a second runner or generalized framework.
- The 4.7/4.8/4.9 amendment is limited to the existing rig/evidence reporting, bounded trace-gated diagnostics, and necessary validation-context authority corrections. It does not revise the 18 live rejection checks, the unchecked 5.3/5.4 gates, or any recorded live verdict. The primary-owned `20261016T225308.339122Z` review remains FAIL; prior rejected-response effects are not acceptance evidence.
- No product dependencies, added product provider operations, persistence protocol, prompts or model settings change. Verification seeds/writes only isolated sandbox state and evidence under `tmp/`; normal live gameplay calls do not turn tooling tests into provider-backed tests. The primary orchestrator owns live execution and the final verdict.
- Shared 1-PC and multi-PC combat paths are affected: both party shapes must retain their current behavior, with 1-PC as the regression floor and multi-PC coverage required.
