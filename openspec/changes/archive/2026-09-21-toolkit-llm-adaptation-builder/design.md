## Context

The current Homebrew path has separate routing, normalization, packet building, readiness, finishing, Markdown, and registry stages. Accurate-ingest artifacts and final reconciliation utilities already provide useful validation, atomic-write, and diagnostic primitives, but their publication semantics assume literal source-fidelity preservation.

This change introduces a separate adaptation mode. The LLM authors a bounded adaptation dossier and ModuleBuilder produces a fresh module from that dossier. Python validates the generated module and controls publication. See `proposal.md` for the motivation and user-facing objective.

## Goals / Non-Goals

**Goals:**

- Make adaptation a first-class, observable build mode.
- Keep creative authorship in the LLM and ModuleBuilder.
- Keep structural truth, validation, persistence, and registration in Python.
- Make semantic failure produce one bounded LLM revision and a fresh rebuild.
- Make Markdown generation and registry registration part of one publication transaction.
- Provide an optional, read-only world-narrative context boundary.

**Non-Goals:**

- Do not make the LLM a direct file-system or campaign-state writer.
- Do not replace schema/readiness/publishability validators with model judgment.
- Do not preserve every source atom or claim literal source fidelity.
- Do not implement background Titan mutation in this change.

## Decisions

### Use a versioned adaptation dossier

The LLM will return a strict JSON dossier that describes the adapted module concept. ModuleBuilder consumes the dossier as builder input. Python validates the dossier shape and provenance before generation, but does not decide its narrative content.

Alternative rejected: asking one LLM call to emit an entire module directory. That creates oversized responses, weak file-level recovery, and poor compatibility with existing ModuleBuilder stages.

### Separate source context from source authority

Raw source text, bounded source summaries, and source manifests are context inputs. They are not mandatory rosters. The adaptation author may retain, omit, merge, or reinterpret source material and must record those decisions.

Alternative rejected: passing deterministic atom lists as required locks, which recreates the catalogue and bogus-heading failure mode.

### Route non-room sources directly to adaptation

Readable sources with unknown, catalogue, lore, or other non-room structures will not be blocked solely by the deterministic normalization gate. The adaptation author chooses an appropriate source profile and creates an NEQ-compatible playable frame.

### Use staged fresh rebuilds for semantic revision

The initial build and any revised build will target an isolated staging location or backup-safe rebuild target. The final LLM auditor returns a revised dossier or rebuild directive, not arbitrary live-file patches.

Alternative rejected: applying LLM patches directly to the partially published module. That would make rollback and report freshness unreliable.

### Let Python be the publication transaction authority

The adaptation flow will run schema, mechanical closure, readiness, semantic, report, and Markdown checks before registry integration. Registry integration is the last stateful publication step and is verified afterward.

### Make source fidelity informational in adaptation mode

Adaptation reports will explicitly state that literal source fidelity is not applicable. Legacy fidelity evidence may be retained for provenance but cannot block a module that passes playable publication gates.

Alternative rejected: mapping adaptation output to `reconciled_degraded`, which would falsely imply a source-fidelity repair rather than an intentional rewrite.

### Use bounded read-only world context

The world-narrative context provider will return a compact, versioned pack containing campaign model, active pressures, registry context, and approved module seeds when available. The LLM may propose hooks, but Python will not directly apply canon or mechanical mutations from that response.

### Make Markdown and registry checks transactional

`MODULE_SUMMARY.md` must be generated and quality-checked before registry integration. A registry entry must not survive a later Markdown, report, or verification failure.

### Keep adaptation provenance explicit

The module context and Markdown credits will carry source hash, rights classification, adaptation mode, model metadata, and the exact `Adapted for NEQ-TTRPG` notice. Provenance is not a legal rights determination.

## Risks / Trade-offs

- [Risk] The LLM may invent incoherent content. Mitigation: bounded dossier schema, NEQ/SRD constraints, Python semantic gates, and one final revision.
- [Risk] A catalogue may be forced into an unnecessary linear adventure. Mitigation: source profiles include catalogue, location, lore, encounter, and sandbox shapes.
- [Risk] A semantic revision may repeat the same failure. Mitigation: include exact failure diagnostics, record attempt identity, enforce a hard retry budget, and leave publication blocked on exhaustion.
- [Risk] Staging may diverge from existing ModuleBuilder output assumptions. Mitigation: reuse the existing builder output contract and test fresh rebuilds with temporary fixtures before live routing.
- [Risk] World context may leak raw campaign state into a provider request. Mitigation: bounded serialization, field allowlists, version/hash metadata, and no raw database dump.
- [Risk] Registry and campaign state may become inconsistent. Mitigation: registry-last ordering, post-write verification, atomic writes, and rollback metadata.
- [Risk] Adapted material may have unclear rights. Mitigation: require the upload rights classification, persist provenance, and fail closed when policy requires operator review.

## Migration Plan

1. Complete and validate the GPT-5 build-path compatibility change.
2. Add adaptation dossier and report contracts without changing the default route.
3. Add provider-free author, parser, staging, and final-revision tests.
4. Route a feature-flagged non-room fixture through adaptation.
5. Add adaptation-aware publication ordering and Markdown quality checks.
6. Run a bounded JeremysMagicShop smoke.
7. Enable adaptation as the default readable-source route after the smoke passes.
8. Keep legacy accurate-ingest available as an explicit diagnostic fallback.

Rollback disables adaptation routing and restores the prior normalization/build path. Existing published modules, source uploads, and registry entries are not rewritten by rollback.

## State and Observability Boundaries

- Source upload and source digest are immutable inputs for an attempt.
- Adaptation dossier and failure report are attempt-scoped artifacts.
- Module files are provisional until publication succeeds.
- `world_registry.json` and `campaign.json` remain runtime-only state.
- Every attempt records mode, model, provider, world-seed version, failure class, revision number, and terminal status.
- Logs must not include API keys, credentials, or unbounded raw source text.
