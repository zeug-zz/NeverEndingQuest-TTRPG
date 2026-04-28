# phase2-llm-npc-visibility-classification Specification

## Purpose
TBD - created by archiving change phase2-llm-classification. Update Purpose after archive.
## Requirements
### Requirement: NPC mention detection SHALL identify ambiguous visibility

Authored NPC mentions that deterministic extraction cannot classify as definitely visible or definitely hidden SHALL be batched for LLM classification.

#### Scenario: Ambiguous mention triggers classification

- GIVEN authored text says "you hear whispers from the shadows"
- AND deterministic extraction detects an NPC mention but cannot determine visibility
- WHEN the ambiguity detector runs
- THEN the NPC mention IS added to the visibility classification batch

#### Scenario: Definitive mention bypasses classification

- GIVEN authored text says "the innkeeper Thalen stands behind the bar"
- AND deterministic extraction classifies this as `visible` (explicit presence)
- WHEN the ambiguity detector runs
- THEN this NPC mention is NOT sent to LLM classification

### Requirement: LLM visibility classification SHALL return validated enum labels

The LLM SHALL return one of `visible`, `hidden_reveal`, or `lore_only` for each ambiguous NPC mention. Python SHALL validate labels. Unrecognized labels SHALL fall back to `lore_only`.

#### Scenario: Visible NPC populates visibility arrays

- GIVEN "the watch captain patrols the walls" is classified as `visible`
- WHEN Python validates the label
- THEN the NPC's `visible_location_ids` is populated
- AND semantic probes treat the NPC as visible

#### Scenario: Hidden/reveal NPC populates reveal authority

- GIVEN "something skitters in the darkness" is classified as `hidden_reveal`
- WHEN Python validates the label
- THEN the NPC's reveal authority metadata is populated
- AND semantic probes treat the NPC as revealable

#### Scenario: Lore-only NPC excluded from visibility

- GIVEN "legends speak of the ancient king" is classified as `lore_only`
- WHEN Python validates the label
- THEN the NPC has no visibility or reveal data
- AND semantic probes do NOT check for this NPC's presence

### Requirement: Visibility classification SHALL be fail-open

On API failure, all ambiguous NPC mentions SHALL be treated as `visible` (most permissive). The build SHALL continue.

#### Scenario: API failure defaults to visible

- GIVEN the LLM API fails during NPC visibility classification
- WHEN the classification engine handles the error
- THEN all ambiguous NPC mentions are treated as `visible`
- AND the build continues

### Requirement: Classified NPC visibility SHALL be cached by content hash

NPC visibility classifications SHALL be cached per the same content-hash contract as other classification domains. Unchanged text MUST reuse cached classifications without an LLM call.

#### Scenario: Cached NPC visibility reused on unchanged text

- GIVEN an NPC mention was previously classified as `hidden_reveal`
- AND the authored text has not changed
- WHEN the ambiguity detector runs again
- THEN the cached classification is reused
- AND no LLM call is made

