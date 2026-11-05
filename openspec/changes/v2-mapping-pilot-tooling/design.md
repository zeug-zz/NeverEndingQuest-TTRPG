# Design

## Context

See `proposal.md` - Why. This design is constrained by the frozen SP0 inputs in `plans/v2-mapping-pilot-prereg/`; their `MANIFEST.sha256` verified during planning.

The existing seeder copies application code and `scripts/` into `tmp/combat_capture/`, while excluding `test_*.py`, and initially copies only `Capture_Arena`. Its unmodified/default path must remain the baseline. The runtime has two prompt seams: `main.py` imports `build_enhanced_dm_note` and calls it for the non-combat path; `core/combat/prompts.py` calls `assemble_combat_prompt`. `core/combat/turn.py` parses a full JSON response object, keeps it as `parsed_response`, and consumes `narration` and `actions`; `core/combat/validation.py` checks those fields and action records without a top-level allowlist in the inspected path. The combat retry owner resolves `combat_manager.validate_combat_response` into its retry dependencies, providing a sandbox-only observation point for response metadata.

## Goals / Non-Goals

**Goals:**

- Keep all executable pilot tooling in the existing `scripts/` boundary and keep generated artifacts below project-relative `tmp/`.
- Make the frozen fixtures the sole spatial truth source and preserve the current runtime as arm A.
- Keep fixture/layout, filtered projection, renderer, adapter, ledger, scoring, M1, and D1 responsibilities separable and provider-free testable.

**Non-Goals:**

- No production spatial model, module backfill, model routing, gameplay mechanics, `core/`, `main.py`, `model_config.py`, `web/`, or client change.
- No live D1 calls or SP3/SP4 execution in this change's build. A live D1 run is a later owner-authorized operation; live captures remain orchestrator-owned.
- No separate classifier request for movement intent unless a future owner-approved scope changes the chosen channel.

## Decisions

### 1. Keep the implementation in a focused scripts package

Use `scripts/mapping_pilot/` for the new implementation, with a deliberately small public surface and no import-time provider or server startup:

| File | Responsibility |
| --- | --- |
| `manifest.py` | Verify manifest entries and frozen source bytes before any fixture generation. |
| `fixtures.py` | Load frozen truth, derive expected-property files, and generate the pilot module only inside the sandbox. |
| `layout_schema.json`, `layout.py` | Define and validate the prototype layout contract. |
| `knowledge.py` | Filter shared party-known facts by current viewpoint without creating a persistent per-PC knowledge system. |
| `projections.py` | Render B relationship statements and D schematic-plus-statements, and produce canonical packet bytes/hashes. |
| `launcher.py`, `adapter.py` | Start the sandbox runtime and install explicit opt-in wrappers; do not alter runtime source files. |
| `zone_ledger.py` | Maintain the fixture-derived shadow combat ledger and movement-hint observations. |
| `scoring.py`, `evidence.py` | Calculate preregistered measures, cap/route accounting, and write per-row evidence beneath `tmp/router-rollout/mapping-pilot/`. |
| `m1.py` | Render filtered ASCII sketches from fixtures and validated D1 layouts. |
| `cartographer.py` | Extract authored source facts, build per-location prompts, validate proposed layouts, and generate audit sheets through an injected client boundary. |

Focused `scripts/test_mapping_pilot_*.py` files follow the repository's direct `unittest` script convention (`unittest.main()`), e.g. the existing `scripts/test_capture_drive.py`. This keeps tests adjacent to script tooling and lets each task test only the modules it introduces. The existing sandbox copy includes non-test scripts, so `launcher.py` can be invoked from the copied `scripts/` tree; tests are not copied.

This is smaller than introducing `core/mapping/`, a production schema family, or a general experiment framework. Reusing or modifying Capture Arena's authored module in place was rejected because it would make arm A and existing capture gates depend on pilot-specific content. Instead, pilot seeding adds a separate `Mapping_Pilot_Arena` directory below `tmp/combat_capture/modules/`; that is inside the sandbox copy and is not the repository's `modules/` directory or published catalog.

### 2. Verify the sandbox injection seam before implementation

The first implementation task is a stop/go verification of the copied-runtime seams, before other code changes. It checks that the sandbox launcher can wrap the `main.build_enhanced_dm_note` binding, `core.combat.prompts.assemble_combat_prompt`, and the response observation path while delegating to the originals. Current source inspection supports the no-core-edit approach. If the copied runtime cannot expose those seams, stop and request explicit owner approval; an environment-gated `# TABLETOP MODE:` core hook is not an automatic fallback and must not be added by this task.

The launcher requires an explicit mapping-pilot arm. For A it does not install augmentation wrappers. For B/D it wraps only the copied process's imported functions: exploration packet bytes are appended at the DM-note boundary; D combat context is appended after prompt assembly. The adapter records the actual packet bytes and hash it supplied, not a reconstructed representation. It delegates all other arguments, return fields, and exceptions unchanged.

The adapter snapshots one packet at the accepted logical-turn boundary and reuses those exact bytes across retry prompts and any same-turn transition prompt. The first seam task must verify that the launcher can identify that boundary in the sandbox runtime; adapter tests then simulate repeated normal, retry, and transition uses. If stable turn identity cannot be established without editing core code, stop for owner review rather than keying cache state to a guess. Packet-hash observations are bounded to the row evidence and contain no credentials.

### 3. Use the frozen truth files as inputs, not as generated runtime state

Before creating directories or writing sandbox content, `manifest.py` reads the manifest from the preregistration directory and verifies every listed relative path against SHA-256. It fails closed on a mismatch. `fixtures.py` then reads the four canonical fixtures, emits only the required sandbox module representation, and derives a distinct expected-properties payload from each fixture's `expected_properties`. The source fixtures and preregistration remain read-only.

The seeder extension is opt-in and branches only when the pilot-specific options are present. The omitted-option path remains byte-for-byte compatible. Allowed seed values come from `counterbalance.json` (planned seeds 5101-5106 and 5201-5204; reserve seeds 5901-5904). It records the effective seed and party identity. Dry seeding covers every registered fixture for both P1 and P4 without starting a server.

### 4. Filter once, then render equivalent B/D packets

`layout.py` validates stable IDs and explicit feature, exit, location, anchor, and authored-distance relationships. `knowledge.py` produces a single canonical party/viewpoint projection: shared party facts remain shared, while viewpoint-specific perception is filtered for the current prompt; the tooling does not persist character knowledge or infer new discoveries. It excludes hidden facts and unperceived exits, marks unknown destinations as `unknown`, labels the layout `schematic`, and omits distances not present in authored fixture data.

`projections.py` renders B from canonical facts as concise relationship statements. D renders an ASCII sketch plus those exact same statements, not a second fact set. Both append the instruction verbatim from the preregistration: `Use these places as the stable stage of the scene. Refer to landmarks naturally when relevant; do not recite the map, coordinates or this note.` Stable key ordering and explicit ASCII serialization make bytes and packet hashes reproducible. M1 reuses the same filtered projection and labels its sketch schematic; it does not infer exits, geometry, or distance.

### 5. Choose the additive movement-hint channel; do not add a classifier call

The chosen channel is an optional top-level `movement_hint` in the D-only sandbox prompt contract, with `from`, `to`, `disengage`, and `cover_sought` fields. This is supported by the inspected response path: the turn stage parses the complete JSON object and passes the raw response to the combat validation wrapper; validation requires `narration` and `actions` but does not reject other top-level fields in this path. The adapter wraps the sandbox's `combat_manager.validate_combat_response`, parses only the optional hint for observation, and delegates the original response unchanged. A provider-free contract test must prove the field survives this path before live use. The separate-classifier alternative is rejected because it adds a request and latency when the additive field is available; it would also consume the preregistered row/matrix attempt caps. If the provider-free test disproves the inspected seam, stop for owner review rather than silently adding a classifier or core hook.

`zone_ledger.py` initializes the party-size-specific positions, engagement groups, adjacency, elevation, cover, bands, and enemy policy exactly from `combat_stage_tavern.json`. It updates only its own shadow record from valid hints and deterministic fixture enemy phases. Invalid or absent hints and narrative contradictions are observations; none changes or vetoes production combat state. Distances remain graph bands, never feet or metric values.

### 6. Keep scoring, evidence, and offline cartography reproducible

`scoring.py` implements the definitions in preregistration section 7.1, including not-estimable denominators, separate guard counts, `unknown` cost/token values, and per-arm route distributions. It applies 800 total / 35 per-row attempt ceilings and 6-hour total / 25-minute per-row wall-time ceilings; D1 has its separate 60-call cap. Resolved-model share differences of at least 10 percentage points from A are flagged, as are fallback-share or unknown-model-share differences. The scorer does not pin Auto Router's downstream model or issue the primary's live verdict.

`evidence.py` creates unique bundles under `tmp/router-rollout/mapping-pilot/<gate>/<run-id>/`, refuses reuse, and separates offline/provider-free artifacts from live-row evidence. It records the fields required by preregistration section 8 and keeps unknowns explicit. It excludes secrets and credential/config values.

`cartographer.py` accepts an owner-configured set of three published module slugs and a selected set of about 20 locations; it does not choose or write modules. Python extraction and validation run locally. A prompt is built per location, while an injected fake client exercises response handling and the 60-call budget provider-free. The later live D1 run is deliberately not an apply task in this change.

### 7. Preserve repository boundaries and default behavior

Python source under `scripts/mapping_pilot/` and new tests carry the repository Fair Source header and ASCII-only text. Any sandbox JSON state write uses existing atomic helpers. Tests and tools use project-relative `tmp/` outputs. Final verification checks that the source diff is limited to `scripts/` and this OpenSpec change and that `core/`, `main.py`, `model_config.py`, published modules, `web/`, `MULTIPLAYER_MODE`, and party-size gates remain untouched. No server is started for provider-free build verification, and port 8357 is never inspected or used.

## Risks / Trade-offs

- [Manifest mismatch or changed preregistration bytes] -> Fail before fixture generation and name the mismatched path; do not repair or regenerate the frozen manifest.
- [Prompt seam or stable turn identity is unavailable in the copied sandbox] -> Stop at the first seam task and request owner approval; do not add a core hook or guess a cache key.
- [The model omits or malforms `movement_hint`] -> Record missing/invalid hint; do not classify it as a valid move, change mechanics, or issue another request.
- [Auto Router resolves different models across arms] -> Preserve per-call identity, flag the preregistered imbalance, and report it as a confound rather than pinning a model.
- [D1 source selection affects feasibility] -> Keep module selection configurable and provider-free; require the owner to choose the three slugs and location set before the separate live run.

## Migration Plan

No production migration exists. The new seeding flags and launcher are opt-in; existing seeder invocations continue through their unchanged path. All pilot module data and evidence are scratch artifacts under `tmp/` and are not published.

## Open Questions

- Before a later live D1 run, which three published module slugs and approximately 20 locations should the owner approve? The tooling accepts an explicit configured selection, so this does not block its provider-free implementation.
- The live D1 run itself remains gated on separate explicit owner go-ahead; it is not part of this change's implementation/build task list.
