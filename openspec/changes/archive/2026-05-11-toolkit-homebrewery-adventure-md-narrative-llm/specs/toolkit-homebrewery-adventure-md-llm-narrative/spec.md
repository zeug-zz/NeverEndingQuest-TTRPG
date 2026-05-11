## Purpose

Define the LLM-powered narrative generation for the adventure document's introduction and plot overview lead-in. The builder SHALL use LLM calls to produce flowing prose, falling back to deterministic behavior on any failure.

## ADDED Requirements

### Requirement: SHALL generate intro section via LLM with deterministic fallback

The `_build_intro_section()` function SHALL attempt an LLM call that receives module stats, full plot text, author name, and level range, and produces three markdown sub-sections (`### Module Overview`, `### The Story So Far`, `### Running the Adventure`) in colourful fantasy prose. On any LLM failure, the function SHALL fall back to the current deterministic assembly (bullet stats, concatenated abstract, author line, running paragraph).

#### Scenario: LLM intro generation succeeds

**Given** the LLM client is available and the summarization model responds
**When** `_build_intro_section(data)` is called with 9 NPCs, 13 plot points, 4 locations, 12 creatures
**Then** the output SHALL contain `### Module Overview`, `### The Story So Far`, and `### Running the Adventure` as markdown headings

#### Scenario: LLM intro generation fails

**Given** the LLM client raises an exception or the API call times out
**When** `_build_intro_section(data)` is called
**Then** the output SHALL match the current deterministic behavior (bullet list stats, concatenated abstract, author line, running paragraph) exactly

#### Scenario: Intro LLM call uses correct model parameters

**Given** the LLM client is available
**When** the intro narrative call is made
**Then** it SHALL use temperature=0.5, max_tokens=800, and the `DM_SUMMARIZATION_MODEL`

### Requirement: SHALL generate plot overview lead-in via LLM with deterministic fallback

The `_build_plot_overview()` function SHALL attempt an LLM call that receives plot point data and produces a 1-paragraph colourful fantasy hook paragraph replacing the mechanical "The adventure follows a chain of N plot points:" line. On any LLM failure, the function SHALL fall back to a deterministic one-line summary.

#### Scenario: LLM plot hook succeeds

**Given** the LLM client is available
**When** `_build_plot_overview(data)` is called with 13 plot points
**Then** the lead-in text SHALL NOT contain the literal string "The adventure follows a chain of"

#### Scenario: LLM plot hook fails

**Given** the LLM client raises an exception
**When** the plot overview lead-in is generated
**Then** the fallback text SHALL be a one-line deterministic summary mentioning the number of scenes

#### Scenario: Plot hook LLM call uses correct model parameters

**Given** the LLM client is available
**When** the plot hook call is made
**Then** it SHALL use temperature=0.7, max_tokens=250, and the `DM_SUMMARIZATION_MODEL`

### Requirement: SHALL remove standalone _build_plot_abstract function

The standalone `_build_plot_abstract()` function SHALL be removed. Its plot summarization responsibility SHALL be absorbed into the intro LLM call's "The Story So Far" section. The concatenation fallback behavior SHALL be preserved as part of the intro section's LLM fallback path.

#### Scenario: _build_plot_abstract no longer exists

**Given** the updated `utils/homebrewery_adventure_writer.py` module
**When** the module is imported
**Then** the function name `_build_plot_abstract` SHALL NOT be present

### Requirement: SHALL sanitize LLM output through markdown sanitizer

All LLM-generated text SHALL be passed through `sanitize_markdown_text()` before inclusion in the document, to ensure ASCII safety.

#### Scenario: LLM output sanitization

**Given** the LLM returns text containing non-ASCII characters
**When** the text is processed by the intro or plot hook builder
**Then** the output SHALL contain only ASCII characters
