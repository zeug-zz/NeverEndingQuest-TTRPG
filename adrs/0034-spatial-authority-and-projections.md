# ADR-0034: Spatial Authority and Projections

- Date: 2026-11-06
- Status: Proposed
- Revision: 2026-11-09 draft revision; owner review required; not a decision
- Supersedes: None
- Superseded by: None

## Context

Spatial information must keep the shared imagined world coherent without
confusing narrative orientation, player knowledge, and tactical legality.
One layout can support several audiences, but a single unfiltered payload can
reveal unknown facts or make missing information look definitive.

The spatial plans distinguish schematic positions from authored metric facts,
and the mapping pilot observes zone behavior without enforcing it. The SP4
report records the main SP3 comparisons as inconclusive, SP3b as closed blocked,
and the original M1 sketch packet below its frozen threshold. The D1 owner audit,
seven complete-for-rating transcript ratings, format choice, combat
granularity/enforcement, and data-pipeline choice remain pending.

The owner has directed subsequent planning toward Narrator-first mise-en-scene:
an actionable, coherent imagined scene for narration, with cumulative,
knowledge-filtered player maps as secondary projections. PR116 adds offline,
supplied-fixture tooling for explicit provenance, audience-scoped projections,
and fact-bound staged-arrival checks. Neither the owner direction nor PR116 is
evidence of production behavior, LLM Builder capability, or acceptance of this
ADR. Future implementation and enforcement remain subject to owner decisions.

## Decision

This ADR is a proposed contract only. It does not guide implementation until
the owner explicitly accepts it.

### Python authority

- Python is the authority for canonical spatial layout, topology, zone state,
  and committed spatial changes. The LLM is never the source of spatial truth.
- The LLM may narrate spatial facts and interpret player intent into a
  proposal. It cannot commit movement or change spatial state by assertion.
- Python validates and commits a spatial change before it is narrated as fact.

### Provenance and authoring modes

- Distinguish three proposed modes: source extraction faithfully records
  consulted evidence and leaves unsupported facts unknown; validated Builder
  authoring may create initial-world facts within Python-owned topology and
  labels them `builder_authored`; runtime narration elaborates within canonical
  facts, state, and knowledge boundaries.
- Never relabel a Builder-authored decision as source-extracted. Keep
  provenance classes explicit as `source_extracted`, `builder_authored`, or
  `unknown`. Unknown facts remain unknown unless an authoritative source or an
  explicitly validated Builder decision establishes them.
- Builder-authored scene staging may make approaches, thresholds, focal
  relationships, multi-cell features, usable space, and initial occupants
  coherent. It cannot contradict approved topology or silently create a route,
  access rule, metric, or mechanical fact.
- Runtime narration may enrich atmosphere but may not relocate committed
  anchors, change topology, or commit a new actionable fact by assertion.

### Projections by audience

- Keep one spatial truth and project it separately for each audience. A
  projection is a scoped view, not a second authority or state model.
- Prioritize the Narrator projection for coherent scene staging and spatial
  continuity; give it bounded scene-relevant facts for narration and intent
  interpretation rather than a full unfiltered atlas by default.
- The player map is a secondary, cumulative projection, filtered by the party's
  viewpoint, revealed knowledge, and committed discoveries. It does not
  disclose hidden spatial facts and does not replace narration.
- The combat zone view contains the tactical facts needed for the encounter,
  without making its payload the player map or the Narrator packet.
- Keep perception, knowledge, visibility, connectivity, and traversal distinct
  where those states are represented. Label unknown facts as unknown.
- A fact's absence from a projection does not assert that the fact or place
  does not exist.

### Fact-bound scene and arrival staging

- A staged arrival may organize supported facts as approach, threshold, and
  focal point, and may describe authored or known sensory gradients and
  invitations to act.
- Every checkable spatial claim in staged prose must trace to a known structured
  fact and its provenance, and must respect approved topology, perception, and
  audience knowledge. Staging adds presentation, not unbound factual content.
- Unknown or non-applicable route, metric, sensory, access, and mechanical facts
  stay unknown or non-applicable. Prose must not prescribe a player choice or
  successful outcome.
- These are proposed contract rules. PR116's offline checks bind approved text
  and supplied typed claims; they are not general natural-language or semantic
  validation and do not prove that all checkable claims have been discovered.

### Schematic and metric facts

- Treat display positions and generated layout bearings as schematic unless an
  authored metric frame explicitly defines them otherwise.
- Schematic position, orientation, or adjacency does not imply physical
  distance, scale, travel time, or a shared coordinate frame between areas.
- Schematic cells and co-location do not by themselves establish access,
  passage, a door, visibility, audibility, traversal, movement cost, or
  mechanical legality.
- Provide a metric distance only when that distance is authored as a metric
  fact. Otherwise report the distance as unknown; do not infer one from a
  schematic drawing.

### Observed and enforced legality

- The mapping pilot's zone ledger is observational (shadow-only): it records
  what happened and does not veto or authorize an action.
- Keep observed behavior separate from enforced legality. Pilot observations
  alone do not enable enforcement or establish an owner decision.
- Any later enforcement level requires the owner gate and Python validation
  before narration where a rule depends on it. Python remains the host and
  canonical store.
- For a migrated rule family, legality is decided by the pinned Firelight
  engine through the Python bridge under ADR-0033. Families not yet migrated
  keep their existing Python guards.

### Frozen close-enough rule

The following preregistered rule is preserved verbatim; it is not a pilot
result or an acceptance decision:

| Decision | Adopt when | Otherwise |
| --- | --- | --- |
| Zones are "close enough" | Zone contradictions at most 1 per 10 rounds unenforced **and** intent parse at least 90% exact or acceptable | High contradictions with good parsing: SC1 validates legality before narration. Poor parsing: SC3 adds a clarify step and a move picker. Both poor: SC0 reconsiders granularity with the owner |

### Owner gate and scope

- Pilot evidence is recorded in the draft pilot decision report. Main SP3 is
  INCONCLUSIVE, SP3b is CLOSED BLOCKED, and M1 is below its frozen threshold;
  none selects a production format or enforcement level.
- Explicit owner acceptance is required before S1. The draft and its Proposed
  index entry do not imply acceptance.
- This ADR does not change `MULTIPLAYER_MODE` or existing party-size gates. It
  applies to the single tabletop runtime for 1..x PCs, preserving the 1-PC
  regression floor and multi-PC compatibility.
- Open owner inputs remain unresolved: D1 audit; seven transcript ratings;
  format; combat granularity and enforcement; backfill-versus-Builder data
  pipeline; ADR acceptance; and any separate Section 2 evaluation authorization
  and protocol decisions. No proxy or default is selected here.

## Consequences

- Narrator, player, and combat views can differ in payload while remaining
  projections of the same Python-owned spatial truth.
- Missing and schematic information remains explicitly uncertain instead of
  becoming an invented fact or physical measurement.
- Pilot observation remains distinct from mechanical enforcement; any later
  enforcement must follow the owner gate and the applicable rules authority.
- Until accepted, this draft makes no runtime change and is not an active
  implementation authority.
- Narrator-first scene staging is a proposed design priority; the relative
  payload format, data pipeline, combat enforcement, and player-map delivery
  remain open pending owner input and appropriate evidence.

## Sources

- `AGENTS.md` (Python authority, Firelight boundary, party-size constraints).
- `adrs/0032-single-tabletop-runtime.md`.
- `adrs/0033-firelight-rules-engine-under-python-host-authority.md`.
- `openspec/changes/v2-mapping-pilot-execution/design.md` (Decision 9).
- `openspec/changes/v2-mapping-pilot-execution/specs/mapping-pilot-execution/spec.md`.
- `plans/v2-spatial.md` (sections 2, 4, 5, and 7).
- `plans/v2-mapping-pilot.md` (sections 1, 5.3, 7.2, and 10).
- `plans/v2-mapping-pilot-prereg/README.md` (proposed decision rules).
- `openspec/changes/v2-mapping-pilot-execution/reports/sp4-primary-report.md`
  (SP3 adjudication, SP3b, M1, and pending owner inputs).
- `openspec/changes/v2-mapping-pilot-execution/reports/pilot-decision-report.draft.md`
  (provider-free evidence synthesis and recommendations; not a decision).
- `plans/v2-mapping-pilot-owner-feedback.md` (IMPORTANT mise-en-scene direction;
  read-only planning input).
- `openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/proposal.md`
  and `design.md` (proposed offline contract and boundaries).
- `openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/reports/offline-build-verification.md`
  and `scripts/mise_en_scene/README.md` (supplied-fixture prototype and limits).

## Revision history

- 2026-11-06: Initial Proposed draft.
- 2026-11-09: Revised draft for owner review to add Narrator-first
  mise-en-scene, provenance classes, audience-scoped projections, non-metric
  schematic cells, fact-bound arrival staging, and current evidence boundaries.
  This is not acceptance or implementation authorization; status remains
  Proposed.
