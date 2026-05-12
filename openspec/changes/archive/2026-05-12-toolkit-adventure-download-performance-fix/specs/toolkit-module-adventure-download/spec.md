## MODIFIED Requirements

### Requirement: SHALL expose an API endpoint for adventure markdown download

The web interface SHALL expose `GET /api/toolkit/modules/<slug>/adventure.md` that returns the generated Homebrewery V3 adventure markdown. The endpoint SHALL first check for a pre-generated file at `modules/<slug>/MODULE_SUMMARY.md`. If the file exists and contains sufficient content (>500 bytes), it SHALL be served directly without regeneration. If no pre-generated file exists, the endpoint SHALL fall back to calling `generate_homebrewery_adventure(slug)` and writing the result to `MODULE_SUMMARY.md` for future requests.

#### Scenario: Pre-generated summary exists on disk

**Given** a module that has completed the toolkit build or ingest pipeline
**When** `GET /api/toolkit/modules/The_Thornwood_Watch/adventure.md` is requested
**Then** the response SHALL return the contents of `modules/The_Thornwood_Watch/MODULE_SUMMARY.md` within 500ms
**Then** the response SHALL NOT trigger any LLM API calls

#### Scenario: No pre-generated summary exists (legacy module)

**Given** a legacy module without a `MODULE_SUMMARY.md` file
**When** the adventure download is requested
**Then** the endpoint SHALL call `generate_homebrewery_adventure(slug)` to generate content
**Then** the result SHALL be written to `modules/<slug>/MODULE_SUMMARY.md` for future requests
**Then** subsequent requests for the same module SHALL serve the cached file

#### Scenario: Pre-generated summary is too short or corrupt

**Given** a module where `MODULE_SUMMARY.md` exists but contains fewer than 500 bytes
**When** the adventure download is requested
**Then** the endpoint SHALL regenerate via `generate_homebrewery_adventure()` and overwrite the file

### Requirement: SHALL show loading state on download button

The `downloadAdventure()` JavaScript function SHALL disable the clicked button and change its text to "Generating..." during the download request. On completion (success or error), the button SHALL be re-enabled and its original text SHALL be restored.

#### Scenario: Button shows loading state during fetch

**Given** the `[Download Adventure]` button is clicked for any module
**When** the fetch to the adventure endpoint is in progress
**Then** the button text SHALL change to "Generating..."
**Then** the button SHALL be disabled

#### Scenario: Button restores on completion

**Given** the download fetch completes (either success or error)
**When** the response is received
**Then** the button text SHALL be restored to "Download Adventure"
**Then** the button SHALL be re-enabled
