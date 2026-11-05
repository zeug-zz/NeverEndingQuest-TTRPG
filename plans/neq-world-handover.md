# NEQ-world Producer-to-NEQ-TTRPG Handover: Structured Seed Pilot

Updated: 2026-10-27
Audience: NEQ-world producer, then NEQ-TTRPG consumer/integration agent.
Status: PRODUCER PILOT DELIVERED to the consumer seed path; consumer integration
is pending. This is not publication approval or a claim that runtime integration
has been tested.

Owner sequencing clarification (2026-11-05): this is the 240-fragment
evaluation bundle, not an instruction to start production processing of the
full roughly 40k-fragment corpus. Consumer TITAN/Module Builder pilot evidence
must inform schema iteration with NEQ-world and explicit optimized-schema
sign-off first. Full-corpus execution then requires separate authorization.
Export requirements here are contract/acceptance considerations, not an
active production job. See `plans/v2-memory-pilot.md` section 7.

This document supersedes the pre-pilot export request retained in Appendix A.
The old document's statements that delivery is BLOCKED and the installed seed is
empty describe a pre-handoff snapshot, not the current artifact. The current
sections below govern. No consumer source, migration, runtime database, or game
logic was changed as part of this documentation update.

## 1. Executive Status And Ownership

NEQ-world delivered the bounded structured-world-seed pilot as a seed-only
copy. The approved baseline was preserved as the reference; the candidate and
delivered consumer seed have the same SHA-256. Exactly 240 selected
`inspiration_atoms.seed_detail_json` cells differ from that baseline. The pilot
adds no atoms, SQL columns, relations, campaign facts, or runtime mechanics.

The read-only inspected consumer seed path is
`../NeverEndingQuest/data/world_narrative_seed.db`. On 2026-10-27 its SHA-256
matched the candidate. This confirms the seed handoff, not a successful consumer
bootstrap, migration, import, retrieval integration, or game test. Those checks
are consumer-owned and remain pending. The existing
`../NeverEndingQuest/data/memory.db` was not opened, modified, bootstrapped, or
tested during this work. Never delete or overwrite it to install the pilot.

**Publication status: NOT CERTIFIED.** The pilot-specific preservation decision
does not grant privacy-minimal publication approval, legal clearance, or blanket
redistribution permission. No wider corpus enrichment was done. A semantic
review of the pilot's new prose is not legal or publication certification.

## 2. Delivered Artifact And Content Contract

| Artifact | Identity / status |
| --- | --- |
| Approved baseline | `data/world_narrative_seed_public.db`; SHA-256 `4208e6b747c36601c60ab040a0f320359f1ad5b7960b9ae5fc4255738729bd0c` |
| Producer candidate | `tmp/structured_seed_pilot/candidate/world_narrative_seed_pilot_candidate.db`; SHA-256 `6dbefe49f72733d11cc1ae6c15c41f9ce97435235842192effd9295ab56bb66e` |
| Delivered consumer seed | `../NeverEndingQuest/data/world_narrative_seed.db`; SHA-256 `6dbefe49f72733d11cc1ae6c15c41f9ce97435235842192effd9295ab56bb66e`; 26,296,320 bytes at read-only inspection |
| Selection manifest | `tmp/structured_seed_pilot/selection_manifest.json`; SHA-256 `7722bc6357829624140975e01289b055a0a8a1c6b94222f2ba5dbada06b7282a` |

The candidate report records a byte-copy of the approved baseline followed by
one transaction that updated the selected IDs in manifest order. It reports
exactly 240 changed cells, and that every other schema object and value is
preserved. The delivery report records 41,216 atoms, 41,216 statistics rows,
95 profiles, and zero relation rows in the baseline and candidate. Thus the
delivered database contains 41,216 atoms total: exactly 240 pilot details and
40,976 other atoms whose prior data remains unchanged. The rest is legacy,
unannotated, or otherwise non-pilot data; it is not implicitly v1 structured
content.

The candidate added no SQL schema change and no row to `atom_relations`.
`atom_statistics` remains at 41,216 rows. The policy preserving existing
statistics, weights, IDs, text, and schema applies only to this pilot and this
candidate. It does not replace or amend NEQ-world's general public-export policy.

There are two distinct version labels:

- The structured detail envelope has integer `schema_version: 1`.
- The actual SQLite `schema_version` metadata row stores `version = '1.0.0'`.

The table, its actual metadata row, and all table counts are recorded below.
Do not interpret `source_book_count = 0` in the public metadata row as a claim
that the data had no source material; the public artifact is source-anonymous.

## 3. Structured Detail v1 Contract

The format reuses the existing `seed_detail_json` column. It deliberately keeps
supported annotation (A) separate from inferred/authored extensions (B):

- **A / `content_supported`** is a bounded annotation supported by the same
  public atom. Each evidence item names `atom_id`, `field`, JSON Pointer `path`,
  and exact `text`; this establishes location/text correspondence, not semantic
  entailment by itself.
- **B / `extensions`** is an ordered array of independently labelled entries.
  Each entry has `group`, `field`, `value`, `derivation` (`inferred` or
  `authored`) and may have exact public `references`. B is not source evidence,
  an established campaign fact, or a committed event. Do not merge it into A.
- `extensions[].group` is `context`, `roles`, `themes`, or one of the typed
  groups above; `field` and `value` must match that group's declared type.
  `roles` and `themes` extensions use the `items` field. Each reference is an
  exact `{namespace, id}` object; references are never resolved by label.
- A evidence item has only `atom_id`, `field`, `path`, and `text`. The evidence
  field is one of `atom_type`, `entity_kind`, `label`, `description`, or
  `seed_detail_json`. Non-JSON fields use the empty root pointer; detail JSON
  uses a JSON Pointer to a scalar leaf.

The exact envelope keys are `schema_version`, `content_supported`, and
`extensions`; `schema_version` is exact integer `1` (not boolean `true`).
`content_supported` requires `context` and `evidence`, and may
contain `roles`, `themes`, `actor`, `relationship`, `faction_front`,
`information`, `location_scene`, `weather_ecology`, `alignment`, and `affinity`.
Unknown keys are invalid. The contract, validator, and full details are in
`tmp/structured_seed_pilot/data_dictionary.md` and
`scripts/structured_seed_pilot_contract.py`.

### 3.1 Common Fields, Typed Groups, And Limits

- `context` keys are `state`, `summary`, `scope`, `pressure_tags`,
  `narrative_functions`, and `target_kinds`. Scope is one of `personal`,
  `interpersonal`, `community`, `regional`, `world`, `cosmic`. The controlled
  pressure tags are `conflict`, `control`, `discovery`, `identity`, `loss`,
  `scarcity`, `survival`, `threat`, `transformation`, `uncertainty`. Narrative
  functions are `complication`, `escalation`, `revelation`, `threshold`,
  `turning_point`, `transformation`, `resolution`, `contrast`. Target kinds
  are `npc_seed`, `monster_seed`, `faction_seed`, `artifact_seed`,
  `treasure_seed`, `location_seed`, `pattern_only`, `unknown`.
- `roles` is a list of `{role, description}` objects. Role names are reusable
  lowercase labels matching `[a-z][a-z0-9_]{0,63}`, not campaign participants.
  `themes` is a list of prose strings.
- `actor`: `state`, `motives`, `fears`, `contradictions`, `voice_cues`,
  `social_tactics`, `loyalties`, `retreat_conditions`,
  `escalation_conditions`, `opportunities`, `alternatives`.
- `relationship`: `state`, `kind`, `participants`, `conditions`, `dependencies`,
  `opportunities`, `possible_consequences`, `alternatives`. Participants are
  reusable role labels.
- `faction_front`: `state`, `aims`, `resources`, `dependencies`, `phases`,
  `opportunities`, `possible_consequences`, `alternatives`.
- `information`: `state`, `channel`, `audience_roles`, `reliability`, `delay`,
  `secrecy_conditions`, `alternatives`. Channel is `messenger`, `rumor`,
  `testimony`, `propaganda`, `signal`, or `other`. Reliability is `unknown`,
  `unverified`, `reliable`, or `possibly_false`. A possibly-false report is
  attributed information, not proof that its contents are true or false.
- `location_scene`: `state`, `sensory_cues`, `clues`, `conditions`,
  `opportunities`, `possible_consequences`, `alternatives`.
- `weather_ecology`: `state`, `conditions`, `progression`, `benefits`, `costs`,
  `opportunities`, `seasonal_constraints`.
- `information.audience_roles` and `relationship.participants` use reusable
  role labels, never campaign IDs or PC identities. There is no literal
  `preconditions` key in v1; use a declared typed `conditions` field where one
  exists, plus `dependencies`, `opportunities`, `possible_consequences`, and
  `alternatives` only in groups that declare them.
- Every stateful content group uses `known`, `unknown`, or `not_applicable`;
  `known` requires at least one value, while the other states carry only
  `state`. Omitting an optional group means no content was supplied, not that
  the group is known empty. Alignment and affinity have their own states below.

Limits are enforced by the v1 data dictionary and validator: canonical JSON at
most 16 KiB; raw JSON input at most 64 KiB; nesting depth at most 16; ordinary
bounded lists of 1-8 values; evidence arrays of 1-16 items; at most 16 total
public references; and an `extensions` array of 0-16 entries. When an
extension includes `references`, that list has 1-16 entries and the whole
payload still has at most 16 references. New prose strings are at most 280
characters; evidence text is at most 1,200 characters; role labels at most 64
characters; public IDs at most 128 characters; and JSON Pointers at most 1,024
characters. Values and keys must be printable ASCII, duplicate object keys are
rejected, and numbers must be finite. Unknown fields, duplicate list values,
invalid enums and over-limit payloads fail validation.

Type notes: `context.summary` and `relationship.kind` are scalar prose;
`context.scope` and the state/channel/reliability fields are controlled enums.
The context tag/function/target fields are unique enum arrays. The other typed
prose-list fields are unique, non-empty arrays of 1-8 strings. `roles` is an
array of role/description objects; participant and audience lists are arrays of
reusable role labels, not prose descriptions.

### 3.2 Alignment And Five-Head Affinity

The existing alignment axes keep their established signs:

- `ethical_score`: -1 is Evil; +1 is Good.
- `moral_score`: -1 is Chaos; +1 is Order.
- Both detail scores are finite in [-1, 1]. `confidence` is finite in [0, 1]
  and means confidence in the classification, not its intensity.
- The SQLite `alignment_profiles.balance_score` is a separate 0..1
  neutrality/detachment emphasis; it is not itself a five-head affinity score.
  The v1 detail `alignment` object contains no `balance_score` key.
- Detail alignment states are `unknown`, `unaligned`, `known_neutral`,
  `classified`, and `not_applicable`. `unknown`, `unaligned`, and
  `not_applicable` have no scores or confidence. `known_neutral` explicitly
  provides 0.0 on both axes and a confidence. Never turn unknown into zero.
- `alignment` has only `state`, `ethical_score`, `moral_score`, and
  `confidence`; the scores are both required with confidence for `classified`
  and `known_neutral` states.

Five-head affinity (Bonum, Malum, Ordo, Chao, Statera; JSON keys `bonum`,
`malum`, `ordo`, `chao`, `statera`) is a separate concept with exactly those
five scores, each finite in [0, 1]. A known affinity also has
confidence in [0, 1] and basis `content_supported`, `inferred`, `authored`, or
`symbolic`. Unknown and not-applicable affinity have no scores, confidence, or
basis. `affinity` has only `state`, `scores`, `confidence`, and `basis`.
Symbolic affinity does not imply moral alignment, species-wide morality, or
which agent controls an actor. Statera is a head, not a sixth agent. No runtime
decision or reward is computed by this producer annotation.

Null, unversioned, malformed, unsupported-version, or structurally invalid
legacy detail is unavailable detail, not a reason to discard its base atom.
Retrieval falls back to the unchanged atom fields; no legacy value is coerced
into v1.

## 4. Actual Delivered SQLite Schema And Counts

The following counts and DDL are from the delivered file, read with SQLite
`mode=ro&immutable=1` on 2026-10-27. The candidate report records the same row
counts. `PRAGMA integrity_check` returned `ok`; `PRAGMA foreign_key_check`
returned zero rows. There are 17 user tables. Each count is exact:

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

The actual `schema_version` row is `version='1.0.0'`,
`build_date='2026-01-01T00:00:00+00:00'`, `source_book_count=0`,
`atom_count=41216`, `alignment_count=3944`, `domain_count=188`,
`conflict_count=190`, and `deity_archetype_count=246`.

Exact `CREATE TABLE` SQL from the delivered DB, ordered by table name; statement
terminators are added for display:

```sql
CREATE TABLE alignment_profiles (
    profile_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    ethical_score REAL NOT NULL DEFAULT 0.0,
    moral_score REAL NOT NULL DEFAULT 0.0,
    balance_score REAL NOT NULL DEFAULT 0.0,
    classic_label TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE atom_relations (
    relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    left_atom_id TEXT NOT NULL,
    right_atom_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5,
    updated_at TEXT NOT NULL,
    UNIQUE(left_atom_id, right_atom_id, relation_type),
    FOREIGN KEY(left_atom_id) REFERENCES inspiration_atoms(atom_id) ON DELETE CASCADE,
    FOREIGN KEY(right_atom_id) REFERENCES inspiration_atoms(atom_id) ON DELETE CASCADE
);

CREATE TABLE atom_statistics (
    atom_id TEXT PRIMARY KEY,
    support_count INTEGER NOT NULL DEFAULT 0,
    avg_weight REAL NOT NULL DEFAULT 0.5,
    variance REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(atom_id) REFERENCES inspiration_atoms(atom_id) ON DELETE CASCADE
);

CREATE TABLE campaign_world_delta (
    delta_id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    proposal_json TEXT NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0,
    applied_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE campaign_world_model (
    campaign_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    summary_json TEXT NOT NULL,
    generated_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id, version)
);

CREATE TABLE conflict_alignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conflict_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    alignment_strength REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    FOREIGN KEY(conflict_id) REFERENCES mythic_conflicts(conflict_id) ON DELETE CASCADE
);

CREATE TABLE cosmological_domains (
    domain_id TEXT PRIMARY KEY,
    domain_name TEXT NOT NULL,
    domain_type TEXT NOT NULL,
    parent_domain_id TEXT,
    alignment_affinity TEXT,
    elemental_affinity TEXT,
    description TEXT NOT NULL,
    srd_reference TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE deity_archetypes (
    archetype_id TEXT PRIMARY KEY,
    archetype_name TEXT NOT NULL,
    domains TEXT NOT NULL,
    typical_alignments TEXT,
    narrative_role TEXT,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE deity_manifestations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archetype_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    manifestation_strength REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    FOREIGN KEY(archetype_id) REFERENCES deity_archetypes(archetype_id) ON DELETE CASCADE
);

CREATE TABLE inspiration_atoms (
    atom_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    atom_type TEXT NOT NULL,
    label TEXT NOT NULL,
    description TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5,
    srd_compatibility TEXT NOT NULL DEFAULT 'unknown',
    entity_kind TEXT NOT NULL DEFAULT 'unknown',
    seed_detail_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(profile_id) REFERENCES inspiration_profiles(profile_id) ON DELETE CASCADE
);

CREATE TABLE inspiration_profiles (
    profile_id TEXT PRIMARY KEY,
    profile_kind TEXT NOT NULL,
    weights_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE module_narrative_seeds (
    seed_id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_slug TEXT NOT NULL,
    seed_type TEXT NOT NULL,
    content_json TEXT NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE mythic_conflicts (
    conflict_id TEXT PRIMARY KEY,
    conflict_name TEXT NOT NULL,
    pole_1 TEXT NOT NULL,
    pole_2 TEXT NOT NULL,
    description TEXT NOT NULL,
    narrative_patterns TEXT,
    alignment_mapping TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE narrative_actor_state (
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    current_goals TEXT,
    current_strategy TEXT,
    allegiances_json TEXT,
    hostility_json TEXT,
    last_updated TEXT NOT NULL,
    PRIMARY KEY(entity_id, entity_type)
);

CREATE TABLE narrative_thread_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    description TEXT NOT NULL,
    source_event_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES narrative_threads(thread_id) ON DELETE CASCADE
);

CREATE TABLE narrative_threads (
    thread_id TEXT PRIMARY KEY,
    thread_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE schema_version (
    version TEXT PRIMARY KEY,
    build_date TEXT NOT NULL,
    source_book_count INTEGER NOT NULL DEFAULT 0,
    atom_count INTEGER NOT NULL DEFAULT 0,
    alignment_count INTEGER NOT NULL DEFAULT 0,
    domain_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    deity_archetype_count INTEGER NOT NULL DEFAULT 0
);
```

No explicit user-named index, view, or trigger appeared in the delivered
`sqlite_master`; primary-key and unique constraints remain part of the DDL.
The table DDL is not identical to the stale schema reference in the prior
handover. In particular, `source TEXT NOT NULL` is **absent** from each of
`alignment_profiles`, `conflict_alignments`, and `deity_manifestations`. The
prior document described those columns as present/required; that description is
not true of the delivered DB. Conversely, `inspiration_atoms.entity_kind` and
`seed_detail_json` are present here. NEQ-TTRPG must compare this exact DDL with
its actual schema and migrations, and plan an explicit adapter or migration if
needed. Do not assume the old handover schema or silently add/omit `source`.

## 5. Public References And Known Gaps

The reference contract uses exact public keys only:

| Namespace | Exact public key column | Inventory |
| --- | --- | ---: |
| `atom` | `inspiration_atoms.atom_id` | 41,216 eligible IDs |
| `alignment_profile` | `alignment_profiles.profile_id` | 3,565 eligible string IDs among 3,944 rows; 379 null/non-text keys |
| `domain` | `cosmological_domains.domain_id` | 188 eligible IDs |
| `conflict` | `mythic_conflicts.conflict_id` | 190 eligible IDs |
| `deity_archetype` | `deity_archetypes.archetype_id` | 246 eligible IDs |

`public_subject` is disabled because no approved public-subject catalogue is
included. Domain parent references are resolved by exact `domain_id`. The
pilot does not use labels, string similarity, private IDs, or profile IDs as
source identities to infer joins.

The producer reference inventory reports 364 unresolved public references and
13 ambiguous polymorphic subject references **outside the selected 240-atom
scope**, using its documented public-key inventory and reference-location
rules. These are aggregate inventory findings, not a count of all label-like
strings or a claim that every such string was intended as a relation. They
were not repaired or used to create `atom_relations`. Selected pilot examples
resolve exact references; the out-of-scope findings remain limitations for a
future, separately scoped reconciliation.

## 6. Six Fixtures: Baseline Coverage Versus Pilot Additions

All six actual-ID fixtures have `status: PASS`; the fixture index binds them to
the approved baseline and selection manifest. Each `baseline_coverage` is
`PARTIAL`: that field reports baseline support separately from enhancement.
They are examples, not statements that selected atoms share a source, event,
relationship, campaign, or sequence.

| Fixture | Capability and actual selected public IDs | Baseline support and gap | B-class enhancement / limit | Workspace file |
| --- | --- | --- | --- | --- |
| `fixture_01` | Wizard / social alternatives; `archetype_npc_seed_10e8e713` | Magical power and deliberate steering; baseline has no voice-cue list or social alternatives. | Authored voice cue and two conditional listener alternatives. | [fixture_01.json](../tmp/structured_seed_pilot/fixtures/fixture_01.json) |
| `fixture_02` | Proactive bully and ordinary animal; `archetype_npc_seed_bully_431b1739`, `princes_warhound_moping_from_travel` | Repeated bullying and ordinary wolfhound behavior; no baseline unaligned state or symbolic affinity, and no relation between these atoms. | Authored response options; explicit unaligned state; separate symbolic five-head affinity. No species-wide moral claim. | [fixture_02.json](../tmp/structured_seed_pilot/fixtures/fixture_02.json) |
| `fixture_03` | Conditional faction / convoy / delayed report; `hospitable_desert_nomads`, `supply_train_absence_limits_campaign`, `dragon_corpse_found_in_desert`, `delayed_revelation_instruction` | Separate baseline fragments support shelter, supply dependency, an unreliable report, and delayed disclosure; they do not establish a shared group, report source, or event. | Authored conditional composition only. A delayed, possibly false account is not proof or fact; no source edge is added. | [fixture_03.json](../tmp/structured_seed_pilot/fixtures/fixture_03.json) |
| `fixture_04` | Ambiguous room clue; `tone_pattern_only_37ee2906` | Baseline supports a light-through-door clue without identifying the occupant; it has no multiple interpretations. | Two inferred alternatives preserve the unresolved identity and do not prescribe a PC action. | [fixture_04.json](../tmp/structured_seed_pilot/fixtures/fixture_04.json) |
| `fixture_05` | Contextual weather trade-off; `winter_weather_shifts_quickly`, `hospitable_desert_nomads`, `scene_template_pattern_only_7831301c` | Forecast, storm shelter, and snow-route cost occur in separate fragments; they do not describe one established journey. | Authored weather benefits/costs and a conditional comparison; no moral label or mechanical rule. | [fixture_05.json](../tmp/structured_seed_pilot/fixtures/fixture_05.json) |
| `fixture_06` | Two alignment axes and five heads; `princes_warhound_moping_from_travel`, `joy_outweighs_pain_philosophy`, `alignment_axis_pattern_only_1d5fb88c` | Exact public profiles support classified scores `(ethical=0.6, moral=0.2, confidence=0.8)` and known-neutral `(0.0, 0.0, 0.8)`. They do not supply symbolic affinity. | Separately shows unknown/unaligned states and five-head affinities; unknown/unaligned carry no alignment scores. | [fixture_06.json](../tmp/structured_seed_pilot/fixtures/fixture_06.json) |

Examples below are copied from the actual reviewed fixture content so this
handover remains useful if the gitignored workspace disappears:

- `fixture_01` (authored): "A listener could ask for a clear account before
  agreeing." Another authored alternative is to decline and seek independent
  advice.
- `fixture_02` (symbolic, not moral): the unaligned animal affinity has
  `bonum=0.15`, `malum=0.0`, `ordo=0.1`, `chao=0.35`, `statera=0.4`, with
  confidence `0.3`; these values are not ethical alignment scores.
- `fixture_03` (authored possibility): "A delayed, possibly false account
  might arrive, and recipients could seek another account before deciding
  whether it matters." No account is made a fact by the fixture.
- `fixture_04` (inferred alternatives): "Someone may still be awake nearby."
  Or "A lamp may have been left on while the room is otherwise empty."
- `fixture_05` labels weather benefits and costs as conditional and drawn from
  separate fragments; it makes no shared journey or outcome true.
- `fixture_06` retains the negative-is-Evil / positive-is-Good ethical axis and
  negative-is-Chaos / positive-is-Order moral axis, separately from affinity.

The actual paths above and the supporting
`tmp/structured_seed_pilot/fixtures/index.json` are project-local, gitignored,
transient artifacts. The examples here are summaries, not a replacement for
the hash-bound original fixtures while those files are available.

## 7. Deterministic Bounded Retrieval Guidance

Retrieval must be bounded and deterministic; it must not dump the database into
a prompt or infer a link from an atom label. A basic SQL candidate query can
select on stable existing columns, then apply detail facets in Python:

```sql
SELECT atom_id, profile_id, atom_type, entity_kind, label, description,
       weight, seed_detail_json
FROM inspiration_atoms
WHERE atom_type = ? AND entity_kind = ?
ORDER BY atom_id
LIMIT ?;
```

Validate the caller's limit before binding it (for example, 1 through 8 for a
small retrieval pack). If a facet is inside JSON, page through a bounded
candidate set in stable `atom_id` order and filter each row in Python; do not
call `json_extract` on untrusted legacy values without guarding malformed JSON.
An indexed JSON predicate is optional, not a v1 requirement. Exact public
reference namespaces above are the only supported join keys; labels are never
join keys.

The consumer parser should use only local standard-library code or its own
validated implementation; no Hindsight service, embeddings, provider, or
external service is needed. It should reject duplicate JSON object keys and
non-finite constants, apply the v1 byte/depth/list/key/enum/reference rules in
the data dictionary, and preserve the base atom when detail is absent or
invalid. Illustrative parsing boundary:

```python
import json

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result

def reject_constant(value):
    raise ValueError("non-finite JSON constant: " + value)

def parse_detail_for_retrieval(raw, validate_detail_v1):
    if raw is None or not isinstance(raw, str):
        return None
    try:
        if len(raw.encode("ascii")) > 64 * 1024:
            return None
        detail = json.loads(
            raw,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
        if (type(detail) is not dict
                or type(detail.get("schema_version")) is not int
                or detail["schema_version"] != 1):
            return None
        validate_detail_v1(detail)  # consumer implementation of the full v1 contract
        return {
            "A": detail["content_supported"],
            "B": tuple(detail["extensions"]),
        }
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return None  # retain and return the base atom; detail is unavailable
```

The snippet is an error-boundary example, not a complete contract validator.
After validation, keep `A` and `B` separate. Iterate every item in the `B`
array in its stored order, retaining its group, field, value, derivation, and
references. Do not use `dict.update`, collapse entries into a single
`(group, field)` key, or overlay B onto A: that would silently erase provenance
or multiple extensions. Malformed, unversioned, invalid, or unsupported legacy
JSON is a base-atom fallback, never a fact or score. Current immutable
inspection found 229 `seed_detail_json` values that raised Python's ordinary
`json.loads` parse error; no raw values are reproduced here. This is another
reason to keep the fallback path.

Fixture queries are deterministic and bounded (at most 8 selected atoms, 24
components, 16 evidence entries and 16 references per fixture; canonical
fixture at most 12 KiB). Bounded retrieval is a consumer implementation
responsibility; the producer fixture files are examples and tests, not a
runtime API or a consumer SDK.

## 8. Limitations And Non-Goals

- Only 240 of 41,216 atoms receive v1 pilot details. The other 40,976 atom rows
  are preserved and are not claimed to be enriched or uniformly parseable.
- The pilot changed no relation table rows. No selected or unselected atoms
  should be connected from textual similarity, names, insert order, or an
  inferred source sequence. Cross-fragment fixture compositions are explicitly
  authored possibilities, not baseline relationships.
- The seed is a prior/catalog of possibilities, not campaign history, a
  complete world, an established event, a fixed NPC dossier, or a scripted
  story. Rumor/testimony can be unreliable; attributed reports are not facts.
- No PC action is mandatory. No executable instruction, game rule, statblock,
  mechanical outcome, reward, or agent control decision is supplied.
- The pilot did not change consumer code, SQL migrations, `memory.db`, runtime
  state, gameplay integration, semantic indexes, embeddings, or model/provider
  setup. It did not enrich the full corpus or regenerate the public export.
- The independent semantic review is limited to the new pilot prose and the
  report's specified fixture/relationship checks. It is not review of all
  41,216 legacy atom descriptions, legal advice, rights clearance, or a public
  release certificate.
- The pilot-specific baseline/statistics precedence is not a general waiver of
  privacy, publication, exporter, or copyright requirements.

## 9. Consumer-Owned Integration Plan

The seed-only handoff is complete; the following integration work belongs to
NEQ-TTRPG. It must be separately planned and authorized in the consumer repo.
This handover itself does not authorize consumer code or runtime changes.

### Phase 1 - Receive And Independently Verify The Seed

- Confirm the installed seed path is `data/world_narrative_seed.db` and compare
  its SHA-256 with
  `6dbefe49f72733d11cc1ae6c15c41f9ce97435235842192effd9295ab56bb66e`.
- Open a read-only copy/connection; verify 17 tables, counts listed above,
  `PRAGMA integrity_check`, and `PRAGMA foreign_key_check`. Verify the detail
  v1 count is 240 and check the exact schema version metadata.
- At handoff time the report recorded a zero-byte destination WAL and verified
  the copied hash. A later read-only producer-side inspection on 2026-10-27
  again found a zero-byte `-wal`; a 32,768-byte `-shm` sidecar was present at
  that inspection. Do not delete/checkpoint sidecars as a repair. Candidate
  sidecars were zero bytes and the candidate report marked it self-contained.
- This handover did not open or test the consumer `memory.db`. Keep it intact.

### Phase 2 - Reconcile Consumer Schema Before Coding

- Compare the exact DDL in Section 4 with the consumer's current schema,
  bootstrap, initialization, and migrations. Do not rely on the old Appendix A
  DDL as a description of the delivered database.
- Confirm how the consumer will preserve `entity_kind` and `seed_detail_json`.
- Explicitly resolve that the delivered DB has no `source` column in
  `alignment_profiles`, `conflict_alignments`, or `deity_manifestations`,
  although the old handover described one. If consumer code requires a source
  field, choose and document an adapter or additive migration; do not invent a
  source title/path or silently change the producer artifact.
- Keep any consumer migration additive and idempotent. Define fresh bootstrap
  and existing-runtime paths separately, with backup and rollback criteria.

### Phase 3 - Design A Non-Destructive Import Path

- Keep the normal first-run seed bootstrap behavior only for a missing runtime
  DB. It must not overwrite an existing runtime DB.
- If existing installations need the seed content, design a separate,
  idempotent import keyed by stable public IDs and an explicit seed/content
  version. Preserve existing campaign rows, resolve ID conflicts explicitly,
  and use a transaction with a tested rollback path.
- Never delete, replace, or reset an existing `data/memory.db` to receive this
  seed. Use a disposable test DB for tests; production runtime state remains
  consumer-owned.

### Phase 4 - Implement And Test Consumer Retrieval

- Implement deterministic bounded SQL/Python retrieval using exact public IDs
  and stable ordering. Parse v1 defensively and keep `content_supported` and
  `extensions[]` separate, including each extension's provenance and
  references.
- Test null, malformed, unversioned, unsupported, over-limit, duplicate-key,
  and invalid-v1 legacy detail; the base atom must remain retrievable.
- Test exact reference resolution without label joins, unknown versus
  unaligned versus known-neutral, five-head affinity independent of alignment,
  and unreliable reports remaining attributed possibilities.
- Use the six fixtures if the transient producer workspace is available; the
  concise examples above document their intent if it is not. A consumer-owned
  fixture copy/test must record its own hashes and source.
- Do not make embeddings, semantic-index services, Hindsight, or network access
  prerequisites for the structured retrieval path.

### Phase 5 - Consumer Acceptance And Separate Gameplay Scope

- Run consumer-owned tests against a disposable fresh runtime and a disposable
  existing-runtime/import copy. Verify migrations, row preservation, schema,
  integrity/FKs, bounded retrieval, fallback, and seed immutability.
- Separately verify any existing user installation only under its approved
  backup/rollback procedure. Do not write campaign/runtime state back to the
  seed.
- Record the exact seed hash, migration/schema compatibility decision,
  installed table counts, tests and unresolved limitations in the consumer
  repo. Integration or game modifications require their own consumer plan;
  no such changes were part of this producer handoff.

## 10. Evidence And Verification Record

Evidence dated 2026-10-27 is in the producer-local
`tmp/structured_seed_pilot/` workspace (gitignored and potentially transient):

- `tmp/structured_seed_pilot/delivery_report.md`: delivered candidate and consumer hashes, scope,
  producer test totals, handoff status, coverage statement, and boundary.
- `tmp/structured_seed_pilot/data_dictionary.md`: normative v1 JSON contract, field types, namespaces,
  limits, and fallback behavior.
- `tmp/structured_seed_pilot/selection_report.md`: 240 selected IDs, stratification, baseline coverage,
  fixture anchors, and the outside-scope gap counts.
- `tmp/structured_seed_pilot/reference_inventory.json`: public namespace inventory and qualified
  unresolved/ambiguous counts.
- `tmp/structured_seed_pilot/fixtures/index.json` and
  `tmp/structured_seed_pilot/fixtures/fixture_01.json` through
  `tmp/structured_seed_pilot/fixtures/fixture_06.json`: six actual-ID retrieval fixtures and hashes.
- `tmp/structured_seed_pilot/candidate/candidate_report.json`: baseline/candidate hashes, 240 changed
  cell count, row preservation, candidate self-contained status, and inputs.
- `tmp/structured_seed_pilot/review/review_report.json`: independent review verdict and hash-bound
  findings.
- `openspec/changes/structured-world-seed-pilot/design.md` and
  `openspec/changes/structured-world-seed-pilot/specs/structured-world-seed-pilot/spec.md`:
  scope and acceptance contract.

The delivery report records 125 focused pilot tests passed (contract 66,
selection 13, shards 11, retrieval 10, candidate 13, review 6, baseline 6),
2,803 full `python3 -m pytest scripts/` tests passed, pilot `py_compile` passed,
ASCII check passed, and strict OpenSpec validation passed. It records candidate
integrity `ok`, zero FK violations, 240 changed cells, preserved weights,
statistics and relations, six PASS fixtures, byte-identical fixture
regeneration, and the seed-only handoff hash check. These are report results;
they are not consumer runtime tests.

The review report records verdict `PASS` for 1,146 hash-bound findings, all
severity `PASS`, under its stated independent reviewer scope. This review is
limited to new pilot prose, including A/B prose and authored/inferred fixture
relationships; it is not a review of legacy prose or the full corpus, nor a
rights or publication certificate. The actual delivered DB was separately
opened read-only with `mode=ro&immutable=1` on 2026-10-27: SHA-256 matched the
candidate, all 17 table counts matched the inventory, integrity was `ok`, and
FK violations were zero.
No SQLite write, checkpoint, bootstrap, runtime test, consumer source edit, or
`memory.db` access was performed for this document.

## Appendix A - Superseded Pre-Pilot Handover (Historical Only)

The prior handover body below is retained for history and to preserve useful
consumer design notes. It predates the seed-only copy and includes obsolete
statements, schema descriptions, and requests. In particular, its BLOCKED
status and empty-installed-seed report are historical; the delivered seed is
now populated and hash-verified. Its claimed required `source` columns are
contradicted by the current DDL above. Do not execute the historical export
request as current work. Current Sections 1-10 govern; consumer integration and
any consumer code change remain separate consumer-owned work.

## 1. Task for the NEQ-world agent

Inspect your private world seed and exporter, identify why the consumer received
an empty/schema-incomplete artifact, and export the approved, source-anonymous
narrative corpus needed by NEQ-TTRPG. Do not merely recreate empty tables or send
the private database wholesale. This repository has not inspected the private
database and makes no claim about its exact filename, contents or export failure.

`world_seed.db` denotes the producer's private input if that is its local name.
The consumer installation path remains **`data/world_narrative_seed.db`**.
Do not introduce a second consumer path or rename the runtime `data/memory.db`.

Read [V2 TITAN Game Engine](v2-titan-game-engine.md), especially sections 3-12,
and [V2 Narrator](v2-narrator.md) for the current design. The old six-Titan,
ten-minute-rotation and EGO/Ratio-dependent drafts are superseded. Five heads
compete: Bonum, Malum, Ordo, Chao and Statera; Statera includes Fate/neutrality.
These are volitional forces, not physical earth/water/fire/air elements.

We need fragments from which each campaign incrementally builds its own world:
distinctive actor motives/voices, relationships, factions, locations, conflicts,
omens, weather, information and consequences. The seed is potential world facts,
not a prewritten campaign, finished module, NPC roster or mandatory story script.
TITAN selects and adapts fragments; Python validates commitments; the Narrator
discloses consequences within character knowledge. Disclosed/committed details
then persist as that campaign's facts. Two campaigns can instantiate different
worlds from the same reusable corpus.

## 2. Verified consumer gap: what is actually missing

Read-only SQLite audit on 2026-10-27, before this handover edit:

| Check | Actual installed result |
| --- | --- |
| Artifact | `data/world_narrative_seed.db` |
| File size | 135,168 bytes |
| Main-file SHA-256 | `0ed5a2a74cafe26cd6bd82beddbdaa0bdb14964102282e326b4567f7b3b85de7` |
| User tables | 17 |
| Content | Only `schema_version` has a row; all other 16 tables are empty |
| Metadata | Version `1.0.0`; build `2026-06-28T06:07:24.834456+00:00`; all declared counts 0 |
| Integrity | `PRAGMA integrity_check`: `ok` |
| Declared foreign keys | `PRAGMA foreign_key_check`: 0 violations |
| Journal/sidecars | WAL mode; observed WAL 0 bytes, SHM 32,768 bytes |
| Atom schema | Missing `entity_kind` and `seed_detail_json` |
| Source fields | `source TEXT NOT NULL` exists on alignment/conflict/deity bridge tables, absent from the former handover schema descriptions |

The empty content tables are `inspiration_profiles`, `inspiration_atoms`,
`atom_relations`, `atom_statistics`, `alignment_profiles`, `cosmological_domains`,
`mythic_conflicts`, `conflict_alignments`, `deity_archetypes`,
`deity_manifestations`, and all six campaign/narrative tables listed below.
Empty campaign tables are correct; empty narrative catalogues are the blocker.
No conclusion about deliberate stripping, private corpus quality or the cause
of the export discrepancy follows from this consumer-only inspection.

The former handover described a different 26,169,344-byte artifact with SHA-256
`a4d8c58f6c3b3b4649d35afa6af16c408095252c3352341cbbedd072f628b5e6`,
95 profiles, 41,216 atoms/statistics, 3,944 alignment profiles, 188 domains,
190 conflicts, 558 conflict links, 246 deity archetypes and 602 manifestations.
Those are **historical producer claims, not verified current content or fixed
new-export quotas**. Reconcile them against the actual private source/export
logs; explain legitimate exclusions or changed counts. Compute totals from the
delivered DB rather than copying the former stated aggregate of 88,256.

Integrity and FK checks passing on empty tables do not establish useful content.
The main-file hash alone also does not prove a live WAL database is a complete
standalone distribution. Producer must deliver and verify a closed, self-contained
snapshot; consumer must not checkpoint, delete sidecars or overwrite campaigns
as an attempted repair. No seed or runtime DB is modified by this request.

## 3. Export priorities and ownership

### P0 - Blocking delivery requirements

1. Export populated approved inspiration profiles, substantive atoms and associated
   statistics; restore continuous alignment profiles, cosmological domains,
   mythic conflicts, conflict links, deity archetypes and manifestations where
   present/approved in the private corpus. Explain every unavailable category.
   A deliberately omitted optional catalogue needs an explicit capability gap,
   not fabricated rows or a claim of full readiness.
2. Include `entity_kind` and `seed_detail_json` with useful typed detail on relevant
   fragments; publishing all rows as `unknown`/null does not fulfil typed coverage.
   Mixed legacy/pattern-only fragments can legitimately lack structured details.
3. Make alignment/conflict/deity references joinable to exported public subjects.
   Opaque IDs alone are insufficient if their target entities remain private.
4. Document score semantics, JSON contracts, source sanitisation, stable-ID policy,
   schema/version, capabilities, coverage and omissions. Supply a manifest and
   reproducible validation evidence tied to the final file hash.
5. Deliver no campaign history, private text, credentials, local paths, source-book
   identity leakage or unsupported rule/statblock inventions.

### P1 - Requested enrichment for maximum TITAN usefulness

Export available approved structured actor, relationship, world-front, information,
weather and affinity patterns described below. Where private content lacks them,
report the gap and propose a separately identified enrichment pass. Distinguish
extracted/curated patterns from newly generated inferences; do not fabricate that
an enrichment already existed in the source. Do not block recovery of the core
populated export on unapproved new corpus-generation work.

### Consumer responsibilities, not NEQ-world deliverables

NEQ-TTRPG owns campaign identity, runtime instantiation, actor dossiers and control
assignment, patronage, session selection, Hindsight banks, agendas, alignment
reward evaluation, tools, declarations, mechanical state, weather rules, narration,
save/restore and migrations. Export patterns that support those features, not live
Titan plans, scored campaign results or a replacement runtime. EGO/Ratio are not
required. Model/provider configuration is not seed data. No Hindsight/vector index
or private service dependency is required for portable basic retrieval.

## 4. Required semantic export coverage

The following are retrieval capabilities and content expectations, not a demand
for one new SQL table per feature or a full dossier for every source character.
Prefer existing tables plus versioned `seed_detail_json` and documented additive
fields. Propose schema extensions explicitly with mapping/migration notes before
changing public interfaces. Preserve cross-fragment composition, not one script.

| Use in TITAN/NEQ | Exportable fragments and retrieval cues |
| --- | --- |
| Lazy actor personification, including Malarok | Specific motives, fears, contradictions, voice/register habits, social tactics, bargaining levers, loyalties, secrets, retreat/surrender/escalation patterns; alternatives and context rather than a fixed biography |
| Non-allied NPCs, monsters and animals | Role/species/ecology, capabilities as qualitative cues, motivations, individual exceptions and eligible affinity; unaligned animals must not become inherently Evil |
| Relationships and actor continuity | Oaths, debts, rivalry, patronage, trust, betrayal, attachment, changing allegiance, conditions for learning/reaction and consequences |
| Wider-world fronts | Faction aims/resources/dependencies, institutions, trade, succession, conflict, scarcity and possible phased developments with causal preconditions |
| Module interventions | Guards/patrols/reinforcements, abandoned rooms, warm-kettle clues, tracks, hazards, refuge, services, optional quests and resource opportunities |
| Disclosure/news | Rumour, testimony, propaganda, messenger/animal carrier, reliability, audience, delay and how facts could become known |
| Weather/ecology | Seasonal/regional conditions, forecasts/transitions, sensory cues, travel/visibility/tracking/shelter consequences and opportunities; not automatic moral labels |
| Narrator mood | Concise tone/emphasis patterns, mischief/solemnity/generosity/orderly procedure, compatible variants rather than instructions to favour a PC mechanically |
| Cross-module world-building | Reusable region/location/faction/artefact seeds with dependencies, compatibility, consequence and continuation cues |
| Alignment direction | Dual-axis tendencies, neutral/unaligned distinction, affinity, contextual dilemmas, supported interpretations and confidence, not hard-coded rewards |

Preserve enough concrete fantasy texture to avoid interchangeable "sneering
villain" prompts. Avoid excerpts or recognisable renamed replicas of source
characters. Malarok is a consumer acceptance exemplar: do not export a private
literary character as a supposedly established Malarok dossier. Module builders
may flag important actors; full dossiers are created lazily by TITAN at runtime.

### 4.1 Versioned detail payload

Document permitted keys, types, optionality, limits, enums and null/unknown handling.
Requested semantic groups (names negotiable, must be mapped explicitly):

- Detail schema version; subject/role and theme/context tags.
- Motivations, fears, contradictions, voice cues and social/tactical intent patterns.
- Conditions, opportunities, dependencies, possible consequences and alternatives.
- Knowledge/disclosure cues: witness, report, reliability and secrecy conditions.
- Setting/ecology/weather/season constraints and compatible/incompatible fragments.
- Titan affinity/receptivity separate from ethical classification, with confidence
  and basis (`curated`, `inferred`, `symbolic`, etc.).
- Safe provenance/derivation classification and compatibility limitations.

Not every fragment needs every group. Payloads must be bounded and composable;
no tool calls, system instructions, active goals, enforced PC actions, executable
code or promises of rule outcomes. Mechanical statblocks require a separately
approved licensed/schema-valid pipeline; narrative cues are not legal abilities.

### 4.2 Alignment and the five heads

Retain existing public field meanings even though their names are counterintuitive:

- `ethical_score`: -1 Evil to +1 Good -> Malum/Bonum tendency.
- `moral_score`: -1 Chaos to +1 Order -> Chao/Ordo tendency.
- `balance_score`: 0..1 neutrality/detachment emphasis; one input for Statera,
  not an automatic computed reward, Fate score or proof of ecological balance.
- `confidence`: 0..1 classification confidence, not alignment intensity.
- `classic_label`: optional derived nine-alignment label, not a replacement for
  continuous values. Do not silently swap the two axes or clamp unknowns to neutral.

If the private schema uses different conventions, transform explicitly and include
sign/range test cases. Preserve ambiguity, unavailable evidence and unaligned
animals using documented optional metadata, rather than inventing moral certainty.
A morally unaligned crow can have symbolic affinity for Malum and Chao. A
lawful-good figure can be receptive to Bonum and Ordo; mappings may be many-to-many.
No sixth Fate agent is required. Do not force equal counts across heads or generate
alignments to satisfy quotas. Export observed distributions and gaps honestly.

Seed tendencies are priors, not mutable campaign alignment or measures of Titan
success. The consumer's independent evidence ledger measures actual outcomes;
producer weights/statistics are not reward points.

### 4.3 References, relations and statistics

All public references must resolve without private tables: specify the namespace
and subject resolver for `alignment_profiles.entity_id`,
`conflict_alignments.entity_id`, `deity_manifestations.entity_id` and domain
parents. These polymorphic links need explicit validation beyond SQLite FKs.
Map private subjects to public atoms or an approved public subject catalogue;
never retain an inaccessible private character ID and claim it is usable.

Export approved `atom_relations` where they actually exist, with direction,
meaning, weight range and derivation confidence. Relations useful for composition
include supports/opposes, requires, consequence-of, compatible-with and variants,
but this is not a mandatory enum or an instruction to invent edges. If none exist,
declare zero and explain composition fallback; empty relations are nonblocking.

Define `weight`, `support_count`, `avg_weight` and `variance`, including units,
normalisation, missing-value handling and whether support counts distinct sources
or repeated extraction. Do not treat copied summaries as independent support.
Preserve public stable IDs across re-export when identity is unchanged; document
changed/deleted/merged IDs with public-safe mappings and schema/content versions.
IDs must be opaque, not reversible private paths, source titles or insertion order.

## 5. Public-safe export and delivery bundle

Keep private source text, bibliography/character mappings and audit evidence in
NEQ-world's private environment. Public material must pass the producer's actual
rights/distribution review; anonymisation or paraphrasing alone is not proof of
redistribution permission. Strip quotes, page references, distinctive protected
names, file paths and private-only identifiers. Export generalised approved
patterns, not raw novel text or copyrighted statblocks. Retain required SRD 5.2.1
CC BY 4.0 attribution where applicable; compatibility tags are not a rights grant.

The consumer currently has required `source` columns on alignment/conflict/deity
links. Supply a public-safe nonempty derivation category/token (not a title/path),
document its semantics, and preserve full private traceability only producer-side.
If the delivered schema instead omits these columns, propose the explicit adapter
and existing-runtime migration; do not silently ship incompatible definitions.

Deliver one versioned bundle (suggested filenames; paths agreed at integration):

1. `world_narrative_seed.db`: standalone closed SQLite snapshot, no required WAL/SHM.
2. `world_narrative_seed.manifest.json`: exact hash/bytes, schema and content/exporter
   versions, actual build time, every table count, capability flags, distribution
   summaries, omissions and public-safe provenance/licensing statement.
3. Public schema/data dictionary: CREATE TABLE/index definitions, JSON contracts,
   axis conventions, ID/subject resolver, field semantics and compatibility notes.
4. Export validation report tied to the same hash: integrity/FK checks, semantic
   reference validation, JSON/range/uniqueness checks, content/rights screening,
   coverage limitations and regeneration/reconciliation notes.
5. Bounded worked retrieval examples using real exported IDs: inputs, relevant
   SELECT/join or filter strategy, selected rows/payloads and expected capabilities.

Manifest/schema metadata must agree with actual rows. The old `1.0.0` label alone
cannot distinguish this empty artifact from a populated schema-complete one:
declare an explicit schema revision and content revision without reusing stale
hashes/timestamps. Stable IDs and logical export reproducibility are required;
if timestamps/build tools prevent byte-identical regeneration, document that and
provide a deterministic content fingerprint plus the exact delivered-file hash.

### 5.1 Required examples and producer acceptance evidence

Demonstrate real exported fragments for:

- A distinctive manipulative wizard with more than one viable social response.
- A proactive bully and an ordinary animal with non-moral symbolic affinity.
- A faction/convoy conflict with dependencies and a delayed, possibly false report.
- A room clue such as warm tea without a preordained encounter outcome.
- Weather progression with contextual benefits/costs, not "rain equals Evil".
- Dual-axis/neutrality retrieval spanning all five heads, plus unknown/unaligned.

Examples are retrieval fixtures, not precommitted campaign facts. Label any
synthetic gap-demonstration separately; it cannot prove production corpus coverage.
Show how unknown optional fields and zero relations degrade gracefully. Report
counts by atom type, entity kind, profile kind, alignment/affinity, confidence,
detail completeness and compatibility; report missing groups, not just totals.

Acceptance requires nonempty substantive core content, complete required schema,
joinable public subjects, safe content, truthful coverage, a standalone artifact
and matching evidence. Domain/deity/relationship enrichment gaps must be explicitly
accepted as reduced capability, not silently called "maximally useful" or complete.
NEQ-TTRPG will independently verify delivery and run fresh/existing-runtime tests.

## 6. Requested response from the NEQ-world agent

Return: (a) diagnosis/reconciliation of the empty consumer export; (b) which
requested data exist privately, are approved, were exported, excluded or require
enrichment; (c) delivered bundle/version/hash/counts; (d) schema/JSON/ID mapping and
examples; (e) validation/rights-screening evidence and unresolved gaps. If blocked,
name the blocker rather than exporting placeholders or fabricating success.

The following schema and consumer guidance are retained as integration reference.
Historical row counts below describe the former handover only. They do not prove
the installed artifact is populated; sections 1-6 govern this export request.

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
database does not exist; it does not import missing corpus rows into an existing
runtime. A populated, schema-complete export is required before this produces a
useful fresh runtime. Copy-before-migrations alone is not content validation. Keep
the world-narrative migration definitions in `core/memory/memory_db.py` for
defensive initialization and compatibility with runtimes created without a
seed copy.

## Public Schema Reference - Required Export Contract

The following tables are part of the public seed contract. Do not drop or
rename columns. Additive consumer migrations are allowed when the runtime
needs indexes, helper tables, or new application fields. This describes the
intended schema, not the installed schema: the two atom-detail columns are
currently missing. Validate exact DDL against the delivered schema dictionary.
The public-safe `source` fields below also reconcile the current consumer schema.

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

The old handover claimed version `1.0.0`, atom count 41,216, alignment count
3,944, domain count 188, conflict count 190, and deity archetype count 246.
The installed row instead reports zero for every count. New delivery metadata
must be recomputed from the actual export and distinguish schema/content versions.

### `inspiration_profiles`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `profile_id` | TEXT | no | | PK |
| `profile_kind` | TEXT | no | | |
| `weights_json` | TEXT | no | `{}` | |
| `created_at` | TEXT | no | | |

Historical claimed row count: 95; installed count: 0.

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

Historical claimed row count: 41,216; installed count: 0. `entity_kind` and
`seed_detail_json` are required export columns currently absent from the installed
artifact. They must be retained by runtime/bootstrap code after delivery.

Previously documented `atom_type` vocabulary (verify actual export distribution):

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

Requested/documented `entity_kind` vocabulary:

- `artifact_seed`
- `faction_seed`
- `location_seed`
- `monster_seed`
- `npc_seed`
- `pattern_only`
- `scene_template`
- `treasure_seed`
- `unknown`

Documented `srd_compatibility` values are `high`, `medium`, `low`, and `unknown`.

### `atom_relations`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `relation_id` | INTEGER | no | | PK |
| `left_atom_id` | TEXT | no | | FK to `inspiration_atoms.atom_id` |
| `right_atom_id` | TEXT | no | | FK to `inspiration_atoms.atom_id` |
| `relation_type` | TEXT | no | | |
| `weight` | REAL | no | 0.5 | |
| `updated_at` | TEXT | no | | |

Installed count: 0; the old handover also claimed 0. The table and foreign keys must still be created and
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

Historical claimed row count: 41,216; installed count: 0.

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
| `source` | TEXT | no | | public-safe derivation category/token |
| `confidence` | REAL | no | 0.5 | |
| `created_at` | TEXT | no | | |
| `updated_at` | TEXT | no | | |

Historical claimed row count: 3,944; installed count: 0. The continuous scores are the primary alignment
model:

- `ethical_score`: -1.0 evil to +1.0 good
- `moral_score`: -1.0 chaotic to +1.0 lawful
- `balance_score`: 0.0 to 1.0 neutrality/detachment emphasis
- `confidence`: 0.0 to 1.0 confidence in the classification

Documented `classic_label` values are:

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

Historical claimed row count: 188; installed count: 0. Documented `domain_type` values are `demiplane`, `domain`,
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

Historical claimed row count: 190; installed count: 0. Treat conflict poles as data, not as a closed enum;
the catalog contains many narrative values.

### `conflict_alignments`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `id` | INTEGER | no | | PK |
| `conflict_id` | TEXT | no | | FK to `mythic_conflicts.conflict_id` |
| `entity_id` | TEXT | no | | |
| `alignment_strength` | REAL | no | 0.5 | |
| `source` | TEXT | no | | public-safe derivation category/token |
| `created_at` | TEXT | no | | |

Historical claimed row count: 558; installed count: 0. `alignment_strength` is a continuous value; do not
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

Historical claimed row count: 246; installed count: 0. Documented `narrative_role` values include `absentee`,
`antagonist`, `distant_creator`, `hungry`, `meddler`, `patron`, and `sleeping`.

### `deity_manifestations`

| Column | Type | Null | Default | Key |
|---|---|---:|---|---:|
| `id` | INTEGER | no | | PK |
| `archetype_id` | TEXT | no | | FK to `deity_archetypes.archetype_id` |
| `entity_id` | TEXT | no | | |
| `manifestation_strength` | REAL | no | 0.5 | |
| `source` | TEXT | no | | public-safe derivation category/token |
| `created_at` | TEXT | no | | |

Historical claimed row count: 602; installed count: 0.

### Campaign and narrative state tables

These tables are present and empty, which is correct for a reusable seed. Create
and retain their compatibility schema but do not export private campaign rows:

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

## Consumer Integration Guidance - Not Producer Export Work

Audit the current consumer migrations against the delivered DDL before integrating.
The installed seed lacks `entity_kind` and `seed_detail_json`, and required
`source` fields must match the export or have an explicit adapter. Fixing consumer
schema does not restore missing content. Published migrations must not be edited
in place: use an additive, idempotent migration preserving runtime rows.

Recommended approach:

1. Keep `bootstrap_memory_db_from_seed()` first-run copy behavior.
2. Compare the 17-table compatibility schema and producer-declared additions with
   installed migrations; define fresh and existing-runtime upgrade paths.
3. Use additive migrations for shipped schemas and validate downgrade/rollback
   expectations before enabling new consumers.
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
10. Existing runtimes may already exist with an empty seed catalogue. Implement
    an explicit idempotent seed-content import keyed by stable public IDs/version,
    preserving campaign facts. Never delete `memory.db` or rerun first-copy
    bootstrap over it. Coordinate conflicts, changed IDs and scoped save manifests.

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

The older proposed retrieval surfaces below are consumer-owned starting points,
not implemented/verified producer APIs or immutable numeric caps. TITAN additionally
needs bounded actor/theme/affinity/context retrieval and public-subject joins;
the producer examples must demonstrate these capabilities using actual exported
IDs and documented fields. Runtime budgets are ratified in the master plan.

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

The [TITAN master plan](v2-titan-game-engine.md) owns runtime lifecycle. At campaign
start, compose only a sparse campaign-specific outline, not a complete fixed
world or an import of private story history, from:

- selected inspiration atoms
- atom statistics
- alignment profiles
- mythic conflicts
- cosmological domains
- deity patterns when relevant
- campaign/module setup context

During play:

1. Canonical events enter runtime memory and narrative-thread tables.
2. A campaign-scoped Titan proposes conditional developments/instantiations as
   typed deltas; EGO/Ratio are not prerequisites.
3. Approval rules determine whether a delta can be applied.
4. Applying a delta creates the next version of `campaign_world_model`.
5. Python alone commits permitted campaign facts and mechanics through canonical
   APIs. Distinguish seed possibilities, committed facts, attributed beliefs and
   conditional agendas. Offscreen commitment and later player disclosure are
   distinct; interpreted world state must not silently rewrite either history.

The seed is a prior and catalog, not a campaign history. Two campaigns may
begin from the same seed while producing different relationship maps and
world-model deltas.

## Integration Sequence

Implement in this order:

1. Obtain and independently verify the populated export, manifest/hash, exact
   schema, content coverage and semantic references; integrity alone is insufficient.
2. Add/verify migration parity for the complete public schema, especially
   `entity_kind`, `seed_detail_json` and public-safe `source` compatibility.
3. Add a fresh-runtime bootstrap test using a temporary `data/memory.db`.
4. Verify all 17 seed tables exist after bootstrap and initialization.
5. Verify representative counts and foreign-key checks.
   Also verify non-FK subject resolution and existing-runtime seed-content import.
6. Implement bounded retrieval helpers in `core/memory/narrative_state.py`.
7. Add retrieval tests for atom/profile, alignment, conflict, domain, deity,
   statistics, and empty relation-table behavior.
8. Implement campaign world-model version 1.
9. Implement delta proposal/apply lifecycle with explicit approval.
10. Wire turn, transition, and module-builder pressure packs.
11. Verify runtime writes never modify the seed baseline.
12. Verify save/export/import preserves world-narrative tables and runtime state.

## Verification Checklist

After producer delivery, run the applicable focused consumer checks from the
NEQ-TTRPG repository using its venv. These commands are integration guidance,
not a claim they were run for this documentation edit:

```bash
.venv/bin/python scripts/verify_world_narrative_bootstrap.py -q
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
- populated-corpus acceptance, safe provenance and public subject resolution
- existing-runtime import without deletion, duplicate corpus rows or campaign loss
- producer examples for actor, alignment, world, disclosure and weather retrieval

Useful direct checks:

```bash
python3 - <<'PY'
import hashlib
from pathlib import Path

path = Path('data/world_narrative_seed.db')
print(hashlib.file_digest(path.open('rb'), 'sha256').hexdigest())
PY
```

Compare with the newly delivered manifest, not the historical hash above. For a
live WAL database, a main-file hash alone is not a full logical snapshot; acceptance
uses the producer's closed standalone artifact and verified logical contents.

## Non-Goals And Boundaries

- NEQ-world produces the requested replacement export; normal NEQ-TTRPG runtime
  must not regenerate it or overwrite campaigns to install it.
- Do not require a semantic index for bootstrap or basic retrieval.
- Do not infer narrative meaning from identifier formatting.
- Do not use physical insertion order as a narrative signal.
- Do not write runtime campaign state into the seed file.
- Do not replace continuous alignment scores with only the nine classic labels.
- Do not treat empty relation or campaign tables as absent schema.
- Do not place raw database dumps into LLM prompts.

## Starting Point For Each Agent

**NEQ-world producer:** begin with sections 1-6, inspect your private source and
export pipeline, reconcile missing content, and return the verified public bundle
and explicit gaps. Do not modify NEQ-TTRPG runtime or claim consumer gates passed.

**NEQ-TTRPG consumer:** independently inspect the delivered artifact alongside
`core/memory/memory_db.py`, `scripts/verify_world_narrative_bootstrap.py`,
`plans/v2-titan-game-engine.md` and `plans/v2-narrator.md`. Scope migrations,
content import, retrieval and runtime changes through authorised OpenSpec work.
The current installed seed is not content-ready; neither agent may replace this
blocker with a schema-only PASS or overwrite existing campaign state.
