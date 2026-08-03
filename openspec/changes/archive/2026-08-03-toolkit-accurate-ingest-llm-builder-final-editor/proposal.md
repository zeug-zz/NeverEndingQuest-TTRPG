# Proposal: LLM Builder Final Editorial Reconciliation

## Why

Accurate-ingest now preserves source material through source graph extraction, normalized packets, blueprint handoff, backstage audit evidence, source-enhanced ModuleBuilder generation, and provider-free final blocker classification. The remaining gap is the final editorial step after `final_reconciliation_required` is reached.

The Well of Ruin failure demonstrates the product problem. Source analysis classified markdown/mechanics headings such as `Trigger`, `Passive Element`, and `Active Element` as required locations. ModuleBuilder correctly did not create rooms with those names, so build fidelity reported missing required locations. The archived boundary change now classifies those blockers as editorial and writes a `final_reconciliation_brief.json`, but no live LLM Builder final editor exists to consume that brief, resolve bogus source atoms, and produce a playable module.

There is also a small safety bug observed during this flow: a malformed write/lock path can include serialized JSON payload text, causing `[Errno 63] File name too long`. This must be fixed before the final editor depends on reconciliation artifact writes.

## What Changes

Implement a bounded LLM Builder final editorial reconciliation pass that consumes `final_reconciliation_brief.json`, emits a strict patch plan, applies only safe canonical JSON changes, reruns deterministic validation/publication gates, and persists an honest `final_reconciliation_report.json` with `source_fidelity_effective_status: reconciled_degraded` when accepted.

## Non-Goals

- MUST NOT change source graph extraction, source manifest generation, normalized packet generation, blueprint generation, backstage audit briefing, or source-enhanced ModuleBuilder handoff.
- MUST NOT mutate original source artifacts to hide source-fidelity issues.
- MUST NOT claim clean source fidelity when reconciliation accepted degraded source fidelity.
- MUST NOT bypass schema, readiness, publishability, or report-agreement gates.
- MUST NOT edit runtime-only files as canonical final output.

## Scope

This change adds final-editor behavior after the provider-free boundary has classified blockers and persisted a brief. It also fixes the reconciliation artifact path/lock safety bug if still present.

Contract Layer (MUST):

- The final editor SHALL run only when reconciliation is required for editorial-only blockers and no fatal blockers are present.
- The final editor SHALL fail closed on provider failure, invalid output JSON, forbidden targets, malformed patch shapes, validation failure after retry budget, or attempts to report false clean source fidelity.
- Applied patches SHALL target only whitelisted canonical module artifacts.
- Final reporting SHALL preserve original source-fidelity status and expose reconciled/degraded effective status separately.

Guidance Layer (SHOULD):

- Use existing chat-client/model-routing patterns.
- Implement final-editor logic in a new helper module rather than embedding patch validation in routes.
- Support injected/mock provider output so tests remain provider-free.
- Prefer minimal JSON whole-file or path-scoped edits that remove bogus source atoms from final structure without rewriting unrelated module content.

## Risks And Mitigations

- Risk: LLM patch output edits unsafe files. Mitigation: whitelist target files and reject forbidden targets before writes.
- Risk: LLM output hides source degradation. Mitigation: normalize or reject any patch/report claiming source fidelity pass unless source fidelity truly passed.
- Risk: LLM output creates invalid JSON. Mitigation: strict JSON parser, patch contract tests, atomic writes, and post-write validation.
- Risk: Provider outage blocks builds. Mitigation: fail closed with clear diagnostics when reconciliation is required; no silent acceptance.
- Risk: Over-broad final editor rewrites module structure. Mitigation: bounded decisions and one retry only.

## Rollback

Disable final-editor invocation and keep the existing `final_reconciliation_required` terminal state from the archived boundary. Existing brief/report artifacts remain additive and compatible.
