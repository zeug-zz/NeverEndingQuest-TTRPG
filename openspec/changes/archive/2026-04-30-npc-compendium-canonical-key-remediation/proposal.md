# Why

`data/bestiary/npc_compendium.json` contains durable NPC keys generated from descriptive labels instead of canonical identities, such as `arannis,_vault_scholar_and_alarmed_archivist` and multiple `kobe,...` variants. The toolkit boundary fix in `toolkit-npc-identity-canonicalization` prevents new bad keys, but it intentionally does not mutate existing persisted compendium data.

Leaving the existing keys in place keeps duplicate NPC identities in the global compendium and can continue to confuse media lookup, description reuse, and future builder flows.

# What Changes

- Add a deterministic remediation workflow for `data/bestiary/npc_compendium.json`.
- Detect descriptive NPC keys and labels using the shared `utils.npc_identity` canonicalization helper.
- Merge bad descriptive entries into canonical keys such as `arannis`, `elaris`, `ilyra`, `kobe`, and `letharel`.
- Preserve legacy information as metadata instead of deleting context blindly.
- Provide a dry-run report by default and require explicit `--apply` for mutation.
- Write migrated compendium data atomically and produce an audit artifact describing every merge/delete.

# Capability Scope

- Canonical-key remediation for `data/bestiary/npc_compendium.json` only.
- Conflict-safe merge behavior for duplicate variants that collapse to one canonical key.
- Regression tests for Numillian descriptive-key examples and metadata preservation.
- Operator-safe CLI with dry-run default.

# Non-Goals

- Do not modify module-authored area files or `module_context.json` in this change.
- Do not alter monster compendium keys or monster/bestiary normalization helpers.
- Do not automatically run remediation during app startup.
- Do not remove source labels, source IDs, or role hints without preserving them in metadata.
- Do not change the toolkit canonicalization behavior already implemented in `toolkit-npc-identity-canonicalization`.

# Impact

- Affected data: `data/bestiary/npc_compendium.json` when remediation is explicitly applied.
- Affected code: new remediation script and tests; possibly a small helper extension in `utils/npc_identity.py` if needed.
- Runtime impact: none unless the operator runs the remediation command.

# Risks

- Multiple legacy entries can collapse into one canonical key with differing descriptions.
- A generic descriptive group could be over-canonicalized if detection is too aggressive.
- A bad merge could lose the preferred description if merge precedence is not deterministic.

# Fallback

- Dry-run is the default and must show planned changes without writing.
- `--apply` must create a timestamped backup or audit artifact before replacing the compendium.
- Atomic write must be used so partial writes cannot corrupt the compendium.
- If validation or merge conflict handling fails, the script must stop without changing the file.

# Merge Safety and SP/MP Impact

- This is an offline remediation tool, not a runtime behavior change.
- No Single-Player or TABLETOP MODE behavior should change unless the operator applies the migration.
- Host-file changes should be minimal; prefer a new script under `scripts/` and existing helper reuse.
