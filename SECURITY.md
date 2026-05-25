# Security Policy

[![Security Audit](https://github.com/zeug-zz/NeverEndingQuest-TTRPG/actions/workflows/security-audit.yml/badge.svg)](https://github.com/zeug-zz/NeverEndingQuest-TTRPG/actions/workflows/security-audit.yml)
[![Pre-commit: gitleaks](https://img.shields.io/badge/pre--commit-gitleaks-brightgreen)](.pre-commit-config.yaml)
[![Pre-commit: bandit](https://img.shields.io/badge/pre--commit-bandit-brightgreen)](.pre-commit-config.yaml)
[![Dependabot](https://img.shields.io/badge/dependabot-active-blue)](.github/dependabot.yml)
[![pip-audit](https://img.shields.io/badge/pip--audit-passing-brightgreen)](requirements-lock.txt)

**Last audit:** 2026-05-25 · **Status:** 0 secrets · 0 SAST findings · 0 CVEs

---

## Supported Versions

| Version | Supported |
| ------- | --------- |
| main    | ✅        |
| < 1.0   | ❌        |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Use GitHub's private vulnerability reporting:
https://github.com/zeug-zz/NeverEndingQuest-TTRPG/security/advisories/new

Expect a response within 72 hours. Please include:

- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Any potential mitigations you've identified

## Scope

This policy covers:

- Application code and its dependencies
- API key handling and configuration management
- CI/CD pipeline security
- Dependency supply chain
- Agent and automation tooling

---

## Defense Layers

| Layer                | Tool                    | Where                  |
| -------------------- | ----------------------- | ---------------------- |
| Secret detection     | Gitleaks                | Pre-commit + CI        |
| SAST (Python)        | Bandit                  | Pre-commit + CI        |
| SAST (framework)     | Semgrep (Flask, Python) | CI only                |
| Dependency CVEs      | pip-audit               | CI only                |
| Supply chain updates | Dependabot              | Weekly (pip + Actions) |
| Threat intelligence  | threat-monitor skill    | On-demand              |

---

## Best Practices for Contributors

### Secrets

- **Never commit `config.py`.** It's in `.gitignore`. Use `config_template.py` as a reference.
- **Never hardcode keys** in source files. All API keys go in `config.py`.
- **Rotate keys immediately** if they appear in any commit, even a private branch.
- The Gitleaks pre-commit hook blocks accidental secret commits. Do not bypass it.

### Dependencies

- **Pin versions** in `requirements-lock.txt`. Use `pip-audit` before adding new packages.
- **Run `pip install --upgrade -r requirements.txt`** monthly and regenerate the lock file.
- **Dependabot PRs** are opened weekly on Mondays. Review and merge within 48 hours for CVEs.

### Code

- **All `requests.get()` calls must include `timeout=`.** This is enforced by Bandit (B113).
- **Use `usedforsecurity=False`** for MD5/SHA1 hashing used for caching/seeding (not crypto).
- **Avoid shell execution of user input.** MCP tools and subprocess calls must sanitize inputs.
- **Flask debug mode must remain off** in production. `0.0.0.0` binding is accepted for local use only.

### CI/CD

- **GitHub Actions are pinned to commit SHA**, not tags or branches.
- **Review third-party action provenance** before adding new workflows.
- The `security-audit.yml` workflow runs on every push and PR to `main`.

---

## Key Rotation Policy

| Key          | Location      | Rotation                                  |
| ------------ | ------------- | ----------------------------------------- |
| All API keys | `config.py` | Every 90 days or after suspected exposure |

Rotation procedure:

1. Generate new key at provider portal
2. Update `config.py`
3. Verify application starts and makes API calls
4. Revoke old key at provider portal
5. Run `gitleaks detect` to confirm old key is not in git history

---

## Audit Cadence

| Activity                  | Frequency               | Trigger                              |
| ------------------------- | ----------------------- | ------------------------------------ |
| Pre-commit scan           | Every commit            | Automatic (gitleaks + bandit)        |
| Full security audit       | Weekly                  | `audit security`                   |
| Audit report              | After audit             | `audit report`                     |
| Dependency CVE scan       | Weekly (CI) + on-demand | CI pipeline +`audit dependencies`  |
| Threat intelligence check | Every 3 days            | `threat check` + `threat report` |
| Threat landscape report   | With audit reports      | Auto-refreshed if >3 days stale      |
| Key rotation              | Every 90 days           | Manual                               |

---

## Accepted Risks

| Date       | Finding                    | Severity | Rationale                                                                            |
| ---------- | -------------------------- | -------- | ------------------------------------------------------------------------------------ |
| 2026-05-25 | allow_unsafe_werkzeug=True | MEDIUM   | Required for Flask-SocketIO; local-only app. Review during v2 client hardening.      |
| 2026-05-25 | 0.0.0.0 binding            | MEDIUM   | Required for local network access. Tracked in `plans/version-2/client_network.md`. |
| 2026-05-25 | python-engineio CORS       | LOW      | Flask-SocketIO default; review with v2 CORS hardening.                               |

---

## Audit Trail

Structured audit data: `scripts/security/last-audit.json`
Markdown audit reports: `scripts/security/audit_report-YYYYMMDD.md` (gitignored)
Threat assessments: `plans/security/risk_assessment-YYYYMMDD.md` (gitignored)

---

## Related Documentation

- `plans/version-2/client_network.md` — v2 client hardening plan (CORS, TLS, network segmentation)
- `plans/version-2/client-web.md` — v2 web client security review
- `.github/workflows/security-audit.yml` — CI security pipeline
- `docs/security/` — Security tooling documentation (gitignored)
