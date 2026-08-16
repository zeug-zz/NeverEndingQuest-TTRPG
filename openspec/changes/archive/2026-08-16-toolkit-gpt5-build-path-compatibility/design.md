## Context

The existing factory already resolves provider-specific Chat Completions parameters for several runtime paths. Build-time toolkit callers still construct requests directly and pass legacy sampling parameters, so GPT-5.6 Luna rejects otherwise valid normalization and generation requests.

The compatibility change must cover the build path without changing model assignments, OpenRouter request shape, or the later adaptation workflow. The existing GPT-5 runtime contract and `get_chat_completion_params` helper are the authoritative reference.

## Goals / Non-Goals

**Goals:**

- Make all priority Homebrew and ModuleBuilder calls use one provider-aware parameter boundary.
- Preserve task-specific reasoning and verbosity profiles.
- Preserve non-GPT-5 and OpenRouter behavior.
- Make request shape testable without provider calls.
- Make unsupported provider parameters fail with explicit stage diagnostics.

**Non-Goals:**

- Do not migrate every legacy runtime call site in this change.
- Do not change prompts, model IDs, temperature policy for non-GPT-5 providers, or publication semantics.
- Do not introduce a second routing factory or model configuration source.

## Decisions

### Use the existing shared parameter helper

All priority callers MUST use `get_chat_completion_params` rather than branching on model names locally. This keeps GPT-5 handling, OpenRouter handling, and future model-family changes in one place.

Alternative rejected: adding `if model.startswith("gpt-5")` logic to every generator. That would duplicate provider policy and make future model swaps unsafe.

### Preserve creative overrides through the helper

Existing temperature intent will be passed as a helper override. The helper will omit unsupported legacy sampling fields for direct GPT-5 requests while retaining the configured value for compatible providers.

Alternative rejected: deleting all temperature values. That would silently change OpenRouter and legacy model behavior.

### Use task IDs as the profile boundary

Each call site will retain its existing task classification or adopt the nearest existing task family. Builder calls will use builder profiles, validation calls will use validation profiles, and Markdown enrichment will use the summary profile.

Alternative rejected: one global reasoning profile for every build call, which would either waste tokens on extraction or reduce creative generation quality.

### Test final request kwargs

Provider-free tests will capture `client.chat.completions.create` kwargs and assert GPT-5 requests omit `temperature` and `top_p` while including the expected reasoning parameters.

Alternative rejected: source-only tests that assert helper imports but never inspect the actual request payload.

### Keep provider errors stage-local

A request-shape error will be recorded as a provider compatibility failure at the current stage. It will not be converted into a successful placeholder artifact and will not consume adaptation semantic-revision budget.

## Risks / Trade-offs

- [Risk] A missed direct call site can still fail later in the build. Mitigation: maintain a priority inventory and add source-contract coverage for every in-scope call site.
- [Risk] Helper migration changes request payload shape for a compatible provider. Mitigation: preserve existing overrides and add an OpenRouter regression assertion.
- [Risk] GPT-5 reasoning increases latency or cost. Mitigation: use task-specific low profiles for extraction/validation and bounded timeouts.
- [Risk] A provider outage is mistaken for a source failure. Mitigation: emit explicit provider-stage status and keep source/adaptation diagnostics separate.

## Migration Plan

1. Inventory priority build-time calls and assign task profiles.
2. Migrate normalizer and ModuleBuilder generator calls.
3. Migrate Homebrewery and toolkit auxiliary calls.
4. Add request-shape and provider-branch tests.
5. Run the focused provider-free suites.
6. Run one bounded GPT-5.6 Luna smoke on a small build call.
7. Enable the later adaptation change only after this contract is green.

Rollback consists of disabling the new call-site routing through the feature branch or reverting the compatibility commit. Existing source and module artifacts remain untouched.

## Observability

Each migrated call should retain existing task, model, provider, and stage metadata. Provider errors must include the stage and model family without logging credentials or full source payloads.
