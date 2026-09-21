## 1. Existing Pipeline Seams

- [x] 1.1 Inventory and lock the existing spatial normalizer, semantic-authority builder, readiness gate, gameplay audit, and publishability gate interfaces with provider-free contract tests.
- [x] 1.2 Add an adaptation-only convergence/finalization orchestrator seam that consumes the completed monster-guardrail staging revision, writes only staging revisions, and enforces a bounded attempt budget.

## 2. Spatial Convergence

- [x] 2.1 Normalize invalid direct-grid connectivity using the existing spatial topology contract, preserving unambiguous logical area/module edges and recording changed-edge provenance.
- [x] 2.2 Add fail-closed diagnostics for ambiguous, malformed, or non-repairable map topology without silently deleting authored links.
- [x] 2.3 Add Hostis-shaped regression coverage proving rich maps survive normalization and invalid `map_WM002`-style edges no longer block when safely reclassified.

## 3. Semantic Authority

- [x] 3.1 Build and persist current-attempt `semantic_authority` from authored context, areas, plot, source manifest, and normalized packet evidence using existing semantic-authority utilities.
- [x] 3.2 Resolve unique destination phrases to canonical location IDs with aliases and provenance; preserve unresolved phrases as bounded blockers.
- [x] 3.3 Add semantic-authority and destination-resolution regression tests for `moonlit-shrine`-style source phrases, missing authority, and ambiguous candidates.

## 4. LLM Ambiguity Resolution

- [x] 4.1 Add a bounded Module Builder LLM proposal contract for ambiguous destinations containing only the phrase, bounded candidates, source references, and topology summary.
- [x] 4.2 Define whitelisted finalization operations for destination aliases, bounded narrative completion, and canonical stat completion requests; reject structural, identity, authority, and arbitrary-file edits.
- [x] 4.3 Validate proposals in Python against canonical IDs, source evidence, topology, confidence, allowed operations/fields, and current attempt identity before applying them.
- [x] 4.4 Persist provider failures, malformed proposals, rejected proposals, accepted provenance, proposal hashes, and attempt-budget state with bounded status fields; never expose raw provider payloads or mutate live files.
- [x] 4.5 Add provider-free tests with injected proposal responses plus provider-tripwire, invalid-operation, malformed-output, timeout, and bounded-retry tests.

## 5. Gate Integration

- [x] 5.1 Run convergence before readiness, gameplay, and publishability checks; reject stale reports from other attempts or revisions; and rerun relevant checks after each accepted repair. The convergence result/report now carries the validated current staging `source_hash`, with provider-free stage-order, identity-refusal, gate-marker, callback-failure, report-preservation, and legacy-isolation regression coverage.
- [x] 5.2 Re-run schema, readiness, gameplay, semantic, and publication gates against the final converged staging revision.
- [x] 5.3 Define adaptation `playable_status`, `publishable_status`, and informational source-fidelity reporting without weakening structural or gameplay gates.
- [x] 5.4 Keep legacy ModuleBuilder and non-adaptation paths unchanged; add source-contract tests proving no convergence metadata leaks into legacy results.

## 6. Verification And Rollout

- [x] 6.1 Replay the Hostis staging failure shape through spatial convergence, semantic authority, bounded finalization, and all final gates without mutating the live module.
- [x] 6.2 Verify a complete playable staging module: schema-valid, topology-valid, semantic-authority complete, gameplay-ready, and publishable, with all reports tied to one attempt/revision.
- [x] 6.3 Document the fixed finalization attempt budget, feature-flag/default rollout, provider outage behavior, rollback, terminal blocker behavior, and exact promotion boundary for a passing staging revision.
- [x] 6.4 Add a regression proving the finalizer can complete an approved canonical monster stat request without changing its identity or bypassing the monster guardrail.
- [x] 6.5 Update this task list immediately when each implementation and verification step is completed.

## 7. Semantic Authority Collision Hardening (Follow-up Slice)

- [x] 7.1 Harden destination evidence so exact authored aliases seed canonical authority without generating independent unresolved destination blockers from token windows derived only from alias text; preserve real unresolved player-facing phrases found in authored prose as blockers.
- [x] 7.2 Add area-scoped internal location identity for duplicate raw location IDs (for example, `EVR001:K01` and `FC001:K01`) so location names, aliases, destination resolutions, shortform anchors, and scene authority cannot be overwritten by last-write-wins indexing; preserve raw `location_id` compatibility fields for existing consumers.
- [x] 7.3 Add provider-free regressions covering alias phrases with trailing terminal words, duplicate location IDs across areas, unique area-qualified resolution, ambiguous raw-ID resolution, correct provenance, and legacy modules whose location IDs are already globally unique.
- [x] 7.4 Recompute the current staging semantic-authority report and verify the final payload is tied to the current attempt/revision, contains no synthetic alias-window blockers, and does not mutate live module, registry, campaign, or runtime files.

## 8. Production Destination-Resolution Closure

- [x] 8.1 Build current staged semantic authority and a bounded repair context from the source manifest, normalized packet, source graph, staged module, canonical area-scoped location IDs, source references, and topology; preserve current attempt, revision, and source identity.
- [x] 8.2 Expose an explicit bounded provider request to the existing convergence callback containing only the repair context, one ambiguous phrase, bounded candidates, and allowed operation contract; preserve callback/provider safety, the three-attempt budget, one-operation-per-round limit, 30-second timeout, and legacy isolation. The adaptation packet-builder forwards the prepared context only for repairable adaptation ambiguity, and the existing callback emits a bounded destination-resolution request without raw module/provider data.
- [x] 8.3 Validate and atomically apply an accepted `resolve_destination_alias` operation to staging only, requiring one canonical area-scoped target, supported source evidence, topology compatibility, confidence, current identity, provenance, and input/output hashes; refresh authority and rerun relevant and full gates. Verified with provider-free staging/rollback and post-application gate-consumption tests.
- [x] 8.4 Continue to finisher/publication only when current reports and every hard gate agree for the same attempt, revision, and source identity; provider failure, rejection, unresolved ambiguity, stale context, or invalid proposals remain concrete blockers with no promotion. Verified with provider-free continuation identity/all-gate tests and finisher boundary wiring.
- [x] 8.5 Add provider-free Amphail production-path regression coverage for the `softstone inn` ambiguity, including the real packet-builder production seam, legacy isolation, compile, ASCII, git diff, and strict OpenSpec verification; verified with the Amphail finalization suite (15 tests), convergence/gate regressions, compile, ASCII, diff, and strict OpenSpec validation.
