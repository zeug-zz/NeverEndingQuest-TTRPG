# Frontier Builder Profile

This repository is an independently developed fork (ADR-0031); upstream is
read-only reference material, not a compatibility target.

Purpose: keep OpenSpec artifacts reliable across capability tiers by separating
hard contract from flexible execution guidance. "Frontier" means the planner
tier, not a specific vendor or model: a fast builder tier and a frontier-class
planner tier MUST produce the same artifact contract.

## Two-Layer Contract

- Contract Layer (MUST)
  - Normative, testable, enforceable statements.
  - Uses SHALL/MUST language for requirements and failure semantics.
  - Defines invariants, compatibility boundaries, and verification expectations.

- Guidance Layer (SHOULD)
  - Preferred implementation sequence, hints, and style guidance.
  - Non-normative notes for performance, readability, or maintainability.
  - Never overrides a MUST contract.

Conflict resolution:

- If SHOULD conflicts with MUST, follow MUST.

## Minimalism Contract

- Default to the smallest change that satisfies the requirement; justify every
  addition and record the simplest alternative considered.
- Non-goals are binding; delete before adding; do not invent risks, edge cases,
  or migration work no requirement names.
- Budget the capability set and create one spec file per capability.

## Artifact Rules

- proposal.md
  - MUST: problem, objective, scope, and non-goals.
  - MUST: smallest capability set with exact paths (`skip_specs: true` when no spec-level behavior changes).
  - SHOULD: risks, fallback, compatibility impact, and seeding hints only when that surface exists.

- design.md
  - MUST: architecture boundaries, decisions, and the simplest alternative considered.
  - SHOULD: migration, rollback, thread-safety, and observability notes only when that surface exists.

- specs/*/spec.md
  - MUST: requirements and scenarios with explicit acceptance outcomes.
  - MUST: `### Requirement:` plus `#### Scenario:` (exactly 4 hashtags); `## Purpose` only for a new capability.
  - SHOULD: non-normative implementation guidance in separate guidance text.

- tasks.md
  - MUST: dependency-ordered, verifiable, requirement-traceable checkbox steps.
  - MUST: `- [ ]` / `- [x]` markers only; each task states its own verification.
  - SHOULD: optional execution tips outside checklist items.

## Workflow Alignment

- `openspec/config.yaml` supplies CLI-injected context (required), per-artifact
  rules (additive), and apply/archive guidance (advisory); this profile supplies
  the durable KISS and two-layer contract those rules encode.
- Build loops implement one task per builder invocation with planner
  verification before the checkbox is marked complete.
- Completion gate is `openspec validate <change> --strict` plus the affected
  focused test suites; never auto-commit, auto-push, or rewrite git history.

## Style Targets

- Keep MUST statements specific and unambiguous.
- Keep SHOULD guidance concise so stronger models can optimize without drifting from contract.
- Prefer additive compatibility language where a fork requirement needs it; do not preserve legacy structure without a requirement.
- Do not hard-code change names or model IDs; reference `openspec list` and capability tiers.
