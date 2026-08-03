# ingest-sidecar-persistence Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-publication-readiness-closure. Update Purpose after archive.
## Requirements
### Requirement: Accurate-ingest/ModuleBuilder finishing SHALL emit a valid ingest sidecar

The accurate-ingest ModuleBuilder finishing pipeline SHALL emit a deterministic sidecar JSON file to `modules/ingest/archive/<timestamp>_<slug>.result.json` when a build reaches the publishability-check stage.

The sidecar SHALL satisfy the contract expected by `find_latest_sidecar_for_slug()` and `homebrew_sidecar_audit.py --require-success`.

Minimum required payload shape:
```json
{
  "module_slug": "<slug>",
  "status": "success",
  "ingest": {
    "registration": {
      "registered": true,
      "publishable": true,
      "module_slug": "<slug>"
    }
  },
  "media_extraction": {"status": "skipped"},
  "media_handles": {"status": "skipped"},
  "portrait_prewarm": {"status": "skipped"}
}
```

#### Scenario: Sidecar written after finisher completes

- **GIVEN** an accurate-ingest build that produces module artifacts
- **WHEN** the finisher reaches the publishability stage
- **THEN** a sidecar file exists in `modules/ingest/archive/`
- **AND** `find_latest_sidecar_for_slug(slug)` returns the file path
- **AND** `homebrew_sidecar_audit.py --slug <slug> --require-success` exits 0

#### Scenario: Idempotent sidecar overwrite

- **GIVEN** an existing sidecar for the same slug
- **WHEN** a new build completes and the finisher emits a sidecar
- **THEN** the new sidecar replaces the old one (by filename sort recency)
- **AND** no duplicate sidecar entries accumulate

### Requirement: Sidecar persistence helper is available standalone

The sidecar persistence logic SHALL be callable as a standalone helper, not only inside the finisher pipeline, so existing modules can be backfilled.

#### Scenario: Backfill existing module

- **GIVEN** a module with no ingest sidecar
- **WHEN** the standalone helper is called with the module slug
- **THEN** a valid sidecar is written to the archive
- **AND** subsequent sidecar audit passes

