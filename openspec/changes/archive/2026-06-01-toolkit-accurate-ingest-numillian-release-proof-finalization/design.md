# Design: Accurate-Ingest Numillian Release-Proof Finalization

## Contract Layer (MUST)

### Architecture Boundary

This change SHALL run after the archived accurate-ingest recovery chain. It SHALL not replace ModuleBuilder, benchmark logic, or publication gates. It SHALL finalize one production module: `modules/The_Hidden_City_of_Numillian/`.

The release-proof boundary is:

```text
current Numillian artifacts
  -> diagnostic-only blocker snapshot
  -> smallest source-faithful artifact repairs
  -> monster artifact finalization or explicit unresolved blockers
  -> report refresh and cross-report consistency
  -> release proof audit
```

### Truth Sources

- Source-fidelity benchmark results SHALL remain the source-preservation evidence for NPC, location, puzzle, lore, and tone categories.
- Module JSON artifacts SHALL be the source for validation and publishability.
- Existing source monster refs and encounter seeds SHALL drive monster finalization; reports SHALL document results but SHALL NOT create source truth.
- `MODULE_SUMMARY.md` SHALL be derived from final audited module JSON only.

### Failure Semantics

- If semantic audit blockers remain, publishability SHALL remain blocked.
- If source monster refs cannot be safely materialized, unresolved refs SHALL be explicit blockers or diagnostics.
- If report artifacts disagree, release proof SHALL fail until reports are refreshed or the disagreement is explained.
- If source-fidelity categories regress, finalization SHALL fail.

### Compatibility

- Legacy modules and non-source accurate-ingest paths SHALL not be modified by this change.
- Runtime files SHALL remain ignored and SHALL not be required for release proof.
- No provider calls are required for diagnostic and deterministic report-refresh steps.

## Guidance Layer (SHOULD)

### Preferred Sequencing

1. Capture current blocker state with existing audit commands.
2. Patch the smallest source-faithful semantic artifact issue.
3. Finalize monster artifacts with reuse-first helpers.
4. Refresh reports in dependency order: validation, benchmark/source-fidelity, toolkit build, publishability.
5. Verify no runtime artifacts are required for publication.

### Semantic Closure

Prefer editing generated phrase/title text that creates false destination extraction over suppressing audit findings. Preserve the underlying Gatepact/Kobe plot meaning.

### Monster Finalization

Prefer existing module-local/SRD/bestiary-compatible templates. Do not create a made-up stat block from a name alone. If a source monster cannot be resolved safely, preserve it as explicit unresolved materialization output.

### Report Refresh

Prefer existing scripts and finisher/report helpers. Avoid hand-editing reports except where a script explicitly owns the artifact shape and no safer refresh entrypoint exists.
