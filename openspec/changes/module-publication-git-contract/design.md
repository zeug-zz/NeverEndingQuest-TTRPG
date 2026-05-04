## Context

The repository already has a validated publication workflow that distinguishes structural readiness from semantic publishability, but the git layer does not encode the same distinction. `.gitignore` currently blocks every `modules/*/` directory unless a module slug is manually allowlisted, while separate rules attempt to unignore canonical backups and metadata. Because the directory-level ignore wins until the directory is explicitly unignored, new publishable modules such as `Into_the_Deepvault` can be registered in local runtime files and named in `README.md` while remaining invisible to `git status`.

This creates three operational failures:

- Published module content can be omitted from colleague-facing pushes.
- Agents may suggest `git add -f` instead of fixing the repository contract.
- Runtime files and canonical artifacts are easy to conflate during deck-clearing commits.

The existing module-data split remains valid: live gameplay files are mutable runtime state, while `_BU` files, module metadata, monster definitions, media, live map JSON, and publication reports are canonical publish artifacts. `modules/world_registry.json` and `modules/campaign.json` are local-world state, not publication artifacts.

## Goals / Non-Goals

**Goals:**

- Make publishable module artifacts visible to normal `git add` once a module is intentionally public.
- Keep dev-laptop runtime files ignored and unstaged by default.
- Make `README.md` and committed `modules/published_modules.json` registration consistent with committed module payloads.
- Keep `modules/world_registry.json` and `modules/campaign.json` safe for player-local modules and campaign state across `git pull` updates.
- Document the contract in `AGENTS.md` so future agents do not confuse ignored runtime files with ignored publish artifacts.
- Provide a module publishing workflow that validates gitignore behavior before commit/push.

**Non-Goals:**

- Do not change module gameplay content, readiness auditing semantics, media generation, or runtime hydration behavior.
- Do not rewrite OpenSpec archive history.
- Do not require every local draft module to become tracked.
- Do not rely on `git add -f` as the normal publication path.

## Decisions

### Decision 1: Allowlist Published Module Directories Explicitly

Published modules MUST be allowlisted at the directory level after the default `modules/*/` ignore rule. This preserves protection for draft/local modules while making public modules visible to normal git commands.

Alternative considered: remove `modules/*/` and ignore only known runtime file families. This would expose all draft imports and local experiments, increasing accidental commit risk.

### Decision 2: Introduce `modules/published_modules.json` and Keep Runtime Catalogs Ignored

`modules/world_registry.json` and `modules/campaign.json` MUST remain ignored. They represent the user's local world and campaign state and can include gametest imports, manually copied community modules, player-selected current modules, local registry repairs, and wider personal campaign topology. A `git pull` from `origin` MUST NOT overwrite or conflict with those local-world files.

A new committed `modules/published_modules.json` file MUST be introduced as the git-authoritative public module catalog. Runtime and toolkit code can use this catalog to seed or present shipped module availability, but local runtime truth remains in `world_registry.json` and `campaign.json`.

Alternative considered: track `world_registry.json` and `campaign.json` directly. This was rejected because it would create poor update UX for players who add their own modules or whose local world registry expands beyond the shipped catalog.

### Decision 3: Commit Canonical Backups, Metadata, and Live Maps; Ignore Mutable Runtime Files

The git contract MUST track canonical module sources and reports while ignoring mutable gameplay copies. Runtime files include `areas/*.json` except `*_BU.json`, `module_plot.json`, `party_tracker.json`, generated player quest projections, encounters, backups, and `.bak` files.

Canonical artifacts include module context, `_BU` backups, validation/build reports, monster JSON, module-local media, README/player guide summaries, `map_*.json`, and `map_*_BU.json` files when present. Live map files are treated as static authored module structure and MUST be committed for published modules; map hydration is not required unless a future change explicitly makes maps gameplay-mutable.

Alternative considered: hydrate live maps from `map_*_BU.json` to match live area/plot hydration. This was rejected because maps are static authored structure and committing them directly is simpler, less fragile, and better for colleague-facing fresh clones.

Alternative considered: commit both mutable live files and backup copies. This remains rejected because it increases git noise and reintroduces gameplay-mutation poisoning that the module-data git fix intentionally removed.

### Decision 4: Prefer One Centralized `.gitignore` Module Contract

The module section in `.gitignore` SHOULD be consolidated or clearly ordered so last-match-wins behavior is obvious. The rules should be grouped as: default ignore, published directory allowlist, canonical unignores, runtime ignores, backup/temp ignores.

Alternative considered: keep appending allowlist lines to the current scattered sections. This works mechanically but preserves the ambiguity that caused the current confusion.

### Decision 5: Add a Publishing Workflow/Skill Guard

A module publishing workflow MUST verify expected `git check-ignore -v` outcomes before staging. It should refuse to stage runtime paths and should report if canonical artifacts remain ignored.

Alternative considered: rely on human review of `git status`. This failed because ignored canonical files do not appear in `git status` at all.

## Risks / Trade-offs

- Public catalog drift -> Mitigation: keep `published_modules.json` small, stable, and manually updated only during module publication.
- Player local registry overwrite risk -> Mitigation: keep `world_registry.json` and `campaign.json` ignored; public catalog imports must be additive and must preserve local-only modules.
- Accidentally exposing draft modules -> Mitigation: keep default `modules/*/` ignore and require explicit allowlist for each public module.
- Missing canonical file families -> Mitigation: add verification checks for expected canonical paths and fail the publishing workflow if any are ignored.
- Runtime files accidentally staged -> Mitigation: keep ignore rules plus workflow-level path refusal for live area/plot/party/encounter files.
- Map policy ambiguity -> Mitigation: commit live `map_*.json` for published modules and document that maps are static authored structure unless a future OpenSpec change says otherwise.

## Migration Plan

1. Rewrite or consolidate the module-related `.gitignore` rules into a clear published-module contract.
2. Add current README-public modules, including `Into_the_Deepvault`, to the published module allowlist.
3. Add committed `modules/published_modules.json` as the public module catalog.
4. Keep `modules/world_registry.json` and `modules/campaign.json` ignored and document them as user-local runtime/catalog state.
5. Update `AGENTS.md` with the module publication git contract, forbidden runtime files, map policy, catalog policy, and verification commands.
6. Add or update an OpenCode skill for module publishing and git push staging safety.
7. Run gitignore verification against `Into_the_Deepvault`: canonical paths including `map_*.json` must be unignored, runtime paths must be ignored.
8. Stage only canonical module files plus README/public-catalog/docs changes.
9. Validate staged file list before commit/push.

Rollback strategy: restore prior `.gitignore` and AGENTS text if the allowlist exposes unintended draft files. Since the change is git-contract/documentation oriented, rollback does not require data migration.

## Open Questions

- Should `MODULE_SUMMARY.md` remain committed for published modules, or should it be treated as generated/report-like output and excluded?
