# toolkit-gpt5-build-path-compatibility

Review-only OpenSpec scaffold for aligning Homebrew and ModuleBuilder build-time Chat Completions calls with the GPT-5.6 Luna provider contract.

## Scope

- Migrate priority build-time calls to the shared parameter helper.
- Preserve OpenRouter and non-GPT-5 behavior.
- Add provider-free request-shape tests.
- Unblock JeremysMagicShop-style uploads from avoidable provider parameter failures.

## Dependency

This change should land before `toolkit-llm-adaptation-builder` is enabled.

## Status

Planning artifacts are complete. Implementation has not started.
