## 1. Emission Path: Homebrew Ingest

- [ ] 1.1 Add `"author": ""` and `"license": ""` to the `context` dict in `core/importers/homebrewery_importer.py:_emit_module_context()` (after `"validation_issues"`, before `"generated_at"`)

## 2. Emission Path: Module Builder

- [ ] 2.1 Add `author: str = ""` and `license: str = ""` fields to the `ModuleContext` dataclass in `utils/module_context.py`
- [ ] 2.2 Add `"author": self.author` and `"license": self.license` to `ModuleContext.to_dict()` return dict (after `"validation_issues"`, before `"generated_at"`)
- [ ] 2.3 Add `context.author = data.get("author", "")` and `context.license = data.get("license", "")` to `ModuleContext.load()` (after `validation_issues` line)

## 3. Backfill Script

- [ ] 3.1 Create `scripts/backfill_module_context_author.py` that iterates all `modules/*/module_context.json` and `modules/*/module_context_BU.json` files
  - `--dry-run` (default): report which files would be modified
  - `--apply`: write the two fields with `safe_write_json()` if missing
  - Skip files that already have `"author"` key (idempotent)
  - Per-file status: `ok`, `added`, `error`
  - Summary counts at end

## 4. Verification

- [ ] 4.1 Run `python3 -m py_compile core/importers/homebrewery_importer.py utils/module_context.py scripts/backfill_module_context_author.py`
- [ ] 4.2 Run `python3 scripts/test_homebrew_entity_seeding.py` to confirm no regression
- [ ] 4.3 Run `python3 scripts/test_homebrew_ingest_dev.py` to confirm no regression
- [ ] 4.4 Run backfill `--dry-run` on all modules, verify zero errors
- [ ] 4.5 Run backfill `--apply`, verify all module context files now have the fields
