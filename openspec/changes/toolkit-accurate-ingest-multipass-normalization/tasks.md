## 1. Section Extraction Scaffold

- [x] 1.1 Add `utils/toolkit_source_extraction.py` with SPDX/header and public helpers for section unit construction and section extraction orchestration.
- [x] 1.2 Build extraction units from source manifest heading hierarchy, preserving source hash, section ID, heading path, line range, excerpt, and mechanical atom hints.
- [x] 1.3 Add workspace artifact helpers in `utils/toolkit_homebrew_upload_contract.py` for `section_extractions/index.json` and per-section extraction files.
- [x] 1.4 Add degraded section status handling so one failed section does not erase successful section artifacts.

**Verification for 1.1-1.4:** `.venv/bin/python -m py_compile utils/toolkit_source_extraction.py utils/toolkit_homebrew_upload_contract.py` and section unit tests pass.

## 2. Section Extraction Prompt Contract

- [x] 2.1 Add `prompts/toolkit/source_section_extraction_prompt.txt` with JSON-only, facts-only, evidence-required contract.
- [x] 2.2 Implement low-temperature section extraction call path using existing chat client/model config patterns.
- [x] 2.3 Validate extraction payload shape and fail open/degraded on malformed model output.
- [x] 2.4 Cache or skip unchanged section extraction by source hash and section identity where practical.

**Verification for 2.1-2.4:** Tests prove section extraction sends bounded section text, rejects prose-only output, and records degraded status for provider/parse failures.

## 3. Identity and Alias Adjudication

- [x] 3.1 Add `utils/toolkit_source_graph_synthesis.py` with identity adjudication helpers.
- [x] 3.2 Add `prompts/toolkit/source_identity_adjudication_prompt.txt` for alias/entity decisions with ambiguity-first behavior.
- [x] 3.3 Persist `identity_resolution_report.json` with canonical identities, aliases, duplicate decisions, unresolved ambiguities, and evidence refs.
- [x] 3.4 Preserve original source display names and never silently merge ambiguous identities.

**Verification for 3.1-3.4:** Identity tests cover aliases, duplicate merges, display-name preservation, and ambiguous merge surfacing.

## 4. Plot, Puzzle, Clue, and Trial Topology

- [x] 4.1 Add plot topology synthesis helpers in `utils/toolkit_source_graph_synthesis.py`.
- [x] 4.2 Add `prompts/toolkit/source_plot_topology_prompt.txt` for bounded topology synthesis from extracted facts and source graph subsets.
- [x] 4.3 Persist `plot_topology_report.json` with plot beats, puzzle chains, clue dependencies, trials, endings, failures, and assumptions.
- [x] 4.4 Preserve source order when dependency evidence is missing.
- [x] 4.5 Represent Trial-at-the-Door-style puzzle chains as structured topology, not only prose.

**Verification for 4.1-4.5:** Plot topology tests cover source order, puzzle chain preservation, clue dependency linking, and assumption reporting.

## 5. Source Graph and Packet Synthesis

- [x] 5.1 Merge mechanical graph atoms and section facts into a synthesis report without mutating mechanical atom IDs.
- [x] 5.2 Persist `source_graph_synthesis_report.json` with coverage counts, degraded sections, and unresolved ambiguities.
- [x] 5.3 Generate a backward-compatible `normalized_packet.json` from source graph/synthesis data.
- [x] 5.4 Add optional source graph references only in existing optional/confidence/provenance structures where review validation remains compatible.
- [x] 5.5 Preserve legacy one-shot normalizer fallback.

**Verification for 5.1-5.5:** Packet tests prove `validate_review_packet(...)` still accepts legacy packets and multipass-synthesized packets.

## 6. Normalizer Orchestration

- [x] 6.1 Integrate multipass orchestration into `utils/toolkit_homebrew_normalizer.py` after Phase 1 source graph generation and before packet synthesis.
- [x] 6.2 Add compact multipass status, section counts, degraded counts, identity ambiguity counts, and topology summary to `normalization_report.json`.
- [x] 6.3 Ensure provider failures and parse failures are observable and do not silently mark extraction successful.
- [x] 6.4 Keep current behavior available when multipass is disabled or unavailable.

**Verification for 6.1-6.4:** Normalizer tests cover success, provider failure, malformed extraction output, missing source graph fallback, and legacy fallback compatibility.

## 7. Final Validation

- [x] 7.1 Run `.venv/bin/python -m py_compile utils/toolkit_source_extraction.py utils/toolkit_source_graph_synthesis.py utils/toolkit_homebrew_upload_contract.py utils/toolkit_homebrew_normalizer.py`.
- [x] 7.2 Run new section extraction and synthesis test suites.
- [x] 7.3 Run existing source graph, normalizer, and upload contract regression tests impacted by artifact helpers.
- [x] 7.4 Run `openspec validate toolkit-accurate-ingest-multipass-normalization`.
