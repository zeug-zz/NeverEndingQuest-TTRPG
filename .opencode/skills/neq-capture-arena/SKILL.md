---
name: neq-capture-arena
description: Run orchestrator-owned isolated Capture_Arena gameplay gates, review scenario/state evidence, and preserve per-run traces under tmp/. Use for required live rollout verification; socket driver primary, browser alternative documented.
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: testing
  project: NeverEndingQuest
---

# NeverEndingQuest Capture Arena Skill

## Purpose

Run a scripted live capture of combat (and future narration) behavior against
the sandboxed `Capture_Arena` module. The capture drives the real runtime with
the opt-in combat turn trace enabled and preserves bounded JSONL trace evidence
under `tmp/` for latency baselines and future gates.

Primary execution path: `scripts/capture_drive.py`, a headless socket-driven
driver that talks to the sandbox over the real Flask-SocketIO event contract
(`start_game`, `user_input`, `game_output`, `status_update`) plus the
`/api/party/set_active` REST call. `playwright-cli` remains the documented
browser alternative (see the appendix).

Why the driver is primary: browser launch is blocked in the current session
sandbox. Chromium's headless shell exits with SIGSEGV (SEGV_ACCERR) under
`--no-sandbox --disable-gpu`, while `nono why --path <path> --op readwrite`
reports the same paths as ALLOWED - a mach/JIT-class restriction, not a missing
path grant. The socket path carries the same evidence with far less machinery.

This ensemble is test tooling and runs only inside `tmp/combat_capture/`. It
never changes product runtime behavior, prompts, or installed-tree state.

This skill doubles as the checklist. When seed flags, scripted inputs, or
selectors change, update this file (and `scripts/capture_drive.py` for the
socket path) rather than adding new test infrastructure. The tiered roadmap for
generalizing this rig (scenario packs, session trace, assertions, client
metrics, matrix runs) lives in `plans/capture-arena.md`.

### Provider-free live-gate preflight

Before booking a live gate, require a clean provider-free preflight report at
the exact source SHA intended for the run, with matching `requirements-lock.txt`
identity and secret-free routing identity. It must use the same command,
working directory, and `PYTHONPATH`, issue zero upstream provider requests,
record zero infrastructure failures, and report all required checks passing.
Keep preflight evidence only under
`tmp/router-rollout/<gate>/<run-id>/preflight/`. Hold the shared live-window
lock while using port 8360, and verify teardown leaves no listener on ports
8360 or 8370. Missing or unsupported lifecycle profiles block booking eligibility.
`READY_FOR_BOOKING` is preflight-only: it is neither a booking nor a live-gate
PASS; only the owner may make a later booking ruling.

## Trigger Phrases

- `run capture arena`
- `capture combat latency`
- `playwright capture combat`
- `run the capture ensemble`

## Preconditions

### Orchestrator ownership and authorization

The primary orchestrator prepares, starts, drives, reviews, preserves, and tears
down each required live capture after the relevant focused tests pass. Builders
implement tooling and focused fixes; they do not own the final live gate verdict.
Sandbox fixture/runtime writes performed by the documented commands are part of
verification, not product source implementation.

Before execution, read the owning OpenSpec coverage and the rollout matrix in
`plans/archive/combat-openrouter-alignment.md`. Declare the scenario, party size, seed,
step/request bounds, and expected assertions. A goal-owned capture requires an
active, authorized goal. A separate guideline/planning request does not resume a
paused goal or authorize a live run.

### Implemented G3 coverage and required tooling prerequisites

The bounded named-capture tooling is implemented and provider-free tested in
`combat-manager-decomposition` tasks 4.3 and 4.4. The named IDs accepted by the
current seeder/driver are `combat-smoke`, `combat-smoke-allied-inactive`,
`initiative-pc`, `initiative-dm-tie`, `death-save`, `surrender-exit`, and
`resume-replay`; `surrender-exit` requires the `surrender` or `explicit-exit`
branch, and `resume-replay` requires the `complete` or `replay` phase. These are
implemented CLI values, not planning-only identifiers. Run 1-PC and 4-PC rows;
the wrong-actor death-save subcheck applies only to the declared 4-PC row.

Named G3 runs are separate from the unchanged bare-latency scripts. Omitting
`--scenario` preserves the legacy latency script and historical G1 destinations;
do not alter its inputs or treat it as named G3 coverage. Named captures use the
existing sandbox and driver only. Do not add a parallel runner, alter product
mechanics, or substitute fake evidence for the primary-owned live gate.

| Named scenario | Required observations |
|---|---|
| `combat-smoke` | 1-PC/4-PC scripted turns, complete unique roster, active-PC identity, deterministic HP delta, living non-PC enemy batch, and round/phase progression |
| `combat-smoke-allied-inactive` | Bounded allied-NPC/inactive-enemy variant, with non-party allies and inactive enemies excluded from the required active batch |
| `initiative-pc` | Invalid initiative input holds the gate; known PC-group win enters PC_PHASE without an opening enemy batch |
| `initiative-dm-tie` | Known tie chooses DM group; opening marker and eligible non-PC batch are observed, marker clears, and PC_PHASE resumes |
| `death-save` | Python-owned pending save, invalid roll rejected, wrong actor rejected in 4-PC only, legal roll updates only that PC and restores legal turn flow |
| `surrender-exit` | Separate accepted-surrender and explicit-exit branch runs; active encounter clears, narration resumes, no extra damage/rewards, and server survives |
| `resume-replay` | Preserve a completed mechanical turn, restart only the owned SAM ESandbox server without preparing/reseeding, replay the same encounter and chain, and verify no duplicate mechanics/rewards |

Focused dynamic prompt byte-parity tests remain separate from live output/state
checks; differing LLM prose is not compared for literal equality.

### Evidence bundle and verdict

Reserve a unique, not-yet-existing run ID under
`tmp/router-rollout/g3/<run-id>/` before any command. Do not create the run
directory: `capture_drive.py` validates that it does not exist and creates it
when a named run starts. Keep each server stdout file separate from that bundle
under project-relative `tmp/`; pass its path as `--server-log`, which validates
and copies it into the bundle as `server.log`. Never overwrite an earlier run or
historical G1 artifacts. Preserve before teardown:

- Manifest: gate/scenario and scenario version or hash, party roster/size, seed
  identity, executed commands, source HEAD plus relevant dirty-worktree digest,
  configured profile/model/provider, resolved response models when available,
  timestamps, declared bounds, and observed step/request/timeout counts.
- Verbatim driver transcript, owned-server stdout log, runtime JSONL trace, and
  provider-free report. Keep synthetic/fake evidence labelled and separate.
- Read-only before/after sandbox snapshots of relevant party, encounter, character,
  history and save/receipt state, plus assertion records with expected/observed
  values and concrete evidence references. Do not include credential/config values.
- Driver-generated automated evidence status is only `READY_FOR_PRIMARY_REVIEW`
  or blocked/failed. The primary inspects the bundle and records `PASS`, `FAIL`,
  or `BLOCKED` with explanation, every required check, and missing evidence in
  the owning OpenSpec tasks and goal plan. Readiness is not a verdict and must
  never auto-mark the live gate complete.

For G9/G10, include request versus resolved model, actual provider/fallback,
reported versus estimated/unpriced costs and completeness, and the required
rollback or session/week accounting observations. Unknown data stays unknown.

Driver exit 0 means transport/script completion, not gate acceptance. The legacy
driver tolerates timeout warnings, and the report can exit 0 with degraded data.
Required step timeouts/caps, failed assertions, missing scenarios, or degraded
required evidence prevent PASS. A failed observed assertion is FAIL; unavailable
transport/tools or missing prerequisite coverage is BLOCKED. A sparse combat trace
on a narrator-only turn may be explicitly non-applicable when that gate's required
evidence is instead supplied by transcript/state/response metadata; it cannot
replace required combat latency rows. Do not silently waive a requirement.
Expected restart disconnects must be declared before execution; they are lifecycle
steps, not retrospective excuses for a required gameplay timeout.

An attributable failure goes back to a focused builder fix, then primary rerun of
affected scenarios. Required unavailable tools/services are concrete blockers;
stop rather than substituting mocks or builder claims for live evidence.

### G4 fixed four-key matrix (offline evaluation)

The existing driver/seeder accept `--gate g3` (the unchanged default) and
`--gate g4`; G4 is fixed to `narrator-dialogue-travel` and `combat-smoke`, each
for P1 and P4. G3 and its historical raw 18-key evaluator/default latency path
remain separate and unchanged. The offline evaluator is read-only:

```text
.venv/bin/python scripts/capture_evidence.py --gate g4 \
  --run-dir tmp/router-rollout/g4/<narrator-p1> \
  --run-dir tmp/router-rollout/g4/<narrator-p4> \
  --run-dir tmp/router-rollout/g4/<combat-p1> \
  --run-dir tmp/router-rollout/g4/<combat-p4>
```

Each directory must already contain one unique run bundle. The evaluator
revalidates retained artifact bytes/hashes, source/profile identity, fixed seed,
persisted roster/active PC/location, per-step snapshots and actual trace receipt
byte spans. A manifest declaration or saved PASS/check projection cannot replace
missing or contradictory transcript, state, trace, or receipt data. Unknown cost
may remain explicitly unpriced in G4; an unsupported actual/estimated cost claim,
missing/duplicate/extra key, wrong gate, unexpected fallback, echo-only Mira
reply, timeout, or cap blocks review. A failed observed assertion is FAIL;
unavailable or missing required evidence is BLOCKED. Only
`READY_FOR_PRIMARY_REVIEW` is emitted for complete live-candidate bundles; it is
not a primary PASS. Synthetic bundles are always blocked as non-live evidence.

G4 bounds are fixed: narrator P1 6 inputs/8 controls, P4 6/9; combat P1 5/7,
P4 22/35; all have a 300-second turn cap and at most three separately counted
health reads. Combat identity comes from the static seeded fixture (P1 Acheron
and Goblin; P4 Acheron/Merisiel/Kira/Vitreol and Goblin Alpha/Beta), never from
random spawns. Narrator startup's persisted CA01 opening is observed before any
scripted input. Its five adjacent turns are CA02 -> CA03 -> CA03 dialogue ->
CA02 -> CA01; P4 uses Acheron, Acheron, Merisiel, Merisiel, Merisiel, switching
at the Mira turn. The return path is verified from each persisted post-turn
location, not inferred from input wording. Mira's response must be backend
output distinct from the user-input echo.

Owner key rotation remains outstanding before any live capture. Retain the
recorded key-exposure history; do not inspect credentials, run prepare/restore,
reserve or use a live server, or clean up old evidence as part of offline G4
evaluation.

### G7 capture (primary-owned)

G7 tooling is fixed to `turn-commit` and supports paths `normal` and
`enemy_batch`, parties 1 and 4, the approved commit boundaries, and completed
turn/replay rows. The matrix requires interrupt/recover pairs at every applicable
boundary and complete/replay pairs for both paths and party shapes. P1 does not
include `after_character_write:2`.

The primary may run one pair with:

```text
tmp/router-rollout/g7/run_g7_row.sh <party 1|4> <normal|enemy_batch> \
  <boundary|none> <unique-run-id-prefix>
```

For a boundary, the helper prepares once, starts the owned server on port 8360,
sets `NEQ_COMBAT_FAULT_POINT` only for the interrupt phase, verifies the bounded
`COMBAT_TURN_FAULT_INJECTED:<boundary>` expected lifecycle-stop marker, stops
only its owned listener, then restarts and recovers without reseeding. Use
`none` for the completed-turn/replay pair; replay also retains the same sandbox
without preparation. Both server starts use the repository venv and
`NEQ_OPEN_BROWSER=0`. The helper refuses an occupied/unowned port-8360 listener
and never inspects or touches port 8357.

Keep each unique row bundle under `tmp/router-rollout/g7/<run-id>/`. Builders
must not execute the helper or start a server. After collecting the entire
matrix, the primary may run the read-only evaluator:

```text
.venv/bin/python scripts/capture_evidence.py --gate g7 \
  --run-dir tmp/router-rollout/g7/<row-1> --run-dir tmp/router-rollout/g7/<row-2>
```

Repeat `--run-dir` for every required row. Missing matrix keys are reported
exactly; synthetic evidence cannot become review-ready. Automated
`READY_FOR_PRIMARY_REVIEW` is not a live verdict and tooling never emits G7
`PASS`.

### G9 OpenRouter Auto capture (primary-owned)

G9 live execution is forbidden until the owning G7 report records `Current
status: PASS`. The primary runs one fixed row at a time only after G7 PASS; builders
must not execute this helper or start a G9 server:

```text
tmp/router-rollout/g9/run_g9_row.sh <row-key> <run-id-prefix>
```

The row key is one of `narrator-auto:p1`, `narrator-auto:p4`, `combat-auto:p1`,
`combat-auto:p4`, `transport-failure:p1`, `transport-failure:p4`,
`preferred-openai-rollback:p1`, or `preferred-openai-rollback:p4`. The helper
prepares one isolated `tmp/combat_capture/` copy, uses the repository venv,
`NEQ_OPEN_BROWSER=0`, and port 8360 only. It proves listener ownership through
`lsof` parent PID and sandbox-cwd checks, refuses any pre-existing/unowned 8360
listener, keeps server stdout in separate per-start logs, and never touches 8357.

For rollback rows the helper starts the prepared OpenRouter server, stops only
that owned listener, changes the sandbox to direct OpenAI without reseeding, and
restarts exactly once before the capture. It preserves both server logs and a
post-stop lifecycle record in the row bundle. Transport-failure rows use only
the sandbox-scoped one-shot injection. The offline evaluator reads the eight
finished bundles with `scripts/capture_evidence.py --gate g9 --run-dir ...`;
it emits readiness only, never G9 PASS. Missing or synthetic receipts, unknown
costs presented as zero, incomplete state/transcript/log evidence, and degraded
captures remain blocked. The primary inspects every bundle and records the live
verdict in the owning OpenSpec change.

### Runtime prerequisites

1. Sandbox prepared:
   `.venv/bin/python scripts/seed_combat_capture.py --prepare --party 4`
   (or `--party 1`). `--prepare` rebuilds `tmp/combat_capture/`, patches
   sandbox `WEB_PORT = 8360` and `ENABLE_COMBAT_TURN_TRACE = True`, and seeds
   characters, `party_tracker.json`, and a resumable encounter. `--party` is
   required with `--prepare`.
2. Port discipline: the sandbox serves on 8360 ONLY. NEVER start, inspect, or
   kill anything on port 8357 - that is the user's real session.
3. Interpreter: run the sandbox with the main repository venv python. The seed
   output prints the exact interpreter path in its `[NEXT]` lines.
4. Trace gate: confirm `tmp/combat_capture/model_config.py` contains
   `ENABLE_COMBAT_TURN_TRACE = True`. When it is `False`, re-run `--prepare`;
   do not hand-edit the sandbox.
5. Tooling: the driver needs `python-socketio` and `requests` from the main
   venv (both are already installed). The browser alternative additionally
   needs `playwright-cli --help` to succeed (or `npx playwright-cli <command>`)
   with Chromium installed - and is currently blocked in this session sandbox.
6. If a precondition fails, stop and report blocked status. Do not fabricate
   capture results.

## Primary Execution Contract (socket-driven driver)

The seeder prepares a sandbox; the driver never prepares, starts, stops, or
restores it. Every live action is primary/orchestrator-owned and requires the
separate authorization described above. One named run is one party size and one
matrix key. Reserve a different new run ID for every matrix row.

1. **Preflight and sandbox preparation (port 8360 only)**
   - Check `lsof -t -nP -iTCP:8360 -sTCP:LISTEN`; stop only a positively owned
     prior sandbox server. If ownership is uncertain, stop and report BLOCKED.
     Never inspect/stop port 8357.
   - Confirm the intended run ID under `tmp/router-rollout/g3/` does not exist.
     Do not mkdir the run directory; the named driver creates it after strict
     path validation. Keep server stdout in a separate project-relative tmp file.
   - Named 1-PC example:
     `.venv/bin/python scripts/seed_combat_capture.py --prepare --party 1 --scenario combat-smoke`
   - Named 4-PC example:
     `.venv/bin/python scripts/seed_combat_capture.py --prepare --party 4 --scenario combat-smoke`
   - For `surrender-exit`, pass `--branch surrender` or `--branch explicit-exit`
     to both prepare and drive. For `resume-replay`, prepare only
     `--phase complete`; never prepare `--phase replay`. Other named scenarios
     take their exact documented ID, with party 1 or 4.

2. **Start the owned server and drive one named run**
   - Start from `tmp/combat_capture` with the repository venv using
     `NEQ_OPEN_BROWSER=0 <venv-python> -c 'import run_web; run_web.main()'`;
     this capture-only entry uses the existing `main()` function to skip the
     optional `__main__` version-check/network and interactive preamble without
     changing normal CLI behavior. Use the same command for every restart.
     Capture stdout/stderr to a unique separate file under `tmp/` (for example
     `tmp/router-rollout/g3/server-<run-id>.log`). Wait for the server to listen
     on 8360 before driving. Do not use a bundle path as the live stdout
     destination; `--server-log` copies this separate existing owned file into
     the bundle.
   - 1-PC named example:
     `.venv/bin/python scripts/capture_drive.py --party 1 --scenario combat-smoke --run-dir tmp/router-rollout/g3/<run-id> --state-root tmp/combat_capture --server-log tmp/router-rollout/g3/server-<run-id>.log --url http://localhost:8360`
   - 4-PC named example:
     `.venv/bin/python scripts/capture_drive.py --party 4 --scenario combat-smoke --run-dir tmp/router-rollout/g3/<run-id> --state-root tmp/combat_capture --server-log tmp/router-rollout/g3/server-<run-id>.log --url http://localhost:8360`
   - For every named driver invocation, use the matching party/scenario and
     branch/phase values. For a resume pair, use the exact same explicit
     `--chain-id <chain-id>` on complete and replay, and a new `--run-dir` for
     each phase. Metadata flags `--declared-provider`, `--declared-profile`,
     and `--declared-model` are non-secret operator declarations only; they do
     not establish actual provider/model use. Actual runtime identity remains
     unknown unless response metadata observes it.
   - `--url` defaults to `http://localhost:8360` and is restricted to localhost,
     `127.0.0.1`, or `[::1]` at port 8360. The driver uses the real socket/REST
     contract. It waits for first output and then a processing-aware quiet
     window; a zero exit code alone is not a pass. Required timeouts, caps,
     missing artifacts, or failed assertions prevent readiness.

3. **Resume-replay lifecycle**
   - Complete phase: prepare once with
     `.venv/bin/python scripts/seed_combat_capture.py --prepare --party <1|4> --scenario resume-replay --phase complete`,
     then run the driver with that scenario/phase and a declared chain ID/new
     run ID. Preserve its completed turn and artifacts.
   - Stop only the positively identified owned 8360 sandbox server. Restart the
     SAME `tmp/combat_capture` sandbox without `--prepare`, `--restore`, or any
     reseed. Keep the same `--chain-id`, choose a different new run ID, and
     drive `--scenario resume-replay --phase replay` to observe the retained
     encounter after restart.
   - If the replay trace span is empty, it is not permission to reuse old trace
     rows or waive the replay checks. In the replay record, explicitly account
     for trace-enabled status, a freshly captured retained-span boundary,
     quiet readiness, health, before/after state, and history. The replay may
     label trace-derived observations N/A only where they are genuinely
     inapplicable; the evidence helper still requires the trace gate enabled,
     a newly copied zero-byte span with unchanged prefix, quiet readiness,
     healthy roster, and valid before/after state/history snapshots. No blanket
     degraded-evidence waiver or old-row reuse is allowed.

4. **Offline evaluation, primary review, and teardown**
   - The offline matrix evaluator reads existing run bundles only; it does not
     execute captures. Supply each selected bundle by repeating `--run-dir`,
     e.g. `.venv/bin/python scripts/capture_evidence.py --run-dir tmp/router-rollout/g3/<run-id-1> --run-dir tmp/router-rollout/g3/<run-id-2>`.
     The expected matrix contains 18 keys: 5 scenarios x 2 party sizes, 2
     surrender/exit branches x 2 party sizes, and 2 resume phases x 2 party
     sizes. Add a row only once and keep branch/phase keys distinct.
   - Automated status `READY_FOR_PRIMARY_REVIEW` only indicates a complete,
     structurally valid set of candidate live bundles. It is not PASS. The
     primary inspects each bundle and records PASS/FAIL/BLOCKED after inspection
     in the OpenSpec change and goal; do not automatically mark the task done.
   - Confirm trace/report, manifest, snapshots, checks, transcript, and copied
     server log are present in each bundle before teardown. Stop only the owned
     8360 process, then run `.venv/bin/python scripts/seed_combat_capture.py --restore`
     after all required evidence is safely preserved. Verify no listener remains
     on 8360 and the installed tree was untouched. Keep raw artifacts under
     `tmp/`; durable owning reports may summarize results and reference bundles.

## Extension Points

The ensemble is reusable beyond this baseline. In every case, keep the same
sandbox isolation, 8360-only port rules, and evidence handling.

- **Narration captures:** after `--prepare`, start the game and talk to Warden
  Mira in CA03 (Reliquary Alcove). She is the resident NPC and answers dialogue
  sent as `user_input`; the shrine and offering bowl are the check objects in
  the same room. Extend the scripted turn list in `scripts/capture_drive.py`
  (or send the same text through the browser alternative) instead of adding new
  test infrastructure.
- **Travel captures:** the arena connectivity is CA01 (Waystone Gate, the
  seeded start) -> CA02 (Training Pit) -> CA03 (Reliquary Alcove) -> CA04
  (Supply Cellar, locked). Script movement text between rooms and capture the
  same way; expect sparse or absent combat trace rows unless combat is also
  active.
- **Skill-check captures:** use the DC-annotated objects (shrine, offering
  bowl, cellar door with `Investigation DC 12` scratches) and declared check
  text; the runtime may pause on a `requestRoll` and wait for player
  resolution, so answer the roll prompt as the next scripted turn.
- **Router/model bake-off runs:** run identical scripted inputs against a
  different sandbox stack by editing only the sandbox model config after a
  fresh `--prepare`, then compare two `combat_latency_report.py` outputs. Keep
   the inputs identical so differences reflect the stack, not the script.
  These are optional future comparisons. The current rollout reuses accepted
  candidate selection and completed G1 evidence; G5's new same-current-model
  before/after reference is a hot-path gate, not a repeated candidate bake-off.
- **Adjusting scripted inputs:** the scenario steps in the Execution Contract
  are the checklist. Keep the deterministic commands exact for comparability,
  and keep free-text turns in-arena and non-lethal.
- **Expected trace evidence:** combat captures should show `stage` timing rows,
  `provider` rows for the combat sites that ran, and `decision` rows for the
  deterministic fast path. Narration, travel, skill-check, and observation-only
  replay captures may produce sparse combat rows; use only the explicitly
  declared applicability rules for their required checks. A degraded report,
  missing required evidence, or an empty span outside the validated replay case
  is not waived by a transcript or server log.

## Guardrails

- Never write to the installed tree. All sandbox state lives under
  `tmp/combat_capture/`, and all copied evidence lives under `tmp/`.
- Never touch port 8357 or the user's real campaign. If 8360 ownership cannot
  be confirmed, stop and report instead of killing blindly.
- The driver never starts, stops, prepares, or restores the sandbox; those
  steps stay explicit so port ownership stays confirmed.
- Do not commit, amend, push, or otherwise modify git history as part of a
  capture.
- Keep all output ASCII-only (Windows cp1252 safety).
- Keep raw reports/evidence under `tmp/`; durable owning OpenSpec reports may
  contain concise primary summaries and references, not raw capture artifacts.
- Do not fabricate results. Blocked or failed captures must be reported as
  blocked/failed with the failure screenshot path (browser alternative) or the
  driver transcript (socket path).
- Do not kill user browser processes; the `-s=capture` playwright session, when
  used, is the only browser session this skill owns.
- One send at a time; the driver enforces this by waiting for the turn's
  first output and then a processing-aware quiet window before the next turn.

## Appendix: Browser Alternative (playwright-cli)

Retained for environments where a browser can launch. Note: browsers are
blocked in the current session sandbox (headless-shell SIGSEGV; nono path
checks ALLOWED), so this appendix is documentation-only until a browser-capable
environment is used.

Prerequisites: `playwright-cli --help` succeeds (or fall back to
`npx playwright-cli <command>`), Chromium is installed, and the sandbox is
prepared/started exactly as in the primary path steps 1-3.

1. **Browser session and start gate**
   - `playwright-cli -s=capture open http://localhost:8360`
   - `playwright-cli -s=capture snapshot` and confirm the app rendered.
   - Locate `#start-button` in the snapshot and click its ref.
   - Poll snapshots until `#user-input` exists and is enabled. The seed sets
     `worldConditions.activeCombatEncounter`, so combat resumes directly in the
     PC phase. If the startup wizard or an empty campaign appears instead,
     stop: the sandbox seed is invalid and must be re-prepared.

2. **Wait heuristic after every send**
   - Fill `#user-input` and press Enter, or click `#send-button`. One send per
     turn.
   - Backend processing disables `#user-input` and `#send-button`
     (`backendIsProcessing`); after each send, poll `snapshot` until
     `#send-button` is enabled again before typing the next input.
   - Cap each turn at 150 s. If snapshot polling is unreliable, fall back to
     `run-code` waits that poll
     `document.getElementById('send-button').disabled` in a bounded loop, then
     re-check with `snapshot`.
   - Capture a screenshot ONLY on failure:
     `playwright-cli -s=capture screenshot --filename=tmp/capture_failure_<step>.png`
   - Never queue a second input while the send button is disabled.

3. **4-PC scenario (--party 4): three rounds with tab switching**
   - Party roster: Acheron, Merisiel, Kira, Vitreol (initiative 20/18/16/14).
     Enemies: Goblin Alpha (initiative 10) and Goblin Beta (initiative 8),
     each AC 12 and 20 HP.
   - Switch the active PC before each turn: click the ref for
     `.character-tab[data-character="<PC name>"]` (tabs render under
     `#character-tabs-list`).
   - Deterministic pair per round (suggested: Acheron and Merisiel), one turn
     each:
     - `/att Goblin Alpha 20 training blade`, then wait for the hit line.
     - `/dmg 2`, then wait for the applied-damage line.
   - Free-text pair per round (suggested: Kira and Vitreol), one LLM action
     each, for example `Kira snipes at Goblin Beta from the pit rim.` Keep
     free-text turns inside the arena and non-lethal so the seeded enemies
     survive all three rounds.
   - After round 1 PC actions, send `/end` to run the enemy batch; wait for the
     batch to resolve (send enabled again and the round advances).
   - Rounds 2-3: repeat the four PC turns, then send `/end` only when the
     runtime prompt shows the PC phase completed and asks for the enemy-phase
     trigger. Finish after round 3 or when combat ends, whichever comes first.
   - Modest deterministic damage (2 per deterministic PC per round) keeps
     Goblin Alpha alive across the run. If an enemy dies early, let the capture
     continue and note the deviation in the report.

4. **1-PC scenario (--party 1): one round**
   - Party roster: Acheron only. Enemy: Goblin (AC 12, 20 HP).
   - One deterministic turn: `/att Goblin 20 training blade`, wait, then
     `/dmg 2`, wait.
   - One free-text turn, for example `Acheron presses the goblin back toward
     the pit wall.` If the runtime reports the PC has already acted for the
     round, treat that as expected and proceed.
   - Send `/end` to run the enemy phase and complete the one-round capture.

5. **Browser teardown**
   - Close the browser session: `playwright-cli -s=capture close`.
   - Then run teardown exactly as in the primary path step 6.
