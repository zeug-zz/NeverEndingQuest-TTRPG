# phase2-llm-destination-classification Specification

## Purpose
TBD - created by archiving change phase2-llm-classification. Update Purpose after archive.
## Requirements
### Requirement: Destination phrase detection SHALL identify ambiguous phrases

Phrases that deterministic extraction identifies as potential destinations but cannot resolve to known area IDs SHALL be batched for LLM classification.

#### Scenario: Unresolved phrase triggers classification

- GIVEN authored text says "the path winds toward the Veiled Paradox"
- AND deterministic extraction finds "Veiled Paradox" does not resolve to any known area or alias
- WHEN the ambiguity detector runs
- THEN "Veiled Paradox" IS added to the destination classification batch

#### Scenario: Resolved phrase bypasses classification

- GIVEN authored text says "the path leads to the Inner Sanctum"
- AND "Inner Sanctum" matches a known area alias
- WHEN the ambiguity detector runs
- THEN "Inner Sanctum" is NOT sent to LLM classification

### Requirement: LLM destination classification SHALL return validated enum labels

The LLM SHALL return one of `canonical_alias`, `quest_objective`, or `evocative_prose` for each ambiguous phrase. Python SHALL validate labels. Unrecognized labels SHALL fall back to `evocative_prose`.

#### Scenario: Canonical alias adds to travel authority

- GIVEN "the Veiled Paradox" is classified as `canonical_alias`
- WHEN Python validates the label
- THEN the phrase is added to the location's alias list
- AND the travel authority map is regenerated

#### Scenario: Quest objective stays in plot guidance

- GIVEN "find the Soulforge" is classified as `quest_objective`
- WHEN Python validates the label
- THEN the phrase remains in plot/objective fields
- AND it does NOT feed the travel authority map
- AND travel probes do NOT depend on it

#### Scenario: Evocative prose is excluded from travel maps

- GIVEN "a destiny whispered on the wind" is classified as `evocative_prose`
- WHEN Python validates the label
- THEN the phrase is excluded from all structured travel fields
- AND it remains in prose only

### Requirement: Destination classification SHALL be fail-open

On API failure, all ambiguous phrases SHALL be treated as `canonical_alias` (most permissive). The build SHALL continue.

#### Scenario: API failure during destination classification

- GIVEN the LLM API fails during destination classification
- WHEN the classification engine handles the error
- THEN all ambiguous phrases are treated as `canonical_alias`
- AND the build continues
- AND a warning is logged

### Requirement: Classified destinations SHALL be cached by content hash

Classifications SHALL be cached per the same cache contract as entity triage: `modules/<slug>/llm_classification_cache.json`, keyed by `sha256(authored_text)`. Unchanged text MUST reuse cached classifications without an LLM call.

#### Scenario: Cached classification reused on unchanged text

- GIVEN a destination phrase "Veiled Paradox" was previously classified as `canonical_alias`
- AND the authored text has not changed
- WHEN the ambiguity detector runs again
- THEN the cached classification is reused
- AND no LLM call is made

