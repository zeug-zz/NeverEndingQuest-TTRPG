# NEQ-world Handover

## Purpose

This document hands the completed NEQ-world public seed integration to the
NEQ-TTRPG implementation LLM. The immediate goal is to give NEQ-TTRPG a
stable, queryable narrative seed foundation for runtime retrieval, campaign
world-model generation, and module-builder integration.

The public seed is already present at:

```text
data/world_narrative_seed.db
```

This is the committed/install-baseline artifact. Treat it as read-only at
runtime. The working campaign database is `data/memory.db`.

## Verified Artifact

- Seed path: `data/world_narrative_seed.db`
- SHA-256:
  `a4d8c58f6c3b3b4649d35afa6af16c408095252c3352341cbbedd072f628b5e6`
- Size: 26,169,344 bytes
- Schema version: `1.0.0`
- Build timestamp: `2026-01-01T00:00:00+00:00`
- Public seed status: verified and ready for runtime integration
- SQLite integrity check: PASS
- Foreign-key check: PASS, zero violations
- SQLite WAL/SHM sidecars: none required

The public seed contains 17 tables and 88,256 total rows. It uses deterministic
opaque identifiers and deterministic row arrangement. The consumer must treat
IDs as stable API values. Do not infer meaning from their formatting or
insertion order.

## Current Consumer State

The seed has already been atomically installed in `data/world_narrative_seed.db`.
The verified consumer copy has:

- 41,216 inspiration atoms
- 95 inspiration profiles
- 3,944 alignment profiles
- 188 cosmological domains
- 190 mythic conflicts
- 246 deity archetypes
- 602 deity manifestations
- 41,216 atom statistics rows
- 0 atom relation rows in the current seed

Temporary bootstrap, initialization, and retrieval checks passed. The seed
tables and required columns are queryable after initialization. No semantic
index is required for the seed contract.

## Storage And Ownership

Use this storage model:

1. `data/world_narrative_seed.db` is the tracked installation baseline.
2. `data/memory.db` is the runtime working database and is gitignored.
3. On first run, bootstrap the runtime from the seed when `data/memory.db` is
   absent.
4. Run idempotent migrations after bootstrap.
5. Runtime campaign state belongs in `data/memory.db`, not the seed file.
6. Never write campaign state back into `data/world_narrative_seed.db`.
7. Preserve the seed file as a reusable baseline for new campaigns.

The existing consumer functions are the intended integration points:

- `core.memory.memory_db.bootstrap_memory_db_from_seed()`
- `core.memory.memory_db.init_memory_db()`
- `core.memory.memory_db.run_memory_migrations()`

The current bootstrap implementation copies the seed file when the runtime
database does not exist. Because the seed already contains the world-narrative
tables, bootstrap-before-migrations is sufficient for a fresh runtime. Keep
the world-narrative migration definitions in `core/memory/memory_db.py` for
defensive initialization and compatibility with runtimes created without a
seed copy.

## Public Schema

The following tables are part of the public seed contract. Do not drop or
rename columns. Additive consumer migrations are allowed when the runtime
needs indexes, helper tables, or new application fields.

### `schema_version`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `version` | TEXT | no | | PK |
| `build_date` | TEXT | no | | |
| `source_book_count` | INTEGER | no | 0 | |
| `atom_count` | INTEGER | no | 0 | |
| `alignment_count` | INTEGER | no | 0 | |
| `domain_count` | INTEGER | no | 0 | |
| `conflict_count` | INTEGER | no | 0 | |
| `deity_archetype_count` | INTEGER | no | 0 | |

The current row reports version `1.0.0`, atom count 41,216, alignment count
3,944, domain count 188, conflict count 190, and deity archetype count 246.

### `inspiration_profiles`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `profile_id` | TEXT | no | | PK |
| `profile_kind` | TEXT | no | | |
| `weights_json` | TEXT | no | `{}` | |
| `created_at` | TEXT | no | | |

Current row count: 95.

### `inspiration_atoms`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `atom_id` | TEXT | no | | PK |
| `profile_id` | TEXT | no | | FK to `inspiration_profiles.profile_id` |
| `atom_type` | TEXT | no | | |
| `label` | TEXT | no | | |
| `description` | TEXT | no | | |
| `weight` | REAL | no | 0.5 | |
| `srd_compatibility` | TEXT | no | `unknown` | |
| `entity_kind` | TEXT | no | `unknown` | |
| `seed_detail_json` | TEXT | yes | | |
| `created_at` | TEXT | no | | |

Current row count: 41,216. `entity_kind` and `seed_detail_json` are part of
the public contract and must be retained by runtime/bootstrap code.

Current `atom_type` values are:

- `alignment_axis`
- `arc_shape`
- `archetype`
- `artifact_seed`
- `cosmic_conflict`
- `cosmic_force`
- `creature_mythic_role`
- `deity_archetype`
- `faction_pattern`
- `fall_pattern`
- `heroic_cycle`
- `location_seed`
- `magic_tradition`
- `motif`
- `planar_domain`
- `relationship_pattern`
- `scene_template`
- `tone`

Current `entity_kind` values are:

- `artifact_seed`
- `faction_seed`
- `location_seed`
- `monster_seed`
- `npc_seed`
- `pattern_only`
- `scene_template`
- `treasure_seed`
- `unknown`

Current `srd_compatibility` values are `high`, `medium`, `low`, and `unknown`.

### `atom_relations`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `relation_id` | INTEGER | no | | PK |
| `left_atom_id` | TEXT | no | | FK to `inspiration_atoms.atom_id` |
| `right_atom_id` | TEXT | no | | FK to `inspiration_atoms.atom_id` |
| `relation_type` | TEXT | no | | |
| `weight` | REAL | no | 0.5 | |
| `updated_at` | TEXT | no | | |

Current row count: 0. The table and foreign keys must still be created and
preserved. It has a uniqueness contract on
`(left_atom_id, right_atom_id, relation_type)`.

### `atom_statistics`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `atom_id` | TEXT | no | | PK and FK to `inspiration_atoms.atom_id` |
| `support_count` | INTEGER | no | 0 | |
| `avg_weight` | REAL | no | 0.5 | |
| `variance` | REAL | no | 0.0 | |
| `updated_at` | TEXT | no | | |

Current row count: 41,216.

### `alignment_profiles`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `profile_id` | TEXT | yes | | PK |
| `entity_id` | TEXT | no | | |
| `entity_type` | TEXT | no | | |
| `ethical_score` | REAL | no | 0.0 | |
| `moral_score` | REAL | no | 0.0 | |
| `balance_score` | REAL | no | 0.0 | |
| `classic_label` | TEXT | yes | | |
| `confidence` | REAL | no | 0.5 | |
| `created_at` | TEXT | no | | |
| `updated_at` | TEXT | no | | |

Current row count: 3,944. The continuous scores are the primary alignment
model:

- `ethical_score`: -1.0 evil to +1.0 good
- `moral_score`: -1.0 chaotic to +1.0 lawful
- `balance_score`: 0.0 to 1.0 neutrality/detachment emphasis
- `confidence`: 0.0 to 1.0 confidence in the classification

Current `classic_label` values are:

- `chaotic_evil`
- `chaotic_good`
- `chaotic_neutral`
- `lawful_evil`
- `lawful_good`
- `lawful_neutral`
- `neutral_evil`
- `neutral_good`
- `true_neutral`

### `cosmological_domains`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `domain_id` | TEXT | no | | PK |
| `domain_name` | TEXT | no | | |
| `domain_type` | TEXT | no | | |
| `parent_domain_id` | TEXT | yes | | |
| `alignment_affinity` | TEXT | yes | | |
| `elemental_affinity` | TEXT | yes | | |
| `description` | TEXT | no | | |
| `srd_reference` | TEXT | yes | | |
| `created_at` | TEXT | no | | |

Current row count: 188. Current `domain_type` values are `demiplane`, `domain`,
`layer`, `nexus`, `plane`, and `realm`.

### `mythic_conflicts`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `conflict_id` | TEXT | no | | PK |
| `conflict_name` | TEXT | no | | |
| `pole_1` | TEXT | no | | |
| `pole_2` | TEXT | no | | |
| `description` | TEXT | no | | |
| `narrative_patterns` | TEXT | yes | | |
| `alignment_mapping` | TEXT | yes | | |
| `created_at` | TEXT | no | | |

Current row count: 190. Treat conflict poles as data, not as a closed enum;
the catalog contains many narrative values.

### `conflict_alignments`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `id` | INTEGER | no | | PK |
| `conflict_id` | TEXT | no | | FK to `mythic_conflicts.conflict_id` |
| `entity_id` | TEXT | no | | |
| `alignment_strength` | REAL | no | 0.5 | |
| `created_at` | TEXT | no | | |

Current row count: 558. `alignment_strength` is a continuous value; do not
replace it with a fixed enum.

### `deity_archetypes`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `archetype_id` | TEXT | no | | PK |
| `archetype_name` | TEXT | no | | |
| `domains` | TEXT | no | | |
| `typical_alignments` | TEXT | yes | | |
| `narrative_role` | TEXT | yes | | |
| `description` | TEXT | no | | |
| `created_at` | TEXT | no | | |

Current row count: 246. Current `narrative_role` values include `absentee`,
`antagonist`, `distant_creator`, `hungry`, `meddler`, `patron`, and `sleeping`.

### `deity_manifestations`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `id` | INTEGER | no | | PK |
| `archetype_id` | TEXT | no | | FK to `deity_archetypes.archetype_id` |
| `entity_id` | TEXT | no | | |
| `manifestation_strength` | REAL | no | 0.5 | |
| `created_at` | TEXT | no | | |

Current row count: 602.

### Campaign and narrative state tables

These tables are present in the seed schema and currently empty. Create and
retain them even when the initial row count is zero:

- `campaign_world_model`
  - `campaign_id TEXT NOT NULL`
  - `version INTEGER NOT NULL`
  - `summary_json TEXT NOT NULL`
  - `generated_by TEXT NOT NULL`
  - `created_at TEXT NOT NULL`
  - primary key: `(campaign_id, version)`
- `campaign_world_delta`
  - `delta_id INTEGER PRIMARY KEY`
  - `campaign_id TEXT NOT NULL`
  - `base_version INTEGER NOT NULL`
  - `proposal_json TEXT NOT NULL`
  - `applied INTEGER NOT NULL DEFAULT 0`
  - `applied_at TEXT`
  - `created_at TEXT NOT NULL`
- `narrative_threads`
  - `thread_id TEXT PRIMARY KEY`
  - `thread_type TEXT NOT NULL`
  - `status TEXT NOT NULL DEFAULT 'active'`
  - `summary TEXT NOT NULL`
  - `created_at TEXT NOT NULL`
  - `updated_at TEXT NOT NULL`
- `narrative_thread_events`
  - `event_id INTEGER PRIMARY KEY`
  - `thread_id TEXT NOT NULL`
  - `event_kind TEXT NOT NULL`
  - `description TEXT NOT NULL`
  - `source_event_id TEXT`
  - `created_at TEXT NOT NULL`
  - foreign key: `thread_id` -> `narrative_threads.thread_id`, `ON DELETE CASCADE`
- `narrative_actor_state`
  - `entity_id TEXT NOT NULL`
  - `entity_type TEXT NOT NULL`
  - `current_goals TEXT`
  - `current_strategy TEXT`
  - `allegiances_json TEXT`
  - `hostility_json TEXT`
  - `last_updated TEXT NOT NULL`
  - primary key: `(entity_id, entity_type)`
- `module_narrative_seeds`
  - `seed_id INTEGER PRIMARY KEY`
  - `module_slug TEXT NOT NULL`
  - `seed_type TEXT NOT NULL`
  - `content_json TEXT NOT NULL`
  - `applied INTEGER NOT NULL DEFAULT 0`
  - `created_at TEXT NOT NULL`

These tables are intended to become campaign-facing runtime state. The seed
currently provides their schema but no rows. Do not assume an empty table is
unused or safe to omit.

## Runtime Migration Guidance

The existing consumer migration `003_world_narrative_tables` already creates
the core world-narrative tables, but its current `inspiration_atoms` definition
does not include the public `entity_kind` and `seed_detail_json` columns. Add
those columns in an additive migration, or update the world-narrative migration
before it is used to initialize a new runtime database.

Recommended approach:

1. Keep `bootstrap_memory_db_from_seed()` first-run copy behavior.
2. Make migration 003 match the complete public seed schema for all 17 tables.
3. Add a new additive migration only if migration 003 has already shipped in
   environments where changing its SQL would be unsafe.
4. Add `entity_kind TEXT NOT NULL DEFAULT 'unknown'` and
   `seed_detail_json TEXT` to existing runtime `inspiration_atoms` tables when
   needed.
5. Preserve existing runtime rows during migration.
6. Add indexes only when retrieval code demonstrates a need; use
   `CREATE INDEX IF NOT EXISTS`.
7. Do not drop, rename, or narrow public columns.
8. Enable foreign keys on every runtime connection.
9. Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` in migration
   tests.

The public seed has no required custom indexes beyond SQLite primary-key and
unique constraints. Consumer-side indexes should target actual query patterns,
for example:

```sql
CREATE INDEX IF NOT EXISTS idx_inspiration_atoms_profile_kind
ON inspiration_atoms(profile_id, atom_type, entity_kind);

CREATE INDEX IF NOT EXISTS idx_alignment_profiles_entity_type
ON alignment_profiles(entity_type, classic_label, confidence);

CREATE INDEX IF NOT EXISTS idx_conflict_alignments_entity
ON conflict_alignments(entity_id, alignment_strength DESC);

CREATE INDEX IF NOT EXISTS idx_deity_manifestations_entity
ON deity_manifestations(entity_id, manifestation_strength DESC);
```

Do not add indexes speculatively to the tracked seed file. Add them in the
runtime schema/migration layer unless a future seed contract explicitly adopts
them.

## Retrieval Design

Do not dump the seed database into prompts. Retrieval must be bounded,
deterministic, and shaped for the caller.

The intended retrieval surfaces are:

- Turn-time pack:
  `get_narrative_turn_pack(module_name, location_id, active_entities, max_items=6)`
  returning `threats`, `obligations`, and `continuity`.
- Transition pack:
  `get_transition_pressure_pack(from_module, to_module, max_items=6)`.
- Builder pack:
  `get_module_seed_pack(target_module, max_items=10)`.

Use this ordering for bounded result selection:

1. priority descending
2. recency descending
3. stable opaque ID ascending

Recommended first implementation layers:

1. Add `core/memory/narrative_state.py` for seed/runtime queries.
2. Add explicit query helpers for atoms, profiles, alignments, conflicts,
   domains, deities, and campaign state.
3. Keep SQL row retrieval separate from prompt-pack formatting.
4. Return aggregate/selected fields, not arbitrary database rows.
5. Cap every retrieval result and enforce deterministic ordering.
6. Preserve confidence and continuous scores so callers can apply thresholds.
7. Use `entity_kind` to distinguish generation intent:
   `npc_seed`, `monster_seed`, `faction_seed`, `artifact_seed`,
   `treasure_seed`, `location_seed`, `pattern_only`, and `unknown`.
8. Parse `seed_detail_json` defensively. Invalid or absent detail must not make
   the base atom unusable.

## World-Model Lifecycle

At campaign start, compose a campaign-specific `campaign_world_model` from:

- selected inspiration atoms
- atom statistics
- alignment profiles
- mythic conflicts
- cosmological domains
- deity patterns when relevant
- campaign/module setup context

During play:

1. Canonical events enter runtime memory and narrative-thread tables.
2. The Ratio/EGO interpretation layer proposes a `campaign_world_delta`.
3. Approval rules determine whether a delta can be applied.
4. Applying a delta creates the next version of `campaign_world_model`.
5. Mechanical truth remains in canonical event/gameplay systems; interpreted
   world state must not silently rewrite facts.

The seed is a prior and catalog, not a campaign history. Two campaigns may
begin from the same seed while producing different relationship maps and
world-model deltas.

## Integration Sequence

Implement in this order:

1. Confirm `data/world_narrative_seed.db` hash and SQLite integrity.
2. Update/verify migration 003 for the complete public schema, especially
   `entity_kind` and `seed_detail_json`.
3. Add a fresh-runtime bootstrap test using a temporary `data/memory.db`.
4. Verify all 17 seed tables exist after bootstrap and initialization.
5. Verify representative counts and foreign-key checks.
6. Implement bounded retrieval helpers in `core/memory/narrative_state.py`.
7. Add retrieval tests for atom/profile, alignment, conflict, domain, deity,
   statistics, and empty relation-table behavior.
8. Implement campaign world-model version 1.
9. Implement delta proposal/apply lifecycle with explicit approval.
10. Wire turn, transition, and module-builder pressure packs.
11. Verify runtime writes never modify the seed baseline.
12. Verify save/export/import preserves world-narrative tables and runtime state.

## Verification Checklist

Run from the NEQ-TTRPG repository:

```bash
python3 scripts/verify_world_narrative_bootstrap.py -q
python3 -m pytest scripts/ -q
```

Add or retain tests for:

- seed bootstrap into a missing runtime database
- idempotent initialization
- complete 17-table presence
- `entity_kind` and `seed_detail_json` preservation
- row counts and schema-version validation
- integrity and foreign-key checks
- deterministic retrieval ordering
- bounded retrieval result sizes
- empty `atom_relations` handling
- campaign world-model versioning
- delta proposal/apply approval boundaries
- seed immutability after runtime writes
- save/export/import parity
- two campaigns sharing the seed but diverging in interpreted state

Useful direct checks:

```bash
python3 - <<'PY'
import hashlib
from pathlib import Path

path = Path('data/world_narrative_seed.db')
print(hashlib.file_digest(path.open('rb'), 'sha256').hexdigest())
PY
```

Expected hash:

```text
a4d8c58f6c3b3b4649d35afa6af16c408095252c3352341cbbedd072f628b5e6
```

## Non-Goals And Boundaries

- Do not regenerate or replace the seed during normal NEQ-TTRPG development.
- Do not require a semantic index for bootstrap or basic retrieval.
- Do not infer narrative meaning from identifier formatting.
- Do not use physical insertion order as a narrative signal.
- Do not write runtime campaign state into the seed file.
- Do not replace continuous alignment scores with only the nine classic labels.
- Do not treat empty relation or campaign tables as absent schema.
- Do not place raw database dumps into LLM prompts.

## Starting Point For The Next LLM

Begin by inspecting:

1. `core/memory/memory_db.py`
2. `scripts/verify_world_narrative_bootstrap.py`
3. `plans/version-2/world-narrative.md`
4. `data/world_narrative_seed.db`

Then implement the migration/schema parity for `entity_kind` and
`seed_detail_json`, add fresh-runtime verification, and create the bounded
retrieval layer. The seed is installed and ready; the remaining work is
consumer-side runtime integration.
