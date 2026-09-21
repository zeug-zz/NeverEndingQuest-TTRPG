# Fork Final Upstream Sweep - Implementation Notes

Status: Initial reference record. Later tasks append audit inventories and outcomes here.

## Upstream References

- PR #399 / merge `2940c9f0`: legacy UI output encoding for text, attributes, and inline handler values.
- `3fa138f7` with issues #161/#162: transient empty provider response recovery.
- `3e6dbb6f` with issue #240: completed provider-error reissue behavior.

These references were confirmed against `plans/independent-fork.md`. No upstream fetch is
performed for this change.

## Fork Adaptation Boundary

The fork adapts the safety behavior manually as fork-native code. Do not cherry-pick
upstream commits and do not copy the upstream template diff wholesale. Preserve the
fork's existing authority, routing, slug, and compatibility contracts.

## Bounded #240 Inspection Procedure

Review `utils/ai_client_factory.py` provider error and fallback state, then review the
narrator fallback blocks in `main.py`. Record whether a completed provider error can be
reissued by the fork's current control flow. Port only if the defect is reproduced in
 fork code, using the smallest fork-native fix and provider-free coverage. Record the
 inspection outcome here; the inspection result is pending the later #240 task.

## Audit Inventory

Audit target: `web/templates/game_interface.html`. The file currently contains
64 `innerHTML` occurrences (`grep -c "innerHTML"`). The inventory below is the
enumerated high-risk set for the later safety-port tasks, not a complete list of
all HTML construction sites. Line numbers were confirmed with the required
`grep -n` checks after this inventory was written.

### (a) Character-sheet inline handler interpolations

Count: 6 handler contexts. These arguments need `legacyJsonAttribute`, not
`escapeLegacyHtml` alone. The existing `normalizedName` values are embedded
directly in quoted inline handlers.

- Line 7501: `onclick="openReadinessRepairModal('${normalizedName}')"` - readiness repair character name.
- Line 7512: `onclick="uploadPortrait('${normalizedName}')"` - portrait upload character name.
- Line 7513: `onclick="createPortrait('${normalizedName}')"` - portrait create character name.
- Line 7514: `onclick="downloadPortrait('${normalizedName}')"` - portrait download character name.
- Line 7707: `onclick="openCharacterEdit('${normalizedName}')"` - character edit name.
- Line 7711: `onclick="downloadCharacterSheetPDF(event, '${normalizedName}')"` - PDF download name.

### (b) NPC panel handler interpolations

Count: 7 handler contexts. Every `npc.name` argument and every structured JSON
payload needs `legacyJsonAttribute`. The structured values are currently
protected only by quote replacement after `JSON.stringify`, and the name is a
raw single-quoted handler argument.

- Line 7920: `showNPCSaves('${npc.name}', ${JSON.stringify(savesData).replace(...)})` - name and saves payload.
- Line 7924: `showNPCSkills('${npc.name}', ${JSON.stringify(skillsData).replace(...)})` - name and skills payload.
- Line 7928: `showNPCInventory('${npc.name}', ${JSON.stringify(npc.equipment).replace(...)})` - name and inventory payload.
- Line 7933: `showNPCDetailList('${npc.name}', 'Key Abilities', ${JSON.stringify(featuresData).replace(...)})` - name and features payload.
- Line 7938: `showNPCDetailList('${npc.name}', 'Racial Traits', ${JSON.stringify(traitsData).replace(...)})` - name and traits payload.
- Line 7943: `showNPCDetailList('${npc.name}', 'Background', ${JSON.stringify(backgroundData).replace(...)})` - name and background payload.
- Line 7947: `showNPCSpells('${npc.name}', ${JSON.stringify(npc.spellcasting).replace(...)})` - name and spellcasting payload.

The NPC header at line 7875 also inserts `npc.name` as display text; it is
covered as a text insertion in subsection (e), not as a handler argument.

### (c) Save-game and archive items

Count: 4 high-risk contexts across 2 save rows. Handler arguments need
`legacyJsonAttribute`; the `data-save` attribute payloads also need serialized
attribute handling rather than quote-only replacement.

- Line 9882: `selectSaveGame('${save.save_folder}', this)` - save folder handler argument.
- Line 9882: `data-save="${JSON.stringify(save).replace(...)}` - save object attribute payload.
- Line 9919: `selectArchiveZip('${archive.zip_name}', this)` - archive zip handler argument.
- Line 9919: `data-save="${JSON.stringify(archiveData).replace(...)}` - archive object attribute payload.

Save display description is separately a text insertion at line 9904 and is
covered in subsection (e).

### (d) Tooltip and attribute sites with quote-only protection

Count: 23 quote-only high-risk sites, plus 3 complete escaping-helper
occurrences in the grep total of 26. The 23 sites below use only
`.replace(/"/g, '&quot;')` and therefore need `escapeLegacyHtml` for text and
attribute values, or `legacyJsonAttribute` when the value is a handler
argument.

- Line 7120: `item.description ... .replace(/"/g, '&quot;')` - inventory tooltip description.
- Line 7542: `JSON.stringify(data).replace(/"/g, '&quot;')` - character data attribute payload.
- Line 7543: `JSON.stringify(proficientSkills).replace(/"/g, '&quot;')` - skills attribute payload.
- Line 7593: `weapon.description ... .replace(/"/g, '&quot;')` - weapon tooltip description.
- Line 7639: `feature.description ... .replace(/"/g, '&quot;')` - feature tooltip description.
- Line 7648: `effect.description ... .replace(/"/g, '&quot;')` - effect tooltip description.
- Line 7658: `trait.description ... .replace(/"/g, '&quot;')` - trait tooltip description.
- Line 7684: `tooltipParts.join('<br>').replace(/"/g, '&quot;')` - composed tooltip attribute; escape each data part, preserve the intentional `<br>` join.
- Line 7690: `data.backgroundFeature.description ... .replace(/"/g, '&quot;')` - background tooltip description.
- Line 7696: `feat.description ... .replace(/"/g, '&quot;')` - feat tooltip description.
- Line 7816: `s.description ... .replace(/"/g, '&quot;')` - scroll tooltip description.
- Line 7824: `p.description ... .replace(/"/g, '&quot;')` - potion tooltip description.
- Line 7837: `item.description ... .replace(/"/g, '&quot;')` - magic item tooltip description.
- Line 7920: `JSON.stringify(savesData).replace(/"/g, '&quot;')` - NPC saves handler payload.
- Line 7924: `JSON.stringify(skillsData).replace(/"/g, '&quot;')` - NPC skills handler payload.
- Line 7928: `JSON.stringify(npc.equipment).replace(/"/g, '&quot;')` - NPC inventory handler payload.
- Line 7933: `JSON.stringify(featuresData).replace(/"/g, '&quot;')` - NPC features handler payload.
- Line 7938: `JSON.stringify(traitsData).replace(/"/g, '&quot;')` - NPC traits handler payload.
- Line 7943: `JSON.stringify(backgroundData).replace(/"/g, '&quot;')` - NPC background handler payload.
- Line 7947: `JSON.stringify(npc.spellcasting).replace(/"/g, '&quot;')` - NPC spells handler payload.
- Line 8923: `item.detail.replace(/"/g, '&quot;')` - pseudo-inventory tooltip title attribute.
- Line 9882: `JSON.stringify(save).replace(/"/g, '&quot;')` - save `data-save` attribute payload.
- Line 9919: `JSON.stringify(archiveData).replace(/"/g, '&quot;')` - archive `data-save` attribute payload.

The remaining grep matches are complete escaping helpers and are not quote-only
protection sites: line 5470 in `escapeMessageHtml`, line 7269 in
`escapeRepairHtml`, and line 10158 in `journalEscapeHtml`. Intentional HTML
fragments such as the `<br>` join at line 7684 and the surrounding `html`
builders must remain markup; only their data-derived components should be
escaped before joining or insertion.

### (e) Other data-derived text insertions

Count: 26 insertion lines. These are text and attribute display contexts and
need `escapeLegacyHtml`; they are not handler arguments unless separately
listed above.

- Line 7121: `${item.item_name}` and quantity in inventory item text.
- Line 7595: `${weapon.name}` in weapon tooltip title and visible name.
- Line 7608: `${ammo.name}` and `${ammo.quantity}` in ammunition text.
- Line 7640: `${feature.name}` and refresh text in feature markup.
- Line 7649: `${effect.name}` and duration text in effect markup.
- Line 7659: `${trait.name}` in trait markup.
- Line 7685: `${label}` in pseudo-inventory tooltip text.
- Line 7691: `${data.backgroundFeature.name}` in background tooltip title and visible name.
- Line 7697: `${feat.name}` in feat markup.
- Line 7817: `${s.item_name}` and spell item metadata in magic-item text.
- Line 7825: `${p.item_name}` and potion metadata in magic-item text.
- Line 7838: `${item.item_name}` and charge metadata in magic-item text.
- Line 7875: `${npc.name}`, `${npc.race}`, `${npc.class}`, `${npc.level}`, and `${npc.alignment}` in the NPC panel header.
- Line 8942: `${item.item_name}`, `${item.quantity}`, and `${item.item_type}` in NPC inventory modal text.
- Line 8943: `${item.description}` in NPC inventory modal text.
- Line 9904: `${save.description}` in save detail text.
- Line 10031: `${content}` in spell tooltip content.
- Line 10051: `${spellInfo.description}` in spell tooltip content.
- Line 10480: `${point.title}` in quest title text.
- Line 10481: `${point.description}` in quest description text.
- Line 10490: `${sq.title}` in side-quest title text.
- Line 10491: `${sq.description}` in side-quest description text.
- Line 10540: `${container.name}` in storage container text.
- Line 10541: `${container.location}` in storage location text.
- Line 10548: `${item.item_name}` in storage item text.
- Line 10549: `${item.quantity}` in storage quantity text.

Intentional static markup and status labels in the same template strings must
remain functional and must not be escaped as a whole HTML fragment.

## Browser Smoke (Task 2.6)

Scope: adversarial display values for the legacy UI output safety port
(`web/templates/game_interface.html`): optional browser screenshot plus the
deterministic markup check.

### Server startup and shutdown

- Preflight found a stale listener on port 8357 (PID 47959) left by a prior
  interrupted attempt of this task (`tmp/task-2-6-server.pid` matched the PID).
  It was terminated first with `kill -TERM 47959`, then the port was re-checked
  and confirmed free.
- Fresh start (project root):
  `NEQ_OPEN_BROWSER=0 PYTHONPATH=. .venv/bin/python web/web_interface.py > tmp/task-2-6-server.log 2>&1 &`
  (PID captured to `tmp/task-2-6-server.pid`).
- Result: `HTTP 200 after 37.2s` from a bounded `urllib` poll; the server log
  showed `Serving Flask app 'web_interface'` and `Debug mode: off` with no
  startup errors.
- The served page contains the new helpers and the new NPC handler shape
  (`function escapeLegacyHtml`, `function legacyJsonAttribute`,
  `legacyJsonAttribute(npc.name)`), so the smoke target renders post-port code.
- Shutdown: `kill -TERM` using the pid file. Port 8357 was re-checked with
  `lsof -t -nP -iTCP:8357 -sTCP:LISTEN` and is released. No leftover
  `chrome-headless-shell` processes and no task-2-6 scratch files remain.

### Browser screenshot

Result: SKIPPED - Chromium cannot start under the active nono sandbox.

- `playwright screenshot --wait-for-timeout=3000 --browser chromium http://localhost:8357 tmp/task-2-6-ui.png`
  failed: the Chromium `chrome-headless-shell` process crashed during launch
  with `Received signal 11 SEGV_ACCERR` (SIGSEGV).
- `playwright screenshot --wait-for-timeout=3000 --browser chromium --channel chromium ...`
  (full Chromium build) failed with the same launch-time SIGSEGV.
- Direct minimal launch:
  `~/Library/Caches/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-mac-arm64/chrome-headless-shell --no-sandbox --disable-gpu --dump-dom http://localhost:8357`
  exited 139 (SIGSEGV) with zero DOM bytes. The same binary answers `--version`
  normally (`Google Chrome for Testing 145.0.7632.6`), so the failure is browser
  startup inside the sandbox, not a missing or corrupt browser install.
- Browsers are already installed (`chromium-1208`, `chromium-1223`, and matching
  headless shells under `~/Library/Caches/ms-playwright`), so
  `npx playwright install chromium` was not attempted: reinstalling cannot fix a
  runtime SIGSEGV. No screenshot artifact was produced, and no console-error
  capture was possible for this run.

### Adversarial markup check (deterministic, browser-independent)

Command: `.venv/bin/python tmp/task-2-6-markup-check.py` (temporary scratch
script, removed after the run). Result: PASS - 0 failures, 0 skipped.

Adversarial values used:
- `O'Neil & <img src=x onerror=alert(1)>`
- `Ma's "Ghost"` with a backtick on each side of the x
- `x" onmouseover="alert(1)` (attribute-breakout attempt)

The check verified the template helper source contract (`escapeLegacyHtml`
escape chain and `legacyJsonAttribute` delegation), executed the real helper
source extracted from the template with `node`, and confirmed the real JS output
matches the Python mirror for every adversarial value. It then reproduced the
current interpolation shapes for `openCharacterEdit(name)`,
`downloadCharacterSheetPDF(event, name)`, `showNPCSaves(name, payload)`, and
`selectSaveGame(name, this)` plus its `data-save` payload, and parsed each
rendered fragment with `html.parser.HTMLParser`. Confirmed per fragment: raw
attribute text is the expected entity-encoded string; HTML-decoding recovers the
logical value; the parsed attribute set is exactly the designed set with no
extra event-handler attribute created; `json.loads` of the decoded argument
returns the original adversarial value; no unescaped quote breakout and no raw
`<img` / `<script` markup; event-handler-like text remains inert data inside the
quoted attribute. The live served-page check passed as well.

Outcome: task 2.6 markup verification passed; the browser screenshot is a
recorded skip for the environmental sandbox reason above.

## Provider Boundary Audit (Task 3.1)

Scope: the provider factory (`utils/ai_client_factory.py`) and the common Chat
Completions call boundaries in `main.py`. This task records the design decision
only; no code was modified.

### Decision

- New fork-native module `utils/provider_response_recovery.py` owns
  empty-completion classification and bounded retry. Neither concern is added to
  `utils/ai_client_factory.py`.
- `create_chat_client()` remains client construction only. It continues to
  select the provider, apply transport log safety, and return a client; it MUST
  NOT issue requests, classify responses, or retry.
- Wired scope: the `main.py` `get_ai_response()` narrator call sites only, in
  both branches:
  - GPT-5 branch (the `if USE_GPT5_MODELS:` block) primary and fallback requests.
  - non-GPT5/OpenRouter branch (the `else:` block) primary and fallback requests.
- `core/managers/combat_manager.py`, `updates/update_character_info.py`, and all
  other Chat Completions call sites intentionally keep existing behavior in this
  change. They are candidates for a later fork change and are not rewired here.

### Wired Call Sites (verified with `grep -n`)

`get_ai_response` spans `main.py` lines 5065-5526 (next top-level `def` is
`ensure_main_system_prompt` at 5527). Its local provider imports at lines
5086-5091 already bring in `handle_provider_error`,
`get_fallback_notification`, and `create_chat_client`. All four wired sites are
inside this function.

1. GPT-5 branch primary request - line 5345:
   `response = client.chat.completions.create(messages=messages_to_send, timeout=NARRATOR_API_TIMEOUT_SECONDS, **get_chat_completion_params("dm_main", selected_model))`
2. GPT-5 branch fallback request - line 5367:
   `response = fallback_client.chat.completions.create(messages=messages_to_send, timeout=NARRATOR_API_TIMEOUT_SECONDS, **get_chat_completion_params("dm_main", GPT5_MINI_MODEL))`
3. non-GPT5/OpenRouter branch primary request - line 5411:
   `response = client.chat.completions.create(messages=messages_to_send, timeout=NARRATOR_API_TIMEOUT_SECONDS, **get_chat_completion_params("dm_main", actual_model, temperature_override=TEMPERATURE))`
4. non-GPT5/OpenRouter branch fallback request - line 5434:
   `response = fallback_client.chat.completions.create(messages=messages_to_send, timeout=NARRATOR_API_TIMEOUT_SECONDS, **get_chat_completion_params("dm_main", selected_model, temperature_override=TEMPERATURE))`

Evidence: `grep -n "client.chat.completions.create\|fallback_client.chat.completions.create" main.py`
returns lines 432, 539, 2938, 3653, 3674, 5345, 5367, 5411, 5434. The four
wired sites are 5345, 5367, 5411, 5434; the other five matches are the
out-of-scope sites listed below.

Wiring contract for the later task 3.4: `get_chat_completion_params()` remains
the sole parameter resolver, `NARRATOR_API_TIMEOUT_SECONDS` is unchanged, and the
existing `handle_provider_error` fallback structure (post-error
`create_chat_client(use_fallback=True)`, same messages, same timeout) is
unchanged. Only the request-execution call is routed through the helper.

### Existing Provider Exception Classification (to preserve)

`handle_provider_error()` (`utils/ai_client_factory.py` line 240) classifies a
provider exception by lowercased substring match of `str(error)`:

- Retryable (`should_fallback=True`): rate limit, timeout, connection, 503, 502,
  504, overloaded, unavailable, internal server error, 429. Source list:
  `utils/ai_client_factory.py` lines 257-260.
- Non-retryable (`should_fallback=False`): everything not matching that list,
  including auth, quota, and invalid-request errors. The narrator call sites
  then re-raise through their existing `else: raise` branch.
- Fallback bookkeeping: the first retryable error sets
  `_fallback_status['has_triggered']`, increments `fallback_count`, and produces
  the user-facing fallback message; later retryable errors still return
  `should_fallback=True` but do not duplicate the notification (lines 272-290).
  `get_fallback_notification()` supplies the system message appended after a
  successful fallback request (lines 308-325).

The classification list and messages for existing exception classes MUST NOT
change. `handle_provider_error()` must not gain request execution behavior.

### Planned Task 3.3 Note (plan only; no code changed in 3.1)

Task 3.3 will classify `EmptyProviderResponseError` (defined in
`utils/provider_response_recovery.py`) as retryable inside
`handle_provider_error()` so the existing narrator fallback blocks trigger
exactly as they do for retryable provider exceptions. This entry is recorded as
a plan only: `utils/ai_client_factory.py` and `main.py` are untouched by this
audit task.

### Observed Out-Of-Scope Call Sites (not rewired)

Recorded for audit completeness; all keep existing behavior:

- `main.py` line 432, `generate_arrival_narration()`: primary request.
- `main.py` line 539, `generate_seamless_transition_narration()`: primary
  request. Both transition helpers are dormant in active runtime flow per
  AGENTS.md and are not part of this change.
- `main.py` line 2938, `validate_ai_response()`: validation request.
- `main.py` lines 3653 and 3674, `generate_module_summary()`: summary primary
  and fallback requests.
- `core/managers/combat_manager.py`: 9 lines match
  `chat.completions.create`.
- `updates/update_character_info.py`: 1 line matches
  `chat.completions.create`.

Repo-wide first-party matches of `chat.completions.create` (excluding `.venv`):
177 lines. `create_chat_client()` itself is unchanged and remains provider
selection plus client construction only.

## Upstream #240 Inspection (Task 3.6)

Outcome: DEFECT NOT REPRODUCED. The fork does not reissue a completed provider
error. No provider code was changed for #240; `main.py`,
`utils/ai_client_factory.py`, and `utils/provider_response_recovery.py` are
untouched by this task. This records the spec scenario "Defect not reproduced"
in `specs/provider-response-failure-classification/spec.md`.

Defect class checked (per the bounded procedure above and upstream reference
`3e6dbb6f` / issue #240): a provider error that has already been fully handled
is reissued (re-processed as a new error), causing duplicate handling such as a
repeated fallback attempt, duplicated fallback notification, duplicated
bookkeeping increment, or a loop back into the same error path.

### Evidence 1 - `handle_provider_error` is idempotent

`utils/ai_client_factory.py:241-298`:

- Classification (lines 254-268) is a deterministic lowercased substring match
  plus the `EmptyProviderResponseError` isinstance check; repeated calls with
  the same error class return the same `should_fallback`.
- Bookkeeping is gated by `should_fallback and not
  _fallback_status['has_triggered']` (line 278), so `fallback_count`
  increments once, `last_error` is written once, and `fallback_message` is
  populated only on the first retryable failure. Later retryable calls return
  `should_fallback=True` with `fallback_message=None`.
- Terminal (non-retryable) errors return `should_fallback=False` and never
  touch bookkeeping.
- Provider-free simulation (inline `python`; OpenAI client symbol stubbed, real
  factory path; no network): three consecutive retryable errors (503, 503,
  429) returned `should_fallback=True` each time, `fallback_count` stayed 1,
  and `fallback_message` was `None` on calls 2 and 3. `invalid api key`
  returned `should_fallback=False` with no increment.

### Evidence 2 - narrator fallback flow is single-pass and cannot re-enter

AST inspection of `main.py:get_ai_response` (spans 5065-5522):

- GPT-5 branch `try` (5347-5382): the body contains only the primary
  `request_chat_completion_with_recovery(...)` at 5348. The handler body
  (5355-5382) contains `handle_provider_error` (5357), the fallback request
  (5369), and `get_fallback_notification` (5378).
- Other branch `try` (5411-5447): primary at 5412 in the body; handler body
  (5419-5447) contains `handle_provider_error` (5421), fallback request
  (5433), and notification read (5443).
- A fallback failure is raised inside the `except` handler, so it propagates
  out of the handler instead of being caught and re-classified by the same
  `try`. The only enclosing node for both provider blocks is `If:5334`; no
  loop or outer `try` wraps them inside the function.
- The function contains exactly 4 `request_chat_completion_with_recovery`
  calls (2 primary, 2 fallback, one per branch), so the fallback runs at most
  once per narrator call. Exactly 2 `handle_provider_error` calls exist, one
  per branch handler; no other handler in the function re-invokes it.

### Evidence 3 - the recovery helper never catches or reissues errors

`utils/provider_response_recovery.py:210-277`: AST reports 0 `Try` nodes in
`request_chat_completion_with_recovery`. The bounded `while` loop retries only
`CLASS_EMPTY_TRANSIENT`; provider exceptions from
`client.chat.completions.create` (line 250) propagate unchanged, and empty
exhaustion raises `EmptyProviderResponseError` (line 272) without re-entry.

### Evidence 4 - empty-response integration is the same single pass

`EmptyProviderResponseError` is classified retryable by the factory isinstance
check (`utils/ai_client_factory.py:263-268`); the narrator handler then runs
exactly one fallback request. If the fallback also exhausts the empty bound,
that raise propagates terminally with no re-entry. Simulation: repeated
`EmptyProviderResponseError` handling gave `should_fallback=True` both times,
`fallback_count` 1, and `fallback_message=None` on the second call.

### Evidence 5 - fallback state leaves no reissuing state

- `get_fallback_notification` (`utils/ai_client_factory.py:314-331`) is a
  read-only projection: repeated calls returned the identical string and
  mutated nothing (verified).
- `_fallback_status` stores only booleans/strings/count; `last_error` is
  stored and never re-raised or re-processed. `reset_fallback_status`
  (lines 301-311) restores the clean initial state (verified).
- Caller path: the narrator retry loop (`main.py:8213-8220`) has no `try`
  covering the `get_ai_response(...)` call (AST-verified), so a terminal
  fallback failure propagates instead of looping back into provider handling.
  Repo-wide, `handle_provider_error` is only called at `main.py:3669`
  (module summary, out of the narrator scope recorded in task 3.1),
  `main.py:5357`/`5421` (the two narrator handlers), and
  `updates/update_character_info.py:3150` (out of bounded scope).

### Commands used

- `grep -n "handle_provider_error|get_fallback_notification|reset_fallback_status" main.py utils/ai_client_factory.py`
- `grep -n "request_chat_completion_with_recovery|client.chat.completions.create" main.py`
- inline provider-free `python` simulations of repeated
  `handle_provider_error` calls, `create_chat_client(use_fallback=True)`
  transitions, and repeated `get_fallback_notification` reads;
- AST control-flow checks on `get_ai_response` and
  `request_chat_completion_with_recovery`.

### Out-of-class observation (no change made)

With the fork's default provider configuration (`LLM_PROVIDER = "openai"` in
`model_config.py`), `fallback_provider` stays `None` after
`reset_fallback_status()` and `create_chat_client()`, so the user-facing
fallback wording resolves to "Falling back to None" / "openai to None". This is
a cosmetic label artifact, not an error reissue: no completed error is
re-processed, `fallback_count` still increments once, and no fallback loop
exists. It is outside the #240 defect class and outside this task's change
boundary, so no provider code was modified.

## Focused Verification (Task 4.1)

Status: COMPLETE. Suite 3 initially failed on a stale source-shape contract and
was resolved by a focused test-contract update (step 3 below). The known
pre-existing narrator-contract failures (step 6) remain recorded as expected and
are not a regression. All suites were re-run after the fix; no unexpected
failures remain. Task 4.1 is checked in `tasks.md`.

All commands ran from the project root with `.venv/bin/python`.

| # | Command | Refreshed result |
| --- | --- | --- |
| 1 | `.venv/bin/python -m unittest -q scripts.test_legacy_ui_output_safety scripts.test_provider_empty_response_retry` | PASS: Ran 48 tests, OK (exit 0) |
| 2 | `.venv/bin/python scripts/test_gpt56_luna_direct_openai_contract.py` | PASS: Ran 41 tests, OK (exit 0) |
| 3 | `.venv/bin/python scripts/test_gpt54_chat_params_contract.py` | PASS after contract update: Ran 10 tests, OK (exit 0) |
| 4 | `.venv/bin/python scripts/test_gpt54_mini_chat_params_shim.py` | PASS: Ran 6 tests, OK (exit 0) |
| 5 | `.venv/bin/python scripts/test_retry_de_looping.py` | PASS: Ran 18 tests, OK (exit 0) |
| 6 | `.venv/bin/python scripts/test_narrator_prompt_validation_refactor.py` | FAIL: Ran 41 tests, FAILED (failures=2) (exit 1); both are the known pre-existing failures |
| 7 | `.venv/bin/python scripts/c5_regression_combat.py` | PASS: Ran 59 tests, OK (exit 0) |

### Step 3 failure and contract update (resolved)

Failing test:
`TestGPT54ChatParamsContract.test_main_narrator_callsites_use_shared_helper_and_timeout`
in `scripts/test_gpt54_chat_params_contract.py`, formerly comparing
`client.chat.completions.create(` count against the
`timeout=NARRATOR_API_TIMEOUT_SECONDS` count.

Observed failure: `AssertionError: 5 != 9`.

Classification: CHANGE-INDUCED, not pre-existing. Task 3.4 intentionally rewired
the four `main.py` narrator request sites to
`request_chat_completion_with_recovery(...)`, so the old
`raw create count == timeout count` equality no longer describes the
helper-mediated request shape.

Resolution: the assertion block of that single test was updated to the
helper-aware invariant. No other test or code file changed; `main.py` and
`utils/*` are untouched by this fix.

The invariant (verified counts in the current `main.py`):

- `raw_calls = main_source.count("client.chat.completions.create(")` - 5 today.
- `helper_calls = main_source.count("= request_chat_completion_with_recovery(")` - 4 today.
- `raw_calls == main_source.count("**get_chat_completion_params(")` - every remaining raw site uses the shared parameter resolver.
- `helper_calls >= 4` - the four narrator sites route through the fork recovery helper.
- `raw_calls + helper_calls == main_source.count("timeout=NARRATOR_API_TIMEOUT_SECONDS")` - every request site carries the narrator timeout; 5 + 4 == 9 today.
- `helper_calls == main_source.count("request_params=get_chat_completion_params(")` - every helper site resolves params through the shared function.
- The existing `handle_provider_error(` and `create_chat_client(use_fallback=True)` assertions are kept, so the narrator provider error and fallback handling contract is still enforced.

Re-run after the update: PASS, Ran 10 tests, OK (exit 0).

### Step 6 known pre-existing failures (expected; not a regression)

`scripts/test_narrator_prompt_validation_refactor.py`, class
`TestNarratorSceneContextHygieneContracts`:

- `test_narrator_payload_filters_location_history_and_atlas` fails at test
  line 726: it expects the single-line call
  `messages_to_send = _sanitize_narrator_payload(messages_to_send, current_module_name, current_location_id)`.
- `test_narrator_payload_hygiene_helpers_exist` fails at test line 716: it
  expects the single-line signature
  `def _sanitize_narrator_payload(messages_to_send, current_module_name="", current_location_id=""):`.

Both are whitespace-sensitive source assertions; `main.py` already formats the
call and signature across multiple lines at HEAD. The region is untouched by
this change: `git diff main.py | grep -c "_sanitize_narrator_payload"` = 0.
The same two failures exist on pristine HEAD, so they are classified as
pre-existing conditions, not a regression.

### Cross-checks

- `git diff main.py | grep -c "_sanitize_narrator_payload"` = 0.
- `git diff --check`: clean (exit 0, no output).
- Scratch log `tmp/task-4-1-narrator.log` held the step 6 capture and was
  deleted after this record was written.
- The step 3 contract fix touched only
  `scripts/test_gpt54_chat_params_contract.py`; `git diff --name-only` for the
  fix shows no `main.py` or `utils/` changes, and no scratch files remain.

## Final Validation (Task 4.4)

Status: COMPLETE. All five required checks pass, the changed-path scope is
clean, and the upstream push guard is intact. Task 4.4 is checked in
`tasks.md`. All commands ran from the project root; no file was modified by
this task other than this notes file and the 4.4 checkbox.

### Check 1 - OpenSpec strict validation

Command: `openspec validate fork-final-upstream-sweep --strict`
Result: PASS - `Change 'fork-final-upstream-sweep' is valid` (exit 0).

### Check 2 - ASCII compliance summary

Command: `.venv/bin/python scripts/check_ascii_compliance.py --summary-only`
Result: PASS -
`ASCII_CHECK scanned_files=711 files_with_violations=0 violations=0 fixed_files=0 fixed_chars=0`.

### Check 3 - Whitespace check

Command: `git diff --check`
Result: PASS - no output, exit 0.
Also ran `git diff --cached --check` because the task 4.3 rename is staged:
PASS - no output, exit 0.

### Check 4 - Worktree status summary

Command: `git status --short`

Tracked modifications and rename:

- `M` governance files: `AGENTS.md`, `CONTRIBUTING.md`, `README.md`,
  `adrs/0002-merge-safe-tabletop-overlay-architecture.md`,
  `adrs/0003-upstream-first-extend-do-not-replace.md`,
  `adrs/0030-fork-divergence-upstream-as-patch-source.md`, `adrs/index.md`,
  `openspec/config.yaml`, `openspec/frontier_builder_profile.md` (external
  `fork-independence-pivot` set).
- `M` this change: `main.py`, `utils/ai_client_factory.py`,
  `scripts/test_gpt54_chat_params_contract.py`,
  `web/templates/game_interface.html`.
- `M` external Jev spike: `utils/action_predictor.py`,
  `plans/version-2/openrouter_llm_router_architecture.md`.
- `RM plans/upstream-merge-0826.md -> plans/archive/upstream-merge-0826.md`:
  staged rename (R100) plus the task 4.2 ledger content modified in the
  worktree. No active `plans/upstream-merge-0826.md` remains (task 4.3
  satisfied).
- `??` this change: `openspec/changes/fork-final-upstream-sweep/` artifacts and
  the new files `utils/provider_response_recovery.py`,
  `scripts/test_legacy_ui_output_safety.py`,
  `scripts/test_provider_empty_response_retry.py`.
- `??` external: `adrs/0031-independent-development-fork.md`,
  `openspec/changes/fork-independence-pivot/`, `plans/independent-fork.md`
  (governance set), and `scripts/extract_jev_eval_set.py`,
  `scripts/spike_jev_decisions.py`,
  `scripts/test_action_predictor_params_contract.py`,
  `scripts/test_jev_decision_spike.py` (Jev-decisions spike).

### Check 5 - Scope check (forbidden directories and runtime state)

Enumerated the union of unstaged, staged, and untracked changed paths, then
classified every path. Result: 43 changed paths in total. Every path is either
in this change's file set or in the recorded external sets; there were zero
unclassified paths.

This change's file set (all present in the worktree):

- `web/templates/game_interface.html`
- `main.py`
- `utils/ai_client_factory.py`
- `utils/provider_response_recovery.py` (new)
- `scripts/test_legacy_ui_output_safety.py` (new)
- `scripts/test_provider_empty_response_retry.py` (new)
- `scripts/test_gpt54_chat_params_contract.py`
- `plans/archive/upstream-merge-0826.md` (renamed from
  `plans/upstream-merge-0826.md` in task 4.3)
- `openspec/changes/fork-final-upstream-sweep/**`

Forbidden-path scan over all changed paths:
`modules/`, `characters/`, `data/`, `config.py`, and runtime-state patterns
(`party_tracker`, `world_registry`, `campaign.json`, `conversation_history`,
`encounters/`, `journal.json`, `debug/`, `tmp/`) returned no matches.

Conclusion: the change diff contains no changes under `modules/`,
`characters/`, `data/`, `config.py`, or runtime state paths. This matches the
proposal Impact statement ("Data impact: none. No persistence, schema, module,
or save migration.").

External/out-of-scope worktree changes (not touched by this task and not part
of this change): the `fork-independence-pivot` governance set listed in
Check 4, and the separate Jev-decisions spike touching
`utils/action_predictor.py`,
`plans/version-2/openrouter_llm_router_architecture.md`,
`scripts/extract_jev_eval_set.py`, `scripts/spike_jev_decisions.py`,
`scripts/test_action_predictor_params_contract.py`, and
`scripts/test_jev_decision_spike.py`.

### Check 6 - Remote guard and upstream activity

Command: `git remote -v`

```
origin    https://github.com/zeug-zz/NeverEndingQuest-TTRPG.git (fetch)
origin    https://github.com/zeug-zz/NeverEndingQuest-TTRPG.git (push)
upstream  https://github.com/MoonlightByte/NeverEndingQuest.git (fetch)
upstream  DISABLE (push)
```

The upstream push URL is still `DISABLE`, as required.

No fetch, push, or history modification was executed by this change or this
task. Read-only observations made without fetching:

- `git for-each-ref refs/remotes/upstream` lists only historical refs; the
  newest upstream committer date is 2026-03-12
  (`refs/remotes/upstream/multi-model-refactor`), and `upstream/main` still
  points at `c3604eb3` (committer date 2026-02-19). No recent upstream ref
  update is present.
- `.git/FETCH_HEAD` (mtime 2026-09-21 19:21 NZST) references only
  `zeug-zz/NeverEndingQuest-TTRPG` branches (`main` plus Dependabot branches),
  so the most recent fetch journal is an `origin` fetch, not an upstream
  fetch. No upstream entry appears in it.
- Upstream reflog files under `.git/logs/refs/remotes/upstream/` are zero
  bytes with mtimes from June-July, so no upstream reflog activity is
  recorded.

### Task 4.4 conclusion

All required checks pass: OpenSpec strict validation is valid; ASCII
compliance is 0 violations across 711 scanned files; `git diff --check` and
`git diff --cached --check` are clean; the diff scope contains no forbidden
directory or runtime-state paths; and the upstream push guard remains
`DISABLE` with no upstream fetch or push executed. Task 4.4 is marked complete
in `tasks.md`.
