## Why

Validated, README-public modules are currently hidden by `.gitignore` unless their directory is manually allowlisted, which makes publish-ready module content invisible to `git status` and encourages unsafe one-off `git add -f` behavior. This blocks a clean colleague-facing push because the repository does not clearly distinguish committed module publication artifacts from dev-laptop runtime/gameplay files at the git-contract level.

## What Changes

- MUST define a single published-module git contract in `.gitignore` that makes reviewed modules commit-visible while keeping runtime state ignored.
- MUST document the publication chain in `AGENTS.md`: validate/publishability pass -> public README/catalog entry -> canonical module artifacts committed -> runtime files excluded.
- MUST ensure modules named publicly in `README.md` and accepted for publication are allowlisted without requiring `git add -f`.
- MUST keep `modules/world_registry.json` and `modules/campaign.json` ignored as user-local world/campaign state.
- MUST introduce a committed `modules/published_modules.json` public catalog for modules shipped to colleagues/testers.
- MUST track live `map_*.json` for published modules as static module structure, not require map hydration from `map_*_BU.json`.
- MUST update or add a module-publishing git workflow/skill that stages only canonical module artifacts and refuses runtime files.
- MUST preserve runtime hydration semantics for genuinely mutable files: live areas, live plot, party tracker, and derived projections remain local and are rebuilt from tracked canonical backups where applicable.
- SHOULD add deterministic guardrails/tests or source-contract checks that verify canonical files are not ignored and runtime files remain ignored.
- Non-goal: this change will not alter module builder content generation, media generation, gameplay runtime behavior, or OpenSpec archive history.

## Capabilities

### New Capabilities
- `module-publication-git-contract`: Defines which module files MUST be tracked or ignored when a module is publication-ready.
- `module-publication-git-workflow`: Defines the operator/agent workflow for staging, committing, and pushing validated modules without runtime artifacts.

### Modified Capabilities
- `module-runtime-state-hydration`: Clarifies that ignored mutable live files must be hydratable from tracked canonical artifacts, while live maps are tracked as static published module structure.

## Impact

- `.gitignore` module sections: consolidate or reorder rules so published modules are visible and runtime files remain ignored.
- `AGENTS.md`: add an authoritative module publication git contract and staging checklist.
- OpenCode skill docs: update `dev-homebrew-ingest` or add a focused `module-publish-git` skill for commit/push discipline.
- Repository module catalog state: add committed `modules/published_modules.json` while keeping `modules/world_registry.json` and `modules/campaign.json` ignored for user-local state.
- Published module directories: allowlist current README-public modules, including `modules/Into_the_Deepvault/`.
- Verification: add checks that `git check-ignore -v` gives the expected answer for canonical vs runtime paths.
