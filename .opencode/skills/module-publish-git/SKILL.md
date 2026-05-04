---
name: module-publish-git
description: Stage, verify, commit, and push a published NeverEndingQuest module to origin without runtime artifacts. Validates gitignore contract before staging.
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: module-publishing
  project: NeverEndingQuest
---

# Module Publish Git Skill

**Purpose:** Deterministic git workflow for publishing a validated module to colleagues via `origin`. Verifies the `.gitignore` published-module contract, stages only canonical artifacts, rejects runtime files, and pushes explicitly to `origin`.

**Target Audience:** Developers and agents preparing module publication commits.

---

## Trigger Phrases

- "publish module `<slug>`"
- "commit module `<slug>`"
- "push module `<slug>`"
- "module ready for colleagues `<slug>`"
- "publish and push `<slug>`"

---

## Pre-Publish Validation

Before staging, verify the module passes structural and publication gates:

```bash
.venv/bin/python core/validation/validate_module_files.py --module <slug>
.venv/bin/python scripts/audit_module_publishability.py --module <slug> --json
```

If either fails, stop and report the blockers. Do NOT proceed to git staging.

---

## Gitignore Contract Verification

Verify the module's canonical and runtime files follow the published-module git contract:

```bash
# 1. Canonical files must NOT be ignored (no match, or ! unignore rule)
for f in module_context.json module_context_BU.json module_plot_BU.json \
         party_tracker_BU.json validation_report.json toolkit_build_report.json; do
  result=$(git check-ignore -v modules/<slug>/$f 2>&1)
  if [ -z "$result" ]; then
    echo "[OK NOT IGNORED] $f"
  else
    pattern=$(echo "$result" | cut -f1 | rev | cut -d: -f1 | rev)
    if [ "${pattern#!}" != "$pattern" ]; then
      echo "[OK UNIGNORE] $f -> $pattern"
    else
      echo "[FAIL IGNORED] $f -> $pattern"
    fi
  fi
done

# 2. Runtime files MUST be ignored (matched by non-! rule)
for f in module_plot.json party_tracker.json; do
  result=$(git check-ignore -v modules/<slug>/$f 2>&1)
  if [ -z "$result" ]; then
    echo "[FAIL NOT IGNORED] $f"
  else
    pattern=$(echo "$result" | cut -f1 | rev | cut -d: -f1 | rev)
    if [ "${pattern#!}" != "$pattern" ]; then
      echo "[FAIL UNIGNORE] $f -> unexpected unignore"
    else
      echo "[OK IGNORED] $f"
    fi
  fi
done

# 3. Local catalog files MUST be ignored
for f in modules/world_registry.json modules/campaign.json; do
  result=$(git check-ignore -v $f 2>&1)
  if [ -n "$result" ]; then
    echo "[OK IGNORED] $f"
  else
    echo "[FAIL NOT IGNORED] $f"
  fi
done
```

**If any canonical file is IGNORED:** Stop. Fix `.gitignore` (add the module slug to Layer 2 allowlist, verify Layer 4 unignores), then re-run.

**If any runtime file is NOT IGNORED:** Stop. Fix `.gitignore` runtime rules, re-verify, then re-run.

**Do NOT use `git add -f` as the normal publication path.**

---

## Staging Rules

Stage these files for a module publication commit:

```bash
# Canonical module artifacts
git add modules/<slug>/module_context.json
git add modules/<slug>/module_context_BU.json
git add modules/<slug>/module_plot_BU.json
git add modules/<slug>/party_tracker_BU.json
git add modules/<slug>/validation_report.json
git add modules/<slug>/toolkit_build_report.json
git add modules/<slug>/areas/*_BU.json
git add modules/<slug>/map_*.json
git add modules/<slug>/map_*_BU.json
git add modules/<slug>/monsters/*.json
git add modules/<slug>/media/

# Optional report files (stage if present)
git add modules/<slug>/module_media_generator_report.json
git add modules/<slug>/monster_closure_report.json
git add modules/<slug>/llm_classification_cache.json

# Public docs (stage if present)
git add modules/<slug>/README.md
git add modules/<slug>/PLAYER_GUIDE.md
git add modules/<slug>/MODULE_SUMMARY.md

# Public catalog and registry
git add modules/published_modules.json
git add README.md

# Git contract updates (if modified)
git add .gitignore
git add AGENTS.md
```

**Refuse to stage these runtime files:**

```bash
# These MUST NOT be in the staged set:
modules/<slug>/module_plot.json
modules/<slug>/party_tracker.json
modules/<slug>/areas/*.json    (except *_BU.json)
modules/<slug>/player_quests_*.json
modules/<slug>/encounters/**
modules/world_registry.json
modules/campaign.json
modules/<slug>/*.bak
modules/<slug>/**/backup_*
```

Before commit, review the staged diff:

```bash
git diff --cached --name-status
```

If any forbidden runtime file appears in the staged set, unstage it and fix `.gitignore` rules.

---

## Commit and Push

```bash
# Commit with descriptive message
git commit -m "chore(module): publish <display-name> module for colleagues"

# Push to origin explicitly (NEVER push to upstream)
git push origin main
```

---

## Verification Gate (after push)

```bash
# Confirm module directory is tracked
git ls-files modules/<slug>/ | head -10

# Confirm runtime files are NOT tracked
git ls-files modules/<slug>/module_plot.json  # should return empty
git ls-files modules/<slug>/party_tracker.json  # should return empty

# Confirm catalog files remain ignored
git ls-files modules/world_registry.json  # should return empty
git ls-files modules/campaign.json  # should return empty
```

---

## Stop Conditions

HALT and report immediately if:
1. Module validation or publishability audit fails.
2. Any canonical artifact is IGNORED by `.gitignore`.
3. Any runtime file is NOT IGNORED by `.gitignore`.
4. Staged set contains forbidden runtime files.
5. Operator or agent attempts to push to `upstream` remote.

---

## Interpreter Rule

Use `.venv/bin/python` for validation, audit, and publishability commands that require runtime dependencies.

Version: 1.0
Last Updated: 2026-05-04
