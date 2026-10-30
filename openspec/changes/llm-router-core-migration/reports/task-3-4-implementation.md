# Task 3.4 Implementation Report

## Scope

Migrated only `core/combat/combat_manager.py::summarize_dialogue` and
`generate_combat_round_summary` to the provider-neutral facade. Dialogue uses
`combat_summary`, exact existing `dialogue_summary_prompt`, `json_output=False`,
and explicit `temperature=TEMPERATURE`; it strips the returned string before
the unchanged optional JSON narration extraction and persistence path. Round
summary uses `compression`, the unchanged inline system/user messages,
`json_output=False`, and explicit temperature `0.1`, then passes the returned
string directly to `json.loads`.

Both requests use the real per-call receipt adapter. Dialogue retains its
`combat_dialogue_summary` trace, `combat_summary` API logger metadata, and
`USAGE_TRACKING_AVAILABLE` tracker gate in legacy trace -> API logger -> usage
tracker order (`api_log_before_tracker=True`). Round summary retains compression
trace and gated usage tracking in trace -> tracker order without an API logger.
Its legacy endpoint/purpose labels remain, but the undefined
`selected_model` claim was removed; requested/resolved model facts now come from
the actual receipt. Producer-side trace and manual tracker/logger duplicates
were removed. No `utils/compression/` files or compression-engine code changed.

Dialogue terminal errors naturally propagate before encounter, location,
history, or save mutation. Round summary now explicitly re-raises
`GameLLMTerminalError` before its existing broad ordinary-error catch; ordinary
failures and malformed JSON still return `None`. Prompts, text/JSON parse
semantics, encounter-ID fallback, timestamp fields, save callback order, missing
area behavior, and nonterminal output contracts remain unchanged.

## Verification

`scripts/test_combat_summary_router_migration.py` compiles and executes both
complete current owner functions from source under fakes and invokes the real
`LLMRouter` with a fake SDK client. This is the actual-facade/fake-SDK
whole-function proof. The adapter is real; fake consumers verify
dialogue trace/API/tracker order and round trace/tracker/no-API behavior. Tests cover
prompt/message literals and dialogue's special `Combat Summary:` history
filtering, task IDs and text-return temperatures, JSON narration extraction,
round JSON parsing, `max_retries=0`, usage gating, actual requested/resolved
model trace facts, terminal quota/refusal/filter stop before dialogue
mutations, round terminal propagation, ordinary transport failure, malformed
JSON, plain dialogue output, and mismatch/no-save behavior.

An initial attempt to import the full combat manager under the mandatory
pre-import SDK-constructor tripwire correctly stopped at an unrelated module
import-time client constructor. No SDK constructor or network attempt passed
the guard. The focused test therefore executes the exact complete owner AST
functions from current source with explicit dependencies, rather than importing
the unrelated combat-manager dependency graph or running an owner loop.

Primary-source-reviewed verification passed in 20 separate processes with
`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`, `PYTHONDONTWRITEBYTECODE=1`, and
`TMPDIR=tmp`:

- `scripts.test_combat_summary_router_migration`: 6 passed.
- `scripts.test_core_chat_inventory_contract`: 13 passed; both inventory
  transport rows now require `llm.call`.
- `scripts.test_core_chat_request_contracts`: 17 passed after repointing the
  fake-router task and text-parser seams. Existing frozen prompt/asset SHA-256
  literals were not changed.
- `scripts.test_llm_runtime_receipt_adapter`: 15; `scripts.test_llm_runtime_launch_reset`: 3.
- Five facade suites: router 88, benchmark profiles 6, GPT-5.4 chat 10,
  GPT-5.4 mini shim 6, and GPT-5.6 direct OpenAI 41.
- Combat parity suites: persistence stages 12, structured operations 16,
  bootstrap 29, retry stage 15, validation stage 17, decomposition static 9,
  manager decomposition 35, prompt authority 7, truth pack 8, and canonical
  validation facts 3.

The process counts were 6 + 13 + 17 + 15 + 3 + 88 + 6 + 10 + 6 + 41 + 12 +
16 + 29 + 15 + 17 + 9 + 35 + 7 + 8 + 3 = 356 passed across 20 separate
processes. Also passed Python compilation with
`PYTHONPYCACHEPREFIX=tmp/llm-router-core-3-4-pycache`, ASCII compliance
(1,142 files, zero violations), scoped `git diff --check`, no-ignored-cleanup,
and strict CORE validation (`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec
validate llm-router-core-migration --strict`). The existing 131-test facade /
705-test combat baselines were not relabelled or claimed as rerun.

Task 3.4 is checked pending planner verification. The migration ledger now
reports 14/25 tasks checked; the inventory reports 11 of 15 semantic
operations migrated and four legacy operations remaining. All G4 work remains
pending. No live G4, full simulation, game loop, server, network, provider, or
full-goal completion claim is made.
