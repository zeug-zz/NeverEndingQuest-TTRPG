# Combat Latency Baseline - Design

## Context

Phase 0 precedes router migration, combat package decomposition, model changes,
and hot-path optimization. It must measure the current OpenAI combat path
without changing the path being measured. Existing context-packet and
validation-efficiency contracts remain authoritative for those behaviors; this
change records their runtime costs and outcomes rather than redefining them.

## Contract Layer (MUST)

### Trace Architecture And Boundaries

The trace subsystem MUST be an opt-in observer with a small writer API and
stable event schema. Combat stages and provider sites MAY emit events through
that API, but the writer MUST NOT own combat decisions, prompt construction,
provider routing, compression policy, persistence, or phase transitions.

The trace destination MUST be `debug/combat_turn_trace.jsonl` when enabled.
Each record MUST be self-contained enough for the provider-free report script
to aggregate without importing or invoking provider clients.

### State Truth Source

Instrumentation MUST read values already available at the observed boundary.
Python combat state, persisted encounter state, and existing provider response
metadata remain the sources of truth. The trace MUST NOT mutate encounter,
character, party, conversation, compression-cache, or world-time state.

### Failure And Thread Safety

The writer MUST fail open for serialization, directory, file, lock, and
unexpected instrumentation errors. It MUST never raise into combat, wait on a
provider, or delay a combat stage beyond negligible observer work.

Because Flask/SocketIO can run concurrent work, the writer MUST serialize
records safely so concurrent events cannot corrupt a JSONL line. It MUST use a
thread-safe strategy or equivalent atomic append boundary. A writer failure MAY
drop an event, but MUST NOT block or alter combat behavior.

The disabled gate MUST be checked before event payload construction and file
access so the disabled path performs zero trace writes and no measurable
instrumentation work.

### Migration Sequencing

Implementation MUST proceed in this order: gate and writer, stage/provider
instrumentation, decision events, fixed fixtures, provider-free report, then
baseline verification. The baseline MUST be captured before router migration,
model swap, decomposition, or hot-path changes.

### Rollback

The primary rollback MUST be setting the trace configuration gate to OFF and
restarting the process if required by configuration loading. No runtime
rollback, state repair, prompt restoration, or provider fallback change is
permitted because the feature is observational only.

### Observability Requirements

Enabled traces MUST support aggregation of provider calls by site, latency,
token counts, compression calls and cache hit rate, file reads and writes,
named stage wall-clock timings, NL fast-path hit/miss, and the four decision
fields defined by the decision-events capability. The report MUST expose
missing or malformed data as bounded diagnostics rather than silently
inventing measurements.

No provider call MAY be added or removed for measurement. Prompts MUST remain
byte-identical, and trace collection MUST remain read-only.

## Guidance Layer (SHOULD)

- The writer SHOULD use one JSON object per line and stable ASCII field names.
- Event names SHOULD identify the combat turn and stage without embedding full
  prompts, full game state, secrets, or unbounded narrative text.
- Provider-site instrumentation SHOULD record elapsed time around the existing
  call boundary and use response usage metadata when available.
- Fixture output SHOULD be deterministic in actor roster, round count, and
  command sequence while allowing measured provider latency to vary.
- The report SHOULD print tables for p50 latency, provider-call counts,
  per-site token totals, file-operation counts, compression cache rate, and
  decision-source counts.

## Proposed Implementation Surfaces (SHOULD)

This section is SHOULD-level implementation guidance; all normative behavior
remains in the delta specifications.

- `utils/combat_latency_trace.py` (new) - trace writer, schema helpers,
  fail-open thread-safe append (naming convention matches existing
  `utils/combat_*` helpers)
- `model_config.py` - `ENABLE_COMBAT_TURN_TRACE = False` gate
- `core/managers/combat_manager.py` - stage, provider-site, file-operation,
  and decision-seam instrumentation
- `core/managers/multi_pc_combat.py` - phase and NL fast-path observational
  events where already emitted
- `core/ai/combat_compressor.py` - cache hit/miss and compression-decision
  events
- `core/ai/combat_compression_engine.py` - compression provider-call events
- `scripts/combat_latency_report.py` (new) - provider-free report CLI
- `scripts/combat_latency_fixtures.py` (new) - fixed MP (4 PCs x 3 rounds + 1
  enemy batch) and 1-PC party (1 round) fixtures
- `scripts/test_combat_latency_baseline.py` (new) - provider-free
  trace/report/fixture tests

## Scripted Capture Ensemble

The G1 baseline is captured through a dedicated scripted ensemble rather than an
ad-hoc run. The ensemble is test tooling; it adds no product behavior and
changes no runtime contract.

- Lean-copy isolation (MUST): the ensemble MUST run from a real copy of the
  repository under `tmp/combat_capture/` and MUST NOT write to the installed
  tree. A real copy is required because `utils/repo_paths.repository_root()`
  derives the root from its own `__file__` location rather than the process CWD,
  and the path-authorization helpers reject symlinked components, so a symlink
  stand-in cannot redirect runtime writes into the sandbox.
- Separate port (MUST): the sandbox MUST serve on `WEB_PORT=8360` so the
  installed game remains usable on `WEB_PORT=8357`, and capture start/stop
  commands MUST set `NEQ_OPEN_BROWSER=0`.
- Agent-driven execution (SHOULD): captures SHOULD stay agent-driven through a
  documented checklist rather than generated JS or headless test
  infrastructure, so waits, step ordering, and failure recovery stay
  inspectable and cheap to revise.
- Primary execution path and blocking evidence (MUST): the primary execution
  path MUST be the socket-driven driver `scripts/capture_drive.py`
  (`python-socketio` client plus the `/api/party/set_active` REST call);
  `playwright-cli` is retained as the documented browser alternative. Browser
  launch is blocked in the current session sandbox: the headless shell exits
  with SIGSEGV (SEGV_ACCERR) under `--no-sandbox --disable-gpu` while nono path
  checks report the relevant paths as ALLOWED, so the block is a mach/JIT-class
  restriction rather than a path grant.
- Verified socket contract (MUST): the driver implements exactly this
  boundary; the trace itself is still produced by the sandbox runtime, never by
  the driver:
  - connect `socketio.Client()` to `--url` (default `http://localhost:8360`)
    with a clean non-zero exit and no traceback when the connect fails;
  - emit `start_game`, then treat the session as ready on the first
    `game_output` receipt or a `status_update` whose `is_processing` went
    true -> false after start, capped by `--start-timeout` (default 180 s);
  - set the active PC with `POST {url}/api/party/set_active` JSON
    `{"character": name}` and require `success: true`;
  - emit `user_input` with `{"input": text, "character": name}`; a turn is
    complete when at least one new `game_output` arrived after the send and the
    event stream (`game_output` plus `status_update`) has then been quiet for
    `--turn-quiet-seconds` (default 1.5 s) while `is_processing` is False (the
    turn is capped by `--turn-timeout`, default 150 s, and reports a timeout
    only when no new `game_output` arrives at all), then settle 1.0 s and log
    elapsed seconds plus whether the timeout was hit;
  - append every `game_output` payload to `--transcript` (default
    `tmp/capture_transcript_<party>.log`) verbatim as evidence that is never
    synthesized, and copy
    `tmp/combat_capture/debug/combat_turn_trace.jsonl` to `--trace-dst` after
    the scenario with source and destination record counts.
- Capture module (SHOULD): `Capture_Arena` is the tiny dedicated module (one
  area with walkable locations, a hostile group, and NPC and feature objects)
  that keeps captures independent of gameplay state from other modules.
- Seed hooks (MUST): the seeded `party_tracker.json` MUST satisfy
  `utils/startup_wizard.startup_required()` so the sandbox skips the setup
  wizard, and MUST set `worldConditions.activeCombatEncounter` so the `main.py`
  startup path auto-resumes combat with the seeded encounter.
- Reuse (SHOULD): the ensemble SHOULD be documented as a local skill and
  checklist with extension points for future narration and other gameplay
  captures.

The simplest alternative considered was running the capture against the
installed tree on an alternate port. Rejected: the trace-enabled run mutates
runtime state (party tracker, encounter, history), `repository_root()` would
still resolve to the installed tree, and the sandbox write boundary could not
be enforced.

## Gate G1 Baseline (2026-09-22)

This section records the captured G1 baseline from the scripted capture
ensemble. All numbers below come from the two report files listed as evidence;
recording the baseline added no provider calls and changed no prompt, routing,
or gameplay behavior.

### Captures

| Capture | Trace | Records | Steps | Timeouts | Elapsed |
|---|---|---|---|---|---|
| 4-PC party | `tmp/combat_baseline_mp.jsonl` | 266 | 19 | 0 | 188.1 s |
| 1-PC party | `tmp/combat_baseline_one_pc.jsonl` | 69 | 4 | 0 | 75.6 s |

Evidence paths:

- Transcripts: `tmp/capture_transcript_4.log` (4-PC),
  `tmp/capture_transcript_1.log` (1-PC)
- Report copies: `tmp/report_mp.txt`, `tmp/report_one_pc.txt`
- Driver console logs: `tmp/capture_drive_mp_console.log`,
  `tmp/capture_drive_one_pc_console.log`
- Sandbox trace source preserved by copy into both trace files:
  `tmp/combat_capture/debug/combat_turn_trace.jsonl`

Both captures carry mode `mp` because a 1-PC party runs the same single
tabletop runtime (ADR-0032); party size is identified by the trace file name,
not by the trace mode field. The 15 records under `unavailable/unavailable` in
each report are startup/resume events emitted before per-turn context is set;
they carry no fixture or mode identity.

### Metrics (verbatim from `tmp/report_mp.txt` and `tmp/report_one_pc.txt`)

#### Provider calls by site (ms)

| Capture | site | calls | p50_ms | p90_ms | token sums (observed fields only) |
|---|---|---|---|---|---|
| MP | combat_main | 23 | 3719.9990830849856 | 5432.024500099942 | prompt_tokens=358477, completion_tokens=6200, total_tokens=364677 |
| MP | combat_validation | 9 | 3384.7577089909464 | 5705.618208972737 | prompt_tokens=102958, completion_tokens=2488, total_tokens=105446 |
| 1-PC | combat_main | 7 | 5257.866916945204 | 5826.275708852336 | prompt_tokens=84650, completion_tokens=3001, total_tokens=87651 |
| 1-PC | combat_validation | 5 | 5577.151000034064 | 6925.954541889951 | prompt_tokens=43522, completion_tokens=1990, total_tokens=45512 |

Provider totals: MP 32 calls (23 combat_main + 9 combat_validation); 1-PC 12
calls (7 + 5).

#### Stage timings (ms)

| Capture | stage | count | p50_ms | p90_ms | max_ms |
|---|---|---|---|---|---|
| MP | prompt_prep | 23 | 2.7507920749485493 | 5.9258749242872 | 563.386833993718 |
| MP | validation | 23 | 4.1368750389665365 | 4404.037749860436 | 7228.057000087574 |
| MP | turn_start | 20 | 0.042687635868787766 | 0.11708284728229046 | 0.18995883874595165 |
| MP | turn_end | 7 | 13279.455166077241 | 22044.071125099435 | 59078.177749877796 |
| 1-PC | prompt_prep | 7 | 0.6057079881429672 | 0.7177498191595078 | 4.683499922975898 |
| 1-PC | validation | 7 | 4407.823458081111 | 6933.630666928366 | 8606.880249921232 |
| 1-PC | turn_start | 5 | 0.022500054910779 | 0.02870778553187847 | 0.04620896652340889 |
| 1-PC | turn_end | 2 | 28827.170124393888 | 15286.282165907323 | 42368.05808288045 |

#### Compression

| Capture | site | records | calls | cache hits | cache misses | hit rate | p50_ms |
|---|---|---|---|---|---|---|---|
| MP | combat_message_compressor | 58 | 6 | 52 | 6 | 0.896551724137931 | 0.11729204561561346 |
| 1-PC | combat_message_compressor | 3 | 1 | 2 | 1 | 0.6666666666666666 | 0.09350012987852097 |

Compression hit rate: MP 89.7%, 1-PC 66.7%.

#### File operations

| Capture | site | reads | writes |
|---|---|---|---|
| MP | party_tracker.json | 0 | 1 |
| MP | modules/conversation_history/second_model_history.json | 0 | 1 |
| MP | modules/conversation_history/third_model_history.json | 0 | 1 |
| MP | modules/conversation_history/combat_conversation_history.json | 0 | 51 |
| MP | modules/encounters/encounter_capture_mp.json | 0 | 3 |
| MP | party_tracker_turn_start | 20 | 0 |
| MP | encounter_turn_start | 20 | 0 |
| 1-PC | modules/encounters/encounter_capture_one_pc.json | 0 | 3 |
| 1-PC | party_tracker.json | 0 | 1 |
| 1-PC | modules/conversation_history/second_model_history.json | 0 | 1 |
| 1-PC | modules/conversation_history/third_model_history.json | 0 | 1 |
| 1-PC | modules/conversation_history/combat_conversation_history.json | 0 | 16 |
| 1-PC | party_tracker_turn_start | 5 | 0 |
| 1-PC | encounter_turn_start | 5 | 0 |

#### Decisions

| Capture | decision point/source | count | p50_ms | provider avoided |
|---|---|---|---|---|
| MP | combat_command_fast_path/deterministic | 6 | 0.16837497241795063 | 6 |
| 1-PC | combat_command_fast_path/deterministic | 1 | 1.3225420843809843 | 1 |

NL fast path: MP hits=6 misses=0; 1-PC hits=1 misses=0.

#### Baseline fixture summaries

| Capture | fixture/mode | records | provider calls | stage count | decision count |
|---|---|---|---|---|---|
| MP | unavailable/unavailable | 15 | 4 | 4 | 0 |
| MP | unavailable/mp | 251 | 28 | 69 | 6 |
| 1-PC | unavailable/unavailable | 15 | 3 | 4 | 0 |
| 1-PC | unavailable/mp | 54 | 9 | 17 | 1 |

### Target assessment against `plans/version-2/combat-manager-refactor.md` section 1.1

Observed step elapsed (driver-reported; includes the 1.5 s quiet window):

| Observed step | MP | 1-PC |
|---|---|---|
| Deterministic `/att` + `/dmg` steps | 1.62-1.73 s | 1.62-1.63 s |
| LLM free-text steps | 10.77, 10.99, 11.81, 13.25, 16.26 s (first free-text step 21.99 s) | 15.45 s |
| Enemy batch `/end` | 59.15 s | 42.30 s |

| Provisional target | Baseline evidence | Assessment |
|---|---|---|
| PC action turnaround (p50), LLM path <= 8 s | Free-text steps 10.8-16.3 s (MP; first free-text step 21.99 s) and 15.45 s (1-PC); MP turn_end p50 13279.46 ms | Not met - Phase 2 goal |
| PC action turnaround (p50), deterministic fast path < 1 s | Deterministic steps 1.62-1.73 s driver elapsed including the 1.5 s quiet window; work-only ~0.1 s; decision p50 0.168 ms (MP) / 1.32 ms (1-PC) | Met on the work-only measurement |
| Enemy batch (`/end`, all enemies) p50 <= 15 s | 42.30 s (1-PC); 59.15 s (MP) | Not met - Phase 2 goal |
| Provider calls per uncontested PC action <= 2, then <= 1 | 23 combat_main calls across 19 MP steps; 7 across 4 1-PC steps; the report does not attribute calls per action | Baseline recorded; per-action attribution deferred to Phase 2 tracking |
| Provider calls per enemy batch = 1 | Not isolated by the report site split | Baseline recorded; not measurable from this report |
| File writes per combat turn <= 3 | 51 combat_conversation_history.json writes across the MP capture; 16 across the 1-PC capture | Baseline recorded; turn-scoped counting deferred to Phase 2 tracking |
| Per-round latency (4 PCs + enemy batch) improve >= 30% vs baseline | This record is the baseline | Baseline established; improvement is measured against it in Phase 2 |

### Measurement caveats

- (a) Driver step elapsed includes the 1.5 s quiet window
  (`--turn-quiet-seconds 1.5`), so deterministic fast-path work is far below
  the observed 1.62-1.63 s (roughly 0.1 s of work). The provider and stage
  numbers in the tables above are work-only measurements (elapsed around the
  existing call boundary, no quiet window).
- (b) Owner ratification is kept as-is: the section 1.1 provisional targets
  remain the Phase 2 goals, and this baseline quantifies the gap rather than
  adjusting the targets - LLM-path free-text steps 10.8-16.3 s vs <= 8 s;
  enemy-batch `/end` 42.3 s on 1-PC vs <= 15 s; deterministic work ~0.1 s vs
  < 1 s target, met.

Gate G1 is satisfied: baseline captured on the OpenAI stack, targets ratified
(kept as-is), evidence paths recorded.

## Trade-offs

An opt-in observer gives no production telemetry while disabled, but it avoids
confounding the baseline and preserves the zero-overhead requirement. A local
JSONL artifact is simple and provider-free to analyze, but concurrent writes
require careful serialization and individual records must stay bounded. Fixed
fixtures improve comparability, but they do not represent every narrative or
combat state; they are a baseline gate, not a universal performance claim.

## Explicit Boundary With Existing Contracts

This design does not redefine combat context packet contents, validation
compression thresholds, routing reasons, prompt contracts, or mechanical
authority. It only records observed calls, timings, cache outcomes, and
decision outcomes at existing boundaries.
