# phase2-llm-remediation-proposals Specification

## Purpose
TBD - created by archiving change phase2-llm-classification. Update Purpose after archive.
## Requirements
### Requirement: Remediation proposals SHALL consume residual blocker reports

After publishability audit produces blocker classes, and when deterministic remediation has been exhausted, the LLM SHALL be invoked to propose concrete fixes for remaining blockers.

#### Scenario: Blockers trigger proposal generation

- GIVEN the publishability audit reports `spatial_adjacency_convergence_gap` and `monster_media_gap`
- AND deterministic remediation has been exhausted (repair budget consumed)
- WHEN the classification engine invokes DP4
- THEN the LLM receives the blocker report as context
- AND the LLM proposes concrete remediation actions

### Requirement: Proposal transform types SHALL be whitelist-only

The LLM may suggest transforms, but Python SHALL only accept whitelisted transform types:

| Transform Type | Valid For |
|---|---|
| `move_entity_to_scene_entity` | Entity reclassified from combatant to scene_illusion |
| `add_canonical_alias` | Destination reclassified as canonical_alias |
| `add_npc_visibility` | NPC reclassified as visible or hidden_reveal |
| `suppress_from_monsters` | Entity reclassified as narrator_flavor |
| `suppress_from_travel_map` | Destination reclassified as evocative_prose |
| `set_npc_reveal_authority` | NPC reclassified as hidden_reveal |

Unwhitelisted transform types SHALL be rejected with a warning.

#### Scenario: Valid transform accepted

- GIVEN the LLM proposes `move_entity_to_scene_entity` for "spectral servants"
- WHEN Python validates the transform type
- THEN the transform is whitelisted
- AND it appears in the GUI review panel

#### Scenario: Invalid transform rejected

- GIVEN the LLM proposes `rewrite_location_description` (not whitelisted)
- WHEN Python validates the transform type
- THEN the transform is rejected
- AND a warning is logged: "Rejected unwhitelisted transform: rewrite_location_description"

### Requirement: Transform safety SHALL be Python-validated before GUI surfacing

Before a proposed transform appears in the GUI, Python SHALL validate:
1. The target entity/phrase/NPC exists in the module
2. The transform destination field exists in the schema
3. Applying the transform would not violate schema constraints
4. The transform does not modify BU (canonical) files — only live runtime files

Unsafe transforms SHALL be filtered out before GUI display.

#### Scenario: Safe transform appears in GUI

- GIVEN the LLM proposes `add_canonical_alias` for "Veiled Paradox" in area NUBTV003
- AND "Veiled Paradox" exists in the area's authored text
- AND `aliases` field exists in the location schema
- WHEN Python validates transform safety
- THEN the transform passes all safety checks
- AND it appears in the GUI review panel

#### Scenario: Unsafe transform filtered out

- GIVEN the LLM proposes `add_canonical_alias` for "Nonexistent Room" in area NUBTV003
- AND "Nonexistent Room" does NOT appear in the area's authored text
- WHEN Python validates transform safety
- THEN the transform fails target-entity check
- AND it is filtered out before GUI display
- AND a warning is logged

### Requirement: Remediation proposals SHALL be fail-open with empty proposals

On API failure, the proposal engine SHALL return an empty proposal list. The build SHALL continue. The GUI SHALL show "No remediation proposals available" instead of an error.

#### Scenario: API failure returns empty proposals

- GIVEN the LLM API fails during remediation proposal generation
- WHEN the proposal engine handles the error
- THEN an empty proposal list is returned
- AND the build continues
- AND the GUI shows "No remediation proposals available"

### Requirement: GUI SHALL support per-proposal accept/reject

The toolkit GUI SHALL display each proposal with:
- The proposed transform type (human-readable)
- The target entity/phrase/NPC name
- The proposed change (what will be modified)
- The safety validation result (pass/warning)
- An accept button and a reject button

#### Scenario: Author accepts a proposal

- GIVEN the GUI shows a proposal to add "Veiled Paradox" as canonical alias
- WHEN the author clicks "Accept"
- THEN the alias is added to the location's `aliases` field
- AND the proposal is marked "accepted" in the review panel
- AND the publishability audit is re-run

#### Scenario: Author rejects a proposal

- GIVEN the GUI shows a proposal to move "spectral servants" to sceneEntity
- WHEN the author clicks "Reject"
- THEN the entity remains as-is (default classification)
- AND the proposal is marked "rejected" in the review panel
- AND no module data is modified

### Requirement: Applied proposals SHALL persist provenance metadata

When a proposal is accepted and applied, the module SHALL record provenance metadata:
- `provenance: "llm_classification"`
- `classified_by: "<model_name>"`
- `classified_at: "<ISO timestamp>"`
- `reviewed_by: "human_author"`
- `transform: "<transform_type>"`

#### Scenario: Provenance recorded on apply

- GIVEN the author accepts a `move_entity_to_scene_entity` proposal
- WHEN the transform is applied to the area file
- THEN the sceneEntity entry includes `_provenance: {source: "llm_classification", ...}`
- AND the original monster catalog entry is annotated with `_reclassified: true`

