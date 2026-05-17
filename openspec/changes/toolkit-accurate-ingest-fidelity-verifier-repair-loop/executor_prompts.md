# Executor Prompts - Toolkit Accurate Ingest Fidelity Verifier Repair Loop

## Prompt 1 - Fidelity Audit Foundation

Implement tasks 1.1-1.4 only.

Allowed files: `utils/toolkit_normalization_fidelity.py`, `utils/toolkit_homebrew_upload_contract.py`, focused tests.

MUST: Add deterministic coverage checks from source artifacts to normalized packet indexes. Findings must include stable IDs, category, severity, repairability, source atom IDs, and source refs. Missing artifacts must degrade safely and never report clean fidelity.

Verify with py_compile and fidelity-audit unit tests. Report changed files and command results.

## Prompt 2 - Packet Repair Patch Model

Implement tasks 2.1-2.4 only.

Allowed files: `utils/toolkit_normalization_fidelity.py`, focused tests.

MUST: Implement additive repair operation validation only. Require source refs or source atom IDs on every operation. Reject destructive operations. Validate repaired packet copies with `validate_review_packet(...)` before persistence.

Verify accepted/rejected patch tests. Report changed files and command results.

## Prompt 3 - Repair Prompt and Provider Path

Implement tasks 3.1-3.4 only.

Allowed files: `prompts/toolkit/normalization_fidelity_repair_prompt.txt`, `utils/toolkit_normalization_fidelity.py`, `utils/toolkit_homebrew_upload_contract.py`, focused tests.

MUST: Repair provider output is advisory only. Persist attempt artifacts. Bound attempts. Preserve original packet on provider failure, malformed JSON, rejected ops, or exhausted attempts.

Verify repair-loop success/failure tests. Report changed files and command results.

## Prompt 4 - Normalizer Integration

Implement tasks 4.1-4.5 only.

Allowed files: `utils/toolkit_homebrew_normalizer.py`, `utils/toolkit_normalization_fidelity.py`, `utils/toolkit_homebrew_upload_contract.py`, integration tests.

MUST: Run fidelity audit after packet synthesis. Run repair only when enabled and repairable blockers exist. Re-run audit after repair. Add compact fields to `normalization_report.json`. Preserve disabled/fallback behavior.

Verify normalizer orchestration tests. Report changed files and command results.

## Prompt 5 - Reporting and Compatibility

Implement tasks 5.1-5.4 only.

Allowed files: report helper code and tests only.

MUST: Distinguish clean, degraded, repaired, blocked, and failed status. Keep detailed artifacts workspace-local. Add source-contract tests preventing builder blueprint, build-time gate, review UI, or enrichment scope creep.

Verify reporting and source-contract tests. Report changed files and command results.

## Prompt 6 - Final Verification

Run final validation only.

Commands:

```bash
.venv/bin/python -m py_compile utils/toolkit_normalization_fidelity.py utils/toolkit_homebrew_upload_contract.py utils/toolkit_homebrew_normalizer.py
.venv/bin/python -m unittest scripts.test_toolkit_normalization_fidelity
.venv/bin/python -m unittest scripts.test_toolkit_homebrew_normalizer
.venv/bin/python -m unittest scripts.test_source_section_extraction_contract scripts.test_source_extraction_merge scripts.test_source_identity_resolution scripts.test_source_plot_topology scripts.test_normalized_packet_source_refs scripts.test_accurate_ingest_source_graph
openspec validate toolkit-accurate-ingest-fidelity-verifier-repair-loop
```

Report pass/fail with exact commands and any failures. Do not archive or commit.
