# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Positive player registrations and explicit host-surface classifications.

Player allowlists intentionally describe the registrations implemented today,
not the larger target surface in the OpenSpec contract. Tasks 3.2 and 4.x may
add spec-listed routes/events only alongside explicit allowlist and test
updates. Host classifications describe possible typed projections/commands;
they never authorize reuse of the host route, handler, or emission.
"""

from __future__ import annotations

from collections.abc import Iterable


HOST_ONLY = "host-only"
PLAYER_PROJECTION_OR_TYPED_COMMAND = "player-projection/typed-command"
PUBLIC_LOGIN_SHELL_ASSET = "public-login-shell-asset"
HOST_SURFACE_CLASSES = frozenset(
    {
        HOST_ONLY,
        PLAYER_PROJECTION_OR_TYPED_COMMAND,
        PUBLIC_LOGIN_SHELL_ASSET,
    }
)

# Player HTTP registrations are a positive subset of the spec-defined surface.
# Gameplay input events remain unregistered until the sync/runtime tasks.
PLAYER_HTTP_ALLOWLIST = frozenset(
    {
        ("GET", "/"),
        ("GET", "/static/player/<asset-id>"),
        ("POST", "/api/player/login"),
        ("POST", "/api/player/logout"),
        ("GET", "/api/player/snapshot"),
        ("GET", "/api/player/media/<media-id>"),
    }
)

# Only typed input submission is registered at this stage. Socket.IO
# connect/disconnect are transport lifecycle events, kept outside the gameplay
# allowlist. The server emits typed receipts/errors and projected player events.
PLAYER_SOCKET_EVENT_ALLOWLIST = frozenset({"player.input.submit"})
PLAYER_SOCKET_EMISSION_ALLOWLIST = frozenset(
    {"player.event", "player.input.receipt", "player.error"}
)
PLAYER_SOCKET_LIFECYCLE_EVENTS = frozenset({"connect", "disconnect"})


_PUBLIC_LOGIN_SHELL_HTTP_ROUTES = (
    "/static/dm_logo.png",
    "/static/icons/<path:filename>",
)

_PLAYER_PROJECTION_OR_TYPED_COMMAND_HTTP_ROUTES = (
    "/api/character_sheet/pdf",
    "/api/journal/players-diary",
    "/api/journal/story-so-far/pdf",
    "/api/party",
    "/api/party/set_active",
    "/get_character_data",
    "/media/<media_type>/<path:filename>",
    "/spell-data",
    "/static/media/videos/<path:filename>",
    "/static/portraits/<path:filename>",
)

_HOST_ONLY_HTTP_ROUTES = (
    "/",
    "/api/character_sheet/readiness_repair/apply",
    "/api/character_sheet/readiness_repair/preview",
    "/api/journal/diary",
    "/api/memory/entity/<entity_id>",
    "/api/party/add_character",
    "/api/party/characters",
    "/api/party/create_manual",
    "/api/party/create_player",
    "/api/party/creation_status",
    "/api/party/finalize_creation",
    "/api/party/promotion/apply",
    "/api/party/promotion/preview",
    "/api/party/remove_character",
    "/api/party/update_manual",
    "/api/portrait/create",
    "/api/settings/browser",
    "/api/toolkit/add-to-bestiary",
    "/api/toolkit/check_existing_images",
    "/api/toolkit/export-monsters-to-pack",
    "/api/toolkit/generate",
    "/api/toolkit/homebrew/jobs/<job_id>",
    "/api/toolkit/homebrew/jobs/<job_id>/apply_classification",
    "/api/toolkit/homebrew/jobs/<job_id>/build",
    "/api/toolkit/homebrew/jobs/<job_id>/cleanup",
    "/api/toolkit/homebrew/jobs/<job_id>/retry-from-finishing",
    "/api/toolkit/homebrew/jobs/<job_id>/retry-from-packet",
    "/api/toolkit/homebrew/jobs/<job_id>/review",
    "/api/toolkit/homebrew/jobs/active",
    "/api/toolkit/homebrew/upload",
    "/api/toolkit/modules",
    "/api/toolkit/modules/<module_name>/adventure.md",
    "/api/toolkit/modules/<module_name>/media/<media_type>/<path:filename>",
    "/api/toolkit/modules/<module_name>/monsters",
    "/api/toolkit/modules/<module_name>/npcs",
    "/api/toolkit/modules/<module_name>/unified-assets",
    "/api/toolkit/monsters",
    "/api/toolkit/npcs/description",
    "/api/toolkit/npcs/export-to-pack",
    "/api/toolkit/npcs/fetch-descriptions",
    "/api/toolkit/npcs/generate-portraits",
    "/api/toolkit/packs",
    "/api/toolkit/packs/<pack_name>",
    "/api/toolkit/packs/<pack_name>/activate",
    "/api/toolkit/packs/<pack_name>/export",
    "/api/toolkit/packs/<pack_name>/merge",
    "/api/toolkit/packs/<pack_name>/npcs/<npc_id>/image",
    "/api/toolkit/packs/<pack_name>/npcs/<npc_id>/thumbnail",
    "/api/toolkit/packs/<pack_name>/npcs/<npc_id>/video",
    "/api/toolkit/packs/create",
    "/api/toolkit/packs/import",
    "/api/toolkit/packs/preview",
    "/api/toolkit/process-video",
    "/api/toolkit/promote-to-bestiary",
    "/api/toolkit/settings",
    "/api/toolkit/static-cache/audit",
    "/api/toolkit/static-cache/rebuild",
    "/api/toolkit/world/jobs/<job_id>",
    "/api/toolkit/world/sources/build-atoms",
    "/api/toolkit/world/sources/extract",
    "/api/toolkit/world/sources/ingest",
    "/api/toolkit/world/sources/upload",
    "/api/tts",
    "/graphic_packs/<path:filename>",
    "/static/<path:filename>",
    "/toolkit",
    "/toolkit/create_pack",
    "/toolkit/get_monster_description/<monster_id>",
    "/toolkit/get_style_prompt/<style_id>",
    "/toolkit/get_styles",
    "/toolkit/pack_image/<pack_name>/<filename>",
    "/toolkit/pack_video/<pack_name>/<filename>",
    "/toolkit/save_style_template",
    "/toolkit/update_monster_description",
    "/toolkit/update_style_prompt",
    "/upload-portrait",
)

_PLAYER_PROJECTION_OR_TYPED_COMMAND_INBOUND_EVENTS = (
    "connect",
    "request_initiative_data",
    "request_location_data",
    "request_npc_inventory",
    "request_npc_saves",
    "request_npc_skills",
    "request_npc_spells",
    "request_party_data",
    "request_player_data",
    "request_status",
    "user_input",
)

_HOST_ONLY_INBOUND_EVENTS = (
    "action",
    "cancel_build",
    "generate_image",
    "generate_unified_assets",
    "request_module_list",
    "request_plot_data",
    "request_storage_data",
    "start_build",
    "start_game",
    "test_module_progress",
    "toggle_model",
    "trigger_update",
    "user_exit",
)

_PLAYER_PROJECTION_OR_TYPED_COMMAND_EMISSIONS = (
    "cached_messages",
    "connected",
    "game_output",
    "initiative_data_response",
    "location_data_response",
    "narration_stream_commit",
    "narration_stream_delta",
    "narration_stream_end",
    "narration_stream_error",
    "narration_stream_start",
    "narration_stream_superseded",
    "npc_details_response",
    "npc_inventory_response",
    "party_data_response",
    "player_data_response",
    "status_response",
    "status_update",
)

_HOST_ONLY_EMISSIONS = (
    "archive_zip_list_response",
    "bestiary_update_complete",
    "bestiary_update_error",
    "bestiary_update_progress",
    "build_started",
    "debug_output",
    "error",
    "exit_acknowledged",
    "game_started",
    "generation_complete",
    "generation_error",
    "generation_progress",
    "image_generated",
    "image_generation_error",
    "model_toggled",
    "module_complete",
    "module_creation_progress",
    "module_error",
    "module_list_response",
    "module_progress",
    "npc_description_progress",
    "npc_generation_complete",
    "npc_portrait_progress",
    "plot_data_response",
    "reset_complete",
    "restore_complete",
    "save_list_response",
    "storage_data_response",
    "system_message",
    "token_update",
    "unified_generation_complete",
    "unified_generation_progress",
    "update_complete",
    "update_error",
    "update_log",
    "version_status",
)

# Dynamic event names stay visible as call-site inventory entries. The
# compression callback emits host-only telemetry; the narration callback can
# become a typed player projection, while the chat wrapper mirrors arbitrary
# host emissions and therefore remains host-only.
_DYNAMIC_EVENT_CALLSITES = {
    "dynamic:emit:web/web_interface.py:emit_compression_event:635": HOST_ONLY,
    "dynamic:emit:web/extensions/live_chat_monitor.py:setup_live_chat_monitor._tabletop_mode_emit_wrapper:91": HOST_ONLY,
    "dynamic:emit:web/extensions/streaming_events.py:_emit:164": PLAYER_PROJECTION_OR_TYPED_COMMAND,
}


def _make_host_surface_classification() -> dict[str, str]:
    """Build the explicit category-to-surface table and reject overlaps."""
    groups: tuple[tuple[str, str, Iterable[str]], ...] = (
        ("http", PUBLIC_LOGIN_SHELL_ASSET, _PUBLIC_LOGIN_SHELL_HTTP_ROUTES),
        (
            "http",
            PLAYER_PROJECTION_OR_TYPED_COMMAND,
            _PLAYER_PROJECTION_OR_TYPED_COMMAND_HTTP_ROUTES,
        ),
        ("http", HOST_ONLY, _HOST_ONLY_HTTP_ROUTES),
        (
            "inbound",
            PLAYER_PROJECTION_OR_TYPED_COMMAND,
            _PLAYER_PROJECTION_OR_TYPED_COMMAND_INBOUND_EVENTS,
        ),
        ("inbound", HOST_ONLY, _HOST_ONLY_INBOUND_EVENTS),
        (
            "emission",
            PLAYER_PROJECTION_OR_TYPED_COMMAND,
            _PLAYER_PROJECTION_OR_TYPED_COMMAND_EMISSIONS,
        ),
        ("emission", HOST_ONLY, _HOST_ONLY_EMISSIONS),
    )
    result: dict[str, str] = {}
    for surface_kind, classification, surfaces in groups:
        for surface in surfaces:
            key = f"{surface_kind}:{surface}"
            if key in result:
                raise ValueError(f"duplicate host surface classification: {key}")
            result[key] = classification
    for key, classification in _DYNAMIC_EVENT_CALLSITES.items():
        if key in result:
            raise ValueError(f"duplicate host surface classification: {key}")
        result[key] = classification
    return result


HOST_SURFACE_CLASSIFICATION = _make_host_surface_classification()
