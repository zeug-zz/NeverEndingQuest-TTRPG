## MODIFIED Requirements

### Requirement: Audit Recommendation Routes Critical Omissions To Builder Repair

When backstage audit finds critical narrative omissions, next-step routing SHALL recommend Builder repair rather than diagnostic-only report refresh.

#### Scenario: Critical actor and puzzle omitted
- **GIVEN** backstage audit finds Kobe missing as a critical prose actor
- **AND** `skull_riddle` missing as an explicit trial puzzle
- **WHEN** recommendation is generated
- **THEN** `recommended_action` SHALL route to a Builder repair lane
- **AND** it SHALL include evidence references for the source excerpts and missing output surfaces.

## SHOULD Guidance

Prefer a lane name such as `repair_critical_narrative_omissions` so operator review can distinguish this from schema-only or report-freshness remediation.
