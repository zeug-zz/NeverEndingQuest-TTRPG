# Executor Prompts

## Builder Prompt

Implement `toolkit-npc-identity-canonicalization` by adding a shared NPC identity helper and wiring it into toolkit NPC extraction and compendium write boundaries. Preserve original labels as metadata, canonicalize durable IDs from clean NPC identity only, and add regression tests for Numillian-style labels such as `Arannis, vault scholar and alarmed archivist` and duplicate `Kobe, ...` variants.

## Verification Prompt

Verify that toolkit NPC IDs no longer include comma appositives or descriptive role phrases, compendium/temp writes use canonical keys, modified Python files compile, targeted regressions pass, and `openspec validate toolkit-npc-identity-canonicalization` is valid.
