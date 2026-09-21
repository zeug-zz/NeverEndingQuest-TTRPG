## 1. Guardrail Foundation

- [x] 1.1 Add a provider-free adaptation monster guardrail utility that extracts bounded adversaries from the adaptation dossier, invokes accurate-ingest resolution/binding helpers, and returns a versioned report.
- [x] 1.2 Add deterministic normalization for adaptation `location.monsters[]` entries, including quantity stripping, canonical creature matching, NPC/ally classification, and preservation of descriptive prose outside structural monster identity.
- [x] 1.3 Add schema-sufficiency and unresolved-reference diagnostics for canonical adaptation monster references without inventing replacement identities.
- [x] 1.4 Add provider-free guardrail tests covering canonical matches, NPC/ally phrases, ambiguous prose, encounter binding, deterministic reports, and legacy isolation.

## 2. Staging-Safe Materialization

- [x] 2.1 Add an optional explicit output-directory argument to `core/generators/monster_builder.py`, preserving module-derived output behavior when omitted.
- [x] 2.2 Update adaptation materialization to reuse schema-sufficient module, reusable, or compendium artifacts into staging before any generation.
- [x] 2.3 Ensure any allowed canonical monster generation writes and verifies artifacts only under the active staging directory.
- [x] 2.4 Add staging-isolation tests proving failed adaptation attempts do not write new files under `modules/<module_slug>/`.
- [x] 2.5 Normalize existing monster filenames with the same canonicalization used for references before closure comparison.

## 3. Adaptation Pipeline Integration

- [x] 3.1 Invoke the semantic guardrail immediately before adaptation monster closure and persist its report in `build_result`.
- [x] 3.2 Prevent adaptation mode from invoking blind legacy generation for raw prose references; retain the legacy closure path for non-adaptation builds.
- [x] 3.3 Make the generic closure a final consistency check after adaptation normalization/materialization, with unresolved canonical references remaining fail-closed.
- [x] 3.4 Add an integration fixture based on the Hostis failure shape proving rich module artifacts survive monster normalization and reach the normal gates.
- [x] 3.5 Normalize generated `location.monsters[]` before adaptation materialization, merge all canonical normalized refs with dossier/source-reconciled refs, materialize every allowed canonical ref in the active staging directory, then run generic closure with `allow_generation=False`; persist a bounded post-normalization materialization report and add regressions for generated-ref materialization, reuse, bounded source-backed generation, unresolved blocking, filepath-first area writes, and legacy ModuleBuilder compatibility.

## 4. Truthful Failure Reporting

- [x] 4.1 Persist `build_result.json` or an equivalent current failure artifact on every early adaptation blocker path.
- [x] 4.2 Attach bounded failure classification for semantic guardrail, materialization, and closure failures before terminal job state is stored.
- [x] 4.3 Prevent retry and finishing routes from using stale readiness or finishing artifacts from an earlier attempt.
- [x] 4.4 Add reporting tests proving concrete failure codes reach the adaptation status envelope while raw provider payloads remain hidden.

## 5. Verification And Rollout

- [x] 5.1 Run provider-free guardrail, materialization, adaptation pipeline, and reporting test suites with `.venv/bin/python`.
- [x] 5.2 Run syntax checks and the relevant OpenSpec contract tests for legacy ModuleBuilder and adaptation paths.
- [x] 5.3 Replay the Hostis Humanis Generis staging attempt without new LLM generation and verify context, plot, areas, maps, summary, and resolvable monsters.
- [x] 5.4 Generalize reuse-first resolution across all supplied reusable roots, enable bounded LLM stat completion for approved canonical identities with source/SRD context and staging-only schema verification, replay a fresh Hostis staging attempt, and run module validation, readiness, gameplay, and publication checks on the repaired module before enabling the adaptation guardrail by default.
- [x] 5.5 Update this task list immediately when each implementation and verification step is completed.
