# Executor Prompts: Accurate-Ingest Source-Fidelity Propagation

## Builder Prompt - Full Step-By-Step

Implement OpenSpec change `toolkit-accurate-ingest-source-fidelity-propagation` only.

### Goal

Persist the final accurate-ingest source-fidelity status into the module artifact set and make final publishability consume that same status.

The same source-fidelity status must flow through:

```text
workspace build -> modules/<slug>/source_fidelity_report.json -> toolkit_build_report.json -> audit_module_publishability.py
```

### Allowed Files

Primary:

- `scripts/audit_module_publishability.py`
- `scripts/test_audit_module_publishability.py`
- `web/extensions/toolkit_homebrew_packet_builder.py`
- `web/extensions/toolkit_module_finisher.py`
- `scripts/test_toolkit_homebrew_gui_unified_flow.py`
- `scripts/test_toolkit_module_build_publication_parity.py`

Only if a narrow composition bug is found:

- `utils/toolkit_publication_gate_composer.py`

OpenSpec/task docs may be updated only to mark completed tasks after verification:

- `openspec/changes/toolkit-accurate-ingest-source-fidelity-propagation/tasks.md`

Forbidden unless explicitly justified in the report:

- `modules/**`
- GUI templates
- seed writer files
- enrichment provider orchestration

### Hard Contract

- MUST define/persist module-level `source_fidelity_report.json` with `report_version: "source_fidelity_report.v1"`.
- MUST preserve legacy fail-open `source_fidelity_status="unknown"` when no accurate-ingest artifacts exist.
- MUST make `audit_module_publishability.py` prefer `source_fidelity_report.json` over `accurate_ingest_benchmark_report.json`.
- MUST ensure `source_fidelity_status="blocked"` blocks final publishability.
- MUST ensure `toolkit_build_report.json` mirrors final source-fidelity status and categories.
- MUST NOT mutate production module data.

### Implementation Steps

1. Read existing source-fidelity helpers and tests:
   - `web/extensions/toolkit_homebrew_packet_builder.py`
   - `web/extensions/toolkit_module_finisher.py`
   - `scripts/audit_module_publishability.py`
   - `scripts/test_audit_module_publishability.py`
   - `scripts/test_toolkit_homebrew_gui_unified_flow.py`
2. Add tests first:
   - Module-level `source_fidelity_report.json` wins over stale benchmark report.
   - Blocked module-level source fidelity blocks publishability.
   - Legacy module with no source-fidelity artifact remains `unknown` and does not block solely for source-fidelity absence.
   - Accurate-ingest build/finisher persists `source_fidelity_report.json` and mirrors status into `toolkit_build_report.json`.
   - `MODULE_SUMMARY.md` cannot repair or override blocked source fidelity.
3. Implement a compact report contract/helper:
   - Required: `report_version`, `module_slug`, `source_fidelity_status`, `categories`.
   - Optional: `source_hash`, `source_path`, `normalization_fidelity`, `blueprint`, `build_fidelity`, `benchmark`, `waiver`, `workspace_artifacts`.
4. Persist/copy final source-fidelity report into `modules/<slug>/source_fidelity_report.json` for accurate-ingest builds.
5. Add `source_fidelity_status`, category summary, and report artifact ref to `toolkit_build_report.json`.
6. Update `_load_source_fidelity_status(...)` in `scripts/audit_module_publishability.py` with precedence:
   - `source_fidelity_report.json`
   - `accurate_ingest_benchmark_report.json`
   - `unknown`
7. Reuse `utils/toolkit_publication_gate_composer.py` unless tests prove a narrow composer change is required.
8. Run verification. Fix failures with minimal patches.
9. Mark completed tasks in `tasks.md` only after verification passes.

### Verification Gate

```bash
.venv/bin/python -m py_compile scripts/audit_module_publishability.py web/extensions/toolkit_module_finisher.py web/extensions/toolkit_homebrew_packet_builder.py
.venv/bin/python -m unittest -q scripts.test_audit_module_publishability
.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow
.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity
openspec validate toolkit-accurate-ingest-source-fidelity-propagation
python3 scripts/check_ascii_compliance.py --summary-only scripts/audit_module_publishability.py web/extensions/toolkit_module_finisher.py web/extensions/toolkit_homebrew_packet_builder.py scripts/test_audit_module_publishability.py scripts/test_toolkit_homebrew_gui_unified_flow.py scripts/test_toolkit_module_build_publication_parity.py
```

### Report Back

Return only:

- Files changed.
- Source-fidelity artifact contract shape.
- Publishability precedence order.
- Test/validation command results.
- Any blockers or intentionally deferred GUI/status work.

Do not commit. Do not push. Do not edit module data.
