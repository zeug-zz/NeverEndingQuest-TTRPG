# Executor Prompts: Accurate-Ingest GUI State And Overwrite Safety

## Builder Prompt

Implement OpenSpec change `toolkit-accurate-ingest-gui-state-overwrite-safety`.

Scope is narrow: GUI/job status surfacing and overwrite safety only. Do not rebuild Numillian. Do not mutate files under `modules/**`.

Required behavior:

1. Add canonical accurate-ingest phase surfacing for the flow:
   `preflight -> extracting_source_truth -> building_blueprint -> awaiting_review -> seeding_module -> enriching_module -> build_fidelity -> readiness -> finishing -> publishability_audit -> terminal`.
2. Add grouped accurate-ingest summary fields to job polling payloads, including source counts and blueprint/seed/enrichment/build-fidelity/readiness/publishability/source-fidelity statuses when available.
3. Preserve existing job status fields for backward compatibility.
4. Add shared overwrite authorization at the packet-build write boundary:
   - first build into absent directory succeeds;
   - existing module without confirmation fails before writes;
   - confirmed clean rebuild proceeds only with route-level confirmation or validated rebuild plan artifact;
   - retry-from-packet without confirmation refuses overwrite;
   - finishing-only retry remains allowed.
5. Keep fidelity review approval mandatory before module files are written.

Implementation hints:

- Likely files:
  - `web/routes/toolkit_homebrew_routes.py`
  - `web/extensions/toolkit_homebrew_packet_builder.py`
  - `web/extensions/toolkit_homebrew_rebuild_guard.py`
  - `scripts/test_toolkit_homebrew_gui_unified_flow.py`
  - `scripts/test_toolkit_module_build_publication_parity.py`
- Prefer helpers over inline route condition sprawl.
- Do not weaken existing rebuild guard behavior.
- Do not edit `modules/**`.

Verification:

```bash
.venv/bin/python -m py_compile web/routes/toolkit_homebrew_routes.py web/extensions/toolkit_homebrew_packet_builder.py web/extensions/toolkit_homebrew_rebuild_guard.py
.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow
.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity
openspec validate toolkit-accurate-ingest-gui-state-overwrite-safety
python3 scripts/check_ascii_compliance.py --summary-only web/routes/toolkit_homebrew_routes.py web/extensions/toolkit_homebrew_packet_builder.py web/extensions/toolkit_homebrew_rebuild_guard.py scripts/test_toolkit_homebrew_gui_unified_flow.py scripts/test_toolkit_module_build_publication_parity.py
```

Report back with files changed, payload contract, overwrite safety contract, tests added, and any deferred frontend rendering work.
