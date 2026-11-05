# NeverEndingQuest - Agent Guide

Repo-wide durable guidance for coding agents. Active OpenSpec changes define task scope and acceptance criteria; this file is not a changelog.

## Project identity and boundaries

NeverEndingQuest is an AI Dungeon Master platform for SRD 5.2.1-compatible tabletop campaigns, with a web interface and module-authoring toolkit. It is designed for locally facilitated play; the web UI switches among party character sheets, while Python owns PC identity and state. This is an independently developed fork; upstream is read-only historical/reference material, not a merge or compatibility target (ADR-0031).

There is one tabletop runtime with a party of 1..x player characters plus NPCs. A one-PC party is the regression floor; a four-PC party is the primary test shape (ADR-0032). `MULTIPLAYER_MODE` and remaining party-size checks are migration debt owned by the dedicated unification change: do not remove or alter them opportunistically, and do not add new party-size gates. Python owns mechanical, persistence, publication, and campaign-state truth; the LLM interprets and narrates within those boundaries.

The overriding V2 gameplay UX goal is the theatre of the players' mind: judge each change by whether it makes the players' shared imagined world more coherent, more vivid, and easier to act on. The art is the balance of determinism and indeterminism: Python keeps concrete world facts consistent, while the LLM keeps open-ended play flexible and alive. Require deterministic precision only where players would notice its absence or a decision or rule depends on it; do not pursue exhaustive Python modelling that constrains narrative flexibility. The interpretation guide is section 2 of `plans/v2-narrative-overview.md`.

Within that goal, the Narrator's principle is the experience of a "sentient ghost in the machine": a believably intelligent, attentive Narrator who remembers the party, relationships, choices, and consequences across sessions. This describes the player experience, not literal sentience; preserve continuity, player agency, and character-knowledge boundaries without compromising Python authority. The Narrator build plan is `plans/v2-narrator.md`; planning does not authorize runtime implementation.

All core host edits should be deliberate and marked `# TABLETOP MODE:`. Prefer separate extension modules where practical. Preserve shared schemas and 1-PC/multi-PC compatibility; do not create parallel party-size-specific state models.

## Documentation authority

- `AGENTS.md`: durable repository rules and commands.
- `openspec/changes/`: active change scope and acceptance criteria; `openspec/specs/`: current capability contracts.
- `adrs/`: accepted architecture decisions and their supersession links.
- `plans/`: planning and reference material; OpenSpec owns active implementation requirements.
- Conflict rule: repo-wide rules in this file apply generally; active OpenSpec artifacts govern change-specific behavior, subject to accepted ADRs.

## Project memory

Hindsight is project memory for decisions, session history, and knowledge pages. Use it for context, then verify past claims against current code and authoritative docs. `AGENTS.md` holds only durable overview and rules.

Never append completion logs, test counts, or dated change entries here. Edit `AGENTS.md` only when a durable rule, command, or structure changes. History lives in Hindsight, OpenSpec archives, git, and the frozen `docs/history/agents-changelog.md`. `memory-bank/` is retired Cline-era legacy: do not read it as authority or update it.

## Context-mode routing

Use context-mode execution tools to analyze, count, compare, search, parse, or transform data and print only the needed result; prefer JavaScript with Node.js built-ins and handle missing/null values. Use the file-execution tool for analysis of large files, and normal file reads when you need exact text to edit.

Do not use shell `curl`/`wget` or make inline HTTP requests outside the sandbox. Use context-mode fetch/index/search for web retrieval. Route shell commands likely to emit over 20 lines, broad gathering, and large grep results through context-mode batch/execute tools. Keep outputs terse and write large artifacts to files rather than dumping them into context.

Use descriptive source labels when indexing. Use `ctx_stats`/`ctx_doctor` for diagnostics; for `ctx_upgrade`, run only its returned command. `ctx_purge` irreversibly deletes knowledge: warn the user and obtain explicit confirmation before using it.

## Security invariants

- Never commit `config.py`, API keys, credentials, or other secrets; never hardcode secrets. Rotate exposed keys immediately and on the documented 90-day cadence. Report vulnerabilities privately (see `SECURITY.md`), not in public issues.
- Gitleaks and Bandit run in pre-commit/CI. CI also runs Semgrep (advisory, SARIF uploaded) and gate-blocking `pip-audit --strict`, subject only to exceptions documented in `SECURITY.md`. Do not bypass scans or hooks. Keep dependencies pinned in `requirements-lock.txt` and the lock resolvable.
- Every `requests.get()` call must specify `timeout=`. Do not pass unsanitized user input to shell execution or subprocesses.
- Keep Flask debug mode off in production; `0.0.0.0` binding is for local-network use only. Pin GitHub Actions to commit SHAs and review third-party action provenance.
- Keep operational security reports under gitignored `plans/security/`; do not ship them.
- `main` requires PR review/linear history and protected security checks; do not force-push or bypass branch protection.

## Build, validation, and test commands

Use `.venv/bin/python` for runtime, rebuild, migration, and dependency-sensitive commands. It is required for code paths importing project dependencies (provider clients, Flask, schema tools, etc.). Use bare `python3` only for interpreter-independent tools or where explicitly documented.

```bash
# Install dependencies in the project environment
.venv/bin/python -m pip install -r requirements.txt

# Run the application
.venv/bin/python run_web.py          # http://localhost:8357 for ordinary local use
.venv/bin/python launch_toolkit.py
.venv/bin/python main.py

# Validate modules after JSON/module-data changes
.venv/bin/python core/validation/validate_module_files.py
.venv/bin/python core/validation/validate_module_files.py --module <ModuleSlug>

# Focused validation and regression checks
.venv/bin/python test_compression.py
.venv/bin/python analyze_telemetry.py
python3 scripts/check_ascii_compliance.py --summary-only
OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate --specs
```

Run the focused tests for the change and report exact commands/results. Diary rebuild, remediation, Story PDF, and diary/runtime-hook checks must also use `.venv/bin/python`.

### Orchestrator-Owned Runtime Capture Gates

- When an approved change requires live gameplay evidence, the primary orchestrator runs and judges the capture after the relevant focused tests; builders implement tooling and fixes, not the final gate verdict.
- Use `.opencode/skills/neq-capture-arena/SKILL.md`: a real copy under `tmp/combat_capture/`, port 8360, `NEQ_OPEN_BROWSER=0`, and the repository venv. Never use the installed campaign or port 8357.
- Preserve per-gate, per-run evidence under `tmp/router-rollout/<gate>/<run-id>/` before teardown. Record scenario/party/seed identity, current worktree and model/provider identity, expected versus observed checks, and artifact paths.
- Driver exit 0, a degraded report, green unit tests, or builder claims do not establish a live gate PASS. Required missing scenarios/evidence, timeouts, and failed assertions leave the gate incomplete with a FAIL or BLOCKED verdict.
- Active OpenSpec artifacts own scenario coverage and acceptance criteria; `plans/archive/combat-openrouter-alignment.md` maps rollout gates. No required capture may be silently waived or checked complete. Existing G1 evidence and the accepted candidate bake-off are not rerun prerequisites.
- Resume captures only when the rollout goal is active and the workflow is authorized. A separately requested guideline/planning update leaves a paused goal paused.

## Code and data conventions

- Python files use the repository Fair Source SPDX header (`SPDX-FileCopyrightText: 2024 MoonlightByte`, `SPDX-License-Identifier: Fair-Source-1.0`, and the license notice); major modules also include an architecture block.
- Import order: standard library, third-party, internal modules; keep configuration imports near the end. Public functions need type hints. Use `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants, and a leading underscore for private helpers.
- Catch specific exceptions where possible and use `utils.enhanced_logger` with useful categories; do not silently swallow unexpected failures.
- Python source must be ASCII-only for Windows console/tester safety. Use `[PASS]`, `[FAIL]`, and `->` rather than Unicode marks/arrows. Run the ASCII compliance command above.
- State/JSON writes must be atomic via repository helpers such as `safe_write_json`; use canonical readers/writers, not ad hoc writes. Tabletop extensions must not write direct SQL or bypass canonical state APIs.
- For new images, use JPEG quality 95 for full-size assets and repository media locations/patterns; thumbnails follow the existing thumbnail convention.
- For game mechanics, use "5th edition" or "5e" rather than "D&D", follow SRD 5.2.1 rules, use generic fantasy settings, and include `"_srd_attribution": "Portions derived from SRD 5.2.1, CC BY 4.0"` where applicable.

## Runtime and architecture constraints

The unification roadmap and current decision are linked at [`docs/architecture/plugin-runtime-roadmap.md`](docs/architecture/plugin-runtime-roadmap.md); ADR-0032 is authoritative and supersedes ADR-0004. Do not drive-by edit `MULTIPLAYER_MODE` or party-size gates; only the dedicated unification change owns their removal. Shared paths require 1-PC and multi-PC regression checks.

Combat prompt/state and phase contracts are recorded in the relevant ADRs (including ADR-0008 and ADR-0010) and active OpenSpec changes; preserve deterministic Python authority over mechanical state.

Per ADR-0033, mechanical legality for migrated rule families is decided by the pinned Firelight engine through the Python bridge; Python stays host and canonical store. Families not yet migrated keep their Python guards.

- Canonical state owners: character JSON files for character state, `party_tracker.json` for party state, and encounter files for combat state. Managers/caches are not primary storage.
- Use `update_character_info()` for character mutations and `safe_write_json()` for persisted JSON. Preserve PC/NPC role authority: filter party members out of AI-generated NPC rosters before encounter creation. Encounter initialization must preserve enemy AC, including required legacy backfill.
- `ModuleBuilder` orchestrates module generation; generation workers own content-generation behavior. Follow the current component boundary rather than patching symptoms in the orchestrator.
- Upstream behavior enters this fork only through an approved OpenSpec change and fork-native tests. Preserve Python authority, 1-PC party compatibility, and Fair Source/upstream/third-party attribution for ports.

## Fork and Git safety

- Do not merge upstream branches. Never push to `upstream`; always name `origin` explicitly (`git push origin <branch>`), never use bare `git push`.
- PRs target this fork (`zeug-zz/NeverEndingQuest-TTRPG`), never upstream, unless the repository owner explicitly requests otherwise.
- Every `gh` command must name `--repo zeug-zz/NeverEndingQuest-TTRPG`; never rely on `gh`'s default repository resolution, which can select upstream.
- Use descriptive branch names such as `feature/`, `fix/`, or `chore/`.

## Module publication Git contract

A module is publishable and must be committed only after validation and publishability gates pass, it is listed in `README.md` and `modules/published_modules.json`, and it is intended for colleagues/testers via `origin`.

**Commit canonical authored/publication artifacts:** `module_context.json`, `module_context_BU.json`, `module_plot_BU.json`, `party_tracker_BU.json`, `validation_report.json`, `toolkit_build_report.json`, `module_media_generator_report.json` and `monster_closure_report.json` when present, `llm_classification_cache.json` when present, `areas/*_BU.json`, all `map_*.json` (live maps are authored static structure), `map_*_BU.json` when present, `monsters/*.json`, `media/**`, and module `README.md`/`PLAYER_GUIDE.md`/`MODULE_SUMMARY.md` when present.

**Never commit runtime/user-local state:** `areas/*.json` except `*_BU.json`, `module_plot.json`, `party_tracker.json`, `player_quests_*.json`, `encounters/**`, `modules/world_registry.json`, `modules/campaign.json`, or backup files/directories (`*.bak`, `*.backup`, `*.backup_*`, `backup*/`). `modules/published_modules.json` is the git-authoritative public catalog; the world registry and campaign files are user-local.

Before publication, verify the canonical files are not ignored and runtime files are ignored; never use `git add -f`. Review the staged set and push only to `origin`:

```bash
# Canonical artifacts: no ignore match (or an explicit ! unignore rule)
git check-ignore -v modules/<slug>/module_context.json
git check-ignore -v modules/<slug>/map_*.json

# Runtime files: a non-! ignore rule
git check-ignore -v modules/<slug>/module_plot.json
git check-ignore -v modules/<slug>/party_tracker.json
git check-ignore -v modules/world_registry.json
git check-ignore -v modules/campaign.json

git status --ignored -uall modules/<slug>
git diff --cached --name-status
```

If canonical files are ignored, update the `.gitignore` module allowlist and re-verify; do not force-add them. Stage only canonical publication artifacts, docs/catalog files, and necessary `.gitignore`/skill updates.

## Key locations

- `main.py`, `run_web.py`: game loop and web launcher.
- `core/ai/`, `core/combat/`, `core/managers/`: action/narrative, combat, and orchestration logic; `core/generators/`: content generation; `core/validation/`: validators.
- `updates/`: state mutation modules; `utils/`: shared state, persistence, and domain helpers.
- `web/routes/`, `web/extensions/`, `web/templates/`, `web/static/`: web API, integration, UI, and assets.
- `modules/` (including `modules/conversation_history/` and `modules/campaign_summaries/`), `characters/`, `party_tracker.json`: adventures, histories/summaries, character records, and party state; `schemas/`, `data/`, `prompts/`: contracts and game content.
- `utils/pc_manager.py`: party/character state access abstraction.
- `config.py`: local secrets/settings, never commit; `model_config.py`: model routing; `debug_config.py`: debug categories.
- `scripts/`: validation and regression tools (`test_*.py`); `openspec/changes/`: active work; `adrs/`: architecture decisions.

## Quality gates

Before finishing a change:

- Run focused tests and the applicable schema/module validator; include the exact commands and results.
- Run ASCII compliance for source changes; keep Python source Unicode-free.
- Use atomic persistence for state changes; verify correct media paths and image quality for media changes.
- Fix the root cause, not a workaround; keep imports and component ownership consistent.
- For shared tabletop runtime paths, verify both the 1-PC regression floor and the multi-PC party behavior. Do not treat unit tests as a substitute for required orchestrator-owned live captures.
