# V2 Narrative Track (Cohesion Spine)

Status: Working architecture track (in progress)
Date: 2026-03-09
Owner: NEQ v2 narrative architecture

## Purpose

Provide one execution spine across v2 planning docs so continuity, world narrative, memory, EGO, and Titan work advance in a single ordered track with shared vocabulary.

This document is planning-level only. It intentionally does not replace implementation specs.

## Shared Terms (Canonical)

- `continuity_contract`: Module-level continuity payload emitted by ingest.
- strict mode: missing required continuity keys fail closed.
- warn-first mode: soft continuity issues are warnings and do not block publish.
- interpreted state: narrative pressure/state that never mutates mechanical truth.
- mechanical truth: Python-enforced gameplay state.
- proposal/apply lifecycle: interpreted world updates are proposed, reviewed, then applied.
- narrative seed atoms: world narrative units used for long-horizon continuity and world pressure interpretation.
- approval gate: human facilitator review step that must pass before draft artifacts become canonical.
- Ralph loop: iterative proposal -> Python validation -> human approval loop that prevents hallucinated canon writes.
- seed DB: pre-built world-narrative database (`data/world_narrative_seed.db`).

## Prime Directive (Locked for v2)

1. Python is the world reality authority.
   - Mechanical truth is always enforced by Python state and schema-validated persistence.
   - LLM outputs are interpreted proposals until approved and validated.

2. Runtime LLM creative flexibility is required.
   - Raw prose inputs should be transformable into ingestable structure with fantasy-horror creative flair.
   - The entire gameplay narrative development should remain dynamic as it evolves through live play in reaction to indeterministic tabletop PC party inputs.
   - LLM runtime interpretation should continuously adapt narrative framing, interactions, and follow-on hooks while staying grounded to Python mechanical truth.

3. Approval gate first.
   - No direct auto-canon writes from runtime LLM drafts in initial rollout.
   - Canon updates occur only after facilitator review and validation pass.

4. Ralph loop is the safety control surface.
   - Every narrative draft iterates through Python reality checks before apply.
   - Failed checks quarantine the draft and return deterministic remediation guidance.

## Current Baseline (Implemented)

The initial continuity substrate is operational:

1. Ingest emits and persists `continuity_contract`.
2. Sidecar audit validates continuity payload shape.
3. Readiness gate includes continuity checks.
4. Bulk validation reports continuity outcomes, including summary counts.

Required continuity keys in v1 baseline:
- `continuity_version`
- `entry_state_variants`
- `cross_module_refs`
- `standalone_fallback`

## V2 Phase Map

Phase 1: Continuity Substrate (DONE)
- Scope: ingest/readiness/sidecar/bulk continuity contracts.
- Outcome: deterministic module continuity gate now exists.

Phase 2: World Model and Memory Lift (IN PROGRESS)
- Scope: map module continuity signals into world narrative interpretation inputs from the external seed DB.
- Outcome target: continuity-aware world model proposals without mechanical writes.

Phase 2B: Companion Relationship Memory Lift (PLANNED)
- Scope: absorb the remaining unfinished NPC companion-memory work into the v2 memory/retrieval architecture after the live file-backed Phase 2A stopgap.
- Outcome target: DB-backed relationship retrieval for companion NPC <-> PC continuity, with active-PC-aware bounded prompt projection and a single canonical relationship event model.
- Hard guardrails:
  - v2 SHOULD reuse the useful semantics proven in the live Phase 2A path, but MUST NOT keep deepening the legacy file-backed stack.
  - Relationship retrieval MUST distinguish group continuity from specific-PC edges without forcing attribution when evidence is ambiguous.
  - Any richer parser/crystallizer adoption MUST flow into the common memory architecture, not create another parallel long-lived subsystem.
  - Operator-facing diagnosis/rebuild tooling for companion state MUST align with the same v2 memory truth model.

Phase 3: EGO and Titan Runtime Bridge (PLANNED)
- Scope: consume continuity and interpreted world signals in Titan/EGO cycles.
- Outcome target: proposal-only world pressure updates with fail-open runtime behavior.

Phase 4: Builder and Module Feedback Loop (PLANNED)
- Scope: module builder consumes approved pressure and writes provenance-safe continuity seeds.
- Outcome target: ongoing LLM-assisted world-building loop with review boundaries.

Phase 5: Governance and Observability Hardening (PLANNED)
- Scope: policy gates, auditability, rollback, cost/latency envelopes.
- Outcome target: safe long-horizon adaptation pipeline.

## Plan Ownership Matrix

- `plans/archive/ingest-module.md`
  - Owns: historical ingest/watcher operational flow and continuity payload emission behavior (archived reference).
- `plans/version-2/module-import.md`
  - Owns: high-volume import pipeline and any-order readiness policy.
- `plans/version-2/world-narrative.md`
  - Owns: interpreted world model architecture, seed DB consumption, retrieval contracts, campaign world model lifecycle.
- `plans/version-2/memory.md`
  - Owns: retrieval/storage contracts, companion relationship-memory migration after live Phase 2A, and memory-layer integration with continuity quality signals.
- `plans/version-2/narrative-sovereignty-post-gametest.md`
  - Owns: post-gametest continuation of reconcile-first runtime architecture after G1-G4, including event-ledger and prompt-reset sequencing before OpenRouter migration.
- `plans/version-2/CNS build/EGO.md`
  - Owns: bounded adaptive control architecture and write-surface policy.
- `plans/version-2/titan-integration.md`
  - Owns: umbrella runtime integration design for Titan cycle architecture.
- `plans/version-2/titan-retune-execution-order.md`
  - Owns: implementation sequencing, dependency ordering, and retune gates.
- `plans/version-2/encounterEscalationProfile.md`
  - Owns: deterministic combat encounter scaling policy for over/under-level world roaming, including cap-safe elite composition and staged reinforcement behavior.

## Dependency Chain

1. Continuity substrate (already done) ->
2. seed DB populated (`data/world_narrative_seed.db`) ->
3. world-narrative + memory interpreted contracts ->
4. companion relationship memory lift (DB-backed relationship retrieval + companion-state unification) ->
5. post-gametest narrative-sovereignty continuation (event ledger + prompt reset) ->
6. OpenRouter router re-architecture ->
7. EGO/Titan runtime bridge ->
8. module-builder continuity pressure integration ->
9. governance hardening.

## Companion NPC Memory Integration Notes

The archived `plans/archive/npc-memory.md` live-stack plan is now split across:

1. already-landed live fixes (`npc-memory-parser-hardening`, `tt-npc-memory-relationship-edges`), and
2. future v2 memory architecture work.

Within this narrative spine, companion NPC memory work belongs inside the wider memory/world-model track rather than as a separate ad hoc subsystem. The v2 carry-forward scope is:

- relationship retrieval for companion NPC <-> PC continuity from `data/memory.db`,
- unification of legacy companion-memory semantics with the canonical event/link model,
- bounded active-PC-first relationship projection from retrieval rather than raw file packets,
- and operator-safe diagnosis/rebuild flows that explain ambiguous, sparse, degraded, or malformed companion states.

This keeps NPC memory enhancements embedded in the same Ralph-loop, approval-gated, Python-truth-respecting architecture as the rest of the v2 narrative system.

## Next Milestone

Stand up world-narrative seed DB consumption:

1. Bootstrap: copy/merge `data/world_narrative_seed.db` tables into runtime `data/memory.db` on first run.
2. Retrieval: bounded query helpers for inspiration atoms, alignment profiles, and mythic conflicts.
3. World model bootstrap: LLM composes `campaign_world_model` v1 from seed DB data.
4. Draft the first v2 companion relationship retrieval contract so the archived NPC-memory follow-on work has a clear home in the common memory architecture.

## Exit Criteria

This narrative track is considered cohesive when:

1. All listed plans reference this spine and use shared terms.
2. No plan contradicts strict/warn continuity behavior.
3. No plan allows interpreted layers to bypass Python mechanical truth.
4. Titan/EGO phases explicitly consume continuity outputs as quality inputs.
5. Builder integration remains proposal/apply and provenance-safe.
6. Seed DB consumption path is deterministic at bootstrap.
7. Companion NPC relationship continuity is owned by the shared memory architecture rather than a permanently separate legacy subsystem.

## Working Note

OpenSpec implementation sequencing is intentionally deferred for now, per current architecture-in-progress workflow. This file is the planning alignment anchor until execution sequencing resumes.
