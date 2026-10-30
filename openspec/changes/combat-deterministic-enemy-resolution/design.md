# Design

## Context

See `proposal.md` for the motivation and transferred G5 targets. G5 remains a FAIL; its owner disposition D9 transfers the enemy-batch targets without weakening them and requires repeated captures with outcome-normalized no-regression accounting.

The runtime has reusable boundaries rather than needing a replacement combat loop:

- `core/combat/turn.py` and `core/combat/combat_manager.py` own turn-stage execution and persistence dependency construction.
- `core/combat/multi_pc/turn_queue.py` exposes the established initiative order and living non-PC batch roster; `core/combat/multi_pc/manager.py` owns combat state and deterministic narration templates.
- `core/combat/decisions.py` provides typed deterministic decision outcomes; `core/combat/validation.py` owns deterministic prechecks and the existing LLM validation path.
- `core/combat/narration.py` and the `llm.call` router path provide the narration seam. The router remains authoritative for timeout, retries, quota/outage behavior, and terminal provider errors.
- `core/combat/persistence.py` and the existing atomic JSON helpers own state writes. They preserve character-before-encounter ordering, but do not provide a multi-file transaction or turn receipt.
- `utils/combat_latency_trace.py`, `scripts/combat_latency_report.py`, the G5 capture driver, and the existing P1/P4 fixtures provide opt-in trace and live measurement surfaces.

The existing enemy-batch path makes generation and validation calls and writes state by affected file. The G5 evidence records enemy-batch provider counts of 4/2, work-only latency of 22.1/18.9 seconds, and 6/7 raw writes for P1/P4. One stochastic validator rejection explains the P1 call regression; damage to an additional PC explains the P4 phase-write delta. These explanations do not excuse the absolute G5 failures.

## Goals / Non-Goals

**Goals:**

- Resolve a bounded subset of ordinary enemy weapon attacks in Python, planning a complete enemy batch before any mutation.
- Keep the LLM responsible only for narration on eligible batches and preserve the current generate-and-validate behavior for the entire batch whenever an eligibility check fails.
- Keep Python authoritative for attack rolls, target AC, damage, HP, and status; keep narration non-authoritative.
- Preserve the one-PC-party and multi-PC-party runtime, initiative, opening batch, phase/round transitions, death saves, and resume-replay behavior.
- Reuse existing capture infrastructure to judge all transferred absolute targets and comparative no-regression targets with repeated P1/P4 evidence.

**Non-Goals:**

- No expansion into PC action resolution, spells, saving throws, conditions, healing, movement, legendary actions, reactions, or general G8 typed-resolver coverage.
- No Jev implementation, new provider policy, static combat prompt edits, or change to `ENABLE_CHAT_STREAMING`.
- No turn receipts, applied IDs, cross-file transaction, commit-before-publication reordering, or general code-owned round consolidation; except D12's two lifecycle transitions for supported batches. `combat-turn-commit-and-receipts` owns code-owned round advancement for all paths.
- No target positioning/grid inference, tactical threat model, name-based leader inference, or silent broadening of supported attack mechanics.
- No changes to the existing P1/P4 scripted action sequences for G5R.

## Decisions

### D1. Plan an immutable, kind-qualified ledger before applying a batch

The resolver receives the authoritative pre-batch encounter, PC state, monster attack definitions, turn order, and batch identity. It simulates all eligible attacks in a private projection and returns either a complete immutable ledger or one bounded decline result. Each actor and target entry carries both canonical identity and combatant `kind` (`enemy`, `npc`, or `player`) so same-name/cross-kind entries cannot collide. Only enemy actors using supported weapon actions are eligible; a scheduled NPC actor or unresolved identity declines the whole batch.

The seed is deterministic and local to the batch: derive a stable integer from a SHA-256 digest of canonical pre-batch state, encounter ID, round, batch ID/kind, and any fixed capture seed supplied by the fixture. Use a local `random.Random` instance; never use module-global random state. Equal inputs and seed produce byte-equivalent ledger outcomes. No seed or provisional state is persisted.

The ledger records ordered actor/action/target identity, d20 and damage dice, totals, hit/critical result, damage type and amount, before/after HP, and final legal status. Planning never writes files or advances the live turn queue.

### D2. Keep eligibility whole-batch and fail closed

Eligibility is checked for every scheduled non-PC actor and every action before any entry is applied. A later unsupported actor/action invalidates earlier supported work too. Decline reasons are bounded codes, not prose. The runtime then invokes the existing enemy generation-and-validation path unchanged; it does not apply a partial deterministic prefix.

Supported actions are single-target weapon attacks with resolvable authored attack bonus, damage dice, flat damage bonus, damage type, and authoritative target AC. A natural 1 misses; a natural 20 hits and critically hits; other attacks hit at total >= AC. Critical hits roll the authored damage dice twice and add a flat bonus once. Damage expressions must use the explicitly supported dice grammar. Unknown or malformed expressions, missing stats, non-unique identities, attack advantage/disadvantage, resistance/immunity/vulnerability that changes damage, reactions, concentration saves, or any other unmodeled state decline the whole batch.

Eligibility is also declined for spells, saves, conditions, special actions, legendary actions, morale transitions, unsupported NPC attacks, and missing or ambiguous targets. The resolver does not infer mechanics from prose.

### D3. Use explicit multiattack declarations; do not infer from shorthand

`schemas/mon_schema.json` gains an optional `multiattack` array. Each item has exactly `action` (string) and `count` (integer >= 1); additional item keys are rejected. Each action name must match exactly one authored `actions[].name`. The declaration order is the attack order. If no Multiattack action/declaration is present, the resolver performs exactly one attack using the first supported authored attack. A bare `Multiattack` action, an ambiguous name, or a legacy count without an explicit action mapping is unsupported and routes the whole batch to fallback. Attack count is never inferred from the number of `actions` entries.

`schemas/encounter_schema.json` gains an optional boolean `leader` field on a combatant. It is additive and not required for existing encounter files. More than one `leader=true` in an encounter is ambiguous and declines deterministic resolution. No name, CR, faction, or prose inference is permitted.

This favors clear authored intent over shorthand aliases. Schema validation catches malformed new data; runtime eligibility still fails open to the legacy path for malformed data already loaded from older or locally modified files.

### D4. Use interim near-death and leader boundaries; bloodied alone stays supported

At batch start, record a bounded boolean `bloodied` flag for each enemy in the ledger when its HP is positive and at or below half its authoritative maximum HP. Bloodied status alone SHALL NOT decline a batch; narration may describe it. Under this interim rule, only a scheduled enemy with positive HP at or below 25% of its authoritative maximum HP, a designated leader that is dead/defeated/at zero HP, or multiple designated leaders declines the whole batch before mutation. Do not infer a missing leader. This threshold boundary is temporary; intelligent self-preservation belongs to the follow-on `combat-tactical-brain` change.

### D5. Use one narration-only router call; deterministic templates are the only output fallback

After a supported ledger is complete, make one logical `llm.call` using the existing combat-main routing/profile and a new narration-only prompt asset. The request contains bounded ledger facts and scene context, asks for prose only, and does not request actions or mechanics. Do not invoke combat validation for this supported path. Router-owned transport retry remains unchanged; combat adds no retry or second request.

The response is checked against ledger identities and facts. A mismatch, missing response, unparsable response, or contradiction selects deterministic ledger-derived narration composed in ledger order by `build_enemy_batch_template_narration()`, reusing `select_deterministic_template()` and `_build_fast_path_narration()`. It records a bounded reason and makes no second narration or validation call. The template path cannot change mechanics. A router terminal outcome follows existing terminal handling and is not rewritten as successful fabricated narration.

All existing static combat prompt files remain byte-identical. Only a new narration prompt asset is permitted. The exact boundary between harmless descriptive prose and a mechanically false claim must be locked with adversarial provider-free tests before live capture.

### D6. Reuse existing lifecycle and preserve current persistence order

The same eligibility, ledger, narration, and application contract serves `/end` enemy batches and a due DM-group opening batch. It does not own turn progression: existing code clears opening markers, changes phase, and advances rounds as before. PC phase, death-save cadence, initiative, and resume-replay guards remain authoritative and unchanged.

After a complete ledger and accepted/template narration exist, coalesce all attacks per changed PC into one final character projection. Persist each changed character file atomically once, then persist the final encounter projection atomically once, retaining character-before-encounter ordering. In-memory phase, round, and opening-marker changes continue through their existing lifecycle logic but are included in that final encounter projection rather than causing extra supported-batch encounter writes. Unchanged character files are not written. On persistence errors, preserve existing combat error behavior; this change does not invent rollback across files or a new receipt protocol. That partial-commit risk is explicitly handed to `combat-turn-commit-and-receipts`.

### D7. Count physical gameplay/history writes, never helper calls

For G5R, one write is one physical atomic write to one gameplay or history file caused by the batch. A helper that writes three files contributes three writes. The trace identifies each write with the batch ID, a bounded target kind, and an opaque run-local target ID; it does not emit absolute paths. Capture evidence and combat trace output are not gameplay/history writes. The absolute target remains <= 3 raw writes per batch, regardless of outcome normalization. With the D10 write set, raw writes are exactly one combat-history file, one encounter file, and N changed PC files (2 + N); the absolute target passes only when N <= 1. If N >= 2, report FAIL for that batch without a waiver. Consolidated party-state persistence is an owner-decision follow-up outside this change.

### D8. Keep resolver activation off by default and trace decisions observationally

Add `DETERMINISTIC_ENEMY_RESOLUTION_ENABLED = False`. When disabled, use the current generate-and-validate path. It may be enabled only after an orchestrator-reviewed G5R PASS and a separate explicit rollout decision; setting it false is the rollback. Every batch decision emits a bounded decision event with `decision_point=enemy_batch_resolution`, `decision_source` in the existing enum, `decision_outcome` in the new bounded enum, and an allowlisted reason code. Batch stage, provider, decision, and file-operation events share the existing run-local `batch_id` shape. Trace failures fail open and never affect a decision or write.

For a supported batch, `provider_call_avoided` means the resolver avoided the old mechanics-generation and validation work. It does not hide the single narration provider event. A whole-batch fallback reports `llm_fallback`; disabled routing reports its disabled outcome. No Jev event is introduced.

### D9. G5R is repeated, fixed-identity, and outcome-aware without waiving raw targets

Reuse the current G5 before bundles as the comparison reference and the existing P1/P4 Capture_Arena action scripts unchanged. Capture three unique G5R runs per party shape with the same provider/model (`direct OpenAI gpt-6-luna`), fixture/script identity, seed, and measurement method. Preserve every run under `tmp/router-rollout/g5r/<run-id>/` before teardown and retain per-run deviations. Any missing identity, timeout, cap, degraded required evidence, or resolver-ineligible batch leaves the affected gate BLOCKED, not PASS.

The absolute targets remain unchanged: exactly one narration provider call and zero validation provider calls for every supported batch; median batch work-only time <= 15.0 seconds (15000 ms), computed from the three run-level observations; and <= 3 raw gameplay/history writes for each batch. Report raw provider counts and write counts for every run. Do not let the median hide a per-run absolute-call or write miss.

Keep the existing comparative thresholds: P1 action work-only p50 <= 1.10 times its matched before p50; P1 provider-call and write no-increase; P4 round-1 work-only improvement >= 30%; and no phase provider-call/write increase. For comparative deltas only, normalize provider calls by subtracting the delta in provider requests explicitly attributed to post-rejection stochastic validator retries. Normalize write deltas by subtracting the delta in distinct PC character-file targets changed by enemy-batch damage. This formula was confirmed for the artifact plan. Keep raw deltas alongside normalized deltas; no other call/write category is normalized. Missing attribution blocks the comparison. The raw <=3 write target and exactly-one-supported-batch-call target are never normalized.

Compare each three-run party-shape median against its existing matched G5 before bundle; use the pre-recorded G5 threshold/operator and do not silently substitute a different reference. The primary orchestrator reviews the evidence and assigns PASS, FAIL, or BLOCKED. A provider-free report or successful driver exit is not a live verdict.

### D10. Persist one pre-apply batch transcript, then PCs, then encounter

For each supported batch, assemble the batch's user-turn input (including its `/end` instruction where applicable) and final accepted or templated narration into one conversation-history payload and persist that history file exactly once using the existing atomic JSON write helper. `core/combat/turn.py` currently saves input/context before provider generation, and `core/combat/combat_manager.py` saves the final assistant response before processing actions; the supported path defers/coalesces those batch-attributed writes rather than persisting them separately. Apply any batch-local history cleanup/compression in memory before this single write. Existing XP/exit history-writing paths in `core/combat/persistence.py` are outside supported enemy batches; if an input/outcome would require those additional writes, keep it on the existing fallback path. Place this single history write after narration acceptance/template selection and immediately before gameplay-state persistence. This is the existing pre-apply transcript checkpoint: `utils/combat_phase_integrity_precheck.py` reads conversation history as part of already-applied replay checks, so keep history-before-state placement for resume/replay semantics. Then atomically persist each changed PC character file once and persist the final encounter projection once. The final encounter projection includes any existing in-memory round/phase/opening-marker transition so it is not written separately within a supported batch. The required order is history, changed PCs, encounter; character-before-encounter order is preserved. This does not introduce transactionality or receipts.

Under this exact write set, the raw batch count is `1 history + N changed PC files + 1 encounter = 2 + N`. Therefore the unchanged raw <=3 G5 target passes only when N <= 1; N >= 2 is a per-batch FAIL. Do not suppress required PC writes or normalize this absolute count. A future consolidated party-state persistence approach is owner-decision territory outside this change.

### D11. Derive normalization attributes provider-free from bundle evidence

The provider-free G5R report derives distinct damaged-PC targets from per-PC HP differences between the `step-NNN-before` and `step-NNN-after` snapshots around each enemy-batch step in the bundle's `snapshots/` directory. It derives validator-rejection retry provider requests from receipts/trace by counting `combat_main` attempts that follow a failed `combat_validation` in the same batch. Apply only these derived attributes to the approved D9 comparative normalization and retain raw values. If any required attribute cannot be derived from either side of a comparison, mark that comparison BLOCKED and stop for owner/planner review; never invent attribution or substitute zero.

### D12. Scope code-owned lifecycle transitions to supported batches

Only a fully supported deterministic batch may use these two lifecycle cases. For a PC-phase `/end` batch, Case A requires `roundStartsWith` to be `pcGroup` (defaulting to `pcGroup`) and `openingEnemyBatchPending` to be false. Read authoritative round R from `combat_round` (falling back to `current_round`), derive R+1 in code, and invoke the existing `apply_reported_round_transition` with the parsed response `{"combat_round": R+1}`. Its injected `save_json` captures encounter/history payloads in memory rather than writing them; any boundary-compressed history is bound and included in the batch's single history write. The resulting encounter projection is included in the batch's single encounter write.

For a DM-group opening batch, Case B requires `openingEnemyBatchPending` to be true, `roundStartsWith` to be `dmGroup`, and the multi-PC manager to be in `ENEMY_PHASE`. Do not increment the round. Apply `complete_opening_enemy_batch` semantics (clear the opening marker and set `pc_phase_complete` false) using a captured, non-writing `save_json`; include the resulting encounter projection in the batch's single encounter write.

Any other or inconsistent lifecycle state, including `/end` with `roundStartsWith=dmGroup` or an opening marker inconsistent with the manager phase, declines the entire deterministic batch with bounded reason `round_transition_unsupported` and routes the original response through the existing generate-and-validate path. The legacy path retains model-reported `combat_round` unchanged. This is not a general round-advancement redesign; all-path code-owned round advancement remains with `combat-turn-commit-and-receipts`.

## Risks / Trade-offs

- **False eligibility or missed mechanics** -> Keep the allowlist narrow, require complete pre-batch planning, and route any unknown fact to whole-batch fallback. Add negative tests for every decline boundary.
- **Target rotation is deterministic but tactically simple** -> Preserve established turn order and avoid target-name heuristics or position inference; accept the narrow behavior only for this bounded resolver.
- **Narration check misses an indirect contradiction** -> Keep narration non-authoritative, use adversarial fixture responses, and fall back to deterministic ledger prose on any detected mismatch. No second call is permitted.
- **Near-death or leader signal makes fixed captures ineligible** -> Record eligibility per run and do not count a fallback run as resolver acceptance. Bloodied-only enemies remain eligible; confirm the unchanged fixture produces supported batches before consuming live captures.
- **The three-write target fails when multiple PCs take damage** -> D10 yields exactly `2 + N` raw writes. Retain all required writes; report FAIL when N >= 2. A consolidated party-state persistence design requires an owner decision outside this change.
- **Cross-file partial persistence** -> Retain existing ordering and error behavior; do not claim transactionality. The future commit-and-receipts change owns receipts, replay idempotency, and cross-file commit protocol.
- **Historical G5 outcome metadata may be insufficient** -> Keep raw values and block normalized comparison unless retry and damaged-PC attribution can be proven from the reference evidence.
- **Trace overhead or failure** -> Gate tracing, keep fields bounded, and ensure instrumentation is fail-open and excluded from gameplay write counts.

## Migration Plan

1. Author provider-free schema, resolver, fallback, narration-check, persistence, trace, and report tests. Keep the resolver flag off and do not make provider calls.
2. Add optional schemas and runtime eligibility. Preserve compatibility for encounters/monsters without the new optional fields; malformed loaded data falls back rather than crashing.
3. Integrate supported resolution and narration-only request behind the default-off flag. Keep the legacy whole-batch path intact and verify static combat prompt bytes did not change.
4. Extend G5 tooling with the isolated `g5r` selector and three-run report. Prove G1/G3/G4 and existing G5 report behavior unchanged when G5R is not selected.
5. Before live capture, prove fixture eligibility, derive D11 attributes from the four existing G5 bundles, and verify the raw write accounting. If outcome metadata is unavailable or the absolute target is impossible, stop with BLOCKED/FAIL evidence rather than weakening the target.
6. The primary captures three P1 and three P4 G5R runs, reviews the evidence, and records PASS/FAIL/BLOCKED. Keep the shipped flag OFF until primary-reviewed PASS plus a separate rollout decision.
7. Hand off commit receipts, partial-write recovery, and round consolidation to `combat-turn-commit-and-receipts`; do not implement those mechanisms here.

### Rollback

| Surface | Rollback boundary |
|---|---|
| Resolver integration | Set `DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=False`; supported and unsupported batches use the existing generation-and-validation path. |
| Multiattack and leader fields | Remove the new optional declarations from authored data if necessary; legacy files remain valid because both fields are optional. Do not reinterpret malformed values as executable attacks. |
| Narration | Disable the resolver rather than adding a second provider call; terminal router behavior remains unchanged. |
| Trace/report/capture | Do not select G5R; preserve existing G5/G1/G3/G4 defaults, outputs, and evidence roots. |
| Persistence | Retain existing atomic character-before-encounter ordering; do not attempt cross-file rollback without the separately scoped receipt protocol. |

## Open Questions for Planner / Owner

None. D10 resolves history-write placement and the raw write consequence; D11 defines provider-free outcome attribution and its BLOCKED stop condition.

## Phase 6 Handoff

`combat-turn-commit-and-receipts` owns commit-before-publication, durable turn receipts, applied IDs, replay/idempotency redesign, cross-file recovery, and code-owned round advancement for all paths. This change only produces a complete in-memory ledger, applies it through existing atomic files in the existing character-before-encounter order, and verifies established lifecycle outcomes are preserved. The sole exception is D12: supported batches derive the PC-phase `/end` round increment and opening-batch completion in code, while unsupported/legacy batches retain existing model-reported lifecycle behavior.
