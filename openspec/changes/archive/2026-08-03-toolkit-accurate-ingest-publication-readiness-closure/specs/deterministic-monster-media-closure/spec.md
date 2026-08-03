## ADDED Requirements

### Requirement: Accurate-ingest/ModuleBuilder finishing SHALL close missing monster base media with deterministic placeholders

The accurate-ingest ModuleBuilder finishing pipeline SHALL produce a minimal valid JPEG placeholder at `media/monsters/<slug>.jpg` for every monster slug that has a JSON stat block in `monsters/*.json` but lacks a base media file.

The placeholder JPEG SHALL be a valid JPEG image, small file size (under 1 KB), generated deterministically from a pre-computed base64 constant with no PIL/Pillow dependency. It SHALL be recognised by `check_monster_media()` as present (`base=True`).

#### Scenario: All monster refs have media

- **GIVEN** a module where every monster slug has a corresponding `media/monsters/<slug>.jpg`
- **WHEN** the closure helper runs
- **THEN** no new files are created
- **AND** the helper reports `created=0`

#### Scenario: Monster refs missing base media

- **GIVEN** a module with N monster slugs missing base media files
- **WHEN** the closure helper runs
- **THEN** N placeholder JPEG files are created
- **AND** `classify_monster_media_outcome()` returns `base_present=true` for each
- **AND** the gameplay audit no longer reports missing base media errors

### Requirement: Closure helper is idempotent and non-destructive

The closure helper SHALL NOT overwrite existing media files. It SHALL only create files that do not exist.

#### Scenario: Existing media preserved

- **GIVEN** a module with some existing monster media files
- **WHEN** the closure helper runs
- **THEN** existing files are unchanged (mtime, content preserved)
- **AND** only truly missing files are created

### Requirement: Provider-free placeholder generation

The closure helper SHALL NOT call any image generation provider (DALL-E, Stable Diffusion, etc.). It SHALL depend only on Python standard library and a pre-computed base64 JPEG byte constant.

#### Scenario: No external provider calls

- **GIVEN** the closure helper is called with a module directory
- **WHEN** placeholder JPEGs are written
- **THEN** no HTTP calls, subprocess calls, or import of `PIL`/`Pillow` occur
