## Why

The GPT-5.6 Luna runtime contract is already implemented for several narrator and combat paths, but Homebrew normalization, ModuleBuilder generators, and Markdown generation still pass legacy sampling parameters directly. A readable source such as JeremysMagicShop therefore fails before module construction with an avoidable HTTP 400 error.

## What Changes

- Route all priority toolkit and ModuleBuilder Chat Completions calls through `get_chat_completion_params`.
- Omit unsupported `temperature` and `top_p` parameters for GPT-5-family direct-OpenAI calls.
- Preserve existing creative sampling behavior for OpenRouter and non-GPT-5 models.
- Apply the correct reasoning and verbosity profile for builder, validation, summary, and auxiliary tasks.
- Add provider-free request-shape tests for the normalizer, generators, auxiliary toolkit calls, and Homebrewery writer.
- Keep provider failures, quota failures, and unsupported-parameter failures explicit and fail closed at the calling stage.

## Non-Goals

- No change to model assignments or OpenRouter model identifiers.
- No change to prompts, source-fidelity policy, ModuleBuilder behavior, or publication gates beyond request compatibility.
- No broad migration of unrelated runtime compression and memory call sites in this change.
- No automatic provider fallback for a non-retryable request-shape error unless the existing provider policy explicitly permits it.

## Capabilities

### New Capabilities

- `gpt5-builder-chat-params-contract`: Defines the request parameter contract for GPT-5-family build-time calls.
- `toolkit-homebrew-provider-compatibility`: Ensures Homebrew normalization and publication-adjacent LLM calls remain compatible with the configured provider and model family.

### Modified Capabilities

- None. Existing GPT-5 runtime requirements remain authoritative; this change adds build-path coverage for the same contract.

## Impact

- `utils/toolkit_homebrew_normalizer.py`.
- `core/generators/module_builder.py`.
- `core/generators/module_generator.py`.
- `core/generators/area_generator.py`.
- Location, plot, NPC, and monster generator call sites.
- `utils/homebrewery_adventure_writer.py`.
- Toolkit classification and spatial calls.
- GPT-5 compatibility and Homebrew normalization regression suites.
- No schema or runtime save-data changes.

## Rollout And Fallback

- Land the compatibility sweep before enabling the LLM adaptation builder.
- Keep the existing model/profile factory as the single parameter authority.
- Preserve the legacy accurate-ingest route while request compatibility is verified.
- If a provider rejects a request, persist the provider error and stop that stage without writing a false success artifact.
- Roll back by restoring the prior call-site parameter construction while retaining the provider-free contract tests.

## Merge Safety

- Prefer helper usage in existing call sites over generator rewrites.
- Mark required host-file changes with `# TABLETOP MODE:` where applicable.
- Preserve single-player behavior and OpenRouter request shape.
- Do not alter mechanical state or campaign runtime files.
