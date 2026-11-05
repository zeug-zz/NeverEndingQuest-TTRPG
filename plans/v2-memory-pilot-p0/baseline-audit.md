# V2 Memory Pilot P0 Baseline Audit

Status: Read-only consumer audit complete; this is not implementation approval.
Date: 2026-11-05.

## 1. Scope and method

This audit follows `plans/v2-memory-pilot.md` P0. It reviews the current memory
pilot, handover, TITAN and Narrator plans; the applicable code and OpenSpec
contracts; and only the immutable SQLite copies under `tmp/memory-pilot-p0/`.
Both copies were opened with `mode=ro&immutable=1`. This pass did not open,
query, copy, or modify `data/memory.db`, `data/world_narrative_seed.db`, or
installed campaign files. No runtime bootstrap, import, save, restore, gameplay,
provider, network, or git operation was run. No private campaign narrative,
entity names, or raw seed detail is reproduced here.

The copies' SHA-256 values, sizes, SQLite `quick_check`, foreign-key check,
table counts, and aggregate detail counts were recalculated. Source-file hashes
and source sidecar sizes below are the recorded values from snapshot acquisition;
they were not re-read in this audit. Snapshot sidecar state was checked locally.

## 2. Snapshot provenance and integrity

### Runtime memory

- Recorded source main-file SHA-256:
  `7a9e5df9e4c80e763724baf79c940da15f17e43835df2ecc13073f7fcc731855`
- Immutable copy: `tmp/memory-pilot-p0/memory.db`
- Copy size: 137,379,840 bytes
- Copy SHA-256:
  `fb11f6089293a4b27aeaedd9680c38afb5f397517a0cd02073d3e87085abd5c5`
- Copy sidecars: `-wal` absent; `-shm` absent
- Copy checks: `quick_check=ok`; 0 foreign-key violations

### World seed

- Recorded source main-file SHA-256:
  `6dbefe49f72733d11cc1ae6c15c41f9ce97435235842192effd9295ab56bb66e`
- Immutable copy: `tmp/memory-pilot-p0/world_narrative_seed.db`
- Copy size: 26,296,320 bytes
- Copy SHA-256:
  `d8a9184c60151d02b19fa8e2e4b18f615904cd02fbd1d6717ca8ef5db25399f6`
- Copy sidecars: `-wal` absent; `-shm` absent
- Copy checks: `quick_check=ok`; 0 foreign-key violations

At acquisition, the recorded runtime source had no `-wal` or `-shm`; the seed
source had a zero-byte `-wal` and a 32,768-byte `-shm`. These are historical
sidecar observations, not current source inspection. Both SQLite-backup copies
have different byte hashes from their recorded source main files. The copies
are not byte-identical; the digest difference alone does not establish missing
logical rows. Since source databases were not queried, this audit does not claim
a row-by-row source/copy equivalence proof. P1 fixtures must bind to the copy
hashes above and must independently verify the final delivered seed hash.

## 3. Data and schema findings

### Delivered seed copy

The immutable seed copy contains 17 user tables. Counts are:

| Table | Rows |
| --- | ---: |
| `schema_version` | 1 |
| `inspiration_profiles` | 95 |
| `inspiration_atoms` | 41,216 |
| `atom_relations` | 0 |
| `atom_statistics` | 41,216 |
| `alignment_profiles` | 3,944 |
| `cosmological_domains` | 188 |
| `mythic_conflicts` | 190 |
| `conflict_alignments` | 558 |
| `deity_archetypes` | 246 |
| `deity_manifestations` | 602 |
| `campaign_world_model` | 0 |
| `campaign_world_delta` | 0 |
| `narrative_threads` | 0 |
| `narrative_thread_events` | 0 |
| `narrative_actor_state` | 0 |
| `module_narrative_seeds` | 0 |

The seed has 4,060 non-null `seed_detail_json` cells. Ordinary JSON parsing
failed for 229; 240 cells have a JSON object with integer `schema_version: 1`.
That is a shape count, not independent validation of every v1 rule or semantic
claim. The remaining populated cells are legacy or another format and must
fall back to the base atom unless a consumer validator accepts them. The seed
has `entity_kind` and `seed_detail_json`; its SQLite metadata version is `1.0.0`,
distinct from the detail envelope's integer version 1. Its six campaign/runtime
tables are empty, as expected for a reusable catalogue. `source_book_count=0`
is source-anonymous metadata, not proof that source material did not exist.

The handover reports 364 unresolved public references and 13 ambiguous
polymorphic references outside the selected pilot scope. These are producer
inventory findings, not consumer-verified full-corpus results. The pilot has
zero relation rows; no relations should be inferred from labels, textual
similarity, ordering, or fixture composition. Publication and rights clearance
remain explicitly uncertified.

### Runtime memory copy

The runtime copy contains 23 user tables and six applied migrations. Aggregate
counts include 18,486 memory events, 18,484 journal entries, 55,516 links,
7 entities, 8 aliases, 7 role rows, 116 diary entries, 1 diary state row, and
4 story cache rows. `memory_event_provenance`, `inspiration_profiles`,
`inspiration_atoms`, `atom_relations`, `atom_statistics`, `campaign_world_model`
and `campaign_world_delta` each contain zero rows. The runtime has no
`alignment_profiles` table.

The runtime `inspiration_atoms` table lacks the seed's `entity_kind` and
`seed_detail_json` columns. The runtime migration defines `inspiration_atoms`
without them and does not create `alignment_profiles`; it also does not include
the seed's domain, conflict, deity, or narrative catalogue tables. Conversely,
the runtime has event, identity, diary, policy, audit, and migration tables not
in the seed. A seed copy is therefore not a schema merge. P1 must decide among
an explicit adapter, additive versioned migration, or read-only seed catalogue;
it must preserve seed content and provenance without silently changing the
producer artifact.

## 4. Seed timeline and stale-reference reconciliation

The current authority is `plans/neq-world-handover.md` sections 1-10, as
specified by `plans/v2-memory-pilot.md` sections 2-3. The handover records the
delivered populated seed at SHA-256
`6dbefe49f72733d11cc1ae6c15c41f9ce97435235842192effd9295ab56bb66e` and
41,216 atoms. The memory pilot's current baseline agrees with that recorded
source hash and the immutable copy's logical counts.

`plans/v2-titan-game-engine.md` section 3 records a dated, pre-delivery
observation: seed hash `0ed5a2a74cafe26cd6bd82beddbdaa0bdb14964102282e326b4567f7b3b85de7`
and empty content tables. It is historical evidence of the earlier state, not
the current seed status. The current handover explicitly supersedes its empty
seed claim. The handover's Appendix A also preserves the old empty-seed request,
former hash and obsolete schema claims; its appendix preface says not to execute
those requests. The current handover says the delivered seed lacks `source`
columns formerly described for alignment/conflict/deity bridge tables. Do not
revive those old column assumptions or infer a producer defect from them.

`plans/v2-memory-draft.md` section 7 already says the pilot is delivered and
supersedes the empty-seed observation. `plans/v2-narrative-overview.md` index
health check 4 calls for reconciling the TITAN hash; this report records that
reconciliation. The overview's schedule says to prepare/send the producer
request early; that schedule is not permission to send this draft. Archived
Titan/memory plans and the handover appendix remain historical references.
No other planning file was changed under this task's two-file limit.

## 5. Identity and campaign-scope audit

The memory schema has global `entities`, aliases, temporal role rows, events,
links and provenance. `memory_events`, `memory_links` and
`memory_event_provenance` have no campaign ID, worldline ID, effective
generation, or perspective scope columns. `campaign_world_model` and
`campaign_world_delta` have `campaign_id`, but this does not scope or authorize
the event/link history. The inspected provenance table is empty. The save
metadata code stores a module and worldline lineage, but no stable campaign ID
or immediate effective-generation token.

Current retrieval is entity-scoped, not campaign-authorized. `get_entity_timeline`
accepts entity ID, limit and DB path; `get_context_memories` accepts scene type,
active entity IDs, limit and DB path; retirement/return retrieval accepts one
entity ID. None accepts campaign, worldline/generation, caller perspective,
knowledge permission or query text. `get_context_memories` is not token-budget
aware. Limits are bounded (1-100; context default 12; campaign milestones cap
at 15 and query up to five events per party entity), but bounds do not provide
isolation. Optional retrieval auditing opens a separate writable connection;
no retrieval API was invoked against the audited snapshots.

`ACTION_LOOKUP_MEMORY` normalizes supplied entity names and retrieves timelines;
it does not use a query-text parameter. The memory route reads the global
`DEFAULT_MEMORY_DB_PATH` and accepts an entity ID, with no campaign/generation
parameter in the route contract. Main prompt milestone injection is partial
and occurs only on the first validation attempt. These are existing integrations,
not the planned server-resolved scoped gateway. Before P1 retrieval can be
authorized, define canonical campaign and stable character identity, alias and
role-transition resolution, perspective permissions, generation fencing,
unknown-scope denial, and the exact owner of shared versus per-PC evidence.

## 6. Bootstrap, save/restore, and portability audit

`web/web_interface.py` calls `bootstrap_memory_db_from_seed()` before
`init_memory_db()`. Bootstrap copies the seed only when the runtime path is
absent; an existing runtime returns `runtime_exists` and is not merged. This
protects the existing DB from startup overwrite, but leaves an existing runtime
without newly delivered seed catalogue rows. The archived
`world-narrative-seed-bootstrap` change specifies this first-run-only behavior;
it is archived, not an active OpenSpec change.

`memory_portability.py` exports by `shutil.copy2` of the main DB file, then
creates a hash/count manifest. Import validates that manifest and copies the
package to the target; explicit overwrite is supported. The manifest's
campaign metadata is derived from active character, party member names, and
party NPCs, not a stable campaign ID. It packages the whole database rather
than a campaign-filtered slice. A live SQLite-aware snapshot boundary,
WAL-aware backup, and multi-store save cut are not established by this helper.

The save manager copies JSON files before exporting the memory package. The
export is performed separately from those copies; no shared snapshot barrier
binds their logical time. `get_essential_files()` does not list `data/memory.db`;
the pre-restore essential-file backup therefore does not back up that DB.
Restore validates a memory package before mutations, then restores JSON files
and imports the DB with `overwrite=True`. This meets the preflight contract for
invalid packages, but a later copy/import failure is not shown to roll back the
already-restored JSON files. A legacy save removes the current memory DB before
clean initialization. No such save/restore/import was run.

Worldline lineage is generated in save metadata and restore context, with a
fork on the first save after restore. It is not an immediate generation fence
for retrieval or in-flight work. P1 must test and design campaign isolation,
effective-generation fencing, SQLite backup/restore, JSON/DB consistency,
pre-restore memory backup, import collision policy, interruption rollback,
legacy-save policy, clean-server portability, and seed immutability. A SQLite
transaction alone cannot coordinate JSON and other stores.

## 7. Existing work and OpenSpec ownership

`openspec/changes/` has no active change directories; only `archive/` is present
(and a metadata file). This does not mean there are no applicable contracts.
Active specs include `memory-foundation-schema`, `memory-ingestion-idempotency`,
`memory-retrieval-ranking`, `memory-observability-readiness`,
`memory-db-portability`, `memory-save-restore-parity`, and
`memory-worldline-branching`. The seed-bootstrap change is archived. Reconcile
these contracts rather than creating a duplicate event store or migration chain.

The narrative overview assigns campaign/effective-generation fencing and save
manifest ownership to Narrator P2; Pilot P1-P2 wait for Narrator P1's migration
chain, Pilot P3 waits for Narrator P2, and TITAN consumes those shared contracts.
The overview says the pilot producer request is to be sent early; this audit
creates a ready-to-send draft only. No producer response, full seed export,
consumer import, gameplay integration, or runtime test is claimed.

## 8. P1 blockers and proposed acceptance matrix

### Schema and import

- Blocker: seed/runtime DDL differs; existing seed bootstrap does not merge.
- Acceptance: preserve every pre-existing runtime row; `quick_check=ok`; zero
  FK violations; identical retry is a no-op; changed content under an existing
  ID is an explicit conflict; injected failure/interruption rolls back; seed
  hash is unchanged. Test fresh bootstrap separately.

### Detail and retrieval

- Blocker: runtime retrieval does not parse the seed v1 envelope or preserve
  A/B provenance.
- Acceptance: test all six handover fixtures plus null, malformed,
  duplicate-key, invalid, unsupported, oversized and excessive-depth payloads.
  Every rejected detail retains the base atom; use exact IDs, stable ordering,
  and no inferred relations. Apply handover fixture caps: at most 8 atoms, 24
  components, 16 evidence entries, 16 references and 12 KiB per canonical
  fixture.

### Scope and identity

- Blocker: events and links lack campaign/worldline/generation scope; APIs rank
  before campaign authorization.
- Acceptance: test the same authored world in campaigns A/B, one-PC and four-PC
  shapes, role/name changes, unknown-scope denial, and restore with a late
  worker. Required threshold: zero cross-campaign, perspective or discarded-
  future leaks; unknown scope fails closed.

### Portability and recovery

- Blocker: package export copies the main file; save JSON and DB are not one
  consistent cut; restore rollback is not demonstrated.
- Acceptance: use SQLite-aware backup; include campaign identity and generation
  in a versioned manifest; test repeat, collision, interruption, restore
  failure, clean-host import and legacy saves. Every failed import/restore
  leaves pre-operation logical state intact; partial restore is never reported
  as success.

### Quality and privacy

- Blocker: producer reports are not full-export consumer validation; rights and
  publication are not certified.
- Acceptance: hash-bind final public artifact, DDL, manifest and validation
  report; all public references resolve or are explicitly unresolved; no
  private IDs/text/paths; exact coverage and limitations; rights-review status
  stated.

### Performance and quality budget

- Blocker: consumer p50/p95 or token/cost thresholds are not ratified in the
  current plans.
- Acceptance: before measuring, the owner ratifies workload, machine, p50/p95
  retrieval latency, import/restore time, prompt-token cap and qualitative
  rubric. Report distributions and failed alternatives; do not infer a PASS
  from row counts.

The structural and privacy thresholds above are hard gates, not statistical
targets: zero data loss, zero unauthorized disclosure, zero seed mutation, and
no partial success. The handover's fixture caps are producer fixture limits,
not a ratified production prompt budget. Numeric latency, token, cost and
quality thresholds remain owner decisions and must be fixed before candidate
measurements; no measured performance PASS is claimed here.

## 9. P0 disposition

The copy-only evidence, schema delta, seed timeline, retrieval/scope risks,
save/restore risks, active-spec ownership and producer questions are recorded.
The producer request is documented separately and approved for local handoff.
This closes the
read-only audit artifact task; it does not approve implementation, seed
publication, existing-campaign import, or a full-seed release. P1 remains gated
on the blockers in section 8, owner ratification of budgets, and coordination
with the Narrator/TITAN owners and NEQ-world producer.
