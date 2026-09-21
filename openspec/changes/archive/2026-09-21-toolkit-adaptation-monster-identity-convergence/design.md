## Context

Adaptation dossier adversaries are source evidence, while generated location monster entries are already normalized through a canonical vocabulary path. The dossier path currently deduplicates and resolves raw slugs before materialization. `monster_builder.py` explicitly requires singular names, so plural or count-qualified dossier labels can produce valid canonical artifacts that the guardrail rejects because the raw slug differs from the payload name.

## Goals / Non-Goals

**Goals:**

- Establish one deterministic identity key for adaptation source adversaries and materialized artifacts.
- Preserve reuse-first ordering and staging-only writes.
- Make encounter binding use the same identity semantics as materialization.
- Keep raw source labels available for audit and diagnostics.
- Preserve strict rejection of provider substitution and unresolved canonical identities.

**Non-Goals:**

- No global change to `normalize_monster_name()`.
- No changes to the shared legacy closure helper.
- No generic natural-language entity classifier.
- No provider-side identity correction.

## Decisions

### 1. Bounded identity variants

Add a private adaptation helper that produces a bounded ordered set of identity variants:

1. the raw normalized slug;
2. the slug after removing an explicit leading quantity phrase such as `two` or `3`;
3. the singular form of the quantity-stripped terminal token when the form is an ordinary plural.

The helper MUST preserve the raw text separately. It MUST NOT remove arbitrary descriptive prose or classify broad terms such as `guardian` or `ooze`.

### 2. Exact-first resolution

For each reference, exact raw artifact resolution remains first. If no exact artifact is schema-sufficient, folded canonical variants may be considered in deterministic order. When generation is needed, Python selects one canonical singular name and passes that name to the existing staging-only builder seam.

This avoids duplicate `memory_thief_impersonations.json` and `memory_thief_impersonation.json` artifacts while retaining compatibility with authored exact files.

### 3. Identity verification

Payload verification MUST compare the payload name against the selected canonical identity key, not arbitrary semantic similarity. A provider result such as `Substituted Beast` remains rejected. The accepted identity, raw reference, selected variant, and resolution source SHOULD be represented in bounded resolution diagnostics.

### 4. Encounter binding

`_bind_adaptation_encounters()` and encounter-context lookup MUST compare adversaries through the same bounded identity variants. A seed containing `Two slime spawn` therefore binds to the resolved `Slime Spawn` artifact. A seed with no resolved canonical or explicitly excluded scene entity remains unresolved or unbound according to the existing contract.

### 5. Compatibility boundary

All behavior is adaptation-only. The packet builder continues to pass approved identities and the existing staging policy. No legacy caller should observe the new fold.

## Verification And Rollback

Provider-free tests will exercise exact reuse, folded reuse, folded generation, duplicate prevention, encounter binding, quantity handling, custom-name preservation, and substitution rejection. Existing adaptation guardrail, integration, reporting, and strict OpenSpec checks must remain green. A fresh Amphail replay is the final runtime confirmation. Rollback restores the prior exact-slug behavior without changing live module data.
