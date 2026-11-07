# Design

## Context and evidence boundary

This is a planning-only follow-up for a bounded offline prototype. The frozen M1 record reports 16 original artifacts averaging 2.625/5 legibility and 2.875/5 usefulness against its frozen 3.5 thresholds. The nine expanded scenes are development/calibration examples, not held-out evidence. SP3 is INCONCLUSIVE, SP3b is CLOSED BLOCKED, and no live PASS, current budget, or implementation approval is established. PR113 is OPEN at pinned commit `2859b59e517bc94ab663e413391e51bb4a20ddf4`; GitHub blob citations below point to that immutable commit, not mutable PR text.

## Central objective: Narrator-first

The prototype optimizes the NEQ LLM's spatial comprehension and actionable, coherent narration first. A cumulative knowledge-filtered player map is a secondary projection of the same authored facts plus committed discoveries—not a full atlas or production S5 geography.

The pinned evidence is the [owner-feedback final M1 record][feedback-final-m1], which binds the reviewed ratings CSV SHA-256 `2611bc239076fc5e7d47f2495576134369e24f823049f45cd1c11da09f1b3b78`. The append-only [SP4 M1 handoff in this PR](../v2-mapping-pilot-execution/reports/sp4-primary-report.md#later-m1-owner-review-and-mise-en-scene-planning-handoff) is a local sibling-file reference, not content present at the PR113 pinned commit. The owner-review source inventory also links [IMPORTANT mise-en-scene direction][feedback-important] and owner examples [Appendix A][feedback-a], [B][feedback-b], [C][feedback-c], [D][feedback-d], [E][feedback-e], [F][feedback-f], [G][feedback-g], [H][feedback-h], and [I][feedback-i].

### Verified current source and contract inventory

These are existing current-tree paths/symbols, not proposed implementation destinations:

| Surface | Verified source |
| --- | --- |
| Production spatial helpers | `utils/spatial_contract.py`: `build_linear_spatial_plan`, `resolve_authored_adjacency`, `resolve_semantic_spatial_plan`, and `build_tactical_grid`. |
| Current authoring/validation path | `core/generators/area_generator.py` calls the spatial helpers; `core/validation/validate_module_files.py::validate_spatial_contracts` checks existing area/map contracts; `schemas/map_schema.json` is the current map schema. |
| Research-only pilot prototype | `scripts/mapping_pilot/layout.py::{normalize_fixture_layout, validate_layout}`, `scripts/mapping_pilot/projections.py::{relationship_statements, render_schematic, render_packet}`, and `scripts/mapping_pilot/knowledge.py::filter_layout_for_viewpoint`. These are not a production scene service. |
| Existing relevant OpenSpec contracts | `openspec/specs/tt-spatial-coordinate-resolution/spec.md`; `tt-narrator-scene-context-hygiene/spec.md`; `tt-location-exclusive-scene-authority/spec.md`; `tt-scene-authority-metadata-contract/spec.md`; and `toolkit-source-locked-builder-narrative/spec.md`. They remain authoritative and are not changed here. |

The current contracts and code establish useful structural checks but do not make the scene-staging requirements below a production capability. This proposal creates no absent `core/mapping/` service, schema, or test path and makes no runtime behavior claim.

## Goals and non-goals

**Goals**

- Prototype a compact scene relationship artifact and deterministic projections that capture an actionable stage rather than merely a valid schema or feature list.
- Preserve extraction unknowns while allowing clearly marked Builder-authored staging inside approved topology.
- Test scene scope/orientation, approach/threshold/focal relations, multi-cell extent, usable space, fixed/mobile identity, frontage identity, and guarded knowledge with provider-free fixtures.
- Compare matched facts in structured-relationship, prose-only, and structured-plus-schematic-grid conditions, without selecting a production format.
- Preregister a small, new, leakage-checked evaluation only after the owner separately approves its manifest, rubric, thresholds, provider, and budget.

**Non-goals**

- Production S1-S5 or SC0-SC4 implementation, tactical AI, full movement enforcement, combat maps, Network clients/transport, prompt integration, persistence, canonical module/schema changes, or existing-module backfill decisions.
- Acceptance of ADR-0034, a production TITAN seed job, authority transfer to TITAN, or Firelight migration of any rule family.
- Re-running, editing, pooling, or rescoring M1/SP3/SP3b evidence; treating the nine expanded examples as held-out; or using any evaluation threshold as current approval.
- Exhaustive atmospheric modeling. The prototype should encode only enough relationships to make the staged scene understandable and actionable.

## Prototype boundary and design choices

The future prototype seam is deliberately offline: supplied source facts and approved topology enter as immutable fixture inputs; an authoring/projection function emits relationship artifacts and diagnostics; tests compare input, authored facts, and render outputs. There is no module write, runtime-state mutation, provider call, live listener, campaign migration, or production consumer.

1. **Provenance and creativity are separate.** Extracted claims cite consulted source material and leave unsupported relationships unknown. A Builder prototype may add useful initial scene staging as new authorship, but may not contradict supplied topology or relabel new decisions as source facts. Runtime PCs from prior play are not initial-scene content.
2. **Scene staging is relational, not decorative.** Each fixture states its scope and either a known compass orientation or explicit unknown. It records applicable approaches, thresholds, focal relationships, path/terrain/boundary extents, and usable space. It need not model every sensory detail. A schema-valid feature inventory with missing required positional relationships fails coverage diagnostics.
3. **Cells do not imply rules.** Cell positions are schematic. They do not establish compass direction, distance, scale, access, doors, line of sight, audibility, travel time, movement cost, or legality. An unknown remains unknown unless a separate source or explicitly marked Builder decision establishes it.
4. **Identity survives multiple views.** Fixed anchors and mobile occupants are separate. One tavern has one shared identity across linked scene views while its different frontages remain separate; neither frontage nor proximity creates a door or exit.
5. **Knowledge is audience-scoped in the fixture.** The GM-aware camp fixture can contain its guard condition. Public arrival and map output cannot expose or activate the surprise from arrival, looking, or tent investigation. Attempted fire-lighting is the sole trigger condition; its effect is unknown, not a license to invent a result.
6. **The projection arms are matched evidence, not an architecture vote.** Condition A is structured relationships without a grid; B is prose-only with the same facts; C is those structured relationships plus a schematic grid. Each must be hash-bound to the same source/fact set. Report C-versus-A as a bounded descriptive grid increment and B as the prose-only comparison; do not claim a broad causal effect.

## Cross-track owner handoffs (not implementation tasks here)

| Owner | Concrete plan/spec/ADR implication for its own reviewed work | Boundary preserved by this proposal |
| --- | --- | --- |
| Spatial | `plans/v2-spatial.md` §§6-8 owns the S1-S5/SC0-SC4 roadmap. A later Spatial change may add a reviewed `tt-spatial-scene-staging` capability or explicitly revise `tt-spatial-coordinate-resolution`; neither candidate is claimed to exist. ADR-0034 is Proposed and must be accepted or revised appropriately before runtime spatial authority is implemented. | This offline prototype does not require acceptance of ADR-0034 and does not implement any production S/SC phase, state, or enforcement. |
| Module Builder | `plans/v2-module-builder.md` owns Builder pipeline decisions. A later Builder-owned change may define initial mise-en-scene authoring as a `toolkit-builder-mise-en-scene-authoring` capability (candidate name only) and reconcile existing `toolkit-source-locked-builder-narrative` with spatial contracts. | Creative initial authoring stays distinct from source-locked extraction. No production Builder, importer, publication, module write, or backfill is included. |
| Narrator | `plans/v2-narrator.md` owns runtime context, perspective isolation, and prompt assembly; a future Narrator-owned delta to existing `tt-narrator-scene-context-hygiene` may reconcile any approved scene projection. | The GM/public camp boundary is an offline fixture only. No runtime prompt, trigger, or narrator path changes here. |
| TITAN | `plans/v2-titan-game-engine.md` retains its own world-context/seed contract and may supply only separately approved wider-world context to the owning track. A later TITAN-owned `titan-spatial-context-consumer` contract (candidate name only) would define that interface and any production seed consumer. | No authority transfer, production seed-job approval, production seed generation, or TITAN implementation is implied. |
| Network | `plans/v2-server-client-network.md` §§4-5 and its N2 dependency own authorization, transport, and client integration. A later Network-owned `server-client-authorized-spatial-projection` contract (candidate name only) must specify the projection consumer boundary. | No auth, API, transport, or client work is assigned to this change. |
| Firelight | `plans/v2-firelight.md` and accepted ADR-0033 own the bridge and migrated-family registry. Any future `firelight-spatial-rule-family` change (candidate name only) remains Firelight-owned; Firelight decides legality only for explicitly migrated families through the Python bridge, while unmigrated families retain Python guards. | No family migration or rules call is included. The prototype reports mechanics as unknown and makes no ruling. |
| Shared plan index | `plans/v2-narrative-overview.md` §§4-8 owns the cross-track index and dependency map; update it only when owner decisions are accepted. Accepted ADR-0032 preserves one tabletop runtime with P1 regression and P4 primary coverage. | No party-size gate or parallel party model is introduced. |

Pinned owner-plan references: [Mapping Pilot authority, owner direction, design, and evidence sections][pilot]; [Spatial S1-S5, SC0-SC4, and integration][spatial]; [Builder ownership, pipeline, and representation][builder]; [TITAN seed prerequisite and world-context contract][titan]; [Narrator authority, perspective, and prompt boundaries][narrator]; [program ownership/dependencies][overview]; [Network trust and authorization boundary][network]; [Firelight authority and bridge boundary][firelight]; [accepted ADR-0032][adr32]; [accepted ADR-0033 authority/family registry][adr33]; and [proposed ADR-0034][adr34].

### Spatial roadmap handoff map (ownership only; implementation excluded)

These are the pinned Spatial plan's future phase boundaries, not tasks or approval to implement any production phase in this change.

| Phase | Pinned owner seam and dependency | This proposal's limit |
| --- | --- | --- |
| S1 — spatial foundation | [S1][spatial-s1] owns module-qualified stable location/feature IDs, read-only graph/topology and relation queries, and the scene-layout foundation. | Offline fixtures may exercise identities and relations only; no production canonical service, loader, overlay, events, or persistence. |
| S2 — Narrator packet | [S2][spatial-s2] owns the bounded Narrator spatial packet and Python-bounded distant-route lookup, coordinated with Narrator packet assembly. | Projection comparison is offline only; no Narrator prompt, atlas, lookup, retry, transition, or arrival integration. |
| S3 — authored spatial data | [S3][spatial-s3] owns published-module layouts; Builder MB1/MB2 author new-module data, while backfill versus Builder-only coverage waits on the D1/owner data-pipeline choice. | The prototype can test fixture authoring, but it neither decides that choice nor writes/backfills/publishes modules. |
| S4 — shared player map | [S4][spatial-s4] owns a knowledge-filtered cumulative projection over existing authored topology and discoveries; it depends on S2 and Network N2 before player protocol/client integration. | No production map, protocol, client, or Network integration. |
| S5 — regional layer | [S5][spatial-s5] is a later, separate regional places/routes layer, dependent on S4 and stable SC2/TITAN P0 contracts and a separate regional plan. | Entirely deferred; no regional graph, seed, placement, or runtime behavior. |
| SC0 — contracts | [SC0][spatial-sc0] owns reconciliation of the combat contracts and the owner decision on zone granularity, enforcement level, and budgets. | No combat contract changes or tactical choice in this proposal. |
| SC1 — encounter spatial state | [SC1][spatial-sc1] owns encounter positions, the zone ledger, placement, validated spatial/mechanical facts, and typed committed position deltas at the approved level. | No positions, ledger, mechanics, movement enforcement, or encounter-state implementation. |
| SC2 — tactics | [SC2][spatial-sc2] owns deterministic enemy/ally tactics and actor-scoped spatial knowledge. | No tactical AI or combat behavior changes. |
| SC3 — intent | [SC3][spatial-sc3] owns movement-intent proposals/clarification and the combat packet; Python validates any later commit. | No intent parsing, move proposals, or runtime commits. |
| SC4 — combat map/acceptance | [SC4][spatial-sc4] owns the combat map atop S4 and its separately authorized P1/P4 live acceptance gates. | No combat map, live gate, or acceptance decision here. |

## Prospective evaluation protocol — for owner review only

Every sample count, threshold, attempt/request limit, and time limit in this section is newly proposed and unratified: a planning ceiling only, not an approved budget, preregistration, or permission to run. No SP3b remaining budget is assumed or reused. Before freeze, the owner must approve the exact manifest, rubric, thresholds, model/provider, separate assessment and gameplay budgets, request/time caps, capture window/port booking, and gate authorization; feasibility of the proposed ceilings must be checked against the actual runtime lifecycle. If live evaluation requires runtime or prompt/injection integration, approval from the independently owning runtime/injection contract is also a prerequisite. The offline prototype cannot authorize that integration.

| Element | Proposed bounded protocol | Freeze/report rule |
| --- | --- | --- |
| Development/calibration | The 16 original M1 artifacts and nine expanded owner examples remain development-only. Use 6 known items with exact, pre-existing owner ratings bound to exact artifact hashes for the proposed calibration sample. | No original, expanded, or derivative example enters the holdout. If fewer than 6 valid owner-score pairs are available, calibration is not estimable and must be reported as uncalibrated; no labels are fabricated. Arithmetic over supplied ratings is provider-free. |
| New held-out sample | Exactly 6 new, independently sourced scenes. Before freeze, ensure coverage of approach/threshold/focal staging, multi-cell path/terrain/boundary extent and usable space, shared identity/frontages, fixed/mobile anchors, and guarded-knowledge/unknown-mechanics cases; requirements may overlap. | Check source identity, text/layout/feature overlap, adaptation lineage, and known-example derivatives. The manifest records an owner-approved deterministic episode/condition-order assignment seed and the resulting order. Freeze source, normalized facts, condition artifacts, fixture/test version, rubric, assessor configuration, and assignment/order hashes before any scoring or capture. Changing the count, source set, or order after approval requires owner reapproval and refreeze before starting. |
| Matched conditions and owner review | 3 conditions per scene: A structured relationships; B prose-only rendering of the same semantic facts; C the same structured relationships plus schematic grid. Total: 18 exact artifact versions. | Hold source facts, approved topology, task, and all non-representation inputs constant. The owner rates legibility and usefulness for each exact artifact/version; owner artifact scoring itself uses no provider. Blind condition labels where practicable and report each condition separately. |
| Advisory model assessment | At most 24 assessment provider attempts total: 18 held-out artifact assessments plus 6 calibration-item assessments, at most one provider attempt per artifact/item. | This is a separate, explicitly approved assessment budget, not part of provider-free tests or the gameplay cap. Count every assessor startup/tool/summary/validation call inside the cap; if an item needs more than one provider attempt, stop for revised owner approval rather than making hidden calls. Freeze the independent assessor identity/configuration and output before owner scores are revealed. Any retry or added call requires separate owner approval. Report exact agreement, within-one agreement, and MAE by axis with paired `n`/denominator for calibration and holdout; advisory output never replaces owner judgment. |
| Party and episode sample | P1 (one PC) and P4 (four PCs), each tested for every scene and each of 3 conditions: exactly 6 scenes x 3 conditions x 2 party shapes = 36 scheduled gameplay episodes. Each episode is at most 6 scripted player/Narrator turns and includes approach/threshold, a transition, and return/revisit assertions. | The 6-turn ceiling is distinct from provider attempts. Report each condition x party-shape cell independently. A synthetic evaluation party may be supplied to an episode; it is not copied into initial authored scene facts from past play. |
| Gameplay attempts, provider attempts, and live time | One initial gameplay episode attempt per scheduled episode; at most one infrastructure-only retry per episode, only if no generated game output was produced. No content-failure reruns. Cap each episode attempt at 24 total provider attempts, including startup, retries, tools, summaries, validation, and narrative calls. | At most 864 provider attempts for 36 initial episodes; at most 1,728 for 72 attempts including all allowed retries. These count the full runtime lifecycle, not one request per turn. Proposed hard live-time cap is 6 hours total including startup, setup, teardown, and retries. Stop at any cap; missing required evidence is BLOCKED. Any increase needs owner reapproval before freeze. |

If both the separate advisory-assessment and gameplay budgets are authorized at their proposed maxima, their combined ceiling is 1,752 provider attempts (24 assessment + 1,728 gameplay), tracked in separate ledgers. The six-hour live cap applies to the complete live evaluation window; any assessor call made in that window consumes that elapsed-time cap too.

### Assertion and rating rules

- Freeze each assertion before evaluation and classify it as critical, non-critical, required-but-unknown, or non-applicable. Count an assertion once per declared episode/turn, not once per repeated narration mention.
- **Critical zero-tolerance failures:** public leakage or false activation of the guarded camp surprise; a protected unknown stated as known (including fabricated trigger effect, route, compass direction, metric, or mechanics); topology/route contradiction; movement by narration without an authorized commit in a future runtime gate; moved fixed anchor; runtime-PC leakage into initial authorship; or a door/access/legality inference from a schematic relationship. Any critical violation fails its condition/party-shape cell regardless of averages.
- **Non-critical denominator:** for each condition and party-shape cell, `n` is the number of predeclared non-critical assertions with enough evidence to adjudicate as correct/acceptable or incorrect. Incorrect assertions enter the denominator only and never the correct/acceptable numerator. Candidate threshold: at least 90% correct/acceptable in every cell. A single non-critical miss is not an automatic gate failure, but it remains in the denominator and may cause the cell to miss the rate threshold.
- A required assertion with missing artifact, turn, state, or rating evidence makes the relevant gate BLOCKED; it is not counted as success or included as a favorable denominator item. A required protected-unknown assertion is evaluated as “must remain unknown”; making a concrete claim is critical. A non-required unknown or genuinely non-applicable outcome is excluded with a reason, never counted as a pass.
- Candidate owner threshold: mean legibility and usefulness each at least 4.0/5 **in each condition separately**, alongside artifact-level scores and ranges. No pooling across conditions or P1/P4. Candidate rates and ratings are not ratified and do not revise M1's frozen 3.5 threshold or result.
- Report the A-versus-C grid increment and B prose-only results descriptively, with artifact/episode counts and all exclusions. Do not pool conditions, party shapes, development examples, or holdout scenes to hide a failing cell or claim general causality.

### Provider-free diagnostics and future live ownership

Required negative fixture pairs distinguish (1) a fact absent from source and correctly left unknown, (2) a source-supported fact omitted during extraction/authoring, and (3) an authored fact lost by a projection or renderer. A positional-coverage report must identify the missing relationship/extent and the stage at which it disappeared; schema validity alone is insufficient. Include negative fixtures for wrong/defaulted compass, missing approach/threshold/focal relations, truncated multi-cell path/terrain/boundary, no usable space, inferred tavern door, changed fixed anchor, PC contamination, public camp leak/false trigger, and fabricated metric/mechanics. All checks are deterministic and provider-free.

If live evaluation is separately approved, the primary orchestrator—not a builder—owns the isolated Capture_Arena run and final gate verdict after focused tests. Any required runtime or injection integration must first be approved by its independent owning contract/team. Follow `neq-capture-arena`: use a real copy under project-relative `tmp/combat_capture/`, port 8360, `NEQ_OPEN_BROWSER=0`, and the repository venv. Preserve per-gate/per-run evidence under `tmp/router-rollout/mise-en-scene/<gate>/<run-id>/`, including frozen manifest and assignment seed/order, artifact hashes, scene/party/condition identity, worktree and model/provider identity, exact expected/observed assertions, transcripts, before/after state where applicable, ratings, and artifact paths. Do not run a provider, start a server, or create capture evidence under this planning-only change.

## Prospective focused tests (paths do not yet exist)

If separately authorized, the proposed provider-free tests are:

| Proposed test path | Coverage | Proposed command |
| --- | --- | --- |
| `scripts/test_mise_en_scene_authoring.py` | Provenance, unknowns, topology, scene scope/orientation, positional coverage, multi-cell extents, tavern identity/frontages, fixed/mobile anchors, and PC exclusion. | `.venv/bin/python scripts/test_mise_en_scene_authoring.py` |
| `scripts/test_mise_en_scene_projection.py` | Matched A/B/C projections, guarded camp knowledge/trigger, protected unknowns, deterministic output, and source-versus-renderer-loss diagnostics. | `.venv/bin/python scripts/test_mise_en_scene_projection.py` |
| `scripts/test_mise_en_scene_evaluation.py` | Leakage checks, frozen hashes, arithmetic over supplied assessor/owner score records only, owner artifact binding, and proposed assertion accounting; no model invocation or provider call. | `.venv/bin/python scripts/test_mise_en_scene_evaluation.py` |

Aggregate prospective command: `.venv/bin/python -m unittest discover -s scripts -p 'test_mise_en_scene_*.py'`. These names and commands are proposals, not existing files or tests run in this planning task.

## Source references pinned at PR113 commit

All GitHub blob links below are pinned to `2859b59e517bc94ab663e413391e51bb4a20ddf4`. The local sibling SP4 report link above is this PR's append-only handoff and is intentionally not represented as pinned PR113 content.

[feedback-final-m1]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#final-m1-owner-score-record-and-prospective-planning-direction
[feedback-important]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#important-owner-development-mise-en-scene-is-the-mapping-goal
[feedback-a]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#a-causeway-a-path-spanning-cells
[feedback-b]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#b-village-market-stalls-inside-a-field-boundary
[feedback-c]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#c-village-square-open-space-extends-to-the-frontages
[feedback-d]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#d-village-tavern-populated-initial-scene
[feedback-e]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#e-crossroads-one-junction-four-route-arms
[feedback-f]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#f-scarecrow-hollow-terrain-rim-and-central-anchor
[feedback-g]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#g-cave-threshold-forest-to-cavern-mise-en-scene-nc01-review-14
[feedback-h]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#appendix-h-abandoned-research-camp-investigation-mise-en-scene
[feedback-i]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot-owner-feedback.md#appendix-i-voidstone-hilltop-climactic-mise-en-scene-nc05-16
[pilot]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-mapping-pilot.md#4-questions
[spatial]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#6-exploration-and-narrator-phases-s1-s5
[builder]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-module-builder.md#5-logical-representation-and-migration-contracts
[titan]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-titan-game-engine.md#3-baseline-audit-and-seed-content-prerequisite
[narrator]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-narrator.md#8-perspective-isolation-and-future-npctitan-access
[overview]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-narrative-overview.md#4-plan-ownership
[network]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-server-client-network.md#4-architecture-and-trust-boundary
[firelight]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-firelight.md#3-authority-and-scope
[adr32]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/adrs/0032-single-tabletop-runtime.md#decision
[adr33]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/adrs/0033-firelight-rules-engine-under-python-host-authority.md#family-registry
[adr34]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/adrs/0034-spatial-authority-and-projections.md#decision
[spatial-s1]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#s1-spatial-foundation
[spatial-s2]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#s2-narrator-spatial-packet
[spatial-s3]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#s3-authored-spatial-data
[spatial-s4]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#s4-shared-player-map
[spatial-s5]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#s5-regional-layer-outline-built-later
[spatial-sc0]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#sc0-contracts
[spatial-sc1]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#sc1-encounter-spatial-state
[spatial-sc2]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#sc2-spatial-tactical-brain-and-allies
[spatial-sc3]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#sc3-player-intent-and-combat-packet
[spatial-sc4]: https://github.com/zeug-zz/NeverEndingQuest-TTRPG/blob/2859b59e517bc94ab663e413391e51bb4a20ddf4/plans/v2-spatial.md#sc4-combat-map-and-live-gates
