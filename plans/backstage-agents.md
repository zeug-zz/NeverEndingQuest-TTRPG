# Backstage Agentic Harness Plan

**Status:** Draft for review  
**Created:** 2026-05-24  
**Scope:** Add supervised backstage agentic harnesses for writer, builder, audit, memory, and RATIO workflows while preserving the live runtime rule: Python enforces reality; LLM interprets it.

---

## Executive Summary

NEQ-TTRPG already acts as a strong live LLM harness: the live narrator and combat LLMs propose structured output, Python validates it, and Python executes durable state changes. That architecture should not be replaced with autonomous gameplay agents.

The next useful evolution is a separate set of **backstage agentic assistants**. These assistants can use ReAct-style observe/reason/propose/validate loops for slow, bounded, reviewable work:

- Audit and diagnosis.
- Module building and repair.
- Journal and Story So Far writing.
- Memory curation and backfill.
- RATIO between-session analysis and prompt/spec/test proposals.

The live runtime remains single-turn and guardrail-heavy. Backstage assistants may loop, inspect artifacts, draft patches, run deterministic validators, and prepare review artifacts, but they do not directly mutate live gameplay truth.

Target shape:

```text
Backstage assistant:
  observe -> reason -> propose -> validate -> summarize -> await approval/apply

Live runtime:
  player input -> bounded narrator/combat LLM -> Python validation -> Python execution
```

Core principle:

> Backstage agents may reason creatively, but every durable change must pass through Python validation, provenance, and approval.

Initial build order:

- First build a read-only accurate-ingest audit assistant for the Numillian recovery workflow.
- Keep the first slice report-only and deterministic-artifact-driven.
- Extract a broader shared harness only after the read-only audit MVP proves the shape.

---

## Non-Goals

This plan does not propose:

- Turning the live narrator into an autonomous agent.
- Turning combat mechanics into agent-controlled state mutation.
- Letting an LLM directly write character, party, module, or encounter state during live play.
- Importing a large generic framework before NEQ-specific harness primitives exist.
- Allowing unbounded tool loops, hidden retries, or undocumented state mutation.
- Replacing OpenSpec, existing validators, readiness gates, or publication gates.

---

## Terminology

### Backstage Agentic Harness

A supervised control loop for non-live workflows. It can inspect files, logs, reports, and validation output; reason over them; generate draft prose or patch proposals; run validators; and stop at explicit approval gates.

### Assistant

A specialization of the backstage harness for one workflow domain: audit, builder, writer, memory, or RATIO.

### Durable Change

Any change that persists beyond the current assistant run:

- File edits.
- Prompt edits.
- OpenSpec artifacts.
- Module JSON changes.
- Memory DB mutations.
- Generated publication artifacts.
- Tooling behavior changes.

### Evidence Bundle

The exact source files, reports, logs, test output summaries, and state snapshots used by an assistant. Every proposal must identify its evidence bundle.

### Proposal Artifact

A structured assistant output containing findings, proposed changes, validation plan, risks, and approval requirements.

---

## Architectural Position

NEQ should borrow the ReAct loop pattern, not generic framework behavior.

Recommended pattern:

```text
Domain-specific loop + NEQ validators + OpenSpec + provenance + review gates
```

Avoid early dependency on:

- LangChain agents.
- AutoGPT-style autonomous goal loops.
- General tool registries with broad filesystem write access.
- Recursive LLM self-correction without deterministic stop conditions.

NEQ already has strong domain-specific primitives:

- `openspec/` workflow.
- Module readiness and publishability audits.
- Accurate-ingest benchmark reports.
- Source graph and fidelity artifacts.
- Character and party state hygiene.
- Travel and NPC validation guards.
- Journal and memory tables.
- Runtime chat monitor and rejected-turn diagnostics.

The backstage harness should compose these existing surfaces rather than bypass them.

---

## Autonomy Levels

Every assistant run must declare one autonomy level.

| Level | Name | Permissions | Intended Use |
|---|---|---|---|
| L0 | Read-only | Inspect and summarize only. No generated patch. | Memory Doctor, first audit pass, RATIO diagnosis. |
| L1 | Draft | Generate prose or proposal artifacts only. No source edits. | Story So Far drafts, RATIO proposal drafts. |
| L2 | Patch proposal | Generate patch plan or patch artifact. Human/apply step required. | Builder repair proposal, prompt edit proposal. |
| L3 | Safe auto-apply | Auto-apply deterministic, low-risk changes after validation. | Formatting, cache refresh, report regeneration, metadata refresh. |
| L4 | Forbidden | Direct live gameplay or mechanical state mutation. | Not allowed in this plan. |

Initial default:

- Audit Assistant: L0, then L2.
- Builder Assistant: L2.
- Writer Assistant: L1.
- Memory Assistant: L0, then L2 for additive repairs.
- RATIO Assistant: L0, then L1/L2 proposals only.

---

## Shared Harness Foundation

### Target Module

Create a small custom harness rather than adopting a full framework first.

Candidate package:

```text
core/agents/backstage/
  __init__.py
  contracts.py
  runner.py
  evidence.py
  proposals.py
  validators.py
  approval.py
  replay_log.py
```

The package name can change during OpenSpec design, but the boundary should remain explicit: these are backstage agents, not runtime narrator agents.

### Shared Run Contract

Every assistant run should produce a JSON artifact similar to:

```json
{
  "assistant_type": "audit|builder|writer|memory|ratio",
  "task_id": "string",
  "autonomy_level": "L0|L1|L2|L3",
  "status": "draft|validated|blocked|approved|applied|failed",
  "created_at": "iso8601",
  "inputs": [],
  "evidence": [],
  "findings": [],
  "proposals": [],
  "validation": [],
  "approval_required": true,
  "approval_reason": "string",
  "budgets": {
    "max_steps": 0,
    "max_tool_calls": 0,
    "max_llm_calls": 0,
    "timeout_seconds": 0
  },
  "replay_log_path": "string"
}
```

### Evidence Contract

Each evidence item should identify:

- `source_type`: file, report, command_summary, db_query, indexed_doc, user_instruction.
- `path` or command label.
- Content hash when applicable.
- Timestamp.
- Read mode: full, excerpt, summary, structured parse.
- Why it was relevant.

Do not copy large source bodies into proposal artifacts. Store paths, hashes, and compact summaries.

### Proposal Contract

Each proposal should identify:

- Problem statement.
- Evidence references.
- Proposed files or DB surfaces.
- Change type: prose, JSON data, prompt, spec, test, generated artifact, memory repair.
- Risk class.
- Required validators.
- Whether human approval is required.
- Whether OpenSpec is required before implementation.

### Validation Contract

Validation should be deterministic wherever possible.

Examples:

- `openspec validate <change>`.
- `openspec validate --specs`.
- `.venv/bin/python core/validation/validate_module_files.py --module <slug>`.
- `.venv/bin/python scripts/audit_module_publishability.py --module <slug> --json`.
- `.venv/bin/python scripts/benchmark_accurate_ingest.py --module <slug> --json`.
- `.venv/bin/python -m unittest -q <test_module>`.
- ASCII compliance checks for changed Python files.

LLM self-critique can be used as an advisory check, but it must never be the only validation gate for durable changes.

### Replay Log Contract

Every assistant run should leave a replayable trace:

```text
data/agent_runs/<assistant_type>/<task_id>/
  run.json
  evidence.json
  proposal.json
  validation.json
  replay.jsonl
```

The exact path can be adjusted, but runtime state and generated logs must be gitignored unless explicitly promoted as docs/test fixtures.

### Budget Controls

Each run must enforce:

- Max observe/reason/propose steps.
- Max LLM calls.
- Max validator attempts.
- Max wall-clock runtime.
- Stop on repeated identical failure.
- Stop on schema/contract violation.
- Stop on ambiguous write authority.

Default MVP budgets:

| Assistant | Max Steps | Max LLM Calls | Max Validator Runs | Timeout |
|---|---:|---:|---:|---:|
| Audit | 6 | 2 | 4 | 5 min |
| Builder | 10 | 4 | 6 | 10 min |
| Writer | 8 | 3 | 3 | 8 min |
| Memory | 6 | 2 | 3 | 5 min |
| RATIO | 8 | 3 | 2 | 8 min |

---

## Assistant 1: Audit Assistant

### Purpose

Diagnose module, runtime, or tooling failures by reading existing reports and validators, grouping blockers by domain, and producing actionable findings.

### Why Build First

Audit is lowest-risk and highest-leverage. NEQ already has strong validators and report artifacts. An audit assistant can orchestrate those outputs without writing anything.

### MVP Scope

L0 read-only module publishability diagnosis.

Inputs:

- `toolkit_build_report.json`.
- `validation_report.json`.
- `accurate_ingest_benchmark_report.json`.
- `monster_closure_report.json`.
- `module_media_generator_report.json`.
- `llm_classification_cache.json` if present.
- CLI output from readiness, publishability, semantic, and benchmark scripts.

Outputs:

- Blocker summary by domain.
- Probable source files.
- Suggested validators/tests.
- Optional L2 patch proposal in later phase.

### Domains

- Schema and required fields.
- Topology/connectivity.
- Semantic authority.
- Monster authority and hydration.
- Scene entity contract.
- Media coverage.
- Source fidelity.
- Publication gate composition.
- Homebrewery summary generation.

### MVP Loop

```text
1. Collect known reports for module.
2. Run publishability audit in JSON mode.
3. Run semantic audit if module has semantic artifacts.
4. Run source-fidelity benchmark if accurate-ingest artifacts exist.
5. Group findings by blocker class.
6. Emit read-only report and suggested next steps.
```

### Later Capabilities

- L2 repair proposal generation.
- Compare previous and current reports.
- Detect stale report freshness markers.
- Generate OpenSpec proposal skeleton for systemic failure classes.

### Safety Rules

- No file edits in MVP.
- Do not suppress blockers.
- Do not create waivers.
- Do not reinterpret a failed deterministic gate as pass.

---

## Assistant 2: Builder Assistant

### Purpose

Help module generation and repair across source graph, blueprint, module JSON, media, validation, and publication artifacts.

### Scope

The builder assistant should improve source-faithful module creation and remediation, especially for accurate-ingest workflows.

It does not replace `core/generators/module_builder.py`. It works around and above existing ModuleBuilder orchestration by preparing evidence, proposing bounded patches, and validating results.

### Sub-Assistants

| Sub-Assistant | Responsibility |
|---|---|
| Entity Resolver | NPC/location/monster/source-name reconciliation, alias proposals. |
| Topology Repairer | Connectivity, area graph, map parity, cross-area edges. |
| Source Fidelity Reviewer | Compare source graph and benchmark to output module. |
| Media Planner | Missing portraits, monsters, thumbnails, MMG queue. |
| Publication Finisher | Readiness/publishability closure sequencing. |

### MVP Scope

L2 source-fidelity repair proposal for a single module.

Inputs:

- Source graph artifacts.
- Accurate-ingest benchmark report.
- Module context and area BU files.
- Toolkit build report.
- Publishability audit output.

Outputs:

- Proposed patch plan with evidence refs.
- Specific files likely needing edits.
- Validators to run after patch.
- Human approval requirement.

### Builder Loop

```text
1. Inspect source graph and benchmark fixture.
2. Inspect generated module artifacts.
3. Compare source-required NPC/location/puzzle/lore/tone items to module output.
4. Identify missing or degraded preservation.
5. Propose bounded repairs.
6. Validate proposed domain with deterministic scripts where possible.
7. Stop at approval unless changes are L3 deterministic refreshes.
```

### Allowed Proposal Types

- Add aliases from source evidence.
- Improve descriptions from source excerpts.
- Add missing source-backed NPC role/faction/prose fields.
- Add source-backed location clues and DM guidance.
- Add media queue entries.
- Regenerate reports.
- Add regression fixture for discovered bug.

### Forbidden Proposal Types Without Separate OpenSpec

- New canonical schema fields.
- New module topology not backed by source or deterministic graph repair.
- New puzzle rules not backed by source.
- New monster authority without source/module evidence.
- Removing validation gates.
- Waiving source-fidelity blockers.

---

## Assistant 3: Writer Assistant

### Purpose

Generate player-facing and DM-facing narrative documents from confirmed facts, with factual consistency checks.

Primary future target:

- Journal and Story So Far LLM harness.

Secondary targets:

- Homebrewery adventure prose.
- Module summaries.
- Session recaps.
- Player guide refreshes.

### Writer Harness Model

```text
facts -> outline -> prose draft -> factual consistency check -> final document
```

### MVP: Story So Far Draft Harness

Inputs:

- Confirmed diary entries only.
- `party_tracker.json` current state.
- Module context and plot progress.
- Scene follower state.
- Major memory events with provenance.
- Combat summaries marked historical-only.

Outputs:

- Draft Story So Far text.
- Source entry IDs used.
- Time range covered.
- Mechanical consistency check result.
- Final PDF/markdown only after validation.

### Critical Constraints

- Draft diary entries are excluded from confirmed Story So Far output.
- Dead PCs remain dead unless resurrection action exists.
- Current HP, conditions, slots, status, and location truth come from Python state.
- Off-location NPCs/followers cannot appear as present unless scene follower or transition state supports it.
- The writer can add literary framing, but cannot create new canon events.

### Writer Loop

```text
1. Build factual timeline from confirmed sources.
2. Detect gaps, contradictions, or missing provenance.
3. Generate outline.
4. Generate prose draft.
5. Run factual consistency validator.
6. Revise once if contradictions are found.
7. Emit final draft or blocked report.
```

### Factual Consistency Validator

Initial validator can be deterministic plus advisory LLM:

- Deterministic checks for PC life state, current location, follower presence, known module names.
- Advisory LLM check for unsupported event claims.
- Final authority remains deterministic source truth.

### Later Capabilities

- Multiple style profiles: chronicle, campfire tale, terse journal, DM recap.
- Per-PC viewpoint summaries.
- Player-safe spoiler filtering.
- Campaign volume compilation from confirmed diary checkpoints.

---

## Assistant 4: Memory Assistant

### Purpose

Curate, diagnose, and repair memory without corrupting canon.

This assistant should be conservative. Memory is supporting context, not mechanical truth.

### MVP: Memory Doctor

L0 read-only diagnostic assistant.

Inputs:

- `data/memory.db` query summaries.
- `journal.json`.
- `party_tracker.json`.
- `scene_followers.json`.
- Companion memory state.
- Role transition events.

Outputs:

- Duplicate aliases.
- Unresolved entity links.
- Missing provenance.
- Contradictory life-state memories.
- Stale follower assumptions.
- Relationship edge drift.
- Suggested additive repair records.

### Memory Loop

```text
1. Inspect entity and alias tables.
2. Inspect event provenance and links.
3. Compare memory claims to current authoritative state.
4. Cluster duplicates and contradictions.
5. Propose additive corrections or supersession records.
6. Stop at approval.
```

### Hard Rules

- Do not delete memories automatically.
- Prefer additive correction, supersession, or deprecation markers.
- Every memory mutation requires provenance.
- Current mechanical state beats memory prose.
- Memory cannot revive, kill, relocate, recruit, or dismiss entities by itself.

### Later Capabilities

- Backfill review assistant for imported campaigns.
- Companion relationship edge summarizer.
- Entity alias merge proposal workflow.
- Memory compression quality audit.
- Memory portability package verifier.

---

## Assistant 5: RATIO Assistant

### Purpose

Perform slow, between-session analysis of recurring LLM/runtime failures and propose prompt, spec, test, or architecture changes.

RATIO is not a live controller in this plan. It is a supervised analyst.

### Inputs

- Rejected narrator turn logs.
- Validation retry telemetry.
- WorldObserver divergence classifications.
- Chat monitor logs.
- User corrections.
- Test failures.
- Provider fallback and timeout telemetry.
- Prompt/runtime source files.
- OpenSpec changes and main specs.

### Outputs

- Failure clusters.
- Root-cause hypotheses.
- Minimal prompt patch proposal.
- Validator rule proposal.
- Regression test proposal.
- OpenSpec change draft.
- ADR or AGENTS update recommendation.

### RATIO Loop

```text
1. Collect rejected turns and validation failures for a time range.
2. Cluster by failure domain and repeated language pattern.
3. Map each cluster to prompt/runtime/spec/test surfaces.
4. Propose the smallest durable fix.
5. Generate regression test suggestion.
6. Stop at human approval.
```

### Allowed Outputs Initially

- Read-only report.
- OpenSpec proposal draft.
- Prompt patch proposal.
- Test plan.
- AGENTS/ADR update suggestion.

### Forbidden Initially

- Automatic prompt edits.
- Automatic schema edits.
- Automatic runtime code edits.
- Live adaptive tuning.
- Session-time intervention.

### Later Integration with EGO

After passive EGO classification is mature:

```text
EGO observes and classifies live divergence.
RATIO clusters and proposes between-session improvements.
Human/agent review approves durable changes.
Python validators prove safety before merge.
```

---

## Phased Implementation Plan

### Phase 0: Current Preservation Prerequisite

**Goal:** Finish the active deterministic accurate-ingest preservation chain before adding backstage automation.

Tasks:

- Finish NPC preservation.
- Finish location preservation.
- Repair the current puzzle preservation regression.
- Re-run benchmark and publishability gates.
- Keep backstage assistant implementation out of the current Numillian NPC/location preservation slice.

Exit criteria:

- Current Numillian preservation change is green or otherwise explicitly closed.
- Deterministic reports are stable enough to serve as audit evidence.
- `plans/accurate-ingest-fix.md` identifies the follow-up read-only audit slice.

### Phase 1: Initial Read-Only Accurate-Ingest Audit Build

**Goal:** Build the first backstage assistant as a read-only accurate-ingest auditor.

Tasks:

- Create OpenSpec change `toolkit-accurate-ingest-backstage-audit-mvp`.
- Add a narrow audit entrypoint for one module.
- Collect existing deterministic artifacts:
  - `accurate_ingest_benchmark_report.json`
  - `toolkit_build_report.json`
  - `validation_report.json`
  - `source_fidelity_report.json`
  - `build_fidelity_report.json`
  - Publishability audit JSON.
- Run existing publishability/benchmark scripts in read-only mode where needed.
- Group findings by source-fidelity, build-fidelity, validation, readiness, and publishability domains.
- Emit a report-only assistant artifact with evidence references and recommended next step.
- Add fixture tests proving no module artifacts are mutated.

Exit criteria:

- The assistant can audit `The_Hidden_City_of_Numillian` without file edits.
- The output identifies blockers/regressions from existing reports.
- The output is compact enough for developer review.
- Tests prove the assistant does not create waivers, weaken gates, replace scripts, or enter the live ModuleBuilder generation loop.

### Phase 2: Harness Skeleton Extraction

**Goal:** Extract shared runner contracts from the read-only audit MVP.

Tasks:

- Add `core/agents/backstage/` package if the MVP proved the need.
- Generalize run schema, evidence schema, proposal schema, validation result schema, and replay log format.
- Implement budget enforcement.
- Implement evidence collection helpers.
- Implement replay log writer.
- Implement validator command wrapper that records concise summaries.
- Implement approval state handling for future write-capable assistants.
- Add unit tests for budget stop, replay logs, schema validation, and approval gating.

Exit criteria:

- The read-only accurate-ingest auditor still works through the extracted contracts.
- A no-op assistant can run L0 and produce a valid `run.json`.
- Budget limits are enforced.
- Replay logs are deterministic enough for debugging.

### Phase 3: General Audit Assistant MVP

**Goal:** Broaden read-only module publishability diagnosis beyond accurate-ingest recovery.

Tasks:

- Add Audit Assistant entrypoint.
- Collect module reports.
- Run publishability audit in JSON mode.
- Group blockers by domain.
- Emit read-only proposal artifact.
- Add tests with fixture reports.

Exit criteria:

- Audit Assistant can diagnose one module without edits.
- It identifies readiness vs publishability vs source-fidelity blockers.
- It produces a compact report suitable for developer review.

### Phase 4: Builder Assistant MVP

**Goal:** Source-fidelity repair proposal for one module.

Tasks:

- Add Builder Assistant entrypoint.
- Read source graph, benchmark, module context, BU areas, and reports.
- Compare required source entities to module output.
- Generate L2 repair proposal only.
- Run relevant deterministic checks.
- Add tests with Numillian-style fixture gaps.

Exit criteria:

- Builder Assistant can propose bounded source-backed repairs.
- It does not auto-edit module files.
- It flags when OpenSpec or human review is required.

### Phase 5: Writer Assistant MVP

**Goal:** Fact-bounded Story So Far draft workflow.

Tasks:

- Add Writer Assistant entrypoint.
- Build confirmed diary timeline input.
- Generate outline and draft.
- Add deterministic factual consistency checks for PC status, location, follower presence, and known module entities.
- Store draft artifact separately from confirmed output.
- Add tests for dead-PC, off-location follower, and draft-diary exclusion cases.

Exit criteria:

- Writer Assistant generates a draft from confirmed facts only.
- Contradictions block finalization.
- Existing diary/PDF flow remains fail-open.

### Phase 6: Memory Doctor MVP

**Goal:** Read-only memory diagnostics.

Tasks:

- Add Memory Assistant L0 entrypoint.
- Query memory DB summaries safely.
- Detect duplicate aliases, unresolved links, missing provenance, and likely stale contradictions.
- Emit additive repair suggestions only.
- Add tests with temp memory DB fixtures.

Exit criteria:

- Memory Doctor produces useful diagnostics without DB writes.
- It never deletes or mutates memory.

### Phase 7: RATIO Analyst MVP

**Goal:** Between-session rejected-turn clustering and proposal generation.

Tasks:

- Add RATIO Assistant entrypoint.
- Read rejected narrator turns, validation telemetry, and chat monitor summaries.
- Cluster repeated failure domains.
- Propose prompt/spec/test changes as drafts.
- Optionally create OpenSpec scaffold in L2 with explicit user approval.
- Add fixture tests for clustering and proposal contract.

Exit criteria:

- RATIO produces reviewable proposals, not direct edits.
- It maps failure clusters to concrete prompt/runtime/spec surfaces.

### Phase 8: Controlled L3 Auto-Apply

**Goal:** Allow narrowly deterministic auto-apply where safe.

Candidate L3 operations:

- Regenerate stale reports.
- Refresh benchmark report after source artifacts are unchanged.
- Normalize generated assistant artifact formatting.
- Update non-authoritative cache artifacts.

Rules:

- L3 operations must be explicitly allowlisted.
- L3 operations must run validators afterward.
- L3 operations must be reversible or regenerable.
- L3 operations must never change live gameplay state.

Exit criteria:

- At least one L3 operation is implemented and tested.
- Approval gates still protect non-allowlisted writes.

---

## OpenSpec Scaffold Summary

The following OpenSpec changes are recommended. Create them incrementally, not all at once, unless a fast-forward planning pass is desired.

### 1. `toolkit-accurate-ingest-backstage-audit-mvp`

Purpose:

- Add the first backstage assistant as a read-only accurate-ingest auditor for the Numillian recovery workflow.

Likely specs:

- `accurate-ingest-backstage-audit-inputs`
- `accurate-ingest-backstage-audit-report`
- `accurate-ingest-backstage-audit-readonly-safety`
- `accurate-ingest-backstage-audit-script-parity`

Acceptance highlights:

- Reads existing benchmark, build, validation, source-fidelity, build-fidelity, and publishability artifacts.
- May run existing audit scripts in read-only mode.
- Produces an evidence-backed blocker/regression summary and next-step recommendation.
- Produces no module artifact edits, no waivers, no gate weakening, and no live ModuleBuilder loop integration.

### 2. `backstage-agent-harness-foundation`

Purpose:

- Extract the shared backstage assistant runner, run schema, evidence bundle, proposal artifact, replay log, budgets, and approval gates after the accurate-ingest audit MVP proves the shape.

Likely specs:

- `backstage-agent-run-contract`
- `backstage-agent-evidence-contract`
- `backstage-agent-proposal-contract`
- `backstage-agent-replay-log`
- `backstage-agent-budget-and-stop-controls`
- `backstage-agent-approval-gates`

Acceptance highlights:

- Assistants must declare autonomy level.
- Runs must emit structured artifacts.
- Budgets must fail closed.
- Durable changes require approval unless explicitly allowlisted as L3.

### 3. `backstage-audit-assistant-mvp`

Purpose:

- Generalize read-only Audit Assistant behavior for module publishability and report diagnosis beyond accurate-ingest recovery.

Likely specs:

- `backstage-audit-module-diagnosis`
- `backstage-audit-blocker-classification`
- `backstage-audit-report-artifact`
- `backstage-audit-readonly-safety`

Acceptance highlights:

- Reads existing reports and audit scripts.
- Groups blockers by domain.
- Produces no file edits.

### 4. `backstage-builder-assistant-proposals`

Purpose:

- Add Builder Assistant proposal workflow for source-fidelity and module repair planning.

Likely specs:

- `backstage-builder-source-fidelity-comparison`
- `backstage-builder-repair-proposal`
- `backstage-builder-validation-plan`
- `backstage-builder-structural-authority-boundaries`

Acceptance highlights:

- Proposals cite source evidence.
- No canonical IDs/topology/puzzle rules invented by LLM.
- Human approval required before patch application.

### 5. `backstage-writer-story-so-far-harness`

Purpose:

- Add Writer Assistant for fact-bounded Story So Far drafts and future journal prose workflows.

Likely specs:

- `backstage-writer-confirmed-facts-input`
- `backstage-writer-outline-and-draft`
- `backstage-writer-factual-consistency-check`
- `backstage-writer-provenance-metadata`

Acceptance highlights:

- Confirmed diary only for canonical story output.
- Mechanical contradictions block finalization.
- Drafts are separate from confirmed artifacts.

### 6. `backstage-memory-doctor-mvp`

Purpose:

- Add read-only Memory Doctor diagnostics and additive repair proposals.

Likely specs:

- `backstage-memory-diagnostics`
- `backstage-memory-provenance-audit`
- `backstage-memory-additive-repair-proposals`
- `backstage-memory-no-delete-safety`

Acceptance highlights:

- No automatic memory deletion.
- Mechanical truth comes from current state, not memory prose.
- Repair proposals are additive and provenance-backed.

### 7. `backstage-ratio-analyst-mvp`

Purpose:

- Add supervised RATIO analyst for rejected-turn clustering and prompt/spec/test proposal generation.

Likely specs:

- `backstage-ratio-failure-clustering`
- `backstage-ratio-prompt-proposal`
- `backstage-ratio-openspec-proposal-draft`
- `backstage-ratio-no-live-tuning`

Acceptance highlights:

- RATIO is between-session only.
- No automatic prompt/runtime edits initially.
- Proposals include regression test suggestions.

### 7. `backstage-agent-safe-autoapply`

Purpose:

- Add strictly allowlisted L3 deterministic auto-apply operations after MVP assistants prove useful.

Likely specs:

- `backstage-agent-l3-allowlist`
- `backstage-agent-post-apply-validation`
- `backstage-agent-reversible-generated-artifacts`

Acceptance highlights:

- L3 is allowlist-only.
- No live gameplay state mutation.
- Validators must run after apply.

---

## Suggested File/Artifact Layout

### Code

```text
core/agents/backstage/
  contracts.py
  runner.py
  evidence.py
  proposals.py
  validators.py
  approval.py
  replay_log.py
  assistants/
    audit.py
    builder.py
    writer.py
    memory.py
    ratio.py
```

### Scripts

```text
scripts/run_backstage_agent.py
scripts/test_backstage_agent_contracts.py
scripts/test_backstage_audit_assistant.py
scripts/test_backstage_builder_assistant.py
scripts/test_backstage_writer_assistant.py
scripts/test_backstage_memory_doctor.py
scripts/test_backstage_ratio_analyst.py
```

### Runtime Artifacts

```text
data/agent_runs/
  audit/<task_id>/
  builder/<task_id>/
  writer/<task_id>/
  memory/<task_id>/
  ratio/<task_id>/
```

These should be ignored by git unless promoted to docs or fixtures.

### Review Artifacts

Possible reviewed outputs:

```text
docs/agent_reports/
  <date>-<assistant>-<topic>.md
```

Only write reviewed summaries here when explicitly useful.

---

## Provider and LLM Routing Notes

The backstage harness should use existing AI client/factory patterns and future router work rather than direct SDK calls.

Requirements:

- Use configured model routing.
- Use timeouts.
- Record provider/model metadata in run artifacts.
- Fail open for advisory analysis where safe.
- Fail closed for proposal schema violations.
- Never silently downgrade a failed deterministic validation to success.

Suggested role categories for future router integration:

| Role | Use |
|---|---|
| `agent_audit` | Finding classification and concise diagnosis. |
| `agent_builder` | Source-backed repair proposal drafting. |
| `agent_writer` | Long-form narrative drafting. |
| `agent_memory` | Memory clustering and provenance diagnostics. |
| `agent_ratio` | Failure clustering and prompt/spec/test proposal generation. |

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Agent writes too broadly | Corrupts module/runtime state | Approval gates, autonomy levels, L3 allowlist only. |
| Source hallucination | Adds unsupported lore/entities | Evidence refs required, source-fidelity validators. |
| Tool-loop spiral | Cost/time blowout | Step, LLM-call, validator, and wall-clock budgets. |
| Prompt injection from module prose | Assistant follows malicious source content | Treat module prose as data, not instructions; system prompt states hierarchy. |
| Validation theater | LLM self-check replaces deterministic tests | Deterministic validators required for durable changes. |
| Memory corruption | Canon drift | Additive repairs only, no deletes, provenance required. |
| RATIO overfitting | Prompt churn from one session | Cluster threshold, human review, regression replay. |
| Framework lock-in | Generic agent abstractions fight NEQ architecture | Start custom and minimal; evaluate frameworks later. |

---

## Framework Evaluation Point

Do not adopt LangChain/AutoGPT-style frameworks through the initial accurate-ingest audit build, harness extraction, or builder proposal MVP.

Re-evaluate after:

- Accurate-ingest read-only Audit Assistant MVP works.
- Shared harness extraction works.
- Builder proposal loop works.
- Replay artifacts prove useful.
- Repeated patterns show a framework would reduce maintenance.

Evaluation criteria:

- Can it enforce NEQ autonomy levels?
- Can it preserve deterministic replay logs?
- Can it constrain tool access by assistant type?
- Can it avoid hidden retries and hidden state?
- Does it integrate with existing `.venv/bin/python` scripts and OpenSpec workflow?

If not, keep the custom harness.

---

## Recommended First Slice

Start with:

```text
toolkit-accurate-ingest-backstage-audit-mvp
```

Reason:

- The current accurate-ingest recovery already produces deterministic evidence artifacts.
- A read-only auditor is the lowest-risk proof of the backstage-agent idea.
- It immediately improves the Numillian recovery workflow without broadening the active preservation slice.
- It can use minimal local scaffolding first; shared harness contracts can be extracted afterward.
- It exercises evidence, validators, report output, and recommendation formatting without write-risk.

Suggested first implementation target:

```bash
.venv/bin/python scripts/run_backstage_agent.py accurate-ingest-audit --module The_Hidden_City_of_Numillian
```

Expected MVP output:

```text
data/agent_runs/accurate_ingest_audit/<task_id>/run.json
data/agent_runs/accurate_ingest_audit/<task_id>/evidence.json
data/agent_runs/accurate_ingest_audit/<task_id>/audit_report.json
data/agent_runs/accurate_ingest_audit/<task_id>/recommendation.json
```

The first version should be mostly deterministic orchestration plus optional compact LLM summarization. It must remain report-only. It should not mutate module artifacts, generate waivers, weaken gates, replace existing audit scripts, or become part of the live ModuleBuilder generation loop.

---

## Success Criteria

The backstage agent program is successful when:

- Assistants reduce time spent manually reading reports and logs.
- All assistant outputs are attributable to evidence.
- Durable changes remain validated and reviewable.
- The live narrator/combat architecture remains unchanged and stable.
- Writer outputs are more useful without creating canon contradictions.
- Builder repairs improve source fidelity without weakening gates.
- Memory diagnostics improve continuity without overwriting truth.
- RATIO proposals produce better tests/specs/prompts without uncontrolled prompt churn.

---

## Final Recommendation

Build NEQ-specific backstage assistants as supervised harnesses, not autonomous game masters.

The right split is:

```text
Live play:
  bounded LLM proposer + Python authority

Backstage:
  supervised agentic assistants + evidence + validators + approval gates
```

That preserves the strongest part of NEQ's architecture while adding agentic leverage where loops are useful: diagnosis, building, writing, memory curation, and between-session improvement.
