## Context

`toolkit-accurate-ingest-source-graph` established deterministic source manifest/source graph artifacts for readable Homebrew uploads. This change plans the next layer: turning the mechanical source graph plus section-bounded LLM facts into a richer normalization substrate without asking a single model call to preserve the entire adventure.

The design deliberately stops before fidelity repair and builder blueprint handoff. Those are later phases in `plans/accurate-ingest.md`.

## Contract Layer (MUST)

- Multi-pass extraction MUST run after deterministic source graph generation and before normalized packet synthesis.
- Section extraction MUST be bounded to one source section or chunk and MUST NOT receive the whole source unless an explicit fallback path is used.
- Every extracted fact MUST include source evidence references with section context, line range where available, and bounded excerpt or atom ID.
- The pipeline MUST persist reviewable artifacts when a workspace is available.
- Provider failure for one section MUST NOT delete or overwrite mechanical `source_manifest.json` or `source_graph.json` artifacts.
- Failed or skipped section extraction MUST be recorded as degraded, not successful.
- Identity adjudication MUST preserve original source display names and aliases.
- Ambiguous identity merges MUST be surfaced for review and MUST NOT be silently resolved as facts.
- Plot/puzzle topology synthesis MUST preserve source order when no stronger dependency evidence exists.
- Source-defined trials, puzzles, clues, and failure states MUST be represented as structured topology where detected, not only summary prose.
- `normalized_packet.json` MUST remain compatible with existing `validate_review_packet(...)` behavior.
- The legacy one-shot normalizer path MUST remain available as fallback.
- Python user-facing console/log text introduced by implementation MUST be ASCII-only.

## Guidance Layer (SHOULD)

- Section extraction SHOULD use low temperature, JSON-only prompts, and bounded retry behavior.
- Section extraction SHOULD cache results by source hash plus section identity.
- Identity merging SHOULD prefer explicit evidence from headings, tables, bold spans, aliases, and repeated co-occurrence.
- Entity adjudication SHOULD keep unresolved cases as `ambiguous` rather than guessing.
- Plot topology SHOULD distinguish mainline beats, optional beats, clue dependencies, puzzle dependencies, failures, and endings where source evidence supports them.
- Synthesis artifacts SHOULD be readable enough for a future review UI.
- Normalization reports SHOULD include compact rollups, not full duplicated artifact data.

## Artifact Contract

New workspace artifacts planned by this change:

- `section_extractions/index.json` - extraction unit registry with source hash, section IDs, status, and artifact paths.
- `section_extractions/<section_id>.json` - bounded facts extracted from one source section.
- `identity_resolution_report.json` - canonical identities, aliases, duplicate decisions, ambiguities, and evidence.
- `plot_topology_report.json` - plot beats, puzzle chains, clue dependencies, trials, endings, and unresolved assumptions.
- `source_graph_synthesis_report.json` - merge summary from mechanical graph plus LLM facts.

Existing artifacts affected later by implementation:

- `source_graph.json` may gain enriched or linked metadata, but mechanical atom identity must remain stable.
- `normalization_report.json` should include compact multipass status and degraded counts.
- `normalized_packet.json` should remain schema-compatible and may include source graph refs inside existing optional/confidence/provenance structures when safe.

## Orchestration

1. Read source text and Phase 1 source graph artifacts.
2. Build extraction units from source manifest heading hierarchy and safe chunking rules.
3. Run section extraction per unit.
4. Merge section facts into candidate collections.
5. Run identity and alias adjudication.
6. Run plot, puzzle, clue, and trial topology synthesis.
7. Synthesize a backward-compatible normalized packet from source graph and synthesis artifacts.
8. Persist all reports and compact status in normalization report.

## Degraded Behavior

- If source graph is missing or invalid, implementation may fall back to legacy normalization and must report that multipass could not run.
- If one section extraction fails, other section artifacts remain valid and synthesis may continue with degraded status.
- If identity or topology synthesis fails, implementation must not overwrite previous successful source graph artifacts.
- If required artifact persistence fails, implementation should follow existing normalizer fail-closed artifact persistence behavior.

## Rollback

Rollback is straightforward: disable multipass orchestration and keep the legacy one-shot normalizer path. Existing source graph artifacts remain additive and safe for later retry.
