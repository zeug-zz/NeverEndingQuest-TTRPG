# Phase 2 LLM Entity Triage

## Purpose

Classify ambiguous authored entities (creatures, monsters, NPCs) into combat-capable or scene-only categories before they enter the structured module schema.

## ADDED Requirements

### Requirement: Entity ambiguity detection SHALL precede LLM classification

When the deterministic builder extracts candidate entities from authored prose, entities that MATCH known bestiary entries SHALL bypass classification (deterministic truth wins). Only entities that fail bestiary lookup SHALL be batched for LLM classification.

#### Scenario: Known monster bypasses classification

- GIVEN the author mentions "a wight in the crypt"
- AND "wight" matches a bestiary file at `data/bestiary/wight.json`
- WHEN the ambiguity detector runs
- THEN "wight" is NOT sent to LLM classification
- AND "wight" is treated as `combatant` by default

#### Scenario: Unknown entity triggers classification

- GIVEN the author mentions "spectral servants drift through the hall"
- AND "spectral servants" does NOT match any bestiary file or known monster template
- WHEN the ambiguity detector runs
- THEN "spectral servants" IS added to the entity classification batch

### Requirement: LLM entity classification SHALL return validated enum labels

The LLM SHALL return one of `combatant`, `scene_illusion`, or `narrator_flavor` for each ambiguous entity. Python SHALL validate every label against this enum. Unrecognized labels SHALL fall back to `narrator_flavor`.

#### Scenario: Valid classification applied

- GIVEN the LLM classifies "spectral servants" as `scene_illusion`
- WHEN Python validates the label
- THEN the classification is accepted
- AND the entity is emitted as scene entity metadata, not in monsters[]

#### Scenario: Hallucinated label falls back

- GIVEN the LLM classifies "phantoms" as `ghost_type` (invalid label)
- WHEN Python validates the label
- THEN the label is rejected
- AND the entity falls back to `narrator_flavor`

### Requirement: Entity classification SHALL be fail-open

When the LLM API call fails (timeout, error, quota), the classification SHALL degrade to treating all ambiguous entities as `combatant`. The build SHALL continue without blocking.

#### Scenario: API failure during classification

- GIVEN the LLM API returns a 503 error during entity classification
- WHEN the classification engine handles the error
- THEN all ambiguous entities are treated as `combatant`
- AND the build continues
- AND a warning is logged: "LLM entity classification degraded: API error"

### Requirement: Classified entities SHALL be cached by content hash

Classification results SHALL be stored at `modules/<slug>/llm_classification_cache.json` keyed by `sha256(authored_text)`. Subsequent builds with unchanged authored text SHALL reuse cached classifications without calling the LLM.

#### Scenario: Cache hit on re-build

- GIVEN "spectral servants" was classified as `scene_illusion` on first build
- AND the authored text has not changed
- WHEN the module is re-ingested
- THEN the cached classification `scene_illusion` is used
- AND no LLM call is made

#### Scenario: Cache miss on text change

- GIVEN "spectral servants" was classified as `scene_illusion`
- AND the author updates the text to "spectral guardians attack"
- WHEN the module is re-ingested
- THEN the cache is invalidated (hash mismatch)
- AND a new LLM classification call is made

### Requirement: Combatant-classified entities SHALL pass readiness gates

Entities classified as `combatant` SHALL be treated as real combatants. They MUST have valid monster files, media, and schema compliance. Missing combatant resources SHALL fail readiness gates as before.

#### Scenario: Combatant without monster file fails readiness

- GIVEN "shadow hound" is classified as `combatant`
- AND no `shadow_hound.json` exists in the bestiary
- WHEN the readiness gate runs
- THEN the module fails readiness with a monster reference error

### Requirement: Scene-illusion entities SHALL NOT trigger monster requirements

Entities classified as `scene_illusion` SHALL be emitted as `sceneEntity` metadata in the location file. They SHALL NOT appear in the monsters catalog, SHALL NOT require monster files, and SHALL NOT trigger media requirements.

#### Scenario: Scene illusion bypasses monster schema

- GIVEN "spectral servants" is classified as `scene_illusion`
- WHEN the module is emitted
- THEN no `spectral_servants.json` monster file is required
- AND no monster media is required
- AND the entity appears as `sceneEntity` in the location JSON

### Requirement: Narrator-flavor entities SHALL be prose-only

Entities classified as `narrator_flavor` SHALL remain in prose text only. They SHALL NOT appear in any structured JSON field (monsters, sceneEntity, NPCs).

#### Scenario: Flavor entity stays in prose

- GIVEN "the wind sounds like a dying scream" contains entity "dying scream"
- AND it is classified as `narrator_flavor`
- WHEN the module is emitted
- THEN "dying scream" appears in the location description text only
- AND no structured JSON field references it
