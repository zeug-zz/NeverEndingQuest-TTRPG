# toolkit-homebrewery-adventure-md-plot-abstract Specification

## Purpose
TBD - created by archiving change toolkit-homebrewery-adventure-md-cleanup. Update Purpose after archive.
## Requirements
### Requirement: SHALL attempt LLM summarization of all plot point descriptions

The builder SHALL attempt to generate a 2-3 paragraph narrative abstract by sending all plot point titles and descriptions to the DM summarization model (`DM_SUMMARIZATION_MODEL`). The prompt SHALL instruct the model to produce a third-person narrative summary of the overall arc, key locations, and central conflict without listing individual plot points.

#### Scenario: LLM abstract generation

**Given** a module with 13 plot points each containing description text
**When** `_build_plot_abstract(data)` is called and the LLM is available
**Then** the output SHALL be a 2-3 paragraph narrative abstract that does NOT enumerate individual plot points by ID

### Requirement: SHALL fall back to deterministic concatenation on LLM failure

If the LLM call fails (timeout, provider error, import failure, or any exception), the builder SHALL fall back to concatenating the first 300 characters of the first plot point's description with the first 300 characters of the final plot point's description, joined by a transition phrase.

#### Scenario: LLM unavailable

**Given** the LLM client factory raises an exception or the API call times out
**When** `_build_plot_abstract(data)` is called
**Then** the output SHALL contain text from PP001's description followed by a transition phrase and text from the final plot point's description

### Requirement: SHALL return placeholder when no plot points exist

If the module has no plot points, the builder SHALL return a deterministic placeholder string noting the absence.

#### Scenario: No plot points

**Given** a module with an empty plot_points list
**When** `_build_plot_abstract(data)` is called
**Then** the output SHALL be `*No plot data available for summary.*`

### Requirement: SHALL set low temperature and bounded token limit for summary

The LLM call SHALL use temperature 0.3 for factual consistency and a max_tokens limit of 400 to control cost and prevent runaway generation.

#### Scenario: LLM parameters

**Given** the LLM client is available
**When** the plot abstract summarization call is made
**Then** it SHALL use temperature=0.3 and max_tokens=400

