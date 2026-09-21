## Why

The Amphail adaptation attempt `tmp/adaptation-staging/adapt-001-43d20e6e155bc035e50f3276/revision_000` stopped at `monster_closure_unresolved` even though the source and staging data identify one canonical `Cave Guardian` stat block. The unresolved label `Cave guardians` was treated as a new plural identity (`cave_guardians`) instead of a scene label for `Cave Guardian`; Python terminated the build before the existing LLM adaptation auditor/revision workflow could see or remediate the content problem.

This change moves content interpretation and bounded remediation to the LLM finalization boundary while keeping Python authoritative for safety, validation, staging, and publication. It is linked to `toolkit-adaptation-build-output-hygiene`, which protects the bounded packets and progress surface used by this finalization path.

## What Changes

- Establish one adaptation-scoped canonical monster identity registry shared by normalization, materialization, encounter binding, revision, and publication checks.
- Map plural/group labels such as `Cave guardians` to an approved `Cave Guardian` identity when the canonical identity is source-grounded or already approved.
- Keep structured quantity separate from identity and preserve scene prose for LLM interpretation; report K08's quantity/prose contradiction as a bounded content diagnostic rather than rewriting it mechanically.
- Convert eligible content-level monster closure failures into bounded LLM revision candidates instead of terminal Python failures at revision zero.
- Persist redacted, bounded failure packets with unresolved references, candidate identities, affected locations, quantities, scene evidence, and attempt/revision identity.
- Route eligible failures through the existing adaptation auditor/revision workflow using a fresh project-relative staging target and the configured revision budget.
- Add a bounded monster-resolution/finalization operation whose accepted identities are validated by Python before any staging write.
- Rerun the complete adaptation pipeline from normalization through publication after a successful revision; publish only after all hard gates and post-write checks pass.
- Preserve terminal handling for unsafe, malformed, rights, infrastructure, schema, and path failures.
- Preserve legacy accurate-ingest and legacy ModuleBuilder behavior unchanged.
- Add exact Amphail regression coverage and keep existing adaptation, revision, publication, and provider-safety suites green.

## Capabilities

### New Capabilities

- `adaptation-content-authority-boundary`: Defines the LLM-versus-Python ownership boundary for adaptation content interpretation, remediation, and transaction safety.
- `adaptation-canonical-monster-resolution`: Defines canonical identity registry, plural/group resolution, quantity separation, scene-prose preservation, and duplicate prevention.
- `adaptation-llm-monster-closure-remediation`: Defines bounded failure packets and the validated LLM monster-resolution operation.
- `adaptation-revision-eligibility-and-budget`: Defines content failure eligibility, revision status projection, fresh staging, and budget exhaustion behavior.
- `adaptation-safe-finalization-publication`: Defines hard-gate ownership, safe LLM-to-Python handoff, full-pipeline rerun, publication ordering, and legacy isolation.

### Modified Capabilities

- None. The completed monster guardrail, identity convergence, publication convergence, runtime-unification, provider-lazy-log-safety, and media-handoff changes remain historical source material; this change adds a linked finalization boundary rather than appending tasks to them.

## Impact

- Likely implementation surfaces include `web/extensions/toolkit_homebrew_packet_builder.py`, `web/extensions/toolkit_adaptation_job_reporting.py`, `web/extensions/toolkit_adaptation_runtime.py`, `utils/toolkit_adaptation_monster_guardrail.py`, `utils/toolkit_adaptation_failure_classifier.py`, `utils/toolkit_adaptation_failure_packet.py`, `utils/toolkit_adaptation_revision.py`, `utils/toolkit_adaptation_publication_convergence.py`, and focused adaptation fixtures/tests.
- Adaptation staging and revision artifacts remain project-relative and isolated; no LLM-selected path or raw patch may reach the filesystem.
- The existing Python-owned publication transaction remains the only path that mutates the registry, campaign, or live module files.
- No new provider or dependency is required. Legacy paths, single-player behavior, and non-adaptation ModuleBuilder output remain unchanged.
- Rollback is disabling the new finalization route or reverting the adaptation-only seam; failed revisions remain unpromoted staging artifacts with bounded diagnostics.
