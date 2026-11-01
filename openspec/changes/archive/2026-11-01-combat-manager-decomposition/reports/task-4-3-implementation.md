# Task 4.3 - Bounded Capture_Arena Scenario Tooling

Status: **Implementation and provider-free verification submitted for primary review. Task 4.3 remains unchecked. No live capture or G3 verdict.**

## Scope and preserved boundaries

- Extended only the existing `scripts/seed_combat_capture.py`,
  `scripts/capture_drive.py`, and `scripts/combat_latency_fixtures.py` paths;
  added focused `scripts/test_capture_drive.py` coverage.
- Profiles are static in-code cases, not external scenario data or a generalized
  framework. Bare legacy `--party 1|4` still selects the fixed latency scripts.
  Their PC names, input text, round counts and seeded encounter payload builders
  are unchanged. The regression suite locks the complete 26-input MP script and
  the exact 1-PC script.
- The driver only connects to an already-running sandbox; it has no server
  prepare/start/stop/restore behavior. `run(args)` validates every URL, bare or
  named, before constructing a session: only HTTP root URLs for `localhost`,
  `127.0.0.1`, or `[::1]` on port 8360 are accepted; credentials, query,
  fragment, non-root path, remote host and other ports are refused. Named case
  transcript/trace paths must resolve under repository `tmp/`. The seeder still
  confines its owned copy to `tmp/combat_capture/` and rejects the resume replay
  phase before destructive prepare work. No live `--prepare`, restore, server,
  socket, provider, or campaign operation was run for this task.
- The separate allied/inactive variant is supported for both party sizes. It
  adds a distinct `Blairen` NPC character, an encounter `type=npc`,
  `npcType=ally` actor, and `partyNPCs` ally projection. It adds a distinct
  defeated `Inactive Goblin` without defeating either baseline living target,
  including the sole 1-PC `Goblin`. The sandbox already copies
  `web/static/media/npcs/blairen.jpg` and its thumbnail, so the ally has reusable
  fixture media and does not require a new auto-generation flag or product
  default. Static character, party, and encounter shapes validate against their
  existing schemas.

## Implemented named choices and declared bounds

Seeder and driver help expose the following scenario IDs:
`combat-smoke`, `combat-smoke-allied-inactive`, `initiative-pc`,
`initiative-dm-tie`, `death-save`, `surrender-exit`, and `resume-replay`.
Invalid IDs, unsupported party sizes, invalid scenario/branch/phase combinations,
and preparing a `resume-replay --phase replay` sandbox are rejected; there is no
quietly skipped scenario.

| Case | Party | Seed/input outline | Max steps | Max control requests |
|---|---:|---|---:|---:|
| `combat-smoke` | 1 | Legacy one-round Acheron script plus optional one `/init` fallback | 5 | 7 |
| `combat-smoke` | 4 | Legacy three-round roster script plus optional one `/init` fallback and `/end` at each of three pending enemy phases | 22 | 35 |
| `combat-smoke-allied-inactive` | 1 | Same bounded one-round script; separate inactive enemy preserves the living `Goblin` target | 5 | 7 |
| `combat-smoke-allied-inactive` | 4 | Same bounded roster script, allied NPC plus distinct inactive enemy | 22 | 35 |
| `initiative-pc` | 1/4 | DM group 8; `/init 21`, then `/init 18` | 2 | 4 |
| `initiative-dm-tie` | 1/4 | DM group 12; `/init 21`, then `/init 12` tie | 2 | 4 |
| `death-save` | 1 | Acheron seeded at 0 HP, unconscious, 0/0 saves; invalid 21 then legal 10 | 2 | 4 |
| `death-save` | 4 | Same; wrong-actor 10 as Merisiel, then invalid 21 and legal 10 for Acheron | 3 | 7 |
| `surrender-exit --branch surrender` | 1/4 | Party accepts the known last hostile's surrender offer and restrains it; other hostiles are seeded inactive | 1 | 3 |
| `surrender-exit --branch explicit-exit` | 1/4 | Separate `/end_combat` run | 1 | 3 |
| `resume-replay --phase complete` | 1/4 | One completed attack/damage turn before primary restart | 2 | 4 |
| `resume-replay --phase replay` | 1/4 | After primary restarts the same copy, `start_game` only; no gameplay input | 0 | 1 |

Step bounds include the optional initial initiative fallback; the 4-PC smoke
bound also allows a pending `/end` on rounds 2 and 3 in addition to the legacy
round-1 trigger. Control-request bounds include `start_game`, all `user_input`
events, and `/api/party/set_active` calls; active-PC switch budgets are separately
bounded. Logs distinguish step/control attempts from confirmed-sent counts and
track cap-blocked attempts separately; a blocked unsent action is never counted
as sent. The 4-PC wrong-actor death-save subcheck is explicitly marked
applicable only to the 4-PC death-save case. For resume replay, the primary owns
the server restart between separate `complete` and `replay` driver invocations;
the replay driver never calls the seeder and never sends a second gameplay
command. The replay seed phase is not preparable.

## Focused test coverage

`scripts.test_capture_drive` arms fatal SDK/network/outside-write guards before
importing the fixtures and driver, then uses a fake Socket.IO transport, fake
REST response and fake filesystem writer under unique `tmp/` roots. It checks
every applicable case/party pair; all pending enemy-end branches and optional
initiative fallback; bare legacy 19-step fake count; separate surrender and
explicit-exit branches; same-sandbox complete/replay phases; sent versus
attempted bounds; death-save wrong-actor/invalid-roll state preservation through
the existing combat manager with persistence stubbed; merged death-save character
fields; persisted fake seed files; schema validation; ally/NPC classification,
party projection and reused media; source event payloads; default latency input
invariants; and endpoint rejection before transport construction for both bare
and named captures (including port 8357, remote/alternate ports, malformed URL,
userinfo, query/fragment, and non-root path). Valid `localhost`, `127.0.0.1`, and
`[::1]` port-8360 forms are accepted only with fake transport. Invalid inputs
assert zero session construction, connect, `start_game`, and REST calls. Synthetic
responses remain only test observations, not gameplay evidence.

Observed verification (separate commands/processes):

- `TMPDIR="$PWD/tmp" PYTHONPYCACHEPREFIX="$PWD/tmp/pycache" .venv/bin/python -m py_compile scripts/seed_combat_capture.py scripts/capture_drive.py scripts/combat_latency_fixtures.py scripts/test_capture_drive.py` -> PASS.
- `TMPDIR="$PWD/tmp" PYTHONPYCACHEPREFIX="$PWD/tmp/pycache" .venv/bin/python -m unittest -q scripts.test_capture_drive` -> 14/14 PASS, including proof that invalid CLI profiles and unsafe endpoints fail before transport construction and `resume-replay --phase replay` cannot call destructive prepare.
- `scripts.test_combat_latency_baseline` -> 24/24 PASS in a guarded test runner with a fake chat client, fatal SDK/network tripwires and writes confined to `tmp/`; default behavior is also locked by exact input-script assertions in the focused suite.
- `TMPDIR="$PWD/tmp" PYTHONPYCACHEPREFIX="$PWD/tmp/pycache" .venv/bin/python -m unittest -q scripts.test_combat_surrender_exit_flow` -> 4/4 PASS.
- `scripts/capture_drive.py --help` and `scripts/seed_combat_capture.py --help` -> PASS; implemented IDs/options listed above; driver help explicitly says it never starts or stops the server. No live CLI capture, prepare, restore, or server command was run.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate combat-manager-decomposition --strict` -> PASS.
- `python3 scripts/check_ascii_compliance.py --summary-only` -> PASS (752 scanned, 0 violations).
- `git diff --check` -> PASS (no output).

## Parent-provided 4.2 context (not 4.3 evidence)

Parent-primary status supplied for 4.2: **checked by parent** on 552 tests in 30
separate processes (core 309, facade 131, other contracts 112), including source
ownership and legacy-loader nested-patch repair. This is recorded as supplied
4.2 parent evidence only; no 4.2 test was rerun in this task. The 4.2 checkbox
alone was reconciled in `tasks.md`; 4.3 remains unchecked. Parent-reported adjacent
UI status remains 8/9 with one unrelated baseline UI failure; no UI files were
changed and no claim that all suites are green is made.

Task 4.3 is still unchecked pending planner review. Task 4.4 evidence/manifests,
state snapshots, required-check evaluation and incomplete-evidence rejection are
not implemented here and remain next. Primary-owned live G3 captures, verdict,
and the package size gate remain outstanding; no required capture was waived.
