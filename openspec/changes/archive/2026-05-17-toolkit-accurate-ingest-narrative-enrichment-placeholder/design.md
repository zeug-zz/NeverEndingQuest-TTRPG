# Design: Narrative Enrichment Placeholder

## Contract Layer (MUST)

### Artifact Boundary

The first implementation SHALL create only a reviewable artifact contract for future enrichment. It SHALL NOT apply field patches, call providers, or mutate generated module data.

The future artifact path is:

```text
narrative_enrichment_plan.json
```

The artifact SHALL default to profile `none` and SHALL be optional for accurate-ingest completion.

### Artifact Shape

The future artifact SHOULD follow this shape:

```json
{
  "version": "narrative_enrichment_plan.v1",
  "status": "not_requested|planned|blocked|skipped",
  "profile": "none|three_stance_single_turn|five_playline_stateful|custom",
  "source_fidelity_status": "pass|degraded|blocked|failed|unknown",
  "can_apply": false,
  "auto_apply": false,
  "eligible_fields": [],
  "field_budgets": {},
  "source_locks": {
    "required_npcs_locked": true,
    "required_locations_locked": true,
    "plot_topology_locked": true,
    "puzzle_rules_locked": true,
    "source_evidence_locked": true
  },
  "profile_notes": [],
  "blockers": [],
  "warnings": [],
  "artifact_refs": {}
}
```

### Source-Lock Rules

An enrichment plan SHALL NOT be considered applicable when source fidelity has blockers. Enrichment planning SHALL NOT lower source fidelity or replace source truth. Specifically, enrichment SHALL NOT:

- rename required source NPCs or locations;
- remove source evidence references;
- alter main plot topology;
- alter puzzle/trial rules or required clue dependencies;
- replace source-authored tone with an unrelated genre frame;
- suppress required source content to make room for enrichment.

### Profiles

The initial profile vocabulary SHALL be:

| Profile | Meaning |
|---|---|
| `none` | Default. No enrichment requested. |
| `three_stance_single_turn` | Deepvault-style single-turn interpretive stance planning. |
| `five_playline_stateful` | Ancients Lab-style multi-playline stateful planning. |
| `custom` | Future review-gated user-authored enrichment profile. |

### Runtime and Compatibility

Legacy and non-accurate-ingest flows SHALL continue without enrichment artifacts. Accurate-ingest flows SHALL remain complete when profile is `none` or when enrichment is skipped.

Existing Homebrewery adventure markdown generation SHALL remain finisher-owned. `MODULE_SUMMARY.md` is already generated after successful toolkit finishing and served by the existing download endpoint. The enrichment placeholder SHALL NOT duplicate, bypass, trigger, or replace that generation path.

## Guidance Layer (SHOULD)

- The helper implementation should live in `utils/toolkit_narrative_enrichment_plan.py` in the later apply step.
- Artifact persistence helpers should extend `utils/toolkit_homebrew_upload_contract.py` only when implementation begins.
- UI/status surfacing should be compact and subordinate to source-fidelity status.
- The first implementation should use deterministic inputs only: selected profile, build/source fidelity reports, blueprint identity, and allowed field budgets.
- The plan may include a future reference to `MODULE_SUMMARY.md`, but should not make adventure markdown generation a dependency of enrichment planning.
- Provider-backed text generation should be deferred to a separate change.

## Open Questions

- Should profile selection be user-facing in the first implementation, or stored as a config/default only?
- Should `custom` be accepted as a stored profile before a custom-profile schema exists, or reserved for later?
- Should warning-only source fidelity allow enrichment planning, or should only full `pass` allow non-`none` profiles?
