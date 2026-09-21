## Why

The completed adaptation monster guardrail correctly excludes scene-only labels, but a fresh Amphail replay exposed a separate identity seam. Dossier adversaries such as `Memory-thief impersonations` and `Two slime spawn` are treated as distinct raw monster references even though the monster builder is required to emit singular identities. The builder generated schema-sufficient `memory_thief_impersonation.json` and `slime_spawn.json`, but the guardrail compared exact raw slugs, rejected the valid outputs as `generation_identity_mismatch`, and blocked publication.

This follow-up closes the canonical identity gap without weakening Python ownership of monster identity or changing legacy ModuleBuilder behavior.

## What Changes

- Add a bounded adaptation-only identity fold for leading quantity phrases and ordinary plural forms.
- Reuse the same identity key for reference deduplication, approved-generation checks, reusable artifact lookup, generated output naming, payload verification, and encounter binding.
- Preserve the original dossier wording in bounded diagnostics and encounter provenance.
- Prefer exact reusable artifacts before folded aliases and avoid duplicate plural/singular artifacts.
- Keep genuine substitutions, ambiguous identities, and unresolved canonical monsters fail-closed.
- Add provider-free regressions for the exact Amphail failure shape.

## Non-Goals

- Do not change the adaptation dossier schema or rewrite source artifacts.
- Do not broaden scene/NPC/hazard classification rules.
- Do not change generic monster closure or non-adaptation ModuleBuilder behavior.
- Do not ask the provider to classify or rename identities.
- Do not relax schema-sufficiency or substitution checks.
- Do not publish, register, commit, archive, or push as part of implementation.

## Impact And Compatibility

The change is limited to `llm_adaptation` monster staging and reporting. Single-player and legacy module-builder paths remain unchanged. Python remains the authority for the canonical identity; the provider may generate mechanics only for the canonical identity selected by Python.

## Risks And Rollback

The main risk is over-normalizing a legitimate custom name. Mitigation: use bounded quantity/plural variants, prefer exact artifacts, preserve raw labels, and add regressions for custom names and provider substitution. Rollback is to disable or revert the adaptation identity-fold path; the existing guardrail remains fail-closed for unresolved references.
