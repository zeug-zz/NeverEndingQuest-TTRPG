## 1. Gitignore Contract Audit

- [X] 1.1 Inventory current module-related `.gitignore` rules and record which rules ignore canonical vs runtime paths.
- [X] 1.2 Identify every README-public module slug and compare it against the published-module allowlist.
- [X] 1.3 Audit `modules/world_registry.json` and `modules/campaign.json` write/read paths and confirm they are user-local runtime/catalog state.
- [X] 1.4 Confirm the map policy for this slice: commit live `map_*.json` as static published module structure and do not require map hydration.

## 2. Gitignore Implementation

- [X] 2.1 Consolidate or reorder `.gitignore` module rules into a single published-module git contract section.
- [X] 2.2 Add all README-public module directories to the published-module allowlist, including `modules/Into_the_Deepvault/`.
- [X] 2.3 Ensure canonical publication artifacts are unignored for allowlisted modules: module metadata, `_BU` files, reports, docs, monster JSON, module-local media, and live `map_*.json` files.
- [X] 2.4 Ensure runtime/dev-laptop files remain ignored: live areas, live plot, live party tracker, generated quests, encounters, local world/campaign registries, backups, `.bak`, and `.backup*` files.
- [X] 2.5 Add committed `modules/published_modules.json` with README-public module slugs/display names and update `.gitignore` so `modules/world_registry.json` and `modules/campaign.json` remain ignored.

## 3. Documentation and Skill Contract

- [X] 3.1 Add a `Module Publication Git Contract` section to `AGENTS.md` defining what MUST be committed and what MUST NOT be committed, including committed live maps and ignored local registry/campaign files.
- [X] 3.2 Document the normal verification commands: `git check-ignore -v` for canonical and runtime paths, `git status --ignored -uall modules/<slug>`, and staged diff review.
- [X] 3.3 Add or update an OpenCode module-publishing skill that validates publishability, verifies gitignore behavior, stages only canonical files, rejects runtime files, and pushes explicitly to `origin` when requested.
- [X] 3.4 Update any existing `dev-homebrew-ingest` or publication workflow guidance that still implies publishable module artifacts should be force-added or omitted because they are ignored.

## 4. Into the Deepvault Publication Readiness

- [X] 4.1 Verify `modules/Into_the_Deepvault/` canonical artifacts become visible to normal git staging after `.gitignore` changes.
- [X] 4.2 Verify no DMsGuild attribution, source filename, author name, or old title remains outside explicitly preserved OpenSpec archive history.
- [X] 4.3 Verify `README.md`, `modules/published_modules.json`, and `Into_the_Deepvault` module metadata agree on slug and display name.
- [X] 4.4 Stage `Into_the_Deepvault` canonical publication artifacts and confirm runtime files are absent from the staged diff.

## 5. Verification

- [X] 5.1 Run `git check-ignore -v` checks for representative canonical files, including `map_*.json`, and confirm they are not ignored.
- [X] 5.2 Run `git check-ignore -v` checks for representative runtime files, including `modules/world_registry.json` and `modules/campaign.json`, and confirm they are ignored.
- [X] 5.3 Validate JSON for all staged module/catalog files.
- [X] 5.4 Run module validation for `Into_the_Deepvault` with `.venv/bin/python core/validation/validate_module_files.py --module Into_the_Deepvault`.
- [X] 5.5 Run publishability audit for `Into_the_Deepvault` if its current media/readiness state supports it, or record any pre-existing publication blockers distinctly.
- [X] 5.6 Review `git diff --cached --name-status` and confirm the staged set contains only intended canonical publication artifacts, live module maps, docs, `published_modules.json`, and `.gitignore`/skill updates.
- [X] 5.7 Run `openspec validate module-publication-git-contract` and fix any artifact issues before implementation is considered ready for commit.

## 6. Rollback and Cleanup

- [X] 6.1 Confirm rollback path by noting which `.gitignore` section and docs/skill files were touched.
- [X] 6.2 Remove any temporary audit output or local-only inspection artifacts created during verification.
- [X] 6.3 Leave historical OpenSpec archive references to `Echoes_Of_Stone` unchanged unless explicitly requested later.
