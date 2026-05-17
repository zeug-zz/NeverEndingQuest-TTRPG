# Executor Prompts - Toolkit Accurate Ingest Multipass Normalization

## Prompt 1 - Section Extraction Scaffold

Implement tasks 1.1-1.4 only.

Allowed files: `utils/toolkit_source_extraction.py`, `utils/toolkit_homebrew_upload_contract.py`, and focused tests. Add no runtime normalizer integration yet.

MUST: Build section units from Phase 1 source manifest heading hierarchy. Each unit must include source hash, section ID, heading path, line range, bounded text, and mechanical atom hints. Add workspace helpers for section extraction artifacts. Section failures must be representable without deleting successful artifacts.

Verify with py_compile and section unit tests. Report changed files and command results.

## Prompt 2 - Section Extraction Prompt and Provider Call

Implement tasks 2.1-2.4 only.

Allowed files: `prompts/toolkit/source_section_extraction_prompt.txt`, `utils/toolkit_source_extraction.py`, tests.

MUST: Use bounded section text only. Prompt must require JSON only, facts only, source evidence, and ambiguity instead of guessing. Provider and parse failures must return degraded section status. Do not modify `utils/toolkit_homebrew_normalizer.py` yet.

Verify prompt contract and degraded behavior tests. Report changed files and command results.

## Prompt 3 - Identity Adjudication

Implement tasks 3.1-3.4 only.

Allowed files: `utils/toolkit_source_graph_synthesis.py`, `prompts/toolkit/source_identity_adjudication_prompt.txt`, tests.

MUST: Preserve original source display names. Merge aliases only with evidence. Surface ambiguous merges in `identity_resolution_report.json` shape. Do not silently resolve uncertain identities.

Verify alias merge, display-name preservation, and ambiguity tests. Report changed files and command results.

## Prompt 4 - Plot, Puzzle, Clue, and Trial Topology

Implement tasks 4.1-4.5 only.

Allowed files: `utils/toolkit_source_graph_synthesis.py`, `prompts/toolkit/source_plot_topology_prompt.txt`, tests.

MUST: Produce topology report shape for plot beats, puzzle chains, clue dependencies, trials, endings, failures, and assumptions. Preserve source order when no stronger dependency evidence exists. Represent source-defined puzzle/trial chains structurally, not only prose.

Verify source order, puzzle chain, clue dependency, and assumption tests. Report changed files and command results.

## Prompt 5 - Packet Synthesis

Implement tasks 5.1-5.5 only.

Allowed files: `utils/toolkit_source_graph_synthesis.py`, `utils/toolkit_homebrew_normalizer.py` only if necessary for isolated packet helper wiring, tests.

MUST: Keep mechanical source atom IDs stable. Generate a review-compatible `normalized_packet.json` from source graph/synthesis artifacts. Optional source refs must live only in compatible optional/confidence/provenance structures. Preserve legacy one-shot fallback.

Verify packet validation compatibility for legacy and synthesized packets. Report changed files and command results.

## Prompt 6 - Normalizer Orchestration

Implement tasks 6.1-6.4 only.

Allowed files: `utils/toolkit_homebrew_normalizer.py`, `utils/toolkit_homebrew_upload_contract.py`, integration tests.

MUST: Run multipass orchestration after Phase 1 source graph generation and before packet synthesis. Persist compact multipass status in `normalization_report.json`. Missing/failed multipass paths must be observable and fallback-compatible. Do not implement fidelity repair, builder blueprint, review UI, or enrichment.

Verify success, provider failure, malformed output, missing source graph fallback, and legacy fallback compatibility. Report changed files and command results.

## Prompt 7 - Final Verification

Run final validation only.

Commands:

```bash
.venv/bin/python -m py_compile utils/toolkit_source_extraction.py utils/toolkit_source_graph_synthesis.py utils/toolkit_homebrew_upload_contract.py utils/toolkit_homebrew_normalizer.py
.venv/bin/python -m unittest scripts.test_source_section_extraction_contract
.venv/bin/python -m unittest scripts.test_source_extraction_merge
.venv/bin/python -m unittest scripts.test_source_identity_resolution
.venv/bin/python -m unittest scripts.test_source_plot_topology
.venv/bin/python -m unittest scripts.test_normalized_packet_source_refs
.venv/bin/python -m unittest scripts.test_accurate_ingest_source_graph
.venv/bin/python -m unittest scripts.test_toolkit_homebrew_normalizer
openspec validate toolkit-accurate-ingest-multipass-normalization
```

Report pass/fail with exact commands and any failures. Do not archive or commit.
