# Fork Final Upstream Sweep - Tasks

## 1. Change Record And Baseline Audit

- [x] 1.1 Create `openspec/changes/fork-final-upstream-sweep/implementation_notes.md`
  capturing the upstream references and fork-adaptation boundaries:
  upstream PR #399 / merge `2940c9f0` (legacy UI encoding), upstream `3fa138f7`
  with issues #161/#162 (empty provider response), and upstream `3e6dbb6f`
  with issue #240 (completed provider error reissue). State the manual-port
  rule (no cherry-pick, no template-diff copy) and the #240 inspection
  procedure. Confirm the recorded references against
  `plans/independent-fork.md` by reading it; do not fetch upstream. Verify the
  notes file contains all three references and the manual-port statement.
- [x] 1.2 Audit `web/templates/game_interface.html` output contexts and record a
  high-risk inventory in `implementation_notes.md` with current line
  references for: (a) character-sheet inline handler interpolations
  (`openReadinessRepairModal`, `uploadPortrait`, `createPortrait`,
  `downloadPortrait`, `openCharacterEdit`, `downloadCharacterSheetPDF`);
  (b) NPC panel handler interpolations using `npc.name` and structured
  payloads; (c) save-game and archive items (`selectSaveGame`,
  `selectArchiveZip`, `data-save`); (d) tooltip/attribute sites using
  quote-only `.replace(/"/g, '&quot;')` protection; (e) other data-derived
  text insertions (NPC name, inventory/magic item names, storage items,
  save descriptions, pseudo-inventory tooltips). Verify each recorded line
  reference still matches the file with `grep -n`.

## 2. Legacy UI Output Safety Port

- [x] 2.1 Add `escapeLegacyHtml(value)` and `legacyJsonAttribute(value)`
  helpers in the `game_interface.html` script scope. `escapeLegacyHtml` MUST
  return `""` for `null`/`undefined`, stringify numbers, and escape
  `&`, `<`, `>`, `"`, `'`, and backtick. `legacyJsonAttribute` MUST return
  `escapeLegacyHtml(JSON.stringify(value))` and MUST NOT double-encode values
  already produced by the helper pair. Helpers MUST be defined before first
  use in script execution order. Verify by extracting the helper block and
  running an adversarial-value harness with `node -e` (or the test harness
  added in task 2.5).
- [x] 2.2 Replace character-sheet handler argument interpolation with
  `legacyJsonAttribute`: readiness repair, portrait upload, portrait create,
  portrait download, character edit, and PDF download call sites
  (approximately lines 7501, 7512-7514, 7707, 7711 at change creation).
  Preserve existing `normalizedName` slug values and behavior; do not change
  handler signatures. Verify with `grep -n` that no raw
  `'${normalizedName}'` interpolation remains inside those quoted handler
  attributes, and run the task 2.5 suite.
- [x] 2.3 Serialize NPC panel and save/archive handler arguments with
  `legacyJsonAttribute`: `npc.name` arguments for `showNPCSaves`,
  `showNPCSkills`, `showNPCInventory`, `showNPCDetailList`, `showNPCSpells`
  (approximately lines 7920-7947), NPC name display text (approximately line
  7875), `selectSaveGame` plus its `data-save` payload (approximately line
  9882), `selectArchiveZip` plus its `data-save` payload (approximately line
  9919), and archive display name (approximately line 9921). Remove ad-hoc
  `JSON.stringify(...).replace(/"/g, '&quot;')` expressions that the helper
  replaces. Verify with `grep -n` that raw `'${npc.name}'` handler arguments
  and ad-hoc quote replacement no longer appear at those sites, and run the
  task 2.5 suite.
- [x] 2.4 Apply `escapeLegacyHtml` to high-risk data-derived text and attribute
  insertions while keeping intentional markup assembly intact: quote-only
  tooltip/description sites (approximately lines 7120, 7269, 7593, 7639,
  7648, 7658, 7684, 7690, 7696, 7816, 7824, 7837, 8923), inventory and magic
  item name/attribute render sites (approximately lines 7121-7123, 7838),
  NPC detail list and inventory render sites (approximately lines 8924,
  8942-8943, 8973), storage item name (approximately line 10548), and save
  description values (approximately lines 9901-9904). Intentional HTML such
  as the `'<br>'` tooltip join MUST remain functional. Verify with
  `grep -n` that the enumerated sites route data-derived values through
  `escapeLegacyHtml`, and run the task 2.5 suite.
- [x] 2.5 Add `scripts/test_legacy_ui_output_safety.py`, a provider-free
  source-contract suite that MUST verify: both helpers exist in
  `web/templates/game_interface.html`; adversarial values (quotes, angle
  brackets, ampersands, backticks, event-handler-like text) are escaped while
  ordinary names stay readable (execute the helper block with `node` when
  available, using `unittest.skipUnless` otherwise); character, NPC, and
  save/archive sites use the helpers; `# TABLETOP MODE:` portrait slug and
  party-strip behavior remain present. Verify with
  `.venv/bin/python -m unittest -q scripts.test_legacy_ui_output_safety`.
- [x] 2.6 Browser smoke for adversarial display values when local browser
  tooling is available: run the `neq-playwright-smoke` skill or an equivalent
  targeted check that renders a quoted, angle-bracketed, ampersand, and
  event-handler-like display name and confirms no rendering breakage, no
  console error, and no executed handler text. Record the result or the
  skip reason in `implementation_notes.md`.

## 3. Provider Empty Response Recovery

- [x] 3.1 Audit the provider factory and common Chat Completions call
  boundaries and record the decision in `implementation_notes.md`: new
  helper module `utils/provider_response_recovery.py`; `create_chat_client()`
  remains construction-only; wired scope is the `main.py` `get_ai_response()`
  narrator primary and fallback call sites; combat, character-update, and
  other call sites intentionally keep existing behavior. Verify the notes
  list the exact wired call sites with current line references.
- [x] 3.2 Add `utils/provider_response_recovery.py` implementing:
  `EMPTY_RESPONSE_RETRY_LIMIT = 2`; `classify_chat_completion(response)`
  returning `ok` / `empty_transient` / `refusal` / `content_filter` with
  defensive attribute access; `request_chat_completion_with_recovery(...)`
  performing bounded retry of empty transient completions with identical
  messages, timeout, and resolved request parameters, returning ok and
  non-transient responses unchanged, and raising
  `EmptyProviderResponseError` with attempt count and context after
  exhaustion; bounded ASCII-only diagnostics that never log prompts, raw
  payloads, or credentials, and that fail open if logging raises. The module
  MUST NOT construct clients, MUST NOT import `config` at module import time,
  and MUST NOT mutate model configuration. Verify with
  `.venv/bin/python -m py_compile utils/provider_response_recovery.py` and
  `.venv/bin/python -c "import utils.provider_response_recovery"`.
- [x] 3.3 Classify `EmptyProviderResponseError` as retryable in
  `handle_provider_error()` without changing classification or messages for
  existing exception classes. Verify with
  `.venv/bin/python -m unittest -q scripts.test_provider_empty_response_retry`
  and the existing GPT-5 contract suites.
- [x] 3.4 Wire the `main.py` `get_ai_response()` narrator call sites through
  `request_chat_completion_with_recovery(...)`: GPT-5 branch primary and
  fallback, and non-GPT5/OpenRouter branch primary and fallback
  (approximately lines 5345, 5367, 5411, 5434 at change creation). Keep
  `get_chat_completion_params()` as the sole parameter resolver,
  `NARRATOR_API_TIMEOUT_SECONDS` unchanged, and the existing
  `handle_provider_error` fallback structure unchanged. A terminal empty
  completion MUST surface `EmptyProviderResponseError` instead of assigning
  blank content; no assistant turn may be persisted for it. Verify with
  `.venv/bin/python -m py_compile main.py` and
  `.venv/bin/python -m unittest -q scripts.test_provider_empty_response_retry`.
- [x] 3.5 Add `scripts/test_provider_empty_response_retry.py`, a provider-free
  suite using fake clients and scripted responses that MUST cover: empty
  response followed by valid response; empty response through the retry bound
  (raises `EmptyProviderResponseError`, attempt count at the bound); fallback
  after primary exhaustion (exception classifies retryable and fallback
  request uses bounded recovery); no retry for refusal or content-filter
  responses; request parameters forwarded verbatim (GPT-5.6 reasoning
  effort/verbosity and OpenRouter shape unchanged, legacy sampling omitted);
  ASCII-only exception message with no prompt or payload content; no empty
  response object returned as success. Verify with
  `.venv/bin/python -m unittest -q scripts.test_provider_empty_response_retry`.
- [x] 3.6 Inspect the fork's provider error and fallback state for the upstream
  #240 defect class (a completed provider error being reissued) using
  `utils/ai_client_factory.py` and the narrator fallback blocks in `main.py`.
  Record the outcome in `implementation_notes.md`. If the defect is
  reproduced, add the smallest fork-native fix with provider-free coverage;
  otherwise make no provider change for #240. Verify the notes state the
  outcome and the evidence inspected.

## 4. Verification And Closing Ledger

- [x] 4.1 Run the focused verification set with `.venv/bin/python`:
  `-m unittest -q scripts.test_legacy_ui_output_safety
  scripts.test_provider_empty_response_retry`, then
  `scripts/test_gpt56_luna_direct_openai_contract.py`,
  `scripts/test_gpt54_chat_params_contract.py`,
  `scripts/test_gpt54_mini_chat_params_shim.py`,
  `scripts/test_retry_de_looping.py`,
  `scripts/test_narrator_prompt_validation_refactor.py`, and
  `scripts/c5_regression_combat.py`. Confirm no regression and record the
  results in `implementation_notes.md`.
- [x] 4.2 Record the closing upstream review ledger in
  `plans/upstream-merge-0826.md` before archival: review date 2026-09-21;
  previous review point `702796eb55`; current upstream tip `44f1458e1e`;
  new review window 524 commits (2026-08-05 through 2026-09-20); final
  decisions (#399 and #161/#162 ported; #240 inspected with its outcome;
  remaining upstream work left behind); reason (incompatible architecture and
  authority boundaries); replacement policy (ADR-0031 and
  `plans/independent-fork.md`). Verify the ledger entries are present and the
  plan status says close/complete.
- [x] 4.3 Move `plans/upstream-merge-0826.md` to
  `plans/archive/upstream-merge-0826.md` only after task 4.2 ledger content
  is written and tasks 2.x and 3.x are verified. Verify the archived file
  exists and no active `plans/upstream-merge-0826.md` remains.
- [x] 4.4 Run `openspec validate fork-final-upstream-sweep --strict` and the
  repository scope checks: `.venv/bin/python scripts/check_ascii_compliance.py
  --summary-only`, `git diff --check`, `git status --short`, and confirm the
  diff contains no changes under `modules/`, `characters/`, `data/`,
  `config.py`, or runtime state, and that `git remote -v` still shows the
  upstream push URL as `DISABLE` with no upstream fetch or push executed.
