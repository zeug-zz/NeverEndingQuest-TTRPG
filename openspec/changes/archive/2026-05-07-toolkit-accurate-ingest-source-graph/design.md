## Context

This change implements Phase 1 from `plans/accurate-ingest.md`: deterministic source manifest and source graph foundation. It intentionally does not yet solve full fidelity loss. It creates the ground truth artifact that later OpenSpec changes will use for multi-pass extraction, fidelity verification, builder blueprints, and enrichment placeholders.

## Contract Layer (MUST)

- Source graph generation MUST run before the existing LLM normalization call for readable normalization-required uploads.
- Source graph generation MUST be deterministic and Python-owned where source patterns are mechanically discoverable.
- Source atoms MUST include evidence references with source path, section or heading context, line range where available, and bounded excerpt.
- Source atoms MUST include `type`, `summary`, `criticality`, and `confidence` fields.
- The pipeline MUST persist `source_manifest.json` and `source_graph.json` in the Homebrew workspace when a workspace is available.
- Source graph generation failure MUST NOT block legacy normalization unless artifact persistence enters an already fail-closed path.
- Existing normalized packet validation MUST remain backward compatible for old workspaces.
- Python user-facing console/log text introduced by this change MUST be ASCII-only.

## Guidance Layer (SHOULD)

- Implement `utils/toolkit_source_manifest.py` as a standalone utility so later LLM extraction and deterministic importer work can reuse it.
- Keep extraction conservative. Prefer high-confidence explicit signals such as headings, markdown tables, bold spans, and map-key headings before broad proper-noun matching.
- Use stable source atom IDs derived from source hash, atom type, normalized name/context, and line range where practical.
- Keep excerpts short enough for later review UI and prompt usage.
- Store false-positive-prone proper noun candidates as `ambiguous` or `minor`, not `required`.

## Source Manifest Shape

`source_manifest.json` should include raw mechanical extraction buckets:

```json
{
  "manifest_version": "toolkit_source_manifest.v1",
  "source_path": "...",
  "source_hash": "...",
  "headings": [],
  "tables": [],
  "location_candidates": [],
  "entity_candidates": [],
  "mechanic_candidates": [],
  "tone_candidates": []
}
```

## Source Graph Shape

`source_graph.json` should convert candidate buckets into typed source atoms:

```json
{
  "graph_version": "toolkit_source_graph.v1",
  "source_path": "...",
  "source_hash": "...",
  "atoms": [
    {
      "id": "stable-id",
      "type": "npc|location|plot_beat|puzzle|clue|encounter|item|faction|tone_marker|mechanic|unknown",
      "name": "optional display name",
      "summary": "source-grounded short summary",
      "criticality": "required|major|minor|ambiguous|ignore",
      "confidence": "high|medium|low",
      "source_refs": [
        {
          "source_path": "...",
          "section": "...",
          "line_start": 1,
          "line_end": 3,
          "excerpt": "..."
        }
      ],
      "metadata": {}
    }
  ],
  "summary": {
    "npc_candidates": 0,
    "location_candidates": 0,
    "puzzle_candidates": 0,
    "tone_candidates": 0
  }
}
```

## Extraction Heuristics

The first implementation MUST cover:

- Markdown headings with levels 1-6 and line ranges.
- Markdown pipe tables with headers and rows.
- Numbered map-key headings such as `### 1. Location Name`, `### 1 Location Name`, `### 1 - Location Name`, and `#### 1. Sub-location`.
- Existing `## Room N: Title` style headings for deterministic path parity.
- Bold spans such as `**NPC Name**`.
- Quoted name candidates where safe.
- Conservative title-case multi-word proper noun candidates.
- DC/check patterns such as `DC 13 Perception`, `Investigation check`, and similar mechanics.
- Treasure/item cue patterns such as `treasure`, `reward`, `key`, `journal`, `relic`, and `artifact`.
- Puzzle/trial cue patterns such as `riddle`, `trial`, `test`, `puzzle`, `flooding`, `door`, and `solution`.

## Persistence Integration

`utils/toolkit_homebrew_upload_contract.py` should add workspace file helpers and persistence helpers for:

- `source_manifest.json`
- `source_graph.json`

`utils/toolkit_homebrew_normalizer.py` should call source graph generation after reading and truncation decisions but before creating the LLM request payload. The existing LLM request payload may include a compact source graph summary if safe, but full multi-pass prompt usage is deferred to a later change.

## Observability

The normalization report SHOULD include source graph summary counts and degraded status if graph generation failed. Detailed graph data belongs in `source_graph.json`, not in the report.

## Rollback

Rollback is straightforward: disable source graph generation with a feature flag or skip artifact generation. Existing normalization remains the fallback path.
