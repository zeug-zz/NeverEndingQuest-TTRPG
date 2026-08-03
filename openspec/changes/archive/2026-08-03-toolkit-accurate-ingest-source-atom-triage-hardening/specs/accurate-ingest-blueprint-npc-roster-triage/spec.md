## ADDED Requirements

### Requirement: Blueprint NPC roster SHALL honor triage exclusions

The source-blueprint NPC roster SHALL exclude rejected candidates and candidates adjudicated as non-actors. Excluded non-actors SHALL NOT be counted as required NPCs during build-fidelity coverage.

#### Scenario: Rejected table effect never enters NPC roster

- **GIVEN** entity triage rejects a source candidate named `Awaken`
- **WHEN** the builder blueprint is generated
- **THEN** `npc_roster` SHALL NOT contain `Awaken`
- **AND** build fidelity SHALL NOT emit `Required npc 'Awaken' not found in module`.

#### Scenario: Non-actor adjudicated type is excluded

- **GIVEN** entity triage classifies a candidate as `narrative_phrase`, `plot_note`, `tone_marker`, or `unknown`
- **WHEN** the blueprint NPC roster is built
- **THEN** the candidate SHALL be excluded from `npc_roster`.

#### Scenario: Kept true NPC remains in roster

- **GIVEN** entity triage keeps a candidate as `true_npc`
- **WHEN** the blueprint NPC roster is built
- **THEN** the candidate MAY appear in `npc_roster`
- **AND** existing source-lock behavior for real NPC preservation SHALL remain unchanged.

## SHOULD Guidance

- Reuse existing `_is_triage_blocked_for_npc_roster(...)` behavior where possible.
- Add only minimal roster safety if prefilter decisions fully solve the false-positive class.
