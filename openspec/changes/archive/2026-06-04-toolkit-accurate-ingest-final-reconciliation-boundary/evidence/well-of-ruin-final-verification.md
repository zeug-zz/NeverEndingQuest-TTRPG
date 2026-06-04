# Well_of_Ruin Final Verification Evidence

Date: 2026-06-02

## 7.4 Validation

`.venv/bin/python core/validation/validate_module_files.py --module Well_of_Ruin`

- Total: 102 files checked across 10 categories
- Passed: 24 (monsters, maps, BU files, media, schemas, characters, encounters)
- Failed: 78 (live runtime files: non-BU areas/*.json, module_plot.json -- expected for fresh module)
- BU artifacts, map BU files, monsters pass 100%
- Live runtime state files (areas/*.json without BU suffix, module_plot.json) expected to have runtime drift -- these are gitignored per .gitignore Layer 2 contract

## 7.5 Publishability Audit

`.venv/bin/python scripts/audit_module_publishability.py --module Well_of_Ruin --json`

- ready_status: fail
- publishable_status: fail
- source_fidelity_status: unknown
- effective_publishable_status: blocked
- exit_code: 1

Expected for freshly ingested module that has not completed readiness/publishability stages.
