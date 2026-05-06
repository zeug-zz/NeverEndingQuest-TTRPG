## Why

The repository now uses GPT 5.4 Mini through a compatibility shim for OpenAI chat completions. The shim introduces GPT-5-family parameters such as `reasoning_effort` and `verbosity` while suppressing unsupported legacy parameters such as `temperature` by default. Recent gametesting suggests GPT 5.4 Mini is sensitive to contradictory prompt context and retry behavior.

The runtime has many chat completion call sites across narrator, validation, combat, transition, summary, and toolkit code. Some paths use `get_chat_completion_params()`, while older or specialized branches may still pass direct model/temperature parameters or may miss timeout/retry-tier behavior. The prompt corpus also contains compressed/uncompressed pairs that can drift over time.

This change creates an audit-and-hardening pass to make GPT 5.4 Mini runtime behavior testable and to reduce prompt/runtime contradiction after narrator and combat stabilization.

## What Changes

- **GPT-5-family parameter contract tests**: Verify the shim sends supported parameters and omits unsupported defaults.
- **Callsite inventory and normalization**: Audit narrator and combat call paths for `get_chat_completion_params()`, timeout, retry tier, usage tracking, and fallback behavior.
- **Retry reasoning audit**: Ensure validation retry paths that need stronger reasoning use high retry tier or a documented equivalent.
- **Prompt parity sweep**: Align compressed/uncompressed narrator and combat prompts on state authority, same-module movement, follower state, combat phase authority, `[ALREADY_APPLIED]`, request-roll pause semantics, and combat exit rules.
- **Runtime prompt contradiction tests**: Add source-contract tests that fail when prompt text or injected context reintroduces known contradictions.

## Capabilities

### New Capabilities

- `tt-gpt54-chat-params-contract`: GPT 5.4 Mini chat completion parameter behavior is source-tested and consistent.
- `tt-prompt-runtime-parity-audit`: Compressed/uncompressed prompts and runtime-injected context are checked for narrator/combat authority parity.

### Modified Capabilities

- `tt-runtime-prompt-authority`: GPT-5-family call paths use consistent parameter construction and timeout handling.
- `tt-validation-retry-hygiene`: Retry paths document and test reasoning-tier escalation where applicable.
- `tt-combat-runtime-prompt-authority`: Combat prompt context is audited for GPT 5.4 Mini contradiction sensitivity.

## Non-Goals

- Do not implement the full OpenRouter LLM router.
- Do not change model provider selection policy except where a callsite bypasses the existing factory/shim contract.
- Do not rewrite all prompts from scratch.
- Do not add provider calls to tests.
- Do not weaken deterministic Python authority to accommodate model behavior.

## Impact

- **Affected code**: `utils/ai_client_factory.py`, `model_config.py`, `main.py`, `core/managers/combat_manager.py`, prompt files, and source-contract tests.
- **Provider behavior**: GPT-5-family requests should consistently use supported params, timeout protection, and retry-tier behavior.
- **Backward compatible**: GPT-4.1 and non-GPT-5-family paths should keep existing supported parameter behavior.
- **SP/MP compatibility**: Runtime callsite cleanup applies across modes; prompt parity focus is tabletop narrator and combat paths.
- **Rollout risk**: Low-medium. Most work is tests and audit cleanup. Risk increases if callsite parameter construction changes are broad.

## Fallback Strategy

If a GPT-5-family parameter breaks a provider path, centralize the rollback in `utils/ai_client_factory.py` rather than patching individual call sites. If prompt parity edits create behavior regressions, keep runtime source-contract tests and roll back only the problematic wording block.
