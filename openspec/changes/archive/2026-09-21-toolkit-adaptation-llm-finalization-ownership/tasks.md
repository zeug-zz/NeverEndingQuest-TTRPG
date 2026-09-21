## 1. Canonical Content Boundary

- [x] 1.1 Build one adaptation-scoped canonical monster identity registry that combines dossier/source-approved identities, existing staging/reusable artifacts, bounded aliases, raw-reference provenance, affected locations, and encounter references; add provider-free registry tests.
- [x] 1.2 Integrate registry-driven normalization so plural/group labels such as `Cave guardians` resolve to approved `Cave Guardian` without creating `cave_guardians.json`; preserve K06 quantity 1, K08 quantity 1, RTR001/K10 quantity 2, and bounded scene prose/contradiction evidence.

## 2. Failure Packet And Classification

- [x] 2.1 Add a redacted, bounded monster-content failure packet with normalized reference, approved/candidate identities, affected locations, quantities, bounded scene evidence, attempt/revision identity, budget state, and no raw source/provider/path leakage; add exact Amphail packet tests.
- [x] 2.2 Update adaptation failure classification, gate revision projection, and job reporting so eligible source-grounded monster content failures are revision-eligible at revision zero while unsafe, malformed, rights, infrastructure, schema, path, and transaction failures remain terminal; preserve concrete status codes across surfaces.

## 3. LLM Finalization Contract And Revision Routing

- [x] 3.1 Extend the adaptation finalization contract with a bounded `resolve_monster_reference` operation or equivalent revised-dossier contract; validate approved identity, target reference, quantity bounds, source references, attempt/revision freshness, and reject arbitrary paths, raw patches, substitutions, and extra fields.
- [x] 3.2 Route eligible monster content failures through the existing LLM adaptation auditor/revision workflow with a fresh project-relative staging target, one bounded operation per revision round, immutable prior revision evidence, and configured revision-budget accounting; provider-free tests must prove the initial failure reaches remediation.
- [x] 3.3 Preserve provider-safe failure and refusal behavior for malformed, unavailable, timeout, or unsafe finalization responses; no raw provider payloads or credentials may enter failure packets, reports, GUI envelopes, or filesystem writes.

## 4. Full Pipeline And Publication Boundary

- [x] 4.1 Re-enter the adaptation pipeline from normalization after accepted monster remediation and rerun closure, spatial/semantic convergence, readiness, gameplay, report agreement, Markdown, registry, campaign, and rollback checks; report `adaptation_revision_required` before revision and exhaustion only after budget consumption.
- [x] 4.2 Enforce the Python hard-safety/publication boundary so LLM content readiness cannot start publication before all hard gates, artifact identity/freshness checks, and post-write verification pass; preserve live-module isolation on failed revisions.
- [x] 4.3 Verify legacy accurate-ingest, concept-builder, single-player, and non-adaptation ModuleBuilder paths remain unchanged and receive no adaptation metadata or finalization routing.

## 5. Regression And Verification

- [x] 5.1 Add exact Amphail regression coverage: `Cave guardians` resolves `cave_guardian.json`, no plural file is generated, K06/K08/K10 quantities remain correct, K08 contradiction reaches LLM context, revision 0 is eligible, fresh staging is used, and publication is withheld until hard gates pass.
- [x] 5.2 Run focused adaptation monster, identity, revision, failure-classifier, job-reporting, publication-convergence, staging, provider-safety, and legacy compatibility suites; run syntax checks, `git diff --check`, ASCII checks, and strict OpenSpec validation for this change.
- [x] 5.3 Update this task list only after each task passes planner verification and record the final end-to-end result without archiving or committing.

## Final Verification Record

2026-08-17: Planner verification complete. The full adaptation-focused batch passed 327/327 tests; focused gates, publication/convergence, revision, legacy/adaptation, and source-context/config suites also passed. Touched implementation and test files passed `py_compile`; the targeted ASCII scan reported 0 violations across 88 files; `git diff --check` passed; and `openspec validate toolkit-adaptation-llm-finalization-ownership --strict` passed. The change is ready for archive review and was not archived or committed.
