# Design: Accurate-Ingest Source-Fidelity Propagation

## Overview

This change connects existing source-fidelity computation to final module publication semantics by establishing a single module-level source-fidelity report contract.

The pipeline intent is:

```text
workspace source fidelity -> module/source_fidelity_report.json -> toolkit_build_report.json -> audit_module_publishability.py -> GUI final status
```

The change is propagation-focused. It does not change how source-fidelity scores are computed.

## Decision 1: Use A Final Module-Level Report

The canonical final report path SHALL be:

```text
modules/<slug>/source_fidelity_report.json
```

Suggested v1 shape:

```json
{
  "report_version": "source_fidelity_report.v1",
  "module_slug": "The_Hidden_City_of_Numillian",
  "source_hash": "...",
  "source_path": "...",
  "source_fidelity_status": "pass|degraded|blocked|unknown",
  "categories": [],
  "normalization_fidelity": {},
  "blueprint": {},
  "build_fidelity": {},
  "benchmark": {},
  "waiver": null,
  "workspace_artifacts": {}
}
```

Required fields:

- `report_version`
- `module_slug`
- `source_fidelity_status`
- `categories`

Other fields are optional provenance/detail fields and MAY be omitted if unavailable.

## Decision 2: Publication Audit Precedence

`scripts/audit_module_publishability.py` SHALL load source fidelity in this order:

1. `modules/<slug>/source_fidelity_report.json`
2. `modules/<slug>/accurate_ingest_benchmark_report.json`
3. Synthetic legacy result: `source_fidelity_status="unknown"`

The first valid report wins. Invalid or unreadable source-fidelity artifacts should degrade to `unknown` with a warning rather than crash publication audit.

## Decision 3: Build Report Mirrors Effective Status

The module `toolkit_build_report.json` SHALL include the same final effective source-fidelity status used by publishability.

Recommended fields:

```json
{
  "source_fidelity_status": "pass|degraded|blocked|unknown",
  "source_fidelity_categories": [],
  "source_fidelity_report": "source_fidelity_report.json"
}
```

Existing report fields should not be removed.

## Decision 4: Legacy Modules Fail Open

Modules without `source_fidelity_report.json` and without `accurate_ingest_benchmark_report.json` SHALL continue to return `source_fidelity_status="unknown"` and SHOULD NOT be blocked solely by source-fidelity absence.

This preserves publication behavior for legacy hand-authored or pre-accurate-ingest modules.

## Decision 5: Blocked Fidelity Blocks Publication

When source-fidelity gating is enabled, `source_fidelity_status="blocked"` SHALL make final publishability fail even if readiness and semantic gates pass.

`source_fidelity_status="degraded"` SHALL follow the existing waiver/composer contract. This change should not invent a new waiver model unless the existing composer cannot represent current behavior.

## Touchpoints

Likely implementation files:

- `web/extensions/toolkit_homebrew_packet_builder.py` for workspace/source-fidelity rollup persistence helpers.
- `web/extensions/toolkit_module_finisher.py` for module report/build report surfacing.
- `scripts/audit_module_publishability.py` for report precedence and final audit consumption.
- `scripts/test_audit_module_publishability.py` for precedence and blocking tests.
- `scripts/test_toolkit_homebrew_gui_unified_flow.py` or `scripts/test_toolkit_module_build_publication_parity.py` for GUI/build report parity contracts.

## Migration And Rollback

Migration is additive. New accurate-ingest builds gain `source_fidelity_report.json`; old modules continue as `unknown` unless they already have benchmark reports.

Rollback is safe by removing the new module-level report preference and reverting to benchmark-only behavior.

## Verification Strategy

Tests should use temporary module directories and mocked readiness/semantic gates. Do not mutate production module data.

Required checks:

```bash
.venv/bin/python -m py_compile scripts/audit_module_publishability.py web/extensions/toolkit_module_finisher.py web/extensions/toolkit_homebrew_packet_builder.py
.venv/bin/python -m unittest -q scripts.test_audit_module_publishability
.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow
.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity
openspec validate toolkit-accurate-ingest-source-fidelity-propagation
python3 scripts/check_ascii_compliance.py --summary-only scripts/audit_module_publishability.py web/extensions/toolkit_module_finisher.py web/extensions/toolkit_homebrew_packet_builder.py scripts/test_audit_module_publishability.py scripts/test_toolkit_homebrew_gui_unified_flow.py scripts/test_toolkit_module_build_publication_parity.py
```
