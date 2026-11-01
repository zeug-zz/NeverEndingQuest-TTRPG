# debug-tab-usage-cost-rollup Specification

## Purpose
TBD - created by archiving change debug-usage-session-week-nzd-rollup. Update Purpose after archive.

## Requirements

### Requirement: Debug tab SHALL show session/week token and cost rollups above existing token stats
The Debug tab SHALL render a compact rollup row above existing TPM/RPM/Total values, showing session and rolling-week tokens, known USD and NZD cost subtotals, actual and estimated cost provenance, unpriced-call counts, and cost completeness.

#### Scenario: Image generation updates cost rollups
- **WHEN** a successful DALL-E 3 image generation event is tracked
- **THEN** session and rolling-week USD/NZD rollup values SHALL increase on subsequent `token_update` payloads
- **AND** existing TPM/RPM/Total token values SHALL remain behaviorally unchanged for that image-cost event

#### Scenario: Chat cost provenance is visible
- **WHEN** chat usage in either window includes actual, estimated, or unpriced responses
- **THEN** the Debug rollup SHALL display actual and estimated known-cost subtotals, unpriced-call counts, and cost completeness for that window
- **AND** it SHALL NOT present an unpriced call as free or include it in the known-cost subtotal

### Requirement: Debug tab SHALL consume additive token_update payload fields
The client SHALL bind new rollup fields from `token_update` payloads while remaining compatible with payloads that contain only legacy fields.

#### Scenario: Full payload update
- **WHEN** `token_update` includes session and week cost/token fields
- **THEN** the Debug tab SHALL display those values with localized numeric formatting

#### Scenario: Partial payload compatibility
- **WHEN** `token_update` omits one or more new rollup fields
- **THEN** missing values SHALL render as zero/default placeholders and no UI error shall occur

### Requirement: UI updates SHALL remain non-blocking
Rollup rendering SHALL not block debug message rendering or game output flow.

#### Scenario: High-frequency updates
- **WHEN** debug output and token updates arrive in quick succession
- **THEN** both streams SHALL continue rendering without freezing the Debug panel

### Requirement: Debug rollups SHALL preserve additive payload compatibility
New provenance and completeness fields SHALL be additive to the existing `token_update` payload and SHALL NOT change legacy token-stat behavior.

#### Scenario: Provenance fields are present
- **WHEN** `token_update` contains session/week actual-cost, estimated-cost, unpriced-count, and completeness fields
- **THEN** the Debug tab SHALL render those values in the matching session or week rollup
- **AND** localized numeric formatting and existing TPM/RPM/Total rendering SHALL remain intact

#### Scenario: Older payload omits provenance fields
- **WHEN** `token_update` omits one or more provenance or completeness fields
- **THEN** the Debug tab SHALL use safe default placeholders without a client error
- **AND** existing token-stat fields SHALL continue to render as before
