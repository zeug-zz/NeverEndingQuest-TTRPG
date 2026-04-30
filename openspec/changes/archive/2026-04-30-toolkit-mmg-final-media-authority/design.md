# Context

Module Builder sidebar entries currently expose `brief_failure` and `media_generator_needed` from `core/generators/module_stitcher.py`. Those signals come from `toolkit_build_report.json`, including nested publishability report media-debt categories and `toolkit_media_policy.structural_media_debt_count`. Module Media Generator already attempts to refresh `toolkit_build_report.json` after generation, but there is no persisted MMG-final media audit. A refresh failure, degraded refresh, or stale media-debt payload can therefore keep the handoff visible after MMG has completed.

# Goals

- Make MMG's final filesystem media audit the final authority for whether the sidebar should show `Needs Module Media Generator`.
- Keep `toolkit_build_report.json` authoritative for non-media blockers.
- Use the same module-local media semantics as unified asset status: module media counts, static fallback media does not.
- Keep failure behavior fail-open and backward compatible for modules without MMG reports.

# Non-Goals

- No broad publishability audit redesign.
- No media generation retry policy changes.
- No static-media promotion or automatic copy from fallback media into module media.
- No UI redesign beyond using corrected sidebar metadata.

# Decisions

1. Persist MMG final media state to `modules/<module>/module_media_generator_report.json`.
2. Use a versioned contract such as `module_media_generator_report.v1` with `source: "module_media_generator"` and `authoritative: true`.
3. Audit required assets from the same module asset inventory used by unified asset status where practical.
4. Treat module-local image and thumbnail presence as the media completion requirement for sidebar handoff purposes.
5. Ignore static fallback media for pass/fail completion, while retaining it only as optional diagnostic context.
6. Apply MMG override only to media handoff signals in `ModuleStitcher`; preserve semantic/build failures from `toolkit_build_report.json`.

# Hard Constraints

- Python additions must be ASCII-only.
- Host-file edits must be marked with `# TABLETOP MODE:` where applicable.
- Report writes must use existing safe JSON/atomic file helpers where practical.
- Malformed or missing MMG reports must not break module listing.
- MMG pass must not suppress non-media failures.

# Guidance

- Prefer a new helper module such as `web/extensions/toolkit_media_generator_report.py` to keep `web/web_interface.py` thin.
- Keep report schema small and explicit: module slug, generated timestamp, contract, source, authoritative flag, status, required assets, missing assets, missing count, and optional generation failures.
- Make sidebar override behavior easy to unit test without starting Flask or SocketIO.
- If asset inventory extraction is shared with existing MMG status code, prefer extracting reusable helpers over duplicating divergent path logic.

# Migration and Rollback

- Rollback removes the MMG report write hook and sidebar loader/override, restoring current `toolkit_build_report.json` behavior.
- Existing `module_media_generator_report.json` files are additive and can be ignored by older code.
- No runtime module content or media files need migration.

# Verification Plan

- Add sidebar tests for stale/current media build report plus MMG pass suppression.
- Add sidebar tests for MMG fail handoff when build report is stale or absent.
- Add sidebar tests that malformed or non-authoritative MMG reports fall back to existing behavior.
- Add sidebar tests that MMG pass does not hide semantic or build failures.
- Add helper tests or source-contract tests for MMG report writing and static fallback exclusion.
- Compile modified Python files and run `openspec validate toolkit-mmg-final-media-authority`.
