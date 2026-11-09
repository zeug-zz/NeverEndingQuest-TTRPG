# Compression event inventory finding

## Reachability

`web/web_interface.py:385` constructs the host `SocketIO` object for the Flask
app. `emit_compression_event` at lines 653-657 calls `socketio.emit(event_type,
data)` at line 655, without a namespace or player-room argument. The installed
Flask-SocketIO implementation defaults an omitted `namespace` to `/`
(`.venv/lib/python3.13/site-packages/flask_socketio/__init__.py:463`).

The player listener is a separate `socketio.AsyncServer` in
`web/extensions/player/app.py:506-523`, configured only for `PLAYER_NAMESPACE`
(`/player`) and wrapped in its own ASGI app at lines 533-537. Its host bridge
accepts only payload-free `transcript`, `active_pc`, and `combat` notices
(`utils/player_host_publication.py:16-27,72-92,150-166`). The player app
rereads canonical state and emits `player.event`/`player.snapshot` only to
authorized player socket IDs with `namespace=PLAYER_NAMESPACE`
(`web/extensions/player/app.py:918-964,966-1002`). The compression callback
does not use that bridge. The in-process inventory fixture confirms dispatch
to host namespace `/` and trips if the player emitter is called. **Finding:
host-only; no compression payload reaches the player listener or clients.**

Only `dynamic:emit:web/web_interface.py:emit_compression_event:655` is
classified `HOST_ONLY`. The previous `:648` inventory anchor was stale; the
live emission is at line 655.

## CI coverage

The three workflow files are `security-audit.yml`, `ascii-compliance.yml`, and
`opencode.yml`. None invokes `scripts.test_player_route_inventory` or a test
runner; the ASCII workflow calls only `scripts/check_ascii_compliance.py`.
The route-inventory unittest is not currently covered by CI.

**Proposed, not applied:** add a dedicated Python test job to the security
workflow that installs repository requirements and runs
`python -m unittest -q scripts.test_player_route_inventory`. No workflow change
is included in this task.

The 8 route-inventory tests passed with socket bind/listen/connect/connect_ex,
`getaddrinfo`, and `create_connection` tripwires installed. Six selected
player access tests covering login/CSRF, session revocation, Origin/Host, and
Socket.IO authentication also passed under those tripwires.

## Scope and status

No host/runtime, player auth/Origin/CSRF, media, transport, or CI code was
changed. Task 6.2 remains open; historical N2 failure and unknown image
outcome remain unchanged. No browser, listener, provider, gameplay, or network
activity was performed.
