---
name: neq-capture-arena
description: Run scripted captures of live combat and narration behavior against the sandboxed Capture_Arena module - socket-driven driver primary, playwright-cli as the documented browser alternative - then preserve trace evidence under tmp/.
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

## Trigger Phrases

- `run capture arena`
- `capture combat latency`
- `playwright capture combat`
- `run the capture ensemble`

## Preconditions

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

The driver never starts, stops, or prepares the sandbox. It only talks to an
already-running server on 8360. One run drives one party size.

1. **Preflight and port hygiene (8360 only)**
   - Check the sandbox port: `lsof -t -nP -iTCP:8360 -sTCP:LISTEN`.
   - If a listener exists, confirm it belongs to a previous `tmp/combat_capture`
     run before stopping it (`kill -TERM <pid>`, then `kill -KILL <pid>` only if
     needed). If ownership cannot be confirmed, stop and report.
   - NEVER run this check against 8357 and never stop a 8357 process.
   - Confirm `tmp/combat_capture/` exists; otherwise prepare it first.

2. **Prepare the sandbox**
   - `.venv/bin/python scripts/seed_combat_capture.py --prepare --party 4`
     (use `--party 1` for the 1-PC run; re-run `--prepare` when switching
     party size so the seeded roster matches the scenario).

3. **Start the sandbox server**
   - Run with the working directory set to `tmp/combat_capture`:
     `NEQ_OPEN_BROWSER=0 <main venv python> run_web.py`
   - This is a long-lived process: start it in the background and keep its
     stdout log at a project-relative path under `tmp/` when a log file is
     needed.
   - `NEQ_OPEN_BROWSER=0` keeps the server from opening the user's real
     browser. Wait until the server reports it is listening on 8360 before
     driving the capture.

4. **Drive the 4-PC capture**
   - `.venv/bin/python scripts/capture_drive.py --party 4 --trace-dst tmp/combat_baseline_mp.jsonl`
   - Defaults: `--url http://localhost:8360`, `--transcript
     tmp/capture_transcript_4.log`, `--trace-src
     tmp/combat_capture/debug/combat_turn_trace.jsonl`, `--start-timeout 180`,
     `--turn-timeout 150`, `--turn-quiet-seconds 1.5`.
   - The scripted scenario is fixed inside the driver:
     - Round 1: Acheron `/att Goblin Alpha 20 training blade`, then `/dmg 2`;
       Merisiel the same pair; Kira free text
       `Kira darts in and slashes at the nearest goblin`; Vitreol free text
       `Vitreol levels her crossbow at Goblin Beta and fires`; then `/end`.
     - Rounds 2-3: same shape with slightly adjusted free-text flavor, sending
       `/end` only when the prior output indicates the enemy phase is pending.
       The driver stops early when the transcript indicates combat has ended.
   - The driver switches the active PC with
     `POST /api/party/set_active` before each turn that needs a different PC.
     Per-turn completion is output-first and processing-aware: it waits for the
     turn's first new `game_output` (capped by `--turn-timeout`), then keeps
     waiting while `is_processing` is True or new `game_output` /
     `status_update` events keep arriving, and completes once the stream has
     been quiet for `--turn-quiet-seconds` while `is_processing` is False. It
     does NOT require a `status_update` true -> false edge, because
     deterministic fast-path replies (for example
     `[ALREADY_APPLIED] Hit!`) emit output with no true edge at all. A timeout
     is recorded only when no new `game_output` arrives within the cap. If the
     first outputs ask for an initiative entry (`/init`), it sends `/init 15`
     automatically and logs the fallback.
   - Turn timeouts and cap-reached turns are logged as warnings inside the
     transcript; they do not invalidate the run. The driver exits 0 when the
     scenario completed and non-zero only on connect/start failure.

5. **Preserve the trace and report**
   - `--trace-dst` copies the sandbox trace
     (`tmp/combat_capture/debug/combat_turn_trace.jsonl`) to the caller path
     BEFORE `--restore` deletes the sandbox, and prints source/destination
     record counts. Omit it only when a run is explicitly evidence-free.
     - 4-PC run: `tmp/combat_baseline_mp.jsonl`.
     - 1-PC run: `tmp/combat_baseline_one_pc.jsonl`.
   - Run the provider-free report:
     `.venv/bin/python scripts/combat_latency_report.py --trace <copied trace>`
     The report exits 0 with a `degraded` report for partial input and exits 2
     when the trace cannot be read.
   - Record actual counts in the capture report: total records, malformed
     count, stage rows, provider sites (calls/latency/tokens as observed),
     compression rows, file-operation rows, NL fast-path hits/misses, and
     decision rows. Do not extrapolate; do not fabricate missing sections.
   - Keep every evidence artifact under `tmp/`; never write capture output to
     `reports/`.

6. **Teardown**
   - Stop ONLY the 8360 listener:
     `lsof -t -nP -iTCP:8360 -sTCP:LISTEN`, then `kill -TERM <pid>` (use
     `kill -KILL <pid>` only if needed). If the sandbox server must be
     restarted at any point, use the same `NEQ_OPEN_BROWSER=0` start command.
   - Remove the sandbox:
     `.venv/bin/python scripts/seed_combat_capture.py --restore`
   - Re-check `lsof -t -nP -iTCP:8360 -sTCP:LISTEN`; it must print nothing.
   - Confirm the copied traces remain under `tmp/` and the installed tree is
     unchanged (`git status --short` shows no capture writes).

7. **Drive the 1-PC capture**
   - `--party 1` is independent of the multi-PC run and exercises the
     minimum-party tabletop path (ADR-0032):
     `.venv/bin/python scripts/seed_combat_capture.py --prepare --party 1`
     -> start the server as in step 3 -> drive the capture:
     `.venv/bin/python scripts/capture_drive.py --party 1 --trace-dst tmp/combat_baseline_one_pc.jsonl`
     (default transcript `tmp/capture_transcript_1.log`) -> preserve and
     report as in step 5 -> tear down as in step 6.
   - The scripted scenario is fixed inside the driver: Acheron
     `/att Goblin 20 training blade`, `/dmg 2`, one free-text turn
     (`Acheron presses the goblin back toward the pit wall`), then `/end`.
     The 1-PC seed names its single enemy `Goblin`
     (`scripts/combat_latency_fixtures.ONE_PC_ENEMY_NAME`), so the driver
     attacks that seeded name rather than the 4-PC `Goblin Alpha`.

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
- **Adjusting scripted inputs:** the scenario steps in the Execution Contract
  are the checklist. Keep the deterministic commands exact for comparability,
  and keep free-text turns in-arena and non-lethal.
- **Expected trace evidence:** combat captures should show `stage` timing rows,
  `provider` rows for the combat sites that ran, and `decision` rows for the
  deterministic fast path. Narration, travel, and skill-check captures may
  produce sparse combat rows; treat those reports as degraded evidence and lean
  on the driver transcript and the sandbox stdout log until the trace schema
  grows matching event types.

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
- Keep reports and evidence under `tmp/`; never write to `reports/`.
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
