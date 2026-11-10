# Firelight G0 Design: Pin, Registry, Seam and Latency

Status: G0 design input for ADR-0033; not runtime authorization. ADR-0033 was
accepted 2026-11-05.
Date: 2026-11-05. Plan: `plans/v2-firelight.md` s5-s7. Companion:
`gap-inventory.md` (this directory).

G0 is docs only. G1 materializes the pin record and build script in
`scripts/` and `tmp/`; G2 builds the bridge and registry. Nothing here
changes runtime behavior.

## 1. Pin record

Path: `third_party/firelight/PIN.json` (created in G1, with the third-party
notice next to it as `third_party/firelight/NOTICE`). Proposed content for
v0.1.0, taken from the published release (verified 2026-11-05: the local copy
of `SHA256SUMS` matches `gh release download v0.1.0`):

```json
{
  "engine": "Firelight Engine",
  "author": "Eternal Tavern",
  "license": "Fair Source 1.0",
  "source": "https://github.com/MoonlightByte/firelight",
  "tag": "v0.1.0",
  "commit": "e807382cac6d8686a664b5a53f4621ea4b9865ff",
  "go_toolchain": "go1.27.1",
  "build_env": {"CGO_ENABLED": "0"},
  "build_flags": ["-trimpath", "-buildvcs=false",
                  "-ldflags", "-s -w -buildid="],
  "package": "./cmd/firelight-apply",
  "binary": "firelight-apply",
  "sha256": {
    "darwin-arm64":
      "4525fa99e9eab247ca95c2eaff22bc84b5d5f1a66db6ace0d1b54c013730190f",
    "linux-amd64":
      "fabff220c5b7a5a0add97794275bc9c3701b0d76f897b19aa4accd327235b400",
    "windows-amd64":
      "38c1cc233310ef12acd10a730854ee9e0e399cfab876a53ccd9694752279684b"
  }
}
```

Notes:

- Only `firelight-apply` is pinned. The bridge needs the stateless apply
  protocol; `firelight` (the interactive CLI) and the `nql*` aliases are
  the same builds under other names and are not used.
- `GO_VERSION` is not pinned by checksum. Its content names the build host
  (`go version go1.27.1 linux/amd64`), so a darwin build differs by design.
  The toolchain string is pinned instead.
- windows-amd64 is recorded for completeness; Windows hosting is out of
  scope (ADR-0033).

## 2. Build script design

`scripts/firelight_build.py` (G1), ASCII, SPDX header, no shell strings:

1. Read `PIN.json`. Clone or fetch the source into `tmp/firelight-src/`
   and check out `commit` detached; refuse if `git rev-parse HEAD`
   differs or the tag does not point at it.
2. Run `go build` through `subprocess.run([...], shell=False)` with
   `GOTOOLCHAIN=<go_toolchain>`, `GOOS`/`GOARCH` per target,
   `build_env` and `build_flags`. `GOTOOLCHAIN` makes Go download the exact
   toolchain; the local go1.27.3 is not used for the build.
3. Write outputs to `tmp/firelight-build/<tag>/` (gitignored). Compute
   SHA-256 and compare with `PIN.json`. Print `[PASS]`/`[FAIL]` per
   platform. Any mismatch exits non-zero and blocks adoption.
4. Cross-build all three targets on one host, as upstream does, so the
   darwin host can verify the linux binary that N3 installers bundle.
5. Installed location for a host (G2): `<data dir>/firelight/<tag>/`,
   outside git. The bridge rechecks the checksum before each process
   start (or once per process with the file's inode and mtime cached).

CI (G2 or N3): a pinned-SHA GitHub Actions job runs the same script and
uploads the verified binaries as artifacts for installers.

## 3. Family registry design

Location: `core/rules/firelight/families.json` (G2), read through one
accessor. Schema per family:

```json
{
  "family": "coins",
  "mode": "python",
  "engine_version": null,
  "phase": "G4",
  "replaces": {
    "guards": ["utils/inventory_possession_authority.py:<symbol>"],
    "validator_sections": ["<section id in validation prompt>"],
    "specs": ["tt-currency-correction-state-sync"]
  },
  "migrated_by": null
}
```

Rules:

- `mode` in `python | shadow | engine`. `engine_version` is required for
  `shadow` and `engine` and must equal `PIN.json` `tag`.
- `migrated_by` names the OpenSpec change that set `engine`.
- Validator sections are named blocks in the validation prompt; the prompt
  builder omits a block exactly when its family is `engine`. Guards check
  the registry and become no-ops (then are deleted) in the migrating change.
- A registry with an unknown family, an `engine` family without a version,
  or a version that differs from the pin fails startup checks.

Initial registry (all `python` until G2 sets candidates to `shadow`):

| Family | Phase | Notes |
| --- | --- | --- |
| storage, custody | G3 | New state; engine-owned from G3, no shadow |
| trade, item catalogue, stock | G3 | New state; price arithmetic stays host |
| charged items, recharge | G3 | Needs reviewed definitions per item |
| coins | G4 | Resource vs coin-item split decided in G1 |
| inventory possession | G4 | Needs stable item IDs first |
| equipment, worn effects, AC | G4 | De-duplicate item vs sheet effects |
| hp, temp hp, resources | G5 | Outside combat; combat via SC |
| spell slots, feature uses | G5 | Host keeps maxima by class and level |
| rests | G5 | Host composes the rest; engine applies |
| timed conditions, concentration | G5 | After the clock is unified |
| ammunition, recovery | G5 | Spend and recover owner agreed with SC |
| damage, healing, saves | G5 | Bookkeeping only (ADR-0033) |
| clock | G5 | One epoch; 28-day month calendar kept host |
| ability checks, skills | G5 | Settled here: with saves outside combat |
| stats, proficiency, derived totals | G6 | Settled here: follow level, with XP |
| xp, level-up tables | G6 | Host awards and splits XP |
| quests | G6 | Import status without inventing history |
| occupants | G6 | With plot and scene presence owners |
| world map, travel | -- | Deferred to Spatial SP4 decision |
| journal, relationships | -- | Not adopted in v0.1.0 |

The gap inventory left checks, proficiency and derived stats unassigned.
They are assigned above: checks move with saves (both read the same
derived bonuses at the point of a roll); proficiency and derived totals move
with level, because level changes them.

## 4. Identity prerequisites

From the gap inventory (s2, s3): the engine requires stable typed IDs and
the fork keys characters and items by name. Before any family enters
`shadow`, G2 needs:

- Character IDs: `character_id` populated for every PC and sheet NPC, with
  `party_tracker` resolution by ID and name kept as display. Rename keeps
  the ID.
- Item IDs: a stable per-row item ID written once by the host through
  `update_character_info()`; duplicate display names stay allowed.
- Place, quest and condition-instance IDs, world-qualified.

This is migration work owned by G2, done through canonical APIs with 1-PC
and 4-PC tests. It is the largest G2 cost and the main G1 question.

## 5. Receipt-to-envelope seam (handed to Narrator P0)

The bridge joins host-owned fields to each committed engine event. Proposed
mapping for P0 to ratify:

| Narrator envelope field | Source |
| --- | --- |
| event ID | host: `<commit id>:<engine event id>`; engine IDs are local to one world and are not global |
| campaign and world refs | host |
| worldline, generation | host; `expected_revision` fences stale generations |
| turn and commit ID | host commit ID; also the engine `request` |
| schema version | host envelope version plus `PIN.json` tag |
| in-game time | engine clock tick after the event, converted by host epoch |
| recording time | host wall clock at commit |
| operation | engine event `kind` and operation index |
| before, after | engine event body (typed) |
| actor | engine `actor` (attribution only; authorization is host) |
| provenance | `engine:<tag>` plus family mode at commit |
| semantics, perspective | host (Narrator P0 owns) |

Rules:

- Receipt `request` equals the host commit ID. Event `request_id` is
  carried through unchanged; the two are not conflated.
- Refusals produce no envelope events. Exit 2 or 3 produces none.
- Shadow-mode events are logged for disagreement reports and never enter
  the envelope or Hindsight.
- The live-state document and the pending receipt file join the Narrator
  P2 save manifest.

## 6. Write order and crash recovery

`docs/LIVE_STATE.md` "The host's write order", applied to the fork:

1. `safe_write_json` a pending record: request, response, receipt, new
   document, commit ID.
2. Apply receipt after-values to canonical records through canonical APIs.
3. `safe_write_json` the new live-state document.
4. Delete the pending record.

On startup or before the next call, a pending record is reapplied using
absolute after-values (idempotent), then cleared. The pending record is part
of correctness, not logging: an already-applied live-state retry returns no
receipt, and item-only changes leave no retry record, so the host cannot
recover them from the engine. G2 fault-injects a crash after each step.

## 7. Latency budget proposal

Upstream medians (WSL2, i9-13900H) are far below these numbers: 25 ms for a
four-character 1,000-item world. The budget leaves room for a slower host
and the fork's projection and writeback, which upstream does not measure.

| Stage | p50 | p95 |
| --- | --- | --- |
| World projection (cached per campaign revision) | 20 ms | 60 ms |
| Process call (spawn, encode, engine, decode) | 50 ms | 150 ms |
| Canonical writeback and document write | 15 ms | 40 ms |
| Total per engine call | 100 ms | 250 ms |

At most two engine calls per player turn outside combat (proposal plus one
corrected proposal after a refusal). G1 measures each stage separately on
1-PC and 4-PC Capture Arena worlds, plus a 10,000-item stress world. A miss
on `live_state` triggers evaluation of checkpoint mode before G2, and the
added p95 must also fit the Narrator turn caps when P0 sets them.

## 8. G1 corpus

- Seeded Capture Arena copies: 1-PC and 4-PC parties, the current
  inventories, plus a synthetic 10,000-item world for the size limits.
- One recorded session's inventory and resource changes, replayed as
  engine actions; every disagreement is listed against the gap inventory.
- Fixture route durations added in the spike copy only (the Arena map has
  none); no change to published modules.
- Report: build checksums per platform, latency per stage, world source
  size, disagreement list, and answers to gap-inventory s7.
