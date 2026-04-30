# Tasks

## 1. OpenSpec Artifacts

- [x] 1.1 Create proposal, design, tasks, executor prompts, and capability spec.
- [x] 1.2 Validate the change with OpenSpec.

## 2. Shared NPC Identity Helper

- [x] 2.1 Add `utils/npc_identity.py` with canonical name, slug, source label, source ID, and role hint support.
- [x] 2.2 Add merge helpers for compendium/source metadata.

## 3. Toolkit Write Boundaries

- [x] 3.1 Canonicalize NPC IDs in module NPC listing route.
- [x] 3.2 Canonicalize NPC description generation writes and temp cache keys.
- [x] 3.3 Canonicalize manual NPC description GET/POST lookup and writes.
- [x] 3.4 Canonicalize unified asset NPC description and media identity handling.

## 4. Regression Coverage

- [x] 4.1 Add helper tests for Numillian descriptive labels.
- [x] 4.2 Add source-contract tests for toolkit web route usage.
- [x] 4.3 Add or document audit/remediation follow-up for existing bad compendium keys.

## 5. Verification

- [x] 5.1 Compile modified Python files.
- [x] 5.2 Run targeted regression tests.
- [x] 5.3 Run OpenSpec validation.

## Guidance

- Keep the implementation minimal and conservative.
- Preserve source metadata rather than deleting bad historical information.
- Do not modify monster classification helpers.
