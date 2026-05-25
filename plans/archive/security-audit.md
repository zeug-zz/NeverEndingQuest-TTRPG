# OpenCode Security Stack Implementation Plan

> [!NOTE]
> **IMPLEMENTED — 2026-05-25.**
> This document is an archived implementation plan. For current state, see:
> - `AGENTS.md` → Security Stack section (defense layers, pre-commit/CI/CodeQL status)
> - `SECURITY.md` (policy, badges, best practices, audit cadence, key rotation)
> - `~/.config/opencode/skills/security-audit/SKILL.md` (skill definition, 5 functions)
> - `~/.config/opencode/skills/threat-monitor/SKILL.md` (threat intelligence with 3-day staleness)
>
> Sections of this plan that are **outdated and not canonical**: failure thresholds in 5.4 (actual: bandit/semgrep use `continue-on-error`), Gitleaks config format in 4.2 (actual: string arrays not nested tables), skill function counts in 17-18 (actual: 5 and 4 functions respectively), risk assessment path in 18 (actual: `plans/security/risk_assessment-`), key rotation cadence in 16 (actual: 90 days not 6 months).

## Purpose

Build a multi-layered, CLI-first security audit stack for NeverEndingQuest-TTRPG and other Python repositories. The stack is designed to be shared across repos, invoked from OpenCode or CI, and requires zero Docker/container infrastructure.

**Source:** Recommendations from OWASP Top 10 2025 / OWASP Top 10 for Agentic Applications 2026 audit guide, adapted for local-first Python web applications.

---

## 1. Current State

### What Exists

| Defense | Status |
|---------|--------|
| `.gitignore` secrets/runtime exclusion | Comprehensive, well-designed |
| `config.py` excluded from git | Correctly gitignored |
| `config_template.py` with placeholders | Present, good pattern |
| No `shell=True` in subprocess calls | Strong defense across 63 call sites |
| ASCII compliance pre-commit hook | Present, single existing hook |
| AI content safety validator (`module_stitcher.py`) | Present, content moderation only |

### What Is Missing

| Gap | Risk Level |
|-----|-----------|
| No pre-commit secret scanning | **HIGH** — one `git add -f config.py` leaks live keys |
| No dependency vulnerability scanning | **HIGH** — no CVE awareness |
| No SAST (static analysis) | **MEDIUM** — no automated code-level vuln detection |
| No CI security gates | **MEDIUM** — ASCII check only |
| No `SECURITY.md` / disclosure policy | **LOW-MEDIUM** |
| No lockfile / pinned dependencies | **MEDIUM** — supply chain risk |
| `allow_unsafe_werkzeug=True` + `0.0.0.0` binding | **LOW** (local-only), needs future hardening note |
| Wildcard CORS on Flask/SocketIO surfaces | **MEDIUM** - acceptable only for trusted LAN/local use; must be documented and revisited before wider client deployment |
| GitHub Actions using tag/latest refs + broad write permissions | **HIGH** - CI supply-chain compromise can exfiltrate secrets or mutate repo contents |

### Live API Key Exposure

`config.py` contains real, active API keys (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`) in plaintext on disk. Although gitignored, any tool that scans the working tree (grep, semgrep, bandit) will see them. A single `git add -f config.py` or `.gitignore` regression would commit them. These keys should be rotated as part of this implementation.

---

## 2. Tool Selection & Rationale

### Why These Tools (Not Others)

| Tool | Chosen Over | Rationale |
|------|------------|-----------|
| **Gitleaks** | detect-secrets, truffleHog | Fastest, best pre-commit hook, active maintenance, no Python dependency |
| **Bandit** | — | Python-specific, 2-3s scan, low false positives, PyCQA-maintained |
| **Semgrep** | CodeQL, SonarQube | CLI-first, framework-specific rules (p/flask), MCP server available for OpenCode, no Docker required |
| **pip-audit** | safety, pip check | Official PyPA tool, reads advisory DB directly, JSON output |
| **Dependabot** | Renovate | Native GitHub, zero config for Python, free |
| **OWASP ZAP** | Burp Suite | Only recommended if app moves to shared-network deployment; deferred for local-only |

### Install-Time Corrections from Architecture Audit

The security stack is approved for implementation with these hard constraints:

1. **Do not workspace-scan ignored local secrets by default.** `config.py` remains gitignored and must not be allowlisted. Pre-commit and CI secret gates must scan staged/history/tracked content so `git add -f config.py` is blocked without making normal local development fail because secrets exist on disk.
2. **Do not use broad secret allowlists.** Avoid path-wide allowlists for all prompts or all tests. Prefer targeted regex/path rules for documented fake placeholders only.
3. **Do not globally skip Bandit B110.** Silent `try/except/pass` is a repo quality risk. Use targeted `# nosec` comments only where a reviewed fail-open pattern is intentional.
4. **Security generated artifacts must be gitignored.** Reports under `scripts/security/` and root scanner reports must not be committed.
5. **Templates must be ASCII-safe.** Repo policy forbids checkmarks, cross marks, and emoji in committed source/docs generated by this stack.
6. **Semgrep may run in CI without local Docker.** If CI uses a container, document that the zero-Docker requirement applies to local/developer infrastructure only. Prefer pip-installed Semgrep if a pure runner path is practical.
7. **GitHub Actions hardening is in scope.** Pin third-party actions to immutable SHAs where feasible and reduce workflow permissions, especially `opencode.yml` `id-token: write` and `contents: write`.

### Where Each Tool Runs

| Tool | Pre-Commit | CI | On-Demand | Rationale |
|------|-----------|----|-----------|-----------|
| **Gitleaks** | YES | YES (safety net) | YES | Fast (~1s), blocks accidental commits at source |
| **Bandit** | YES | YES | YES | Fast (~2-3s), catches Python-specific vulns early |
| **Semgrep** | NO | YES | YES | Heavier (~10-15s), too slow for pre-commit; full ruleset in CI |
| **pip-audit** | NO | YES | YES | Requires network, only meaningful against live advisory DB |
| **Dependabot** | N/A | YES (automated) | N/A | GitHub-native, no install |
| **OWASP ZAP** | N/A | N/A | YES (future) | Requires running server; deferred |

---

## 3. Architecture: 4-Layer Security Stack

```
LAYER 1: PRE-COMMIT (per commit, <5s total)
  └─ Gitleaks: Block secret leaks before they reach git
  └─ Bandit: Catch Python security anti-patterns early

LAYER 2: CI GATES (on push/PR, ~30s total)
  └─ Semgrep: Full SAST with framework-specific rules
  └─ pip-audit: Dependency CVE scan, fail on HIGH/CRITICAL
  └─ Gitleaks: Redundant history scan (safety net)

LAYER 3: SUPPLY CHAIN (automated, continuous)
  └─ Dependabot: Automated PRs for vulnerable dependencies
  └─ Lockfile: Pinned versions for reproducible builds

LAYER 4: ON-DEMAND (manual or scheduled)
  └─ OWASP ZAP: DAST when app moves to shared-network (deferred)
  └─ OpenCode audit prompt: OWASP-aware AI code review (see Section 12)
```

---

## 4. Layer 1: Pre-Commit Hook Implementation

### 4.1 Updated `.pre-commit-config.yaml`

```yaml
repos:
  # Existing: ASCII compliance
  - repo: local
    hooks:
      - id: ascii-compliance
        name: ASCII compliance
        entry: python3 scripts/check_ascii_compliance.py --summary-only
        language: system
        pass_filenames: false

  # NEW: Secret detection. This protects staged commits and git history;
  # it must not require scanning ignored local config.py during normal commits.
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.24.0
    hooks:
      - id: gitleaks

  # NEW: Python security analysis
  - repo: https://github.com/PyCQA/bandit
    rev: 1.8.3
    hooks:
      - id: bandit
        args: ["-c", "pyproject.toml", "-ll"]
        exclude: "^tests/|^scripts/test_"
```

### 4.2 Gitleaks Configuration

Create `.gitleaks.toml` to suppress false positives without hiding real secrets:

```toml
# .gitleaks.toml
[allowlist]
  description = "Allowlist for documented fake placeholders only"

  [[allowlist.paths]]
    pattern = "config_template\\.py"

  [[allowlist.regexes]]
    regex = '''sk-(proj-)?(NEW-KEY|your[-_]?(api[-_]?)?key|example|test|placeholder)'''

  [[allowlist.regexes]]
    regex = '''sk-or-v1-(NEW-KEY|your[-_]?(api[-_]?)?key|example|test|placeholder)'''
```

### 4.3 Bandit Baseline

First run will produce findings. Create a `pyproject.toml` section to configure Bandit exclusions:

```toml
# pyproject.toml (new file or add to existing)
[tool.bandit]
exclude_dirs = [".venv", "node_modules", "backup"]
skips = ["B101"]  # B101=assert (used in tests); do not globally skip B110
```

Intentional silent fail-open blocks should use a local `# nosec B110` plus a short explanatory comment.

### 4.4 Installation

```bash
# Install pre-commit if not present
pip install pre-commit

# Install the hooks
pre-commit install

# Run against all files once to establish baseline
pre-commit run --all-files
```

---

## 5. Layer 2: CI Security Gates

### 5.1 GitHub Actions Workflow

Create `.github/workflows/security-audit.yml`:

```yaml
name: Security Audit

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:       # Manual trigger

jobs:
  secret-scan:
    # Only on code pushes/PRs — secrets don't appear without a push
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITLEAKS_LICENSE: ${{ secrets.GITLEAKS_LICENSE }}

  sast-semgrep:
    # Only on code pushes/PRs — code doesn't change without a push
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install Semgrep
        run: pip install semgrep
      - name: Semgrep SAST
        run: |
          semgrep scan \
            --config auto \
            --config p/flask \
            --config p/bandit \
            --config p/python \
            --config p/secrets \
            --error \
            --metrics=off \
            --sarif > semgrep-results.sarif
      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: semgrep-results.sarif

  sast-bandit:
    # Only on code pushes/PRs — code doesn't change without a push
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install Bandit
        run: pip install bandit
      - name: Bandit scan
        run: bandit -r . -c pyproject.toml -ll -f json -o bandit-results.json
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: bandit-results
          path: bandit-results.json

  dependency-scan:
    # Runs on pushes AND weekly cron — new CVEs are published independently of code changes
    runs-on: ubuntu-latest
    if: github.event_name == 'push' || github.event_name == 'pull_request' || github.event_name == 'schedule'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install pip-audit
        run: pip install pip-audit
      - name: Audit dependencies
        run: pip-audit -r requirements.txt --strict
```

`pip-audit --strict` fails on any known vulnerability. That is intentionally stricter than the HIGH/CRITICAL policy table below for the first rollout. If false positives or accepted-risk cases appear, replace this with a JSON parse gate that fails only on approved severities.

Schedule in a separate workflow file for clarity:

```yaml
# .github/workflows/security-dependency-cron.yml
name: Dependency CVE Scan (Scheduled)

on:
  schedule:
    - cron: '0 8 * * 1'  # Weekly Monday 8AM UTC
  workflow_dispatch:

jobs:
  dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install pip-audit
        run: pip install pip-audit
      - name: Audit dependencies
        run: pip-audit -r requirements.txt --strict
```

### 5.2 Semgrep Ruleset Breakdown

| Ruleset | What It Catches |
|---------|----------------|
| `auto` | Language-appropriate rules (Python: XSS, SQL injection, path traversal) |
| `p/flask` | Flask-specific: debug mode, insecure cookies, SSTI, missing CORS, secret key leaks |
| `p/bandit` | Bandit rules running inside Semgrep (unified dashboard) |
| `p/python` | General Python security: eval, exec, pickle, subprocess, tempfile |
| `p/secrets` | Secret patterns (redundant with Gitleaks but different engine) |

### 5.3 Trigger Matrix

| Scanner | push/PR | Weekly Cron | Rationale |
|---------|---------|-------------|-----------|
| Gitleaks | YES | NO | Secrets only appear via push — cron is pointless |
| Bandit | YES | NO | Code doesn't change without a push |
| Semgrep | YES | NO | Same — static code, not external threat feed |
| pip-audit | YES | YES | New CVEs published daily to advisory DB; code may be fine today and vulnerable tomorrow |

### 5.4 Failure Thresholds

| Scanner | Threshold | Rationale |
|---------|-----------|-----------|
| Gitleaks | Any finding = FAIL | Secrets must never be committed |
| pip-audit | Any CVE in first rollout; HIGH/CRITICAL after triage parser exists | `--strict` is simple and safe; severity-aware gating can be added later |
| Semgrep | ERROR severity = FAIL | Block on confirmed vulns; WARNING = annotate only |
| Bandit | HIGH severity = FAIL | Block on confirmed security issues |

---

## 6. Layer 3: Supply Chain Hardening

### 6.1 Dependabot Configuration

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    labels:
      - "dependencies"
      - "security"
    assignees:
      - "zeug-zz"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 2
    labels:
      - "dependencies"
      - "ci"
```

### 6.2 Dependency Lockfile

Current `requirements.txt` uses `>=` (floating versions). Create a lockfile for reproducible builds and security auditing:

```bash
# Generate lockfile from current venv
.venv/bin/pip freeze > requirements-lock.txt
```

Update CI and documentation to reference the lockfile:

```bash
# For deterministic installs
pip install -r requirements-lock.txt
```

### 6.3 `SECURITY.md`

Create `SECURITY.md` at repo root:

```markdown
# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| main    | :white_check_mark: |
| < 0.4.0 | :x:                |

## Reporting a Vulnerability

Do NOT open a public GitHub issue for security vulnerabilities.

Email: [your email]

Expect a response within 72 hours. Please include:
- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Any potential mitigations you've identified

## Scope

This policy covers:
- The NeverEndingQuest web application (Flask/SocketIO server)
- The Module Toolkit builder interface
- API key handling and configuration management
- Dependency supply chain

This policy does NOT cover:
- LLM prompt injection (this is known and managed via prompt architecture)
- Content safety of AI-generated narration (managed via content validator)
- Local-only deployment scenarios (the app is designed for trusted LAN use)
```

---

## 7. Layer 4: On-Demand DAST (Deferred)

### 7.1 OWASP ZAP - When to Add

OWASP ZAP is only recommended when the app moves to a shared-network or internet-facing deployment model. For local-only tabletop use, the static analysis tools (Semgrep + Bandit) already cover the relevant Flask/web surface.

**Trigger for activation:**
- Phase 2/3 of `plans/version-2/client_network.md` (LAN/internet client deployment)
- Any deployment to a non-localhost address beyond trusted LAN

### 7.2 Future ZAP Integration Pattern

```bash
# Start the app in background
.venv/bin/python run_web.py &
APP_PID=$!

# Run ZAP baseline scan
zap-baseline.py -t http://localhost:8357 -r zap-report.html

# Stop the app
kill $APP_PID
```

---

## 8. Cross-Repo Reusability Design

### 8.1 Design Principle

All tools are CLI-first, pip-installable, and produce JSON output. This means a single shared audit script or Makefile can be dropped into any Python repo and invoked from OpenCode.

### 8.2 Shared Audit Makefile

Create a reusable `scripts/audit_security.sh` (or `Makefile`) that can be symlinked or copied across repos:

```makefile
# scripts/security/Makefile (shared across repos)
.PHONY: audit-secrets audit-code audit-deps audit-all

audit-secrets:
	@echo "=== SECRET SCAN (Gitleaks) ==="
	gitleaks detect --source . -v --no-git --report-format json --report-path .gitleaks-report.json 2>/dev/null; \
	if [ $$? -eq 1 ]; then \
		echo "[FAIL] Secrets found in working tree"; \
		exit 1; \
	else \
		echo "[PASS] No secrets detected"; \
	fi

audit-code:
	@echo "=== SAST (Bandit) ==="
	bandit -r . -c pyproject.toml -ll -f json -o bandit-report.json || true
	@echo "=== SAST (Semgrep) ==="
	semgrep scan --config auto --config p/flask --config p/bandit --metrics=off --json -o semgrep-report.json || true

audit-deps:
	@echo "=== DEPENDENCY AUDIT (pip-audit) ==="
	pip-audit -r requirements.txt --format json -o pip-audit-report.json || true

audit-all: audit-secrets audit-code audit-deps
	@echo ""
	@echo "=== AUDIT COMPLETE ==="
	@echo "Reports: .gitleaks-report.json, bandit-report.json, semgrep-report.json, pip-audit-report.json"
```

### 8.3 OpenCode Integration

From OpenCode, the audit can be triggered as:

```bash
# Full audit
make -f scripts/security/Makefile audit-all

# Individual scans
make -f scripts/security/Makefile audit-secrets
make -f scripts/security/Makefile audit-code
make -f scripts/security/Makefile audit-deps
```

### 8.4 Cross-Repo Deployment Pattern

For other Python repos:

```bash
# In target repo:
mkdir -p scripts/security
cp /path/to/neq/scripts/security/Makefile scripts/security/
cp /path/to/neq/.pre-commit-config.yaml .  # Edit to keep repo-specific hooks
cp /path/to/neq/.gitleaks.toml .
cp /path/to/neq/.github/workflows/security-audit.yml .github/workflows/
cp /path/to/neq/.github/dependabot.yml .github/
cp /path/to/neq/pyproject.toml .  # Or merge Bandit section
cp /path/to/neq/SECURITY.md .  # Edit contact email
```

Then customize for each repo:
- `SECURITY.md` contact email
- `.pre-commit-config.yaml` repo-specific hooks
- `pyproject.toml` Bandit exclusions

---

## 9. Phased Rollout

### Phase 1: Foundation (Week 1, ~1 hour)

| Task | Effort | Dependencies |
|------|--------|-------------|
| Install pre-commit + Gitleaks + Bandit | 10 min | pip |
| Update `.pre-commit-config.yaml` with Gitleaks + Bandit hooks | 10 min | — |
| Create `.gitleaks.toml` allowlist | 5 min | — |
| Create `pyproject.toml` with Bandit config | 10 min | — |
| Run pre-commit against all files, fix findings | 20 min | — |
| Rotate API keys (see Section 10) | 15 min | OpenAI/OpenRouter dashboards |

**Deliverable:** Pre-commit blocks secret leaks and Python anti-patterns before commit.

### Phase 2: CI Gates (Week 1-2, ~2 hours)

| Task | Effort | Dependencies |
|------|--------|-------------|
| Create `.github/workflows/security-audit.yml` | 30 min | Phase 1 |
| Test workflow on push (observe first run) | 30 min | — |
| Triage and fix Semgrep findings | 45 min | — |
| Triage and fix pip-audit findings | 15 min | — |

**Deliverable:** CI blocks merges with known-vulnerable deps or Semgrep ERROR findings.

### Phase 3: Supply Chain (Week 2, ~30 min)

| Task | Effort | Dependencies |
|------|--------|-------------|
| Create `.github/dependabot.yml` | 5 min | — |
| Generate `requirements-lock.txt` | 5 min | .venv |
| Create `SECURITY.md` | 10 min | — |
| Create shared `scripts/security/Makefile` | 10 min | — |

**Deliverable:** Automated CVE alerts, reproducible builds, disclosure policy.

### Phase 4: Cross-Repo Deployment (Ongoing)

| Task | Effort |
|------|--------|
| Copy security stack to other Python repos | 15 min/repo |
| Customize allowlists per repo | 10 min/repo |
| Verify pre-commit hooks install cleanly | 5 min/repo |

### Phase 5: DAST (Deferred to v2 Client Phase 2+)

Triggered by `plans/version-2/client_network.md` Phase 2 (Post-MVP UX Hardening) or Phase 3 (Internet-Ready Thin Client).

---

## 10. Key Rotation Procedure

### 10.1 Why Rotate

The current `config.py` contains API keys that have been on disk and visible to any filesystem-scanning tool (grep, find, semgrep, bandit). While `.gitignore` prevents git tracking, the keys should be rotated as a precaution.

### 10.2 Rotation Steps

```bash
# 1. Revoke old keys at provider dashboards:
#    - OpenAI:    https://platform.openai.com/api-keys
#    - OpenRouter: https://openrouter.ai/settings/keys

# 2. Generate new keys at each provider

# 3. Update config.py with new keys:
#    OPENAI_API_KEY = "sk-proj-NEW-KEY"
#    OPENROUTER_API_KEY = "sk-or-v1-NEW-KEY"

# 4. Verify the app works with new keys:
.venv/bin/python run_web.py  # Start, confirm narration works

# 5. Delete old keys from provider dashboards

# 6. Verify old keys no longer work (optional safety check)
```

### 10.3 Future Secret Storage

For development convenience vs security, consider environment variables as a marginal improvement:

```python
# config.py
import os
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
```

This doesn't add meaningful security for a local-only app (env vars are still plaintext in shell history), but it decouples secrets from the config file and prevents accidental file reads from exposing them.

**Recommendation:** Defer. For local tabletop use, the current gitignored `config.py` pattern is pragmatic. The pre-commit Gitleaks hook is the real defense against accidental exposure.

---

## 11. OWASP-Aware OpenCode Audit Prompt

### 11.1 System Prompt for Security Audits

This is a reusable prompt template for OpenCode security review sessions, targeting the OWASP Top 10 2025 and OWASP Top 10 for Agentic Applications 2026:

```
Perform a comprehensive security audit of this Python web application.
Target the OWASP Top 10 2025 and OWASP Top 10 for Agentic Applications 2026.

AUDIT FOCUS AREAS:

1. A01:2025 Broken Access Control
   - Check all Flask routes for missing authentication decorators
   - Verify user_id handling in route parameters
   - Check WebSocket event handlers for access gating

2. A03:2025 Software Supply Chain
   - Run pip-audit against requirements.txt
   - Check for unpinned dependency versions
   - Verify no direct git-dependency URLs

3. A05:2025 Injection
   - Scan for raw SQL queries (though unlikely in this JSON-based app)
   - Check for unsafe os.system/subprocess calls
   - Verify Jinja2 template auto-escaping is enabled
   - Check for SSTI (Server-Side Template Injection) vectors

4. A10:2025 Mishandling of Exceptional Conditions
   - Review try/except blocks for fail-open logic
   - Check for verbose error leaks that expose stack traces to users
   - Verify debug mode is off in non-development paths

5. ASI02:2026 Tool Misuse (Agentic Applications)
   - Review MCP server configurations
   - Verify OpenCode agent tool permissions are not over-privileged
   - Check that CI workflow permissions (contents: write, id-token: write) are scoped correctly

6. ASI05:2026 Prompt Injection (Agentic Applications)
   - Review system prompt boundaries
   - Check for user-input-to-system-prompt injection paths
   - Verify LLM output is not directly executed as code

REPORT FORMAT:
For each finding, report:
- OWASP category and ID
- File path and line number
- Severity (CRITICAL/HIGH/MEDIUM/LOW)
- Description of the vulnerability
- Proposed fix with code example
- Why the fix is safer
```

### 11.2 Usage

From OpenCode:
```
Read Security audits plan at plans/security-audit.md, load the OWASP audit prompt
from Section 11.1, and run a focused audit of web/web_interface.py routes.
```

---

## 12. OpenSpec Scaffolds

### 12.1 Recommended Change Breakdown

For implementation tracking, create these OpenSpec changes:

| # | Change Name | Scope | Phase |
|---|------------|-------|-------|
| 1 | `security-stack-precommit-gitleaks-bandit` | `.pre-commit-config.yaml`, `.gitleaks.toml`, `pyproject.toml`, key rotation | Phase 1 |
| 2 | `security-stack-ci-gates` | `.github/workflows/security-audit.yml` | Phase 2 |
| 3 | `security-stack-supply-chain` | `.github/dependabot.yml`, `requirements-lock.txt`, `SECURITY.md`, `scripts/security/Makefile` | Phase 3 |
| 4 | `security-stack-werkzeug-network-notes` | Append notes to `plans/version-2/client_network.md`, `plans/version-2/client-web.md` | Phase 1 |

### 12.2 Delta Specs Per Change

**Change 1: `security-stack-precommit-gitleaks-bandit`**
- `precommit-secret-scanning`: Pre-commit blocks commits containing secrets
- `precommit-python-sast`: Pre-commit blocks Python security anti-patterns (Bandit HIGH)
- `key-rotation-procedure`: Documented key rotation procedure exists
- `security-report-ignore-contract`: Scanner report artifacts are ignored and cannot pollute commits
- `secret-allowlist-minimality`: Gitleaks allowlist covers only fake placeholders, never broad source paths or `config.py`

**Change 2: `security-stack-ci-gates`**
- `ci-secret-scan`: CI runs Gitleaks on push/PR
- `ci-dependency-audit`: CI blocks merges on HIGH/CRITICAL dependency CVEs
- `ci-sast-semgrep`: CI blocks merges on Semgrep ERROR findings
- `ci-sast-bandit`: CI blocks merges on Bandit HIGH findings
- `ci-actions-hardening`: GitHub Actions are pinned or explicitly risk-accepted, and workflow permissions are least-privilege

**Change 3: `security-stack-supply-chain`**
- `dependabot-pip-enabled`: Dependabot creates automated PRs for pip dependency updates
- `dependabot-actions-enabled`: Dependabot creates automated PRs for GitHub Actions updates
- `lockfile-present`: `requirements-lock.txt` provides reproducible dependency resolution
- `security-policy-present`: `SECURITY.md` exists with disclosure instructions
- `shared-audit-makefile`: `scripts/security/Makefile` provides cross-repo audit commands

**Change 4: `security-stack-werkzeug-network-notes`**
- `client-network-werkzeug-note`: `plans/version-2/client_network.md` documents `allow_unsafe_werkzeug=True` and `0.0.0.0` binding as future hardening items
- `client-web-werkzeug-note`: `plans/version-2/client-web.md` documents same

---

## 13. Werkzeug/Network Hardening Notes for v2 Plans

### 13.1 Current Risky Configuration

`web/web_interface.py` uses:
```python
socketio.run(app, host="0.0.0.0", port=8357, allow_unsafe_werkzeug=True)
```

It also uses:

```python
app.config['SECRET_KEY'] = 'dungeon-master-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")
```

`module_builder_web.py` separately uses:

```python
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
```

**Risk analysis:**
- `0.0.0.0`: Binds to all network interfaces. On a machine connected to any network (WiFi, Ethernet), the server is accessible to other devices on that network. This is intentional for local tabletop use (DM laptop serving player browsers) but means the server is not localhost-isolated.
- `allow_unsafe_werkzeug=True`: Flask-SocketIO requires this flag for WebSocket support on the Werkzeug development server. It bypasses Werkzeug's security protections. This is standard for Flask-SocketIO development but the Werkzeug dev server is explicitly documented as "not for production."
- Wildcard CORS: Acceptable for trusted local/LAN tabletop use, but not acceptable for internet-facing or untrusted shared-network deployments.
- Static Flask secret key: Acceptable only while the app has no security-sensitive server-side sessions. Replace with per-install secret generation before any authentication or internet deployment.

### 13.2 Future Hardening Path (v2 Client Phases)

These should be addressed in `plans/version-2/client_network.md` Phase 2 (Post-MVP UX Hardening) or Phase 3 (Internet-Ready):

1. **Bind to specific interface** instead of `0.0.0.0` when possible:
   ```python
   host = "127.0.0.1" if local_only else "192.168.1.x"  # LAN-specific
   ```

2. **Replace Werkzeug dev server** with a production WSGI server (gunicorn, waitress) when moving beyond LAN:
   ```python
   # Production path
   from waitress import serve
   serve(app, host="127.0.0.1", port=8357)
   ```

3. **Add TLS** (via nginx reverse proxy or built-in) for internet deployment.

4. **Add rate limiting** on login and input endpoints for internet-facing use.

5. **Add CORS policy** restricting origins to known client domains.

### 13.3 Notes to Append

See appended content in:
- `plans/version-2/client_network.md` — Section: "Security Hardening Notes (from security-audit.md)"
- `plans/version-2/client-web.md` — Section: "Security Hardening Notes (from security-audit.md)"

---

## 14. Risk Acceptance

### 14.1 Known Risks We Accept

| Risk | Rationale |
|------|-----------|
| Plaintext API keys in `config.py` | Local-only machine, gitignored, pre-commit Gitleaks guard |
| `allow_unsafe_werkzeug=True` | Required for Flask-SocketIO WebSocket support; local-only deployment |
| `0.0.0.0` binding | Intentional for LAN tabletop play; v2 will revisit |
| Wildcard CORS | Required for frictionless local/tabletop client testing; v2 client hardening will restrict origins |
| Static Flask secret key | Current app has no security-sensitive auth/session boundary; replace before auth/internet deployment |
| No HTTPS/TLS | Local/trusted-LAN only; v2 Phase 3 will add |
| No user authentication beyond shared password | Intentional KISS design for MVP tabletop sessions |
| LLM prompt injection | Managed via prompt architecture; not a security domain in local context |
| `mitmproxy` in dependencies | Dev-only tool for LM Studio mode; not a runtime dependency |

### 14.2 What We Never Accept

- Committed secrets (any finding from Gitleaks is a hard block)
- Known-vulnerable dependencies with HIGH/CRITICAL CVEs
- `shell=True` in subprocess calls
- Exposed admin/debug routes on client-facing surfaces
- Verbose error leaks showing stack traces to users
- Unpinned or latest-ref third-party GitHub Actions with broad write permissions unless explicitly risk-accepted

---

## 15. Verification Checklist

After each phase, verify:

**Phase 1:**
- [ ] `pre-commit run --all-files` passes
- [ ] Gitleaks blocks a test commit with a fake API key
- [ ] Bandit reports clean (or known-accepted findings)
- [ ] Scanner report files are ignored by git
- [ ] API keys rotated at providers
- [ ] App works with new keys

**Phase 2:**
- [ ] CI workflow triggers on push
- [ ] CI workflow passes on clean code
- [ ] CI workflow fails on intentional secret insertion (test branch)
- [ ] Semgrep SARIF results visible in GitHub Security tab

**Phase 3:**
- [ ] Dependabot opens first PR within 24 hours (if stale deps exist)
- [ ] `pip install -r requirements-lock.txt` succeeds in clean venv
- [ ] `SECURITY.md` renders correctly on GitHub
- [ ] `make -f scripts/security/Makefile audit-all` runs clean

**Phase 4:**
- [ ] At least one other repo has the security stack deployed
- [ ] Pre-commit hooks work identically across repos

---

## 16. Maintenance Cadence

| Task | Frequency | Owner |
|------|-----------|-------|
| Review Dependabot PRs | Weekly | Human |
| Review CI security scan results | Per push | Automated + Human on failure |
| Update pip-audit advisory DB | Automatic (fetches live) | CI |
| Update Semgrep rules | Monthly (or on new Semgrep release) | Human |
| Rotate API keys | Every 6 months or on suspicion of exposure | Human |
| Review Gitleaks allowlist | When false positives accumulate | Human |
| Re-evaluate DAST need | When v2 client Phase 2 begins | Human |

---

## References

- OWASP Top 10 2025: https://owasp.org/Top10/2025/
- OWASP Top 10 for Agentic Applications 2026: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- Semgrep Python/Flask rules: https://semgrep.dev/r?q=python.flask
- Bandit: https://bandit.readthedocs.io/
- Gitleaks: https://github.com/gitleaks/gitleaks
- pip-audit: https://pypi.org/project/pip-audit/
- Dependabot: https://docs.github.com/en/code-security/dependabot

---

## 17. OpenCode Security Audit Skill

### Location
`~/.config/opencode/skills/security-audit/SKILL.md`

### Template Directory
`~/.config/opencode/skills/security-audit/templates/`
- `python/` — 7 config templates for Python repos
- `node/` — 6 config templates for Node.js repos

### Four Functions

| Function | Trigger | What It Does |
|----------|---------|-------------|
| **Install** | `install security audit` | Detects repo type, installs CLI tools (brew/pip/npm), copies templates, merges with existing configs, runs `pre-commit install` + `pre-commit run --all-files` |
| **Audit** | `audit security` / `audit secrets` / `audit dependencies` / `audit staged` / `audit files <paths>` | Runs Gitleaks, Bandit+Semgrep, pip-audit in selected modes and scopes. Writes structured JSON report to `scripts/security/last-audit.json`. **Dependency audit always runs repo-wide regardless of scope.** |
| **Triage** | `triage security` / `triage findings` | Loads last audit report, presents findings one at a time (CRITICAL first). Offers: fix, suppress (update allowlist), accept risk (document in SECURITY.md), skip. |
| **Status** | `security status` / `audit status` | Health check: hooks installed? last audit date? open Dependabot alerts? tool versions? SECURITY.md present? |

### Key Design Decisions

1. **Config templates live inside the skill directory** — self-contained, no dependency on NEQ repo for other projects.
2. **Install auto-runs pre-commit baseline** — no opt-in step; if you install, you scan.
3. **Dependency audit never skips** — even on `audit files <paths>`, pip-audit/npm-audit runs repo-wide. Zero-day exploits in public open-source dependencies are the critical supply chain threat.
4. **Semgrep is CI-only** — too heavy for pre-commit (~10-15s). Bandit covers Python at commit time (~2-3s).
5. **Craft CMS deferred** — PHP/Twig/JS repos with `composer.json` containing `craftcms/cms` are detected but reported as unsupported. Only Gitleaks (secret scanning) is offered. Full Craft CMS support awaits the user's next Craft build cycle.

### Repo Type Detection

| Detected | Template Used | Tools |
|----------|--------------|-------|
| `requirements.txt`, `pyproject.toml`, `setup.py`, `setup.cfg` | Python | Gitleaks, Bandit, Semgrep (p/flask, p/python), pip-audit |
| `package.json` (no `composer.json`) | Node | Gitleaks, Semgrep (p/javascript), npm-audit |
| `composer.json` with `craftcms/cms` | Craft (deferred) | Gitleaks only (reported as limited) |
| Unknown | User chooses | Per chosen template |

### Audit Scope Behavior

| Scope | Secrets | Code (SAST) | Dependencies |
|-------|---------|-------------|-------------|
| `workspace` | Full working tree | Full repo | **Always repo-wide** |
| `staged` | `gitleaks protect --staged` | Staged files only | **Always repo-wide** |
| `files:<paths>` | Specified paths | Specified paths | **Always repo-wide** |
| `diff` | Unstaged changed files | Unstaged changed files | **Always repo-wide** |
| `history` | Full git history | N/A | **Always repo-wide** |

The dependency column is always "repo-wide" by design. A file-scoped audit of `src/auth.py` still scans all of `requirements.txt` because a vulnerable dependency anywhere is a vulnerability everywhere.

### Template Files Provided

**Python (`templates/python/`):**
| File | Destination |
|------|------------|
| `.pre-commit-config.yaml` | `./.pre-commit-config.yaml` (merged if exists) |
| `.gitleaks.toml` | `./.gitleaks.toml` |
| `pyproject.toml` | `./pyproject.toml` (merged if exists) |
| `Makefile` | `./scripts/security/Makefile` |
| `security-audit.yml` | `.github/workflows/security-audit.yml` |
| `dependabot.yml` | `.github/dependabot.yml` |
| `SECURITY.md` | `./SECURITY.md` |

**Node (`templates/node/`):**
| File | Destination |
|------|------------|
| `.pre-commit-config.yaml` | `./.pre-commit-config.yaml` (merged if exists) |
| `.gitleaks.toml` | `./.gitleaks.toml` |
| `Makefile` | `./scripts/security/Makefile` |
| `security-audit.yml` | `.github/workflows/security-audit.yml` |
| `dependabot.yml` | `.github/dependabot.yml` |
| `SECURITY.md` | `./SECURITY.md` |

### Adding New Repo Types

Future maintainers:
1. Create `templates/<type>/` directory with matching template files.
2. Add detection logic to the install function in SKILL.md.
3. Add tool installation commands for the new type.
4. Add audit commands (secrets, code, deps) for the new type.
5. Update this section with the new type's tool matrix.

---

## 18. OpenCode Threat Monitor Skill

### Purpose

An early warning system that fetches public threat intelligence feeds, filters for threats relevant to the current repo's technology stack, and advises on actions. Complements `security-audit` (which scans your code) by scanning the world for what's coming.

### Location

`~/.config/opencode/skills/threat-monitor/SKILL.md`

### Configuration

`~/.config/opencode/skills/threat-monitor/feeds.json`

### Feed Selection (5 Sources)

| Tier | Feed | URL | Format | Why |
|------|------|-----|--------|-----|
| 1 | **Zero Day Initiative** | `https://www.zerodayinitiative.com/rss/published/` | RSS | Published 0-days with CVSS, direct RCE/command injection coverage |
| 1 | **CISA Known Exploited Vulnerabilities** | `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json` | JSON | Only CVEs actively exploited in the wild — "patch today" urgency |
| 1 | **Anthropic Red Team** | `https://red.anthropic.com` | HTML | AI/LLM threat landscape — the most important single source for the LLM-era shift in vulnerability discovery |
| 2 | **Google Threat Intelligence** | `https://feeds.feedburner.com/threatintelligence/pvexyqv7v0v` | RSS | Campaign analysis, APT tracking, supply chain attack deep dives |
| 3 | **Krebs on Security** | `https://krebsonsecurity.com/feed/` | RSS | Investigative journalism — the "how" behind attacks, not just CVE IDs |

### Three Functions

| Function | Trigger | What It Does |
|----------|---------|-------------|
| **Threat Check** | `threat check`, `threat summary`, `what's new in threats` | Fetches all feeds, detects repo tech stack, filters for relevant threats, reports with severity and action items |
| **Threat Advise** | `threat advise` | Full analysis: threat check + landscape summary + stack-specific risk assessment + recommended actions ordered by urgency |
| **Threat Feeds** | `threat feeds`, `list threat feeds` | Shows configured feed list with last fetch timestamps and health status |

### Tech Stack Fingerprinting

The skill auto-detects the repo's technology stack and uses it to filter threats:

| Detection | Tags |
|-----------|------|
| `requirements.txt` has `flask` | `flask`, `python`, `web` |
| `requirements.txt` has `openai` | `ai`, `llm`, `openai`, `api` |
| `.opencode/` directory exists | `opencode`, `mcp`, `agent` |
| `package.json` exists | `javascript`, `npm`, `node` |
| `composer.json` exists | `php`, `composer` |

Threats are reported if their content matches 1+ detected tags. CISA KEV uses structured JSON field filtering (e.g., `vendorProject` contains `python`).

### Integration with `security-audit`

The two skills form a complete security posture:

| `security-audit` | `threat-monitor` |
|-----------------|-----------------|
| Scans YOUR code | Scans the WORLD |
| "Do we have vulnerabilities?" | "What threats are out there?" |
| Pre-commit + CI (automated) | On-demand (user-triggered) |
| Fix what's found | Know what's coming |

`threat advise` cross-references: "Threat X matches your stack. Your last `audit dependencies` ran on Y date. Run `audit security` to check if you're affected."

### Design Decisions (Locked)

1. **On-demand only** — No background cron. User triggers refresh via "threat check". Each `ctx_fetch_and_index` call is up-to-date.
2. **5 feeds exactly** — ZDI, CISA KEV, Google TI, Anthropic Red Team, Krebs. Curated for signal-to-noise.
3. **CISA KEV JSON parsing** — Worth the complexity. It's the only feed that definitively answers "is this being exploited right now?"
4. **Global skill** — Cross-repo. Threat landscape doesn't change per repo; only the relevance filtering does.
5. **Output is always actionable** — Every reported threat includes a concrete action. Never "here's a scary thing, good luck."

### Threat Severity Levels

| Level | Criteria | Example |
|-------|----------|---------|
| **IMMEDIATE** | CVSS >= 9.0, auth not required, matches stack exactly, active exploitation | aws-mcp-server 9.8 command injection |
| **HIGH** | CVSS >= 7.0, or supply chain compromise, or matches stack + active campaign | Axios npm compromised by DPRK |
| **WATCH** | Trend or capability shift, not a specific CVE | AI models finding 0-days at scale |
| **INFO** | Interesting but no direct impact on this stack | Enterprise printer firmware exploit |

### Output Format

```
=== THREAT SUMMARY: <repo> ===
Fetched: <timestamp> | Feeds: 5/5 OK | Stack: python, flask, openai, mcp, agent

IMMEDIATE (ACT NOW)
  [CVSS 9.8] aws-mcp-server Command Injection (CVE-2026-5058)
    ZDI · 2026-03-30 · Auth not required · 0-day
    Relevance: DIRECT · This repo uses MCP servers
    Action: Review all MCP tool definitions. No tool may pass
            user-controlled strings to shell execution.

HIGH (THIS WEEK)
  [Supply Chain] Axios NPM compromised by DPRK (UNC1069)
    Google TI · 2026-03-31
    Relevance: MEDIUM · pip packages equally vulnerable
    Action: Run 'audit dependencies'. Enable Dependabot.

WATCH (TREND)
  AI models finding 0-days at production scale
    Anthropic Red Team · May 2026 · Mythos: 22 Firefox vulns in 2 weeks
    Implication: Codebase will be scanned by AI. Automated SAST is now
                 table stakes — Bandit + Semgrep must be active.
```

### Feed Health Monitoring

Each fetch records:
- HTTP status
- Item count
- Timestamp
- Parse errors (if any)

If a feed fails 2+ consecutive fetches, the skill reports it as degraded and continues with remaining feeds.

### Threat Report (Save) Function

Trigger: `threat report` / `save threat report` / `risk assessment`

Runs full `threat advise` then persists a timecoded standalone report to `plans/Risk_Assessment-YYYYMMDD.md`. Reports include:

- Landscape summary
- All findings grouped by severity (IMMEDIATE / HIGH / WATCH)
- Detailed stack risk assessment with per-component reasoning
- RECOMMENDED ACTIONS table ordered by urgency with effort estimates
- Baseline status (last audit, hooks, Dependabot, key rotation)

**Naming convention:** `plans/Risk_Assessment-YYYYMMDD.md` — one report per date. Overwrites if re-run same day. Each report is a complete standalone snapshot, not a diff.

**Pipeline role:** Risk assessments feed into OpenSpec plan-to-builder scaffolding. The user reads the report, selects actions, and creates OpenSpec changes from the recommended actions table.

### Full Function List (4 Total)

| Function | Trigger | Output |
|----------|---------|--------|
| Threat Check | `threat check` | Console summary — ephemeral |
| Threat Advise | `threat advise` | Console analysis — ephemeral |
| Threat Feeds | `threat feeds` | Console status — ephemeral |
| Threat Report | `threat report` / `risk assessment` | Console + `plans/Risk_Assessment-YYYYMMDD.md` — persistent |
