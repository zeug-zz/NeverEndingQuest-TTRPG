# Design: Accurate-Ingest Critical Narrative Repair Loop

## Contract Layer (MUST)

### Architecture Boundary

Python SHALL provide deterministic evidence and constraints. The LLM Builder SHALL remain responsible for source-faithful narrative synthesis.

The repair loop SHALL follow this boundary:

```text
source markdown + benchmark/source-fidelity gaps
  -> deterministic missing-critical-content evidence
  -> backstage repair brief with source excerpts and output-surface targets
  -> LLM Builder repair pass
  -> validation/benchmark/report refresh
```

Python SHALL NOT manually author Kobe, `skull_riddle`, or equivalent critical narrative content into module JSON as a release fix. Python may write tests, extraction rules, repair brief artifacts, and deterministic validation/reporting code.

### Truth Sources

- Source markdown SHALL remain the authority for narrative content.
- Benchmark fixtures and source-fidelity results SHALL identify required preservation targets.
- Module JSON SHALL remain the authority for validation and runtime publication.
- Repair briefs SHALL be intermediate instructions, not final source truth.
- `MODULE_SUMMARY.md` SHALL remain derived output and SHALL NOT be used as repair input.

### Critical Narrative Omission Model

An omission SHALL be treated as critical when source text contains an actor, puzzle, trial, objective, or failure condition that is required by benchmark expectations or clearly anchors a major adventure beat.

For Numillian, at minimum:

- Kobe SHALL be treated as a critical prose actor because she anchors the final no-win trial objective and failure condition.
- `skull_riddle` SHALL be treated as a critical puzzle because it is the first trial/gate into Shuluth's mind and has explicit mechanics.

### Failure Semantics

- If deterministic evidence finds missing critical content, release proof SHALL remain blocked until the LLM Builder repair pass succeeds or the blocker is explicitly preserved.
- If the LLM provider is unavailable during repair, the job SHALL fail closed with provider diagnostics.
- If Builder repair creates invalid JSON, schema violations, or source-fidelity regressions, release proof SHALL fail.
- If reports disagree after repair, release proof SHALL fail until refreshed or explained.

### Compatibility

- Existing non-source ModuleBuilder paths SHALL not require repair briefs.
- Existing accurate-ingest builds without critical omission evidence SHALL continue through the current path.
- Backstage audit and briefing changes SHALL remain read-only until a Builder repair pass is explicitly invoked.

## Guidance Layer (SHOULD)

### Preferred Implementation Shape

Prefer a new repair-brief utility over broad rewrites of existing ModuleBuilder code. The repair pass should reuse existing source-lock context injection, source-field handoff, and generator source-lock infrastructure where possible.

### Numillian Repair Expectations

The Builder should reconstruct the Numillian adventure arc from source excerpts, not merely add two strings. A good repair should preserve:

- Trial at the Door and Shuluth's mindscape frame.
- First Trial / skull riddle mechanics and solution.
- Second Trial / flooding room.
- False Third Trial / dog prompt.
- True Third Trial / City of the Mind.
- Final no-win scenario centered on Kobe and the Vault.

### Report Refresh

Prefer script-owned report generation. Manual report edits are acceptable only for clearly defined report-shape normalization when no owning refresh command exists, and the report must state the real blocker status.

### Builder Prompting

Builder prompts should include source excerpts, missing items, target JSON surfaces, and a hard instruction that Python has not authored the repair. The Builder must reason from source text.
