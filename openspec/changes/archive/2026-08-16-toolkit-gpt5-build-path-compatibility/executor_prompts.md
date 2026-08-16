# Executor Prompts

## Implementation Boundary

Implement only the GPT-5 build-path compatibility contract. Do not implement the adaptation builder in this change.

## Required Reading

- `proposal.md`
- `design.md`
- `specs/gpt5-builder-chat-params-contract/spec.md`
- `specs/toolkit-homebrew-provider-compatibility/spec.md`
- `tasks.md`
- `openspec/specs/gpt56-luna-direct-openai-runtime/spec.md`
- `utils/ai_client_factory.py`

## Execution Rules

- Use `get_chat_completion_params` as the only provider-parameter boundary.
- Preserve OpenRouter model IDs and request fields.
- Keep legacy accurate-ingest behavior available.
- Use `.venv/bin/python` for tests and runtime-sensitive verification.
- Use ASCII-only Python user-facing text.
- Do not commit or push as part of task execution.

## Verification Output

For each task, report changed files, request-shape evidence, focused test results, and any call sites intentionally deferred to a later compatibility sweep.
