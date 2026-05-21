# Tasks

## 1. Configuration Defaults

- [x] 1.1 Normalize accurate-ingest build flags so `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD` defaults to `False` and add `ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK=False` in `model_config.py` and `config_template.py`.
- [x] 1.2 Add or update tests proving the default config does not select the seed-writer authoring path.

## 2. Packet Builder Routing

- [x] 2.1 Update packet builder routing so default accurate-ingest ready blueprints call `_execute_module_builder(...)` rather than `_execute_seed_writer_build(...)`.
- [x] 2.2 Require explicit fallback/preview state or flag before `_execute_seed_writer_build(...)` can run from a GUI accurate-ingest job.
- [x] 2.3 Persist/report build mode metadata that distinguishes `source_enhanced_modulebuilder` from seed-writer fallback/preview modes.

## 3. GUI Diagnostics Copy And Review Flow

- [x] 3.1 Update GUI route/status payload logic so clean accurate-ingest builds do not enter `awaiting_review` merely because optional diagnostics exist.
- [x] 3.2 Update Module Toolkit copy so fidelity review is presented as diagnostics/waiver/debugging unless the backend marks review as required.
- [x] 3.3 Preserve required-review UI behavior for genuinely blocked or non-approvable states.

## 4. Verification

- [x] 4.1 Run targeted compile checks for modified Python files.
- [x] 4.2 Run toolkit GUI unified flow tests and module build publication parity tests.
- [x] 4.3 Add a targeted source check or regression asserting no default path invokes `_execute_seed_writer_build` without explicit fallback/preview enablement.
- [x] 4.4 Validate the OpenSpec change.

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile model_config.py config_template.py web/extensions/toolkit_homebrew_packet_builder.py web/routes/toolkit_homebrew_routes.py
.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow
.venv/bin/python -m unittest -q scripts.test_toolkit_module_build_publication_parity
openspec validate toolkit-accurate-ingest-gui-stabilize-defaults
```
