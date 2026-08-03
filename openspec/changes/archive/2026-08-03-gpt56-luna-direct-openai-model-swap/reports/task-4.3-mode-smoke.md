# Task 4.3 Mode Smoke for gpt-5.6-luna Direct-OpenAI Model Swap

Timestamp (UTC): 2026-08-03T08:05:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 4.3 Perform a short single-player and TABLETOP MODE smoke check after a clean server restart; confirm both modes select Luna and preserve existing gameplay behavior.

## 1. Method and scope decision

A full web-server/browser smoke (starting `run_web.py`) was NOT performed. The
startup path of the documented server command exercises runtime side effects
(startup preflight, `party_tracker.json` / campaign hydration, live-chat-monitor
log writes) that are explicitly out of scope for this task ("Do not edit ...
runtime state, modules, party tracker, databases, or saved games") and would
leave a long-running background process. The task allows the alternative: a
**fresh-process application smoke** that exercises the same model-loading path
under both mode flags. This report is therefore process-level, not full browser
gameplay.

The model-loading path exercised is exactly the path the running application
uses at startup:

- `config.py` imports `model_config.py` (`from model_config import *`, line 45)
  and defines `MULTIPLAYER_MODE` locally (lines 68/73).
- `utils.ai_client_factory.py` lazily imports `model_config`/`config` and drives
  client creation (`create_chat_client`), provider resolution
  (`_get_actual_provider`), model selection (`get_chat_model_name`), display
  identity (`get_model_display_name`), and request parameters
  (`get_chat_completion_params`).

Two separate fresh `.venv/bin/python` processes were used (one per mode) so each
check represents a clean restart/import boundary. In each process the
`config.MULTIPLAYER_MODE` attribute was set (False = single-player, True =
TABLETOP MODE) via in-process module assignment only; no file edits were made
and `config.py` was not modified (`git status` confirms `config.py` clean).

No live provider/API calls were made in this task (tasks 4.1/4.2 already
verified provider acceptance). No credentials were read or printed.

## 2. Process A - single-player smoke (fresh process, MULTIPLAYER_MODE=False)

Command (inline stdin probe, no scratch files):

```bash
.venv/bin/python - <<'PY'
import config
config.MULTIPLAYER_MODE = False
import model_config
from utils.ai_client_factory import (get_chat_model_name, get_model_display_name,
                                     get_chat_completion_params, _get_actual_provider)
# ... 22 active GPT-5 role constants checked == "gpt-5.6-luna", no "gpt-5.4-mini" ...
PY
```

Results (exact output):

```
PROCESS A (single-player) -- MULTIPLAYER_MODE = False
LLM_PROVIDER model_config = openai
LLM_PROVIDER config       = openai
_get_actual_provider()    = ('openai', False)
get_chat_model_name()     = gpt-5.6-luna
display name              = GPT-5.6 Luna
active roles checked      = 22
all roles == gpt-5.6-luna = True
no gpt-5.4-mini anywhere  = True
non-luna roles            = []
dm_main params            = {'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium', 'verbosity': 'medium'}
combat_main params        = {'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium', 'verbosity': 'medium'}
OPENROUTER_CHAT_MODEL     = moonshotai/kimi-k2.5
PROBE_A_PASS
```

## 3. Process B - TABLETOP MODE smoke (fresh process, MULTIPLAYER_MODE=True)

Command: same inline probe with `config.MULTIPLAYER_MODE = True`.

Results (exact output):

```
PROCESS B (TABLETOP MODE) -- MULTIPLAYER_MODE = True
LLM_PROVIDER model_config = openai
LLM_PROVIDER config       = openai
_get_actual_provider()    = ('openai', False)
get_chat_model_name()     = gpt-5.6-luna
display name              = GPT-5.6 Luna
active roles checked      = 22
all roles == gpt-5.6-luna = True
no gpt-5.4-mini anywhere  = True
non-luna roles            = []
dm_main params            = {'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium', 'verbosity': 'medium'}
combat_main params        = {'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium', 'verbosity': 'medium'}
OPENROUTER_CHAT_MODEL     = moonshotai/kimi-k2.5
PROBE_B_PASS
```

## 4. Mode-flag independence (same model routing in both modes)

Process A and Process B outputs are identical for every model-selection field:
`LLM_PROVIDER=openai`, `_get_actual_provider()=('openai', False)`,
`get_chat_model_name()='gpt-5.6-luna'`, display name `GPT-5.6 Luna`, all 22
active GPT-5 roles `gpt-5.6-luna`, zero `gpt-5.4-mini` references, and identical
`dm_main`/`combat_main` parameter shapes. The mode flag does not alter model
routing. Source evidence: `utils/ai_client_factory.py` contains no
`MULTIPLAYER_MODE` reference (grep confirmed), and `model_config.py` contains
none either; mode is a UI/party-state concern, not a model-routing input.

## 5. Provider-free regression smoke relevant to both modes

Command:

```bash
.venv/bin/python -m unittest -q scripts.test_gpt56_luna_direct_openai_contract \
  scripts.test_gpt54_chat_params_contract scripts.test_gpt54_mini_chat_params_shim \
  scripts.test_multi_pc_combat
```

Result:

```
Ran 128 tests in 0.124s
OK
```

Coverage: 39 Luna direct-OpenAI contract tests (selection, effort profiles,
display identity, OpenRouter isolation), 16 generic GPT-5 shim contract tests,
and 73 `multi_pc_combat` tests (TABLETOP MODE runtime: turn queue, phase
handling, delegation). All provider-free; fixture-based; no canonical campaign
state touched. (The DEBUG line emitted by the multi_pc_combat fixture suite is
normal suite logging, same as in task 3.3.)

## 6. Runtime-preservation findings

- Direct OpenAI remains selected: `LLM_PROVIDER` = `openai` in both
  `model_config` and `config`; `_get_actual_provider()` resolves to
  `('openai', False)` (not OpenRouter) in both modes.
- Active model selection: all 22 active GPT-5 runtime roles resolve to the exact
  model ID `gpt-5.6-luna` in both modes; no active selector branch selects
  `gpt-5.4-mini-2026-03-17`.
- Request-parameter behavior preserved: narrator/combat `dm_main`/`combat_main`
  shapes are `{'model': 'gpt-5.6-luna', 'reasoning_effort': 'medium',
  'verbosity': 'medium'}` (legacy `temperature`/`top_p` omitted by default) in
  both modes, unchanged from tasks 2.1/4.1/4.2.
- OpenRouter isolation preserved: `OPENROUTER_CHAT_MODEL` remains
  `moonshotai/kimi-k2.5` in both processes.
- No persisted state, module artifact, party tracker, database, or saved game
  was read-for-edit or modified; `config.py` shows no diff.
- No server or background process was started or left running (`ps` verified
  clean after the checks).

## 7. Conclusion

Both mode smokes pass. After a clean process restart boundary, single-player
(`MULTIPLAYER_MODE=False`) and TABLETOP MODE (`MULTIPLAYER_MODE=True`) select
`gpt-5.6-luna` on the direct-OpenAI path with identical routing, medium
narrator/combat shim parameters, Luna display identity, and unchanged OpenRouter
isolation. The 128 provider-free regression tests pass. The smoke was
process-level rather than full browser gameplay because the documented server
startup path would mutate out-of-scope runtime state and leave a background
process; provider acceptance was already covered by tasks 4.1/4.2. Task 4.3 is
complete.
