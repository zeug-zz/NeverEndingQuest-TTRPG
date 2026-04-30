# Tasks

## 1. Parameter Shim Foundation

- [x] 1.1 Add GPT-5 chat-parameter profile constants or mapping in the smallest suitable central location.
- [x] 1.2 Add `GPT5_INCLUDE_LEGACY_TEMPERATURE = False` or equivalent rollback flag.
- [x] 1.3 Add a central Chat Completions parameter helper in `utils/ai_client_factory.py`.
- [x] 1.4 Ensure GPT-5-style helper output omits `temperature` and `top_p` by default.
- [x] 1.5 Ensure non-GPT-5 helper output preserves legacy task temperature behavior.

## 2. Helper Contract Tests

- [x] 2.1 Add tests for GPT-5-style model output including `reasoning_effort` and `verbosity`.
- [x] 2.2 Add tests proving GPT-5-style model output omits `temperature` and `top_p` by default.
- [x] 2.3 Add tests proving non-GPT-5 model output preserves legacy `temperature` and omits GPT-5-style fields.
- [x] 2.4 Add tests for the rollback flag behavior without making it the default.

## 3. Limited High-Value Adoption

- [x] 3.1 Adopt the helper in the main narrator/validation paths only where the patch is local and low-risk.
- [x] 3.2 Adopt the helper in combat main/validation paths only where the patch is local and low-risk.
- [x] 3.3 Adopt the helper in `core/ai/action_handler.py` local LLM helper calls where safe.
- [x] 3.4 Leave broad low-traffic direct call sites unchanged for the future router migration.

## 4. Verification and Review

- [x] 4.1 Run syntax checks for all touched Python files.
- [x] 4.2 Run the new helper contract tests.
- [x] 4.3 Run targeted narrator/combat regression tests if call-site adoption was implemented.
- [x] 4.4 Review diffs for scope creep against the v2 router plan.
- [x] 4.5 Document any call sites intentionally left unchanged.

## Guidance

- Keep each implementation step independently reviewable.
- Avoid broad regex rewrites in core runtime files.
- Do not change model constants as part of this change; the user has already performed the GPT-5.4-mini constant swap.
- Do not add provider-specific branching outside the central helper.
