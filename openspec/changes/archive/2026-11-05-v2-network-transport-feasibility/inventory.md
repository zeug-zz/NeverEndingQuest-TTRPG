# Host Surface Inventory (Phase 0, change `v2-network-transport-feasibility`)

Derived from the tree at the worktree baseline (branch `feature/v2-network`,
HEAD `5519e87f`) with:

```bash
grep -rn "@app.route\|@socketio.on\|socketio.emit\|emit(\|\.route(\|add_url_rule\|register_blueprint\|Blueprint(\|namespace" web --include='*.py'
```

Counts: 89 `@app.route` decorators (56 in `web/web_interface.py`; 12
`web/routes/tabletop_party_routes.py`; 10 `toolkit_homebrew_routes.py`; 5
`world_narrative_routes.py`; 4 `memory_routes.py`; 2 `browser_settings_routes.py`),
24 `@socketio.on` handlers (all in `web/web_interface.py`), no blueprints, no
explicit Socket.IO namespaces (everything is on the default `/` namespace).
`web/routes/character_sheet_routes.py` and `web/extensions/tabletop_socket_handlers.py`
contain only `*_impl` helpers that `web_interface.py` routes call; they register
nothing themselves.

Capability classes are INITIAL and conservative (default `host-only`). They are
planning input for `v2-player-security-contract` (Phase 1), which owns the final
positive allowlist. Classes:

- `host-only`: never reachable from the player listener.
- `candidate-player`: may become player-reachable only through a typed gateway
  command or a server-built projection after Phase 1 review; never as a
  pass-through to the existing handler.
- `public-static`: login-shell assets with no session or game data.

Nothing in this change implements an allowlist or exposes any of these.

## 1. HTTP routes

Line numbers are `web/web_interface.py` unless a file is named.

### 1.1 Game and gameplay-adjacent

| Route | Purpose | Class |
| --- | --- | --- |
| `GET /` (1057) | Facilitator game UI (`game_interface.html`) | host-only (player `/` redirects to `/client` or login in N1+) |
| `GET /static/dm_logo.png` (1118) | Logo | public-static |
| `GET /static/icons/<path>` (1127) | UI icons | public-static |
| `GET /static/portraits/<path>` (1140) | Character/NPC portraits | candidate-player (bounded identifiers) |
| `GET /static/media/videos/<path>` (1108) | Video media | candidate-player (bounded identifiers) |
| `GET /media/<media_type>/<path>` (1153) | Module media (monsters/npcs/environment) | candidate-player (bounded identifiers) |
| `GET /graphic_packs/<path>` (433) | Graphic pack assets | host-only (candidate later if packs become gameplay media) |
| `GET /get_character_data` (1333) | Character sheet JSON | candidate-player (read-only projection) |
| `GET /spell-data` (1685) | Spell reference data | candidate-player |
| `GET /api/character_sheet/pdf` (1695) | Character sheet PDF | candidate-player (read-only) |
| `POST /api/character_sheet/readiness_repair/preview` (1701) | Sheet repair preview | host-only |
| `POST /api/character_sheet/readiness_repair/apply` (1708) | Sheet repair apply (mutation) | host-only |
| `POST /upload-portrait` (1362) | Portrait upload | host-only |
| `POST /api/portrait/create` (1563) | AI portrait generation | host-only |
| `POST /api/tts` (4796) | Host-local TTS | host-only (TTS stays host-local) |
| `GET /api/memory/entity/<id>` (routes/memory_routes.py:28) | Entity memory lookup | host-only (may leak GM knowledge) |
| `GET /api/journal/diary` (memory_routes.py:60) | Session diary | host-only until projection review |
| `GET /api/journal/players-diary` (memory_routes.py:120) | Players' diary | candidate-player (projection review) |
| `GET /api/journal/story-so-far/pdf` (memory_routes.py:143) | Story PDF | candidate-player (projection review) |
| `GET /api/settings/browser`, `POST /api/settings/browser` (routes/browser_settings_routes.py:31,47) | Host browser settings | host-only |

### 1.2 Party (`web/routes/tabletop_party_routes.py`, registered at web_interface.py:4000)

| Route | Purpose | Class |
| --- | --- | --- |
| `GET /api/party` (120) | Party members and active character | candidate-player (via typed snapshot) |
| `POST /api/party/set_active` (137) | Set shared active PC (writes `party_tracker.json`) | candidate-player (typed gateway command with revision check, never this route) |
| `GET /api/party/characters` (163) | Add-existing candidate list | host-only |
| `POST /api/party/create_player` (271), `finalize_creation` (371), `GET creation_status` (483), `POST add_character` (503), `remove_character` (658), `promotion/preview` (772), `promotion/apply` (863), `create_manual` (988), `update_manual` (1160) | PC creation, party edit, NPC promotion | host-only |

### 1.3 Toolkit and module authoring (all host-only)

Toolkit pages and APIs in `web_interface.py`: `GET /toolkit` (1718);
`/api/toolkit/packs*` (1725-2086, incl. create, activate, export, delete, merge,
preview, import); `/api/toolkit/static-cache/audit|rebuild` (1798, 1813);
`/api/toolkit/export-monsters-to-pack` (1924); `/api/toolkit/monsters` (2136);
`/toolkit/pack_image|pack_video/...` (2155, 2171); `/api/toolkit/check_existing_images`
(2187); `/api/toolkit/generate` (2223); `/api/toolkit/process-video` (2278);
`/api/toolkit/add-to-bestiary` (2346); `/toolkit/get_style_prompt|get_styles|save_style_template|update_style_prompt|get_monster_description|update_monster_description|create_pack`
(2426-2662); `/api/toolkit/promote-to-bestiary` (2596); `/api/toolkit/settings` (2682);
`/api/toolkit/modules*` incl. monsters, unified-assets, adventure.md, npcs, media
(1292, 2720-3304, 4848); `/api/toolkit/npcs/*` and `/api/toolkit/packs/<pack>/npcs/*`
(4933-5675).
Plus `web/routes/toolkit_homebrew_routes.py` (10 routes, upload/review/build/
retry-from-packet/retry-from-finishing/cleanup/apply_classification/job status,
2621-3810) and `web/routes/world_narrative_routes.py` (5 routes, source upload/
extract/build-atoms/ingest/job status, 182-390).

## 2. Socket.IO inbound events (default namespace `/`, `web/web_interface.py`)

| Event (line) | Purpose | Class |
| --- | --- | --- |
| `connect` (3376) | Greets, starts version check, then replays cached messages and DRAINS the global game/debug/module-progress queues to the connecting client | candidate-player only as a rebuilt authenticated snapshot; existing handler is host-only (leaks debug output and consumes shared queues) |
| `request_status` (3405) | Busy/processing + game started flags | candidate-player |
| `user_input` (3443) | Tags input with `[character]`, echoes, enqueues to `user_input_queue` | candidate-player (typed command with request id, active-PC binding, busy policy; not this handler) |
| `request_player_data` (3729) | Sheet/inventory/etc. by `dataType` | candidate-player (projection) |
| `request_location_data` (3813) | Current location | candidate-player (projection) |
| `request_npc_saves` / `skills` / `spells` / `inventory` (3842-3953) | NPC detail modals | candidate-player (projection; secrets review) |
| `request_party_data` (3992) | Party cards (impl in `tabletop_socket_handlers.py`) | candidate-player (projection) |
| `request_initiative_data` (4002) | Initiative/combat | candidate-player (projection) |
| `request_plot_data` (4009) | Module plot (spoilers) | host-only |
| `request_storage_data` (4015) | Storage/inventory | host-only until reviewed |
| `action` (3486) | Multiplexed lifecycle: save list/create/restore/delete, archive zip, campaign reset | host-only |
| `start_game` (3650) | Starts the game thread | host-only |
| `user_exit` (4020) | Shutdown/restart | host-only |
| `toggle_model` (4063) | Switches model config; broadcasts `model_toggled` | host-only |
| `test_module_progress` (4081) | Debug simulation | host-only |
| `generate_image` (4112) | AI image generation | host-only |
| `request_module_list` (5740), `start_build` (6255), `cancel_build` (6269), `generate_unified_assets` (6326) | Module builder/toolkit | host-only |
| `trigger_update` (7004) | Runs `git fetch/pull` and `pip install` | host-only |

## 3. Server emissions

Emissions use `socketio.emit(...)` (broadcast to every connected client, no
rooms) or `emit(...)` (to sender) from handlers and background threads. Any
player socket attached to the host app would receive every global broadcast,
which is why the player listener is a separate application (see design D2).
`web/extensions/live_chat_monitor.py` wraps `socketio.emit` (idempotent monkey
wrap, ORIGINAL_EMIT_ATTR) to mirror chat; it is host-only plumbing.

| Event(s) | Source | Purpose | Class |
| --- | --- | --- | --- |
| `game_output`, `cached_messages` | queue drain at 4595/4726, connect, user_input | Transcript lines | candidate-player (ordered, sanitized projection) |
| `status_update`, `status_response` | 624, 1026, 3424-3432 | Busy/thinking state | candidate-player |
| `narration_stream_start/delta/end/error/superseded/commit` | `web/extensions/streaming_events.py:28-33` | Streaming narration | candidate-player (projection) |
| `player_data_response`, `location_data_response`, `npc_details_response`, `npc_inventory_response`, `party_data_response`, `initiative_data_response` | request handlers | Read-only panels | candidate-player (projection) |
| `connected`, `error` (generic message), `game_started`, `system_message` | various | Lifecycle/system notices | `connected`: candidate-player; others host-only until text reviewed |
| `debug_output`, `token_update`, `version_status`, `update_log/error/complete`, `model_toggled`, `exit_acknowledged` | various | Debug, cost, update, admin | host-only |
| `compression event` (dynamic `event_type`, 633-637) | status manager callback | Context compression telemetry | host-only |
| `save_list_response`, `archive_zip_list_response`, `restore_complete`, `reset_complete` | `action` | Save/reset lifecycle | host-only |
| `plot_data_response`, `storage_data_response` | request handlers | Spoilers / storage | host-only |
| `module_creation_progress`, `module_progress`, `module_error`, `module_complete`, `module_list_response`, `build_started` | builder | Module build | host-only |
| `generation_progress/complete/error`, `unified_generation_progress/complete/error`, `bestiary_update_progress/complete/error`, `npc_description_progress`, `npc_portrait_progress`, `npc_generation_complete`, `image_generated`, `image_generation_error` | toolkit | Asset generation | host-only |

## 4. State owners (authoritative; the player listener MUST NOT write these directly)

- Characters: character JSON files via `update_character_info()` and
  `safe_write_json()`.
- Party: `party_tracker.json` (including `active_character`); today
  `/api/party/set_active` writes it directly with `safe_write_json`.
- Combat: encounter files; initiative projection is built in
  `tabletop_socket_handlers.py`.
- Message cache (`load_message_cache`/`add_to_message_cache`) and
  `game_output_queue`, `debug_output_queue`, `user_input_queue`, `module_progress_queue`
  are process-global `queue.Queue` objects in `web_interface.py:452-455` and
  `web/shared_state.py`. The game loop runs in `game_thread` (started by
  `start_game`, 3705) in the same process, consuming `user_input_queue`.
- Runtime flags `game_thread`, `startup_in_progress` (456-457) with
  `startup_guard_lock`.

Consequence for integration: the authoritative runtime is a set of in-process
threads and queues inside the process that runs `web/web_interface.py`
(launched as a subprocess of `run_web.py`, which restarts it on exit code 0).
Any separate-process gateway therefore needs authenticated IPC; an in-process
gateway can call the same queues and readers behind a typed interface.

## 5. GUI extraction seams

- `web/templates/game_interface.html` plus inline/static JS own all DOM
  rendering; extraction targets are the typed projections behind
  `*_data_response` handlers (already partly extracted into
  `web/extensions/tabletop_socket_handlers.py`) and `output_markers.py`.
- `web/extensions/streaming_events.py` is a ready seam for narration stream
  events (names above, injected transport via `configure_stream_transport`).
- `web/routes/*.py` already use `register_*_routes(app, ...)` injection; a
  player gateway should be a new module, not an edit to these files.
- The monolith `web_interface.py` (7161 lines) is not decomposed in this
  change; no extraction edits are in scope.

## 6. Serving stack today

- `web/web_interface.py:7156` `socketio.run(app, host=WEB_HOST, port=..., allow_unsafe_werkzeug=True)`,
  default async mode `threading`.
- `app.config['SECRET_KEY'] = 'dungeon-master-secret-key'` (359): hardcoded,
  not a foundation for authenticated sessions.
- `utils/web_boundary.py`: `resolve_web_host` fails closed to `127.0.0.1`
  (rejects `0.0.0.0`/`::`/`*`); `resolve_socketio_origins` fails closed to a
  loopback origin list (`localhost`, `127.0.0.1`, `[::1]` on `WEB_PORT`, default
  8357). Both are reusable helpers for the spike's expected-origin policy.
- Installed (`.venv`): Flask-SocketIO 5.7.2, python-socketio 5.18.1,
  python-engineio 4.15.1, simple-websocket 1.1.0, Werkzeug 3.1.9. Note:
  `requirements-lock.txt` pins python-socketio 5.18.0 while the worktree `.venv`
  has 5.18.1; the lock/venv drift must be resolved by whoever adds dependencies
  (task 5.2). `uvicorn`, `aiohttp`, `websocket-client`, `pytest` are NOT installed.
- Repo tests are `unittest`-style `scripts/test_*.py` run as
  `.venv/bin/python scripts/test_<name>.py` (pytest is commented out in
  `requirements.txt`).

## 7. Installer and launcher paths

- macOS: `install_neverendingquest_macos.sh` creates `${INSTALL_DIR}/.venv`
  (lines 99-110) and launches `.venv/bin/python run_web.py` (136-137, 156).
- Windows: `install_neverendingquest_windows.bat` creates `venv` (213-250) and
  launches `venv\Scripts\python run_web.py` (330, 371). Windows server is out of
  scope for the release.
- Linux: no installer exists today; the plan commits to macOS and Linux hosts.
  N0 uses a Linux container or host and records the interpreter path used.
- Native companion binaries MUST NOT live in `.venv`/`venv`; N0 uses
  `tmp/n0/opentunnel/`; packaging location is an N3 decision.

## 8. Upstream React `/play` reuse

The one-time upstream React `/play` review (event typing, exact Socket.IO
arity, stores, hydration, reconnect, styling, tests) is a later N2 task
(`v2-react-player-foundation`). It is not performed or required by this change.
