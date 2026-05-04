## ADDED Requirements

### Requirement: module_context.json SHALL carry author and license fields

The `module_context.json` file SHALL contain `author` and `license` top-level fields, both initialized as empty strings (`""`) at generation time. These fields are the copyright authority for the module and are intended for human-in-the-loop editing.

#### Scenario: Homebrew ingest emits empty author and license
- **WHEN** a module is generated via the homebrew ingest pipeline (`_emit_module_context`)
- **THEN** the resulting `module_context.json` contains `"author": ""` and `"license": ""` fields

#### Scenario: Module builder emits empty author and license
- **WHEN** a module is generated via the module builder (`ModuleContext.to_dict()`)
- **THEN** the resulting `module_context.json` contains `"author": ""` and `"license": ""` fields

#### Scenario: ModuleContext.load preserves author and license from existing files
- **WHEN** `ModuleContext.load()` reads a `module_context.json` that has `"author": "Jane Doe"` and `"license": "CC BY 4.0"`
- **THEN** the loaded `ModuleContext` instance has `author="Jane Doe"` and `license="CC BY 4.0"`

#### Scenario: Backfill script adds fields to existing module without them
- **WHEN** the backfill script processes a `module_context.json` that lacks `author` and `license` keys
- **THEN** the file is written with `"author": ""` and `"license": ""` added, and all pre-existing fields are preserved unchanged

#### Scenario: Backfill script is idempotent
- **WHEN** the backfill script processes a `module_context.json` that already has `author` and `license` keys
- **THEN** the file is not modified
