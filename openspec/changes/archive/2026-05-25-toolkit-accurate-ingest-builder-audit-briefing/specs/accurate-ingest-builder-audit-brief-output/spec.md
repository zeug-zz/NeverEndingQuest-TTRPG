## ADDED Requirements

### Requirement: Brief Generator SHALL emit compact builder artifacts

The brief generator SHALL emit compact builder-facing artifacts derived from the audit run.

Output artifacts SHALL be:

- `builder_brief.json`
- `builder_prompt_context.md`

#### Scenario: JSON brief preserves audit summary

- **GIVEN** a valid audit run
- **WHEN** `builder_brief.json` is written
- **THEN** it SHALL include `task_id`, `module_slug`, `audit_output_dir`, `recommended_action`, `reason`, `builder_lane`, `evidence_refs`, grouped finding counts, and report-consistency summary
- **AND** it SHALL NOT embed full raw report bodies.

#### Scenario: Markdown context is builder-readable

- **GIVEN** a valid audit run
- **WHEN** `builder_prompt_context.md` is written
- **THEN** it SHALL include a compact module summary, recommendation, builder lane, evidence references, report-consistency summary, and top findings
- **AND** it SHALL include a warning that the brief is advisory and cannot override deterministic gates.

### Requirement: Brief Generator SHALL preserve evidence traceability

The brief generator SHALL preserve evidence references from the audit report and recommendation.

#### Scenario: Evidence refs are copied compactly

- **GIVEN** an audit recommendation with evidence references
- **WHEN** the builder brief is written
- **THEN** the same evidence references SHALL appear in `builder_brief.json`
- **AND** the Markdown context SHALL list those evidence references.
