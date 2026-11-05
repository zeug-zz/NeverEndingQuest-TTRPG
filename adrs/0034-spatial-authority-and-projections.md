# ADR-0034: Spatial Authority and Projections

- Date: 2026-11-06
- Status: Proposed
- Supersedes: None
- Superseded by: None

## Context

Spatial information must keep the shared imagined world coherent without
confusing narrative orientation, player knowledge, and tactical legality.
One layout can support several audiences, but a single unfiltered payload can
reveal unknown facts or make missing information look definitive.

The spatial plans distinguish schematic positions from authored metric facts,
and the mapping pilot observes zone behavior without enforcing it. Future
spatial implementation and enforcement depend on the owner gate; this draft
does not select a pilot outcome or implementation level.

## Decision

This ADR is a proposed contract only. It does not guide implementation until
the owner explicitly accepts it.

### Python authority

- Python is the authority for canonical spatial layout, topology, zone state,
  and committed spatial changes. The LLM is never the source of spatial truth.
- The LLM may narrate spatial facts and interpret player intent into a
  proposal. It cannot commit movement or change spatial state by assertion.
- Python validates and commits a spatial change before it is narrated as fact.

### Projections by audience

- Keep one spatial truth and project it separately for each audience. A
  projection is a scoped view, not a second authority or state model.
- The Narrator packet contains scene-relevant facts for narration and intent
  interpretation.
- The player map is filtered by the party's viewpoint and revealed knowledge;
  it does not disclose hidden spatial facts.
- The combat zone view contains the tactical facts needed for the encounter,
  without making its payload the player map or the Narrator packet.
- Keep perception, knowledge, visibility, connectivity, and traversal distinct
  where those states are represented. Label unknown facts as unknown.
- A fact's absence from a projection does not assert that the fact or place
  does not exist.

### Schematic and metric facts

- Treat display positions and generated layout bearings as schematic unless an
  authored metric frame explicitly defines them otherwise.
- Schematic position, orientation, or adjacency does not imply physical
  distance, scale, travel time, or a shared coordinate frame between areas.
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

- Pilot verdict: pending. This ADR records no pilot outcome, assigns no rating,
  and is not accepted.
- Explicit owner acceptance is required before S1. The draft and its Proposed
  index entry do not imply acceptance.
- This ADR does not change `MULTIPLAYER_MODE` or existing party-size gates. It
  applies to the single tabletop runtime for 1..x PCs, preserving the 1-PC
  regression floor and multi-PC compatibility.

## Consequences

- Narrator, player, and combat views can differ in payload while remaining
  projections of the same Python-owned spatial truth.
- Missing and schematic information remains explicitly uncertain instead of
  becoming an invented fact or physical measurement.
- Pilot observation remains distinct from mechanical enforcement; any later
  enforcement must follow the owner gate and the applicable rules authority.
- Until accepted, this draft makes no runtime change and is not an active
  implementation authority.

## Sources

- `AGENTS.md` (Python authority, Firelight boundary, party-size constraints).
- `adrs/0032-single-tabletop-runtime.md`.
- `adrs/0033-firelight-rules-engine-under-python-host-authority.md`.
- `openspec/changes/v2-mapping-pilot-execution/design.md` (Decision 9).
- `openspec/changes/v2-mapping-pilot-execution/specs/mapping-pilot-execution/spec.md`.
- `plans/v2-spatial.md` (sections 2, 4, 5, and 7).
- `plans/v2-mapping-pilot.md` (sections 1, 5.3, 7.2, and 10).
- `plans/v2-mapping-pilot-prereg/README.md` (proposed decision rules).
