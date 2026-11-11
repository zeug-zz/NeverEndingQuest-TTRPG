# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free projection, display, media, and player access tests."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from web.extensions.player import PLAYER_HOST, PLAYER_NAMESPACE, PLAYER_PORT, PlayerSnapshot, create_app
from web.extensions.player.assets import VerifiedPlayerClientAssets
from web.extensions.player.auth import PLAYER_SESSION_COOKIE, PlayerSecurity
from web.extensions.player.contracts import EVENT_FIELDS, PROTOCOL_VERSION
from web.extensions.player.limits import (
    EXPENSIVE_READS_PER_SESSION_PER_WINDOW,
    MAX_COMBATANTS,
    MAX_PLAYER_MEDIA_BYTES,
    MAX_PLAYER_TEXT_BYTES,
    MAX_TRANSCRIPT_BYTES,
    MAX_TRANSCRIPT_MESSAGES,
    MAX_TRANSCRIPT_SOURCE_ITEMS,
    MEDIA_READS_PER_SESSION_PER_WINDOW,
)
from web.extensions.player.media import (
    MediaRegistration,
    MediaRegistry,
    player_portrait_media_id,
)
from web.extensions.player.projections import (
    CHARACTER_FIELD_ALLOWLIST,
    COMBATANT_FIELDS,
    COMBAT_PROJECTION_FIELDS,
    PARTY_PROJECTION_FIELDS,
    PLAYER_EVENT_FIELD_ALLOWLIST,
    PLAYER_EVENT_TYPE_ALLOWLIST,
    PLAYER_PROJECTION_FIELDS,
    TRANSCRIPT_MESSAGE_FIELDS,
    TRANSCRIPT_PROJECTION_FIELDS,
    WORLD_FIELD_ALLOWLIST,
    ProjectionError,
    PlayerProjectionBuilder,
    project_player_event,
)
from web.extensions.player.rendering import render_safe_markdown

SCRATCH_ROOT = Path("tmp/n2")
PC_NAMES = ("Acheron", "Merisiel", "Kira", "Vitreol")
TEST_CLIENT_BUILD_ID = "0123456789abcdef0123456789abcdef"


class _FixtureGateway:
    def __init__(self, builder: PlayerProjectionBuilder) -> None:
        self.builder = builder

    def read_snapshot(self) -> PlayerSnapshot:
        return PlayerSnapshot(revision=7, projection=self.builder.build())


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("fixture canonical JSON must contain an object")
    return value


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")


def _load_player_transcript_reader(cache_path: Path) -> Any:
    from web import web_interface

    def read_transcript() -> Any:
        with mock.patch.object(web_interface, "MESSAGE_CACHE_FILE", str(cache_path)):
            return web_interface.read_player_transcript()

    return read_transcript


def _make_canonical_fixture(
    root: Path,
    party_size: int,
    *,
    projection_sources: dict[str, Any] | None = None,
) -> tuple[PlayerProjectionBuilder, list[str], list[str]]:
    names = list(PC_NAMES[:party_size])
    party_path = root / "canonical" / "party_tracker.json"
    character_paths: dict[str, Path] = {}
    private_path = root / "canonical" / "private_source.json"
    path_canary = private_path.as_posix()
    canaries = [
        "CANARY-HIDDEN-PLOT-SECRET",
        "CANARY-DM-NOTE",
        "CANARY-NPC-HIDDEN-STAT",
        "sk-player-boundary-canary-do-not-expose",
        path_canary,
        "CANARY-HOST-DEBUG-OUTPUT",
        "CANARY-ENEMY-HP-AND-AC",
    ]
    sharing_canaries = (
        "https://neq-share.account.opentunnel.xyz?token=player-invitation-canary",
        "player-sharing-credential-canary",
        "neq_player_session=player-cookie-canary",
        "-----BEGIN PRIVATE KEY-----player-private-key-canary-----END PRIVATE KEY-----",
        "player-companion-status-canary",
        "player-host-diagnostic-canary",
        "player-companion-output-canary",
    )
    canaries.extend(sharing_canaries)
    party_tracker: dict[str, object] = {
        "module": "CANARY-PRIVATE-CAMPAIGN-NAME",
        "partyMembers": names,
        "partyNPCs": [
            {
                "name": "Goblin",
                "role": "enemy",
                "currentHitPoints": 31,
                "armorClass": 16,
                "hidden_stats": canaries[2],
                "dm_notes": canaries[1],
            }
        ],
        "active_character": names[-1],
        "active_character_revision": 3,
        "worldConditions": {
            "year": 1492,
            "month": "Harvestmonth",
            "day": 4,
            "time": "Noon",
            "weather": "Clear",
            "season": "Autumn",
            "dayNightCycle": "day",
            "moonPhase": "Full",
            "currentLocation": "Lanternkeep",
            "currentArea": "North Road",
            "currentAreaId": "area-private-id",
            "majorEventsUnderway": [canaries[0]],
            "politicalClimate": canaries[0],
            "activeEncounter": canaries[1],
            "activeCombatEncounter": (
                canaries[6]
                if projection_sources is None
                else projection_sources.get("active_encounter_id", "")
            ),
            "weatherConditions": canaries[0],
            "dm_notes": canaries[1],
        },
        "hidden_plot_secret": canaries[0],
        "dm_notes": canaries[1],
        "api_key": canaries[3],
        "debug_output": canaries[5],
        "filesystem_path": path_canary,
        "campaign": {"private": canaries[0]},
        "player_sharing": {
            "state": "ready",
            "invitation": sharing_canaries[0],
            "credential": sharing_canaries[1],
            "session_cookie": sharing_canaries[2],
            "private_key": sharing_canaries[3],
            "companion_status": sharing_canaries[4],
            "host_diagnostic": sharing_canaries[5],
            "companion_output": sharing_canaries[6],
        },
    }
    _write_json(party_path, party_tracker)

    for index, name in enumerate(names):
        character_path = root / "canonical" / "characters" / f"pc-{index + 1}.json"
        character_paths[name] = character_path
        _write_json(
            character_path,
            {
                "name": name,
                "character_role": "player",
                "character_type": "player",
                "type": "player",
                "level": index + 3,
                "race": "Human",
                "class": "Fighter",
                "background": "Guard",
                "alignment": "neutral good",
                "size": "Medium",
                "status": "alive",
                "condition": "none",
                "condition_affected": [],
                "hitPoints": 21 + index,
                "maxHitPoints": 29 + index,
                "armorClass": 17,
                "initiative": 8 + index,
                "speed": 30,
                "abilities": {
                    "strength": 16,
                    "dexterity": 12,
                    "constitution": 14,
                    "intelligence": 10,
                    "wisdom": 11,
                    "charisma": 9,
                    "private_note": canaries[1],
                },
                "deathSaves": {
                    "successes": 0,
                    "failures": 0,
                    "dm_notes": canaries[1],
                },
                "savingThrows": ["Strength", "Constitution"],
                "skills": {"Athletics": 5, "Stealth": 1, "private": canaries[0]},
                "proficiencyBonus": 2,
                "portrait_media_id": player_portrait_media_id(name),
                "portrait_path": path_canary,
                "file_path": path_canary,
                "dm_notes": canaries[1],
                "hidden_plot_secret": canaries[0],
                "hidden_npc_stats": canaries[2],
                "enemy_hit_points": 999,
                "api_key": canaries[3],
                "debug_output": canaries[5],
                "raw_nested": {"secret": canaries[0], "file_path": path_canary},
            },
        )

    def read_party_tracker() -> dict[str, object]:
        return _read_json(party_path)

    def read_character_state(name: str) -> dict[str, object] | None:
        path = character_paths.get(name)
        return _read_json(path) if path is not None else None

    reader_options: dict[str, Any] = {}
    if projection_sources is not None:
        if "busy" in projection_sources:
            reader_options["read_busy_state"] = lambda: projection_sources["busy"]
        if "active_pc_state" in projection_sources:
            reader_options["read_active_pc_state"] = lambda: projection_sources[
                "active_pc_state"
            ]
        if "transcript" in projection_sources:
            def read_transcript_state() -> object:
                value = projection_sources["transcript"]
                if isinstance(value, Exception):
                    raise value
                return value

            reader_options["read_transcript_state"] = read_transcript_state
        if "transcript_reader" in projection_sources:
            reader_options["read_transcript_state"] = projection_sources[
                "transcript_reader"
            ]
        if "encounter" in projection_sources:
            def read_encounter_state(_encounter_id: str) -> object:
                value = projection_sources["encounter"]
                if isinstance(value, Exception):
                    raise value
                return value

            reader_options["read_encounter_state"] = read_encounter_state
    builder = PlayerProjectionBuilder(
        read_party_tracker,
        read_character_state,
        **reader_options,
    )
    return builder, names, canaries


def _dispatch_http(
    app: Any,
    method: str,
    path: str,
    *,
    cookie: str | None = None,
    body: bytes = b"",
    origin: str | None = None,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    headers = [(b"host", f"{PLAYER_HOST}:{PLAYER_PORT}".encode("ascii"))]
    if cookie is not None:
        headers.append((b"cookie", cookie.encode("ascii")))
    if path == "/api/player/snapshot" and cookie is not None:
        assets = app._client_assets
        if assets is None:
            assets = VerifiedPlayerClientAssets(
                shell_document=b"",
                shell_content_type=b"text/html; charset=utf-8",
                client_build_id=TEST_CLIENT_BUILD_ID,
                protocol_version=1,
                assets={},
            )
            app._client_assets = assets
        headers.extend(
            [
                (b"x-neq-client-build", assets.client_build_id.encode("ascii")),
                (b"x-neq-protocol-version", str(assets.protocol_version).encode("ascii")),
            ]
        )
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    if body:
        headers.append((b"content-length", str(len(body)).encode("ascii")))
    messages: list[dict[str, Any]] = []
    sent_body = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_body
        if sent_body:
            return {"type": "http.disconnect"}
        sent_body = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(
        app(
            {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": b"",
                "headers": headers,
            },
            receive,
            send,
        )
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), list(start["headers"]), response_body


def _header_map(headers: list[tuple[bytes, bytes]]) -> dict[bytes, bytes]:
    return {name.lower(): value for name, value in headers}


def _session(security: PlayerSecurity) -> tuple[str, str]:
    grant = security.create_session()
    if grant is None:
        raise AssertionError("fixture session could not be created")
    return (
        f"{PLAYER_SESSION_COOKIE}={grant.cookie_value}",
        grant.session_id,
    )


class PlayerCapabilitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)

    def _temporary_directory(self) -> Path:
        temporary = tempfile.TemporaryDirectory(prefix="player-capabilities-", dir=SCRATCH_ROOT)
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def test_projection_allowlists_support_one_and_four_pc_parties(self) -> None:
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                root = self._temporary_directory()
                builder, names, canaries = _make_canonical_fixture(root, party_size)
                projection = builder.build()
                party = projection["party"]
                self.assertTrue(set(projection) <= PLAYER_PROJECTION_FIELDS)
                self.assertEqual(set(party), PARTY_PROJECTION_FIELDS)
                self.assertEqual(
                    [member["name"] for member in party["members"]],
                    names,
                )
                self.assertEqual(party["active_character"], names[-1])
                self.assertEqual(set(party["world"]), WORLD_FIELD_ALLOWLIST & set(party["world"]))
                for member in party["members"]:
                    self.assertEqual(set(member), CHARACTER_FIELD_ALLOWLIST & set(member))
                    self.assertEqual(member["abilities"]["strength"], 16)
                serialized = json.dumps(projection, sort_keys=True)
                for canary in canaries:
                    self.assertNotIn(canary, serialized)
                self.assertNotIn("Goblin", serialized)
                self.assertNotIn("activeCombatEncounter", serialized)
                self.assertNotIn("area-private-id", serialized)

    def test_bounded_canonical_projection_orders_transcript_and_combat_for_one_and_four_pcs(
        self,
    ) -> None:
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                root = self._temporary_directory()
                names = list(PC_NAMES[:party_size])
                transcript_source: list[dict[str, object]] = []
                expected_texts: list[str] = []
                for index in range(20):
                    if index in {2, 9}:
                        transcript_source.append(
                            {
                                "type": "debug",
                                "content": "CANARY-HOST-DEBUG-OUTPUT",
                                "debug_output": "CANARY-HOST-DEBUG-OUTPUT",
                                "filesystem_path": "tmp/n2/private.log",
                            }
                        )
                        continue
                    message_type = "user-input" if index % 2 else "narration"
                    text = f"Transcript item {index}"
                    expected_texts.append(text)
                    message: dict[str, object] = {
                        "type": message_type,
                        "content": text,
                        "host_payload": "CANARY-DM-NOTE",
                        "debug_output": "CANARY-HOST-DEBUG-OUTPUT",
                        "filesystem_path": "tmp/n2/private.log",
                    }
                    if message_type == "user-input":
                        message["author"] = names[index % party_size]
                    transcript_source.append(message)

                creatures: list[dict[str, object]] = [
                    {
                        "name": names[0],
                        "type": "player",
                        "initiative": 11,
                        "status": "alive",
                        "currentHitPoints": 21,
                        "maxHitPoints": 29,
                        "armorClass": 17,
                        "actions": {"actionType": "hidden", "target": "hidden"},
                    },
                    {
                        "name": "Goblin",
                        "type": "enemy",
                        "initiative": 18,
                        "status": "alive",
                        "currentHitPoints": 31,
                        "maxHitPoints": 36,
                        "armorClass": 16,
                        "dm_notes": "CANARY-ENEMY-HP-AND-AC",
                    },
                    {
                        "name": "Scout",
                        "type": "npc",
                        "initiative": 15,
                        "status": "unconscious",
                        "currentHitPoints": 0,
                        "maxHitPoints": 12,
                        "hidden_stats": "CANARY-NPC-HIDDEN-STAT",
                    },
                ]
                for index, name in enumerate(names[1:], start=1):
                    creatures.append(
                        {
                            "name": name,
                            "type": "player",
                            "initiative": 15 - index,
                            "status": "alive",
                            "currentHitPoints": 20,
                            "maxHitPoints": 28,
                        }
                    )
                encounter_id = f"player-combat-{party_size}"
                encounter = {
                    "encounterId": encounter_id,
                    "encounterSummary": "CANARY-HIDDEN-PLOT-SECRET",
                    "combat_round": 3,
                    "combat_phase": "PC_PHASE",
                    "creatures": creatures,
                    "dm_notes": "CANARY-DM-NOTE",
                    "filesystem_path": "tmp/n2/encounter.json",
                }
                builder, fixture_names, canaries = _make_canonical_fixture(
                    root,
                    party_size,
                    projection_sources={
                        "active_encounter_id": encounter_id,
                        "active_pc_state": (names[-1], 17),
                        "busy": True,
                        "transcript": transcript_source,
                        "encounter": encounter,
                    },
                )

                projection = builder.build()
                self.assertEqual(fixture_names, names)
                self.assertEqual(projection["busy"], True)
                party = projection["party"]
                self.assertEqual(party["active_character"], names[-1])
                self.assertEqual(party["active_character_revision"], 17)
                self.assertEqual(
                    [member["portrait_media_id"] for member in party["members"]],
                    [player_portrait_media_id(name) for name in names],
                )
                self.assertEqual(
                    set(projection["transcript"]),
                    TRANSCRIPT_PROJECTION_FIELDS,
                )
                transcript = projection["transcript"]["messages"]
                expected_selected = expected_texts[-MAX_TRANSCRIPT_MESSAGES:]
                self.assertEqual([item["text"] for item in transcript], expected_selected)
                self.assertTrue(
                    all(set(item) <= TRANSCRIPT_MESSAGE_FIELDS for item in transcript)
                )
                self.assertEqual(
                    [item["sequence"] for item in transcript],
                    list(range(1, len(transcript) + 1)),
                )
                self.assertEqual(len({item["id"] for item in transcript}), len(transcript))
                self.assertEqual(transcript, builder.build()["transcript"]["messages"])

                combat = projection["combat"]
                self.assertEqual(set(combat), COMBAT_PROJECTION_FIELDS)
                self.assertTrue(combat["active"])
                self.assertEqual(combat["round"], 3)
                self.assertEqual(combat["phase"], "PC_PHASE")
                order = combat["turn_order"]
                self.assertEqual(
                    [item["initiative"] for item in order],
                    sorted((item["initiative"] for item in order), reverse=True),
                )
                self.assertEqual(
                    [item["name"] for item in order],
                    ["Goblin", "Scout", *names[1:], names[0]],
                )
                self.assertTrue(all(set(item) == COMBATANT_FIELDS for item in order))
                self.assertLessEqual(len(order), MAX_COMBATANTS)

                serialized = json.dumps(projection, sort_keys=True)
                for canary in canaries:
                    self.assertNotIn(canary, serialized)
                for canary in (
                    "CANARY-HOST-DEBUG-OUTPUT",
                    "CANARY-DM-NOTE",
                    "CANARY-ENEMY-HP-AND-AC",
                    "CANARY-NPC-HIDDEN-STAT",
                    "tmp/n2/private.log",
                    "tmp/n2/encounter.json",
                ):
                    self.assertNotIn(canary, serialized)
                for hidden_field in (
                    "host_payload",
                    "debug_output",
                    "filesystem_path",
                    "currentHitPoints",
                    "actions",
                    "dm_notes",
                    "hidden_stats",
                ):
                    self.assertNotIn(hidden_field, serialized)
                serialized_combat = json.dumps(combat, sort_keys=True)
                self.assertNotIn("currentHitPoints", serialized_combat)
                self.assertNotIn("maxHitPoints", serialized_combat)
                self.assertNotIn("armorClass", serialized_combat)

                event = project_player_event(
                    "safe-projection",
                    18,
                    "projection.updated",
                    projection,
                )
                self.assertEqual(event["projection"]["combat"], combat)
                self.assertEqual(event["projection"]["transcript"], projection["transcript"])

    def test_transcript_byte_and_source_bounds_and_out_of_combat_state(self) -> None:
        root = self._temporary_directory()
        duplicate_sources: dict[str, Any] = {
            "active_encounter_id": "",
            "active_pc_state": (PC_NAMES[0], 4),
            "busy": False,
            "transcript": [
                {"type": "user-input", "content": "Ready?", "author": PC_NAMES[0]},
                {"type": "user-input", "content": "Ready?", "author": PC_NAMES[0]},
            ],
            "encounter": None,
        }
        duplicate_builder, _names, _canaries = _make_canonical_fixture(
            root,
            1,
            projection_sources=duplicate_sources,
        )
        duplicate_messages = duplicate_builder.build()["transcript"]["messages"]
        self.assertEqual(len({item["id"] for item in duplicate_messages}), 2)
        self.assertEqual(
            duplicate_messages,
            duplicate_builder.build()["transcript"]["messages"],
        )

        long_transcript = [
            {"type": "narration", "content": "x" * 4096}
            for _index in range(MAX_TRANSCRIPT_MESSAGES)
        ]
        out_of_combat_sources: dict[str, Any] = {
            "active_encounter_id": "",
            "active_pc_state": (PC_NAMES[0], 4),
            "busy": False,
            "transcript": long_transcript,
            "encounter": None,
        }
        builder, _names, _canaries = _make_canonical_fixture(
            root,
            1,
            projection_sources=out_of_combat_sources,
        )
        projection = builder.build()
        messages = projection["transcript"]["messages"]
        transcript_bytes = len(
            json.dumps(
                projection["transcript"],
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii")
        )
        self.assertLessEqual(len(messages), MAX_TRANSCRIPT_MESSAGES)
        self.assertLessEqual(transcript_bytes, MAX_TRANSCRIPT_BYTES)
        self.assertGreater(len(messages), 0)
        self.assertTrue(projection["combat"]["available"])
        self.assertFalse(projection["combat"]["active"])
        self.assertEqual(projection["combat"]["turn_order"], [])

        oversized_sources = dict(out_of_combat_sources)
        oversized_sources["transcript"] = [
            {"type": "debug", "content": "private"}
            for _index in range(MAX_TRANSCRIPT_SOURCE_ITEMS + 1)
        ]
        oversized_builder, _names, _canaries = _make_canonical_fixture(
            self._temporary_directory(),
            1,
            projection_sources=oversized_sources,
        )
        with self.assertLogs("web.extensions.player.projections", level="WARNING"):
            oversized_projection = oversized_builder.build()
        self.assertEqual(
            oversized_projection["transcript"],
            {"available": False, "messages": []},
        )
        self.assertEqual(len(oversized_projection["party"]["members"]), 1)

    def test_projection_fails_closed_for_malformed_active_revision(self) -> None:

        malformed_revision_builder, _names, _canaries = _make_canonical_fixture(
            self._temporary_directory(),
            1,
            projection_sources={
                "active_encounter_id": "",
                "active_pc_state": (PC_NAMES[0], True),
                "transcript": [],
                "encounter": None,
            },
        )
        with self.assertRaises(ProjectionError):
            malformed_revision_builder.build()

    def test_missing_and_corrupt_transcript_sections_preserve_party_for_one_and_four_pcs(
        self,
    ) -> None:
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                root = self._temporary_directory()
                transcript_path = root / "game_interface_cache.json"
                reader = _load_player_transcript_reader(transcript_path)
                builder, names, _canaries = _make_canonical_fixture(
                    root,
                    party_size,
                    projection_sources={
                        "active_pc_state": (PC_NAMES[party_size - 1], 2),
                        "busy": True,
                        "transcript_reader": reader,
                        "active_encounter_id": "",
                        "encounter": None,
                    },
                )

                missing_projection = builder.build()
                self.assertEqual(
                    missing_projection["transcript"],
                    {"available": True, "messages": []},
                )
                self.assertEqual(
                    [member["name"] for member in missing_projection["party"]["members"]],
                    names,
                )

                bad_file_canary = f"CANARY-CORRUPT-TRANSCRIPT-{party_size}"
                transcript_path.write_text(
                    '{"type":"narration","content":"' + bad_file_canary,
                    encoding="utf-8",
                )
                with self.assertLogs(
                    "web.extensions.player.projections", level="WARNING"
                ) as captured:
                    corrupt_projection = builder.build()
                self.assertEqual(
                    corrupt_projection["transcript"],
                    {"available": False, "messages": []},
                )
                self.assertEqual(
                    [member["name"] for member in corrupt_projection["party"]["members"]],
                    names,
                )
                self.assertTrue(corrupt_projection["busy"])
                self.assertNotIn(bad_file_canary, json.dumps(corrupt_projection))
                self.assertNotIn(bad_file_canary, "\n".join(captured.output))

                event = project_player_event(
                    f"transcript-unavailable-{party_size}",
                    1,
                    "projection.updated",
                    corrupt_projection,
                )
                self.assertEqual(
                    event["projection"]["transcript"],
                    {"available": False, "messages": []},
                )

    def test_malformed_optional_sections_preserve_party_and_combat_is_all_or_nothing(
        self,
    ) -> None:
        for party_size in (1, 4):
            names = list(PC_NAMES[:party_size])
            for failure_case in ("malformed_combatant", "unreadable_encounter"):
                with self.subTest(party_size=party_size, failure_case=failure_case):
                    root = self._temporary_directory()
                    encounter_id = f"bad-player-combat-{party_size}"
                    bad_combat_canary = f"CANARY-BAD-COMBAT-{party_size}"
                    if failure_case == "malformed_combatant":
                        encounter: object = {
                            "encounterId": encounter_id,
                            "combat_round": 4,
                            "combat_phase": "PC_PHASE",
                            "creatures": [
                                {
                                    "name": names[0],
                                    "type": "player",
                                    "initiative": 12,
                                    "status": "alive",
                                },
                                {
                                    "name": bad_combat_canary,
                                    "type": "enemy",
                                    "status": "alive",
                                    "dm_notes": bad_combat_canary,
                                },
                            ],
                            "dm_notes": bad_combat_canary,
                        }
                    else:
                        encounter = OSError(bad_combat_canary)
                    builder, fixture_names, _canaries = _make_canonical_fixture(
                        root,
                        party_size,
                        projection_sources={
                            "active_pc_state": (names[-1], 9),
                            "busy": False,
                            "transcript": [],
                            "active_encounter_id": encounter_id,
                            "encounter": encounter,
                        },
                    )

                    with self.assertLogs(
                        "web.extensions.player.projections", level="WARNING"
                    ) as captured:
                        projection = builder.build()
                    self.assertEqual(fixture_names, names)
                    self.assertEqual(
                        projection["combat"],
                        {
                            "available": False,
                            "active": True,
                            "round": None,
                            "phase": None,
                            "turn_order": [],
                        },
                    )
                    self.assertEqual(
                        [member["name"] for member in projection["party"]["members"]],
                        names,
                    )
                    self.assertEqual(projection["party"]["active_character_revision"], 9)
                    self.assertFalse(projection["busy"])
                    serialized = json.dumps(projection, sort_keys=True)
                    self.assertNotIn(bad_combat_canary, serialized)
                    self.assertNotIn(bad_combat_canary, "\n".join(captured.output))

                    event = project_player_event(
                        f"combat-unavailable-{party_size}-{failure_case}",
                        1,
                        "projection.updated",
                        projection,
                    )
                    self.assertEqual(event["projection"]["combat"], projection["combat"])

    def test_authenticated_snapshot_and_event_contain_only_player_projection(self) -> None:
        root = self._temporary_directory()
        builder, names, canaries = _make_canonical_fixture(root, 4)
        security = PlayerSecurity(lambda: None)
        session_cookie, session_id = _session(security)
        self.assertTrue(
            security.register_socket(
                "player-sid",
                session_cookie.split("=", 1)[1],
                f"{PLAYER_HOST}:{PLAYER_PORT}",
                f"http://{PLAYER_HOST}:{PLAYER_PORT}",
            )
        )
        app = create_app(gateway=_FixtureGateway(builder), security=security)

        status, _headers, body = _dispatch_http(
            app,
            "GET",
            "/api/player/snapshot",
            cookie=session_cookie,
            origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
        )
        self.assertEqual(status, 200)
        snapshot = json.loads(body)
        self.assertEqual(snapshot["schema_version"], PROTOCOL_VERSION)
        self.assertEqual(snapshot["instance_id"], security.server_instance_id)
        self.assertEqual(snapshot["session_epoch"], security.session_context_for_cookie(
            session_cookie.split("=", 1)[1]
        ).session_epoch)
        self.assertEqual(snapshot["revision"], 7)
        self.assertEqual(snapshot["event_cursor"], 0)
        self.assertEqual([pc["name"] for pc in snapshot["projection"]["party"]["members"]], names)
        self.assertEqual(snapshot["projection"]["party"]["active_character"], names[-1])
        self.assertEqual(snapshot["projection"]["party"]["world"]["currentLocation"], "Lanternkeep")

        emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def capture_emit(*args: object, **kwargs: object) -> None:
            emitted.append((args, kwargs))

        app.socket_server.emit = capture_emit
        delivered = asyncio.run(
            app.publish_player_event(
                7,
                "projection.updated",
                builder.build(),
            )
        )
        self.assertEqual(delivered, 1)
        self.assertEqual(len(emitted), 1)
        args, kwargs = emitted[0]
        self.assertEqual(args[0], "player.event")
        self.assertEqual(kwargs["namespace"], PLAYER_NAMESPACE)
        self.assertEqual(kwargs["to"], "player-sid")
        event = args[1]
        self.assertEqual(set(event), EVENT_FIELDS)
        self.assertEqual(event["schema_version"], PROTOCOL_VERSION)
        self.assertEqual(event["event_id"], 1)
        self.assertEqual(event["instance_id"], security.server_instance_id)
        forbidden_sharing_fields = (
            "player_sharing",
            "invitation",
            "credential",
            "session_cookie",
            "private_key",
            "companion_status",
            "host_diagnostic",
            "companion_output",
        )
        snapshot_text = body.decode("ascii")
        event_text = json.dumps(event, sort_keys=True)
        for field in forbidden_sharing_fields:
            self.assertNotIn('"%s"' % field, snapshot_text)
            self.assertNotIn('"%s"' % field, event_text)
        for canary in canaries:
            self.assertNotIn(canary, snapshot_text)
            self.assertNotIn(canary, event_text)
        self.assertNotIn(session_id, snapshot_text)

    def test_public_login_shell_assets_are_unauthenticated_and_game_data_free(self) -> None:
        root = self._temporary_directory()
        _builder, _names, canaries = _make_canonical_fixture(root, 1)
        app = create_app(security=PlayerSecurity(lambda: None))

        shell_status, shell_headers, shell_body = _dispatch_http(app, "GET", "/")
        self.assertEqual(shell_status, 200)
        self.assertIn(b"Player login", shell_body)
        stylesheet = re.search(
            rb'href="/static/player/([A-Za-z0-9._-]{1,128}\.css)"',
            shell_body,
        )
        self.assertIsNotNone(stylesheet)
        self.assertEqual(_header_map(shell_headers)[b"cache-control"], b"no-store")
        self.assertEqual(len([name for name, _value in shell_headers if name == b"set-cookie"]), 1)

        self.assertIsNotNone(stylesheet)
        stylesheet_id = stylesheet.group(1).decode("ascii") if stylesheet else ""
        asset_status, asset_headers, asset_body = _dispatch_http(
            app,
            "GET",
            f"/static/player/{stylesheet_id}",
        )
        self.assertEqual(asset_status, 200)
        self.assertEqual(_header_map(asset_headers)[b"content-type"], b"text/css; charset=utf-8")
        self.assertEqual(
            _header_map(asset_headers)[b"cache-control"],
            b"public, max-age=31536000, immutable",
        )
        self.assertNotIn(b"party", shell_body.lower())
        self.assertNotIn(b"game_interface.html", shell_body)
        for canary in canaries:
            self.assertNotIn(canary.encode("utf-8"), shell_body)
            self.assertNotIn(canary.encode("utf-8"), asset_body)

    def test_snapshot_and_media_deny_missing_expired_and_revoked_sessions(self) -> None:
        class Clock:
            def __init__(self) -> None:
                self.now = 1_000_000.0

            def __call__(self) -> float:
                return self.now

        root = self._temporary_directory()
        media_root = root / "media"
        media_root.mkdir()
        (media_root / "portrait.png").write_bytes(b"PNG")
        registry = MediaRegistry(
            {"test": media_root},
            {"portrait": MediaRegistration("test", "portrait.png")},
        )
        gateway = mock.Mock()
        security = PlayerSecurity(lambda: None, clock=Clock())
        app = create_app(gateway=gateway, security=security, media_registry=registry)

        for path in ("/api/player/snapshot", "/api/player/media/portrait"):
            with self.subTest(path=path, state="missing"):
                status, _headers, _body = _dispatch_http(app, "GET", path)
                self.assertEqual(status, 404)

        expired_cookie, _expired_session = _session(security)
        security.clock.now += 4 * 60 * 60
        for path in ("/api/player/snapshot", "/api/player/media/portrait"):
            with self.subTest(path=path, state="expired"):
                status, _headers, _body = _dispatch_http(app, "GET", path, cookie=expired_cookie)
                self.assertEqual(status, 404)

        revoked_grant = security.create_session()
        self.assertIsNotNone(revoked_grant)
        assert revoked_grant is not None
        revoked_cookie = f"{PLAYER_SESSION_COOKIE}={revoked_grant.cookie_value}"
        self.assertEqual(
            security.revoke_session(revoked_grant.cookie_value, revoked_grant.csrf_token),
            [],
        )
        for path in ("/api/player/snapshot", "/api/player/media/portrait"):
            with self.subTest(path=path, state="revoked"):
                status, _headers, _body = _dispatch_http(app, "GET", path, cookie=revoked_cookie)
                self.assertEqual(status, 404)
        gateway.read_snapshot.assert_not_called()

    def test_private_reads_consume_existing_per_session_limits_before_work(self) -> None:
        root = self._temporary_directory()
        media_root = root / "media"
        media_root.mkdir()
        (media_root / "portrait.png").write_bytes(b"PNG")
        registry = MediaRegistry(
            {"test": media_root},
            {"portrait": MediaRegistration("test", "portrait.png")},
        )
        security = PlayerSecurity(lambda: None)
        session_cookie, session_id = _session(security)
        gateway = mock.Mock()
        app = create_app(gateway=gateway, security=security, media_registry=registry)
        for _index in range(EXPENSIVE_READS_PER_SESSION_PER_WINDOW):
            self.assertTrue(security.limiters.allow_snapshot_read(session_id))
        snapshot_status, _headers, _body = _dispatch_http(
            app,
            "GET",
            "/api/player/snapshot",
            cookie=session_cookie,
        )
        self.assertEqual(snapshot_status, 429)
        gateway.read_snapshot.assert_not_called()

        for _index in range(MEDIA_READS_PER_SESSION_PER_WINDOW):
            self.assertTrue(security.limiters.allow_media_read(session_id))
        media_status, _headers, _body = _dispatch_http(
            app,
            "GET",
            "/api/player/media/portrait",
            cookie=session_cookie,
        )
        self.assertEqual(media_status, 429)

    def test_markdown_escapes_html_and_removes_unsafe_schemes(self) -> None:
        unsafe = (
            "<script>alert(1)</script> <img src=x onerror=alert(1)> "
            "[click](javascript:alert(1)) [data](data:text/html,evil) "
            "[encoded](jav&#x61;script:alert(1)) java%73cript:alert(2) "
            "![image](https://example.test/image.png)"
        )
        rendered = render_safe_markdown(unsafe)
        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertNotIn("<script", rendered.casefold())
        self.assertNotIn("<img", rendered.casefold())
        self.assertNotIn("javascript:", rendered.casefold())
        self.assertNotIn("data:", rendered.casefold())
        self.assertNotIn("vbscript:", rendered.casefold())
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("click", rendered)
        self.assertIn("image", rendered)

        safe = render_safe_markdown("**bold** [reference](https://example.test/page)")
        self.assertEqual(safe, "**bold** [reference](https://example.test/page)")
        self.assertIsNone(render_safe_markdown("x" * 4097))

    def test_media_registry_rejects_traversal_symlink_escape_and_disallowed_types(self) -> None:
        root = self._temporary_directory()
        media_root = root / "approved-media"
        media_root.mkdir()
        safe_bytes = b"approved-image-bytes"
        (media_root / "portrait.png").write_bytes(safe_bytes)
        (media_root / "notes.html").write_text("<script>private</script>", encoding="ascii")
        (media_root / "vector.svg").write_text("<svg></svg>", encoding="ascii")
        (media_root / "large.png").write_bytes(b"x" * (MAX_PLAYER_MEDIA_BYTES + 1))
        outside_path = root / "outside.png"
        outside_path.write_bytes(b"outside-secret")
        (media_root / "escape.png").symlink_to(outside_path)
        registry = MediaRegistry(
            {"approved": media_root},
            {
                "portrait": MediaRegistration("approved", "portrait.png"),
                "escape": MediaRegistration("approved", "escape.png"),
                "html": MediaRegistration("approved", "notes.html"),
                "svg": MediaRegistration("approved", "vector.svg"),
                "large": MediaRegistration("approved", "large.png"),
            },
        )

        media = registry.read("portrait")
        self.assertIsNotNone(media)
        assert media is not None
        self.assertEqual(media.body, safe_bytes)
        self.assertEqual(media.content_type, "image/png")
        for invalid_id in (
            "../outside.png",
            "%2e%2e",
            "%252e%252e",
            "/etc/passwd",
            "unknown",
            "escape",
            "html",
            "svg",
            "large",
        ):
            with self.subTest(media_id=invalid_id):
                self.assertIsNone(registry.read(invalid_id))

        security = PlayerSecurity(lambda: None)
        session_cookie, _session_id = _session(security)
        app = create_app(security=security, media_registry=registry)
        for path in (
            "/api/player/media/../outside.png",
            "/api/player/media/%2e%2e",
            "/api/player/media//etc/passwd",
            "/api/player/media/unknown",
            "/api/player/media/escape",
            "/api/player/media/html",
            "/api/player/media/svg",
        ):
            with self.subTest(path=path):
                status, _headers, body = _dispatch_http(app, "GET", path, cookie=session_cookie)
                self.assertEqual(status, 404)
                self.assertNotIn(outside_path.as_posix().encode("utf-8"), body)
                self.assertNotIn(b"outside-secret", body)

        safe_status, safe_headers, safe_response = _dispatch_http(
            app,
            "GET",
            "/api/player/media/portrait",
            cookie=session_cookie,
        )
        self.assertEqual(safe_status, 200)
        self.assertEqual(safe_response, safe_bytes)
        self.assertEqual(_header_map(safe_headers)[b"content-type"], b"image/png")
        self.assertNotIn(outside_path.as_posix().encode("utf-8"), safe_response)

    def test_event_projector_rejects_unlisted_fields_and_invalid_event_identity(self) -> None:
        root = self._temporary_directory()
        builder, _names, canaries = _make_canonical_fixture(root, 1)
        event = project_player_event(
            "evt-1",
            1,
            "projection.updated",
            builder.build(),
        )
        self.assertEqual(set(event), PLAYER_EVENT_FIELD_ALLOWLIST)
        self.assertIn(event["type"], PLAYER_EVENT_TYPE_ALLOWLIST)
        with self.assertRaises(ValueError):
            project_player_event("../private", 1, "projection.updated", builder.build())
        with self.assertRaises(ValueError):
            project_player_event("evt-1", -1, "projection.updated", builder.build())
        with self.assertRaises(ValueError):
            project_player_event("evt-1", 1, "debug.output", builder.build())
        self.assertFalse(any(canary in json.dumps(event) for canary in canaries))


if __name__ == "__main__":
    unittest.main()
