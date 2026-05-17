## 1. Fidelity Audit Foundation

- [x] 1.1 Add `utils/toolkit_normalization_fidelity.py` with SPDX/header and public helpers for loading source artifacts, building packet indexes, and producing audit reports.
- [x] 1.2 Add deterministic source atom coverage checks for NPCs, locations, monster refs, plot progression, puzzle chains, clue dependencies, and tone/confidence notes.
- [x] 1.3 Add finding model helpers with stable finding IDs, category, severity, repairability, source atom IDs, source refs, expected/actual values, and evidence basis.
- [x] 1.4 Add workspace artifact helper paths and persistence functions for `normalization_fidelity_report.json` in `utils/toolkit_homebrew_upload_contract.py`.

**Verification for 1.1-1.4:** py_compile and focused fidelity-audit unit tests pass for covered, missing, distorted, unsupported, and degraded artifact cases.

## 2. Packet Repair Patch Model

- [x] 2.1 Add a narrow packet repair operation schema for additive operations: `add_location`, `add_npc_seed`, `add_monster_ref`, `add_plot_progression`, `add_warning`, `add_confidence_note`, `add_connectivity_hint`, and `add_assumption`.
- [x] 2.2 Implement repair proposal validation that requires source atom IDs or source refs for every operation.
- [x] 2.3 Reject destructive or unsupported operations in this slice.
- [x] 2.4 Validate repaired packet copies with existing `validate_review_packet(...)` before persistence.

**Verification for 2.1-2.4:** Repair validation tests cover accepted additive operations, missing evidence rejection, unsupported op rejection, destructive op rejection, and packet validation failure.

## 3. Repair Prompt and Provider Path

- [x] 3.1 Add `prompts/toolkit/normalization_fidelity_repair_prompt.txt` with JSON-only, source-evidence-bound repair contract.
- [x] 3.2 Add bounded repair orchestration using existing chat client/model config patterns and a configurable max attempt count.
- [x] 3.3 Persist `packet_repair_attempts/index.json` and `packet_repair_attempts/attempt_<n>.json` artifacts.
- [x] 3.4 Preserve original packet when repair provider output is malformed, provider calls fail, or patch validation rejects all operations.

**Verification for 3.1-3.4:** Repair-loop tests cover successful repair, malformed repair output, provider failure, max attempts exhausted, and original packet preservation.

## 4. Normalizer Integration

- [x] 4.1 Integrate fidelity audit after packet synthesis in `utils/toolkit_homebrew_normalizer.py`.
- [x] 4.2 Integrate optional repair loop after initial audit and before final packet persistence when repair is enabled and blocking repairable findings exist.
- [x] 4.3 Re-run fidelity audit after successful repair and persist final report status.
- [x] 4.4 Add compact fidelity and repair rollups to `normalization_report.json`.
- [x] 4.5 Keep legacy fallback behavior available when fidelity audit is disabled or unavailable.

**Verification for 4.1-4.5:** Normalizer orchestration tests cover clean packet, missing required atom, successful repair, failed repair, skipped audit due missing source artifacts, and disabled audit fallback.

## 5. Reporting and Readiness Compatibility

- [x] 5.1 Add compact final status values for clean, degraded, repaired, blocked, and failed fidelity outcomes.
- [x] 5.2 Ensure existing workspace review packet validation remains compatible.
- [x] 5.3 Ensure later readiness/reporting consumers can read fidelity status without loading full detailed artifacts.
- [x] 5.4 Add source-contract tests so this change does not create builder blueprint, build-time gates, review UI, or enrichment artifacts.

**Verification for 5.1-5.4:** Reporting tests prove compact rollups are present, detailed artifacts remain workspace-local, and review packet compatibility remains unchanged.

## 6. Final Validation

- [x] 6.1 Run `.venv/bin/python -m py_compile utils/toolkit_normalization_fidelity.py utils/toolkit_homebrew_upload_contract.py utils/toolkit_homebrew_normalizer.py`.
- [x] 6.2 Run new fidelity audit and repair loop tests.
- [x] 6.3 Run existing accurate-ingest multipass and normalizer regression suites impacted by integration.
- [x] 6.4 Run `openspec validate toolkit-accurate-ingest-fidelity-verifier-repair-loop`.
