# Fork Final Upstream Sweep

## Why

Only a small number of upstream behaviors remain portable after the
independence pivot recorded by `fork-independence-pivot` and ADR-0031. Two
implemented gaps exist in the fork today:

1. The legacy facilitator template (`web/templates/game_interface.html`) inserts
   authored and runtime values into HTML text, attributes, and inline event
   handlers without a shared encoding helper. Names, descriptions, tooltips,
   and save/archive values reach `innerHTML` and inline handler arguments raw
   (most `data-tooltip-*` fields only quote-escape via
   `.replace(/"/g, '&quot;')`, and `npc.name` is interpolated directly into
   `onclick` arguments).
2. The provider boundary (`utils/ai_client_factory.py` and its call sites)
   classifies retryable provider exceptions but has no shared handling for a
   completion that returns no choices, no usable message, or blank content. An
   empty completion can silently become a successful empty turn (an empty
   content string passes `.strip()` and continues) or raise an unhelpful
   `IndexError`/`AttributeError`.

The surrounding upstream implementations (upstream PR #399 merge commit
`2940c9f0`, upstream commits `3fa138f7` for #161/#162, and upstream `3e6dbb6f`
for #240) assume upstream template and provider architecture that the fork has
replaced. The fork MUST port the behavior manually as fork-native code.

## Objective

Port the security-relevant legacy UI output encoding pattern and add bounded
transient empty-provider-completion recovery using fork-native helpers, tests,
and contracts, and complete the bounded inspection of upstream #240. This
change closes the final upstream sweep approved by `plans/independent-fork.md`.

## What Changes

- Add `escapeLegacyHtml(value)` and `legacyJsonAttribute(value)` helpers to the
  legacy template and apply them to high-risk output paths: HTML text, HTML
  attributes, tooltips, and inline event-handler arguments.
- Add `utils/provider_response_recovery.py`: provider-free completion
  classification, bounded retry, and a fork-native
  `EmptyProviderResponseError`; integrate retryable classification with the
  existing `handle_provider_error` fallback policy.
- Wire the `get_ai_response` narrator primary and fallback call sites in
  `main.py` through the recovery helper without changing request parameters,
  GPT-5.6 Luna behavior, OpenRouter request shape, or SP/MP routing.
- Inspect upstream #240 against the fork's provider error/fallback state and
  port only if the same defect is reproduced.
- Add provider-free test suites
  (`scripts/test_legacy_ui_output_safety.py`,
  `scripts/test_provider_empty_response_retry.py`).
- Update the closing upstream review ledger in `plans/upstream-merge-0826.md`
  and archive it after the sweep is verified.

## Capabilities

### New Capabilities

- `legacy-ui-literal-output-safety`: authored and runtime display values are
  HTML-escaped before insertion into legacy HTML text and attribute contexts.
- `legacy-ui-handler-argument-safety`: structured inline-handler arguments are
  serialized and HTML-attribute escaped so names never execute as JavaScript.
- `provider-empty-response-recovery`: empty chat completions are classified as
  non-success, retried within a bounded limit, fall back through existing
  provider policy, and never persist an empty narration or action artifact.
- `provider-response-failure-classification`: empty transient completions are
  distinguished from refusal, content-filter, authentication, quota,
  timeout, and invalid-request failures, each retaining its existing handling.

### Modified Capabilities

- None. No existing `openspec/specs/` capability requirements are modified by
  this change.

## Non-Goals

- No upstream cherry-pick, wholesale merge, or template-diff copy.
- No Responses API migration, provider registry, typed model matrix, provider
  liveness orchestration, or headless transport adoption.
- No combat, memory, startup, installer, module-builder, or React replacement.
- No legacy template JavaScript framework rewrite or handler signature redesign.
- No rewiring of every Chat Completions call site; the change wires the
  narrator turn path and leaves other call sites for later fork changes.
- No module, saved-game, character, campaign, or runtime state modification.
- No change to `# TABLETOP MODE:` portrait slug, party strip, or character-sheet
  behavior beyond output encoding.

## Impact

- Runtime impact: additive helpers and one wired narrator provider path. Empty
  transient completions fail deterministically instead of producing blank
  content; ordinary completions are unchanged.
- SP/MP compatibility impact: both modes share the narrator path and retain
  existing routing. The legacy template remains the facilitator host at `/`.
- Request-shape impact: none. `get_chat_completion_params()` remains the sole
  parameter resolver; the recovery helper forwards resolved parameters verbatim.
- Data impact: none. No persistence, schema, module, or save migration.
- Reversibility: the UI helper/call-site group and the provider recovery helper
  are independently revertible.

## Rollout And Fallback

Ports are additive and provider-free tested. Revert the UI call-site group if a
rendering regression appears, retaining the helper tests. Revert or disable the
provider retry helper if provider timing or request shape changes appear; do not
alter model configuration as a workaround. Empty-response recovery MUST fail
closed rather than persist empty output. If any test reveals a mechanical,
publication, or state-authority regression, stop the sweep and leave the
remaining upstream work unported.
