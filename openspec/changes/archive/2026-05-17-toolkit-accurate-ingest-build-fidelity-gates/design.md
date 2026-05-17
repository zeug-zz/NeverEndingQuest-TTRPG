## Context

The completed review panel validates source fidelity before build approval. This phase validates the generated module after the packet builder runs and before finishing/publication. The gate should inspect artifacts already present in the workspace and generated module output, not call providers and not mutate module content.

## Contract Layer (MUST)

- Accurate-ingest workspaces MUST persist `build_fidelity_report.json` after packet build execution.
- Accurate-ingest workspaces MUST persist a final `source_fidelity_report.json` rollup when enough upstream reports exist.
- Critical missing source atoms MUST block post-build finishing/publication.
- Critical replacement of source-locked names, required NPCs, keyed locations, puzzle/trial rules, clue chains, or plot topology MUST block.
- Advisory/tone-only divergence SHOULD warn, not block, unless upstream artifacts mark it critical.
- Legacy workspaces without accurate-ingest source/blueprint artifacts MUST preserve existing behavior.
- Feature-flag-disabled build fidelity gates MUST preserve existing behavior.
- The gate MUST NOT modify generated module files.
- The gate MUST NOT call LLM providers.
- The gate MUST NOT alter `ModuleBuilder` or `ModuleGenerator` internals.
- User-facing text and report strings introduced by this change MUST be ASCII-only.

## Guidance Layer (SHOULD)

- Add `utils/toolkit_build_fidelity.py` for artifact-only audit logic.
- Keep packet-builder integration thin: build completes, report helper runs, result status is updated, finishing is skipped on blockers.
- Use `source_atom_id`, canonical names, aliases, and blueprint rosters where available to avoid brittle plain substring checks.
- Prefer compact report rows with source refs and generated artifact paths over dumping full source artifacts.
- Keep status values stable: `pass`, `degraded`, `blocked`, `failed`, `legacy`, `disabled`.

## Architecture

### New helper

Create a helper module with public functions similar to:

```python
def is_build_fidelity_required(workspace: Path) -> bool:
    """Return true when accurate-ingest build fidelity gates apply."""

def build_build_fidelity_report(workspace: Path, module_dir: Path) -> Dict[str, Any]:
    """Return artifact-only report comparing generated module to source/blueprint artifacts."""

def can_continue_after_build_fidelity(report: Dict[str, Any]) -> Tuple[bool, str]:
    """Return whether finishing/publication can continue."""

def build_source_fidelity_rollup(workspace: Path, build_report: Dict[str, Any]) -> Dict[str, Any]:
    """Return final source fidelity rollup across normalization, blueprint, and build phases."""
```

### Report shape

`build_fidelity_report.json` should include:

- `version`
- `status`: `pass`, `degraded`, `blocked`, `failed`, `legacy`, or `disabled`
- `module_slug` / `module_path`
- `source_artifacts`: paths/existence for source graph, blueprint, fidelity reports
- `coverage`: counts for required NPCs, locations, plot beats, puzzles, clues, encounters, items, tone markers
- `blockers`: bounded compact list with source atom IDs, category, message, source ref, generated artifact path where applicable
- `warnings`: bounded compact list
- `stage_results`: overview, areas, locations, NPCs, plot, encounters, monsters/media if deterministically inspectable
- `can_continue`: boolean
- `refusal_reason`: compact reason when blocked/failed

`source_fidelity_report.json` should include a final rollup with:

- normalization fidelity status
- blueprint status
- build fidelity status
- final blocker/warning counts
- source atom coverage totals
- artifact paths for all three phases

### Packet builder integration

After a successful module build in `web/extensions/toolkit_homebrew_packet_builder.py`:

1. Resolve generated module path from build result/workspace metadata.
2. If build fidelity gates are disabled or workspace is legacy, preserve current behavior.
3. If gates apply, run `build_build_fidelity_report(...)`.
4. Persist `build_fidelity_report.json` and `source_fidelity_report.json` atomically.
5. If report cannot continue, return a reviewable blocked result before post-build finishing.
6. If report can continue, include compact build fidelity summary in existing build result payload.

### Status surfacing

Reuse existing toolkit upload status/review surfaces. Do not redesign the UI. Add compact status lines/sections only where the current job payload already displays build/readiness/finishing information.

## Error Handling

- Missing required source/blueprint artifacts in an accurate-ingest workspace should produce `status: failed` or `blocked` and prevent finishing.
- Missing generated module artifacts should produce `status: failed` and prevent finishing.
- Malformed JSON should be reported with artifact path and fail closed for accurate-ingest.
- Legacy workspaces should return `status: legacy` or skip report generation without blocking.

## Phase Boundary

This phase implements build-time fidelity gates only. It does not perform repair, narrative enrichment, waiver policy, or generator refactors.
