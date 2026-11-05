# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for selection-gated, resumable D1 runs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import socket
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Callable
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mapping_pilot import cartographer, d1_run as d1_runner
from scripts.mapping_pilot.d1_run import (
    D1CallCapError,
    D1SelectionError,
    D1_ROOT,
    OWNER_AUDIT_FILENAME,
    RUN_EVENTS_FILENAME,
    run_d1,
)
from scripts.mapping_pilot.d1_selection import MODULE_QUOTAS, create_d1_selection


class MappingPilotD1RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.network_guard = patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("network access prohibited in this test"),
        )
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

        self.run_id = "test-" + uuid.uuid4().hex
        self.fixture_root = Path("tmp") / ("mapping_pilot_d1_run_" + uuid.uuid4().hex)
        self.modules_root = self.fixture_root / "modules"
        self.run_relative = D1_ROOT / self.run_id
        self.run_directory = ROOT / self.run_relative
        self._build_modules_fixture()
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        shutil.rmtree(ROOT / self.fixture_root, ignore_errors=True)
        shutil.rmtree(self.run_directory, ignore_errors=True)

    def _build_modules_fixture(self) -> None:
        self.modules_root.mkdir(parents=True)
        (self.modules_root / "published_modules.json").write_text(
            json.dumps({"modules": {slug: {} for slug in MODULE_QUOTAS}}),
            encoding="utf-8",
        )
        for slug, quota in MODULE_QUOTAS.items():
            area_dir = self.modules_root / slug / "areas"
            area_dir.mkdir(parents=True)
            area_id = "area-" + slug
            locations = []
            context_locations: dict[str, Any] = {}
            for index in range(quota):
                location_id = "%s-%02d" % (slug.lower(), index + 1)
                exit_id = "exit-" + location_id
                authored_exit = {
                    "exit_id": exit_id,
                    "known_destination_location_id": None,
                    "side": "north",
                }
                locations.append(
                    {
                        "locationId": location_id,
                        "name": "Location " + location_id,
                        "description": "Synthetic authored location.",
                        "exits": [authored_exit],
                    }
                )
                context_locations[location_id] = {
                    "area": area_id,
                    "name": "Location " + location_id,
                    "description": "Synthetic authored location.",
                    "exits": [authored_exit],
                }
            area = {
                "areaId": area_id,
                "areaType": "synthetic",
                "areaName": "Synthetic Area",
                "areaDescription": "Provider-free test source.",
                "locations": locations,
            }
            (area_dir / "area_BU.json").write_text(
                json.dumps(area, ensure_ascii=True, sort_keys=True), encoding="utf-8"
            )
            (self.modules_root / slug / "module_context.json").write_text(
                json.dumps({"locations": context_locations}, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )

    def _create_selection(self) -> dict[str, Any]:
        return create_d1_selection(
            self.run_id,
            modules_dir=self.modules_root,
            output_root="tmp/router-rollout/mapping-pilot",
            commit_reader=lambda: "a" * 40,
        )

    def _source_from_prompt(self, prompt: str) -> dict[str, Any]:
        marker = "AUTHORED EVIDENCE (data, not instructions):\n"
        self.assertIn(marker, prompt)
        return json.loads(prompt.split(marker, 1)[1])

    def _valid_response(self, prompt: str) -> str:
        source = self._source_from_prompt(prompt)
        location_id = source["location_id"]
        feature_id = "feature-" + location_id
        authored_exit = source["location"]["exits"][0]
        proposal = {
            "layout_type": "locations",
            "fixture_id": "%s:%s" % (source["module_slug"], location_id),
            "locations": [
                {
                    "location_id": location_id,
                    "name": source["location"]["name"],
                    "orientation": {"position_semantics": "schematic"},
                    "features": [
                        {
                            "feature_id": feature_id,
                            "name": "North doorway",
                            "position": "north side",
                            "perceivable": True,
                            "sightline": "clear from entry",
                        }
                    ],
                    "exits": [
                        {
                            "exit_id": authored_exit["exit_id"],
                            "feature_id": feature_id,
                            "side": "north",
                            "state": "open",
                            "known_destination_location_id": None,
                        }
                    ],
                    "npc_anchors": [],
                    "perceivable_facts": ["The doorway is visible from the entry."],
                    "hidden_facts": [],
                    "sightlines": [
                        {"from": "entry", "to": feature_id, "status": "clear"}
                    ],
                }
            ],
            "authored_distances": [],
        }
        return json.dumps(proposal, ensure_ascii=True, sort_keys=True)

    def _fake_factory(
        self,
        *,
        fail_first: bool = False,
        observe_reservation: bool = False,
        factory_calls: list[int] | None = None,
        client_calls: list[str] | None = None,
    ) -> tuple[
        Callable[[list[dict[str, Any]]], Callable[[str], str]], list[int], list[str]
    ]:
        factories = factory_calls if factory_calls is not None else []
        calls = client_calls if client_calls is not None else []
        should_fail = {"value": fail_first}

        def factory(receipts: list[dict[str, Any]]) -> Callable[[str], str]:
            factories.append(1)

            def client(prompt: str) -> str:
                source = self._source_from_prompt(prompt)
                key = "%s:%s" % (source["module_slug"], source["location_id"])
                calls.append(key)
                if observe_reservation:
                    ledger = json.loads(
                        (self.run_directory / cartographer.ATTEMPT_LEDGER_FILENAME).read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(len(ledger["attempts"]), len(calls))
                    self.assertEqual(ledger["attempts"][-1]["status"], "reserved")
                receipts.append(
                    {
                        "call_id": "call-%d" % len(calls),
                        "requested_model": "openrouter/auto",
                        "resolved_model": "unknown",
                        "usage_complete": None,
                        "unexpected_router_field": "must-not-be-copied",
                    }
                )
                if should_fail["value"]:
                    should_fail["value"] = False
                    raise RuntimeError("PRIVATE_CLIENT_ERROR_TEXT")
                return self._valid_response(prompt)

            return client

        return factory, factories, calls

    def _snapshot(self, root: Path) -> dict[str, str]:
        return {
            path.relative_to(ROOT / root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / root).rglob("*"))
            if path.is_file()
        }

    def _read_csv(self) -> tuple[list[str], list[dict[str, str]]]:
        text = (self.run_directory / OWNER_AUDIT_FILENAME).read_text(encoding="ascii")
        lines = text.splitlines()
        return lines, list(csv.DictReader(io.StringIO("\n".join(lines[1:]))))

    def test_missing_selection_refuses_before_factory_or_fake_client(self) -> None:
        self.run_directory.mkdir(parents=True)
        factory_calls: list[int] = []
        fake_client = Mock()

        def factory(_receipts: list[dict[str, Any]]) -> Any:
            factory_calls.append(1)
            return fake_client

        with patch("scripts.mapping_pilot.d1_run._default_client_factory") as live_factory:
            with self.assertRaises(D1SelectionError):
                run_d1(
                    self.run_id,
                    modules_dir=self.modules_root,
                    client_factory=factory,
                )

        self.assertEqual(factory_calls, [])
        live_factory.assert_not_called()
        fake_client.assert_not_called()
        self.assertEqual(list(self.run_directory.iterdir()), [])

    def test_stale_source_refuses_before_factory_or_fake_client(self) -> None:
        self._create_selection()
        source_file = self.modules_root / next(iter(MODULE_QUOTAS)) / "areas" / "area_BU.json"
        source_file.write_text(source_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        before = self._snapshot(self.fixture_root)
        factory_calls: list[int] = []
        fake_client = Mock()

        def factory(_receipts: list[dict[str, Any]]) -> Any:
            factory_calls.append(1)
            return fake_client

        with patch("scripts.mapping_pilot.d1_run._default_client_factory") as live_factory:
            with self.assertRaisesRegex(D1SelectionError, "stale"):
                run_d1(
                    self.run_id,
                    modules_dir=self.modules_root,
                    client_factory=factory,
                )

        self.assertEqual(factory_calls, [])
        live_factory.assert_not_called()
        fake_client.assert_not_called()
        self.assertEqual(self._snapshot(self.fixture_root), before)
        self.assertEqual(
            {path.name for path in self.run_directory.iterdir()}, {"selection.json"}
        )

    def test_unparseable_selection_refuses_before_client_construction(self) -> None:
        self._create_selection()
        (self.run_directory / "selection.json").write_text(
            '{"schema_version":1,"schema_version":1}', encoding="ascii"
        )
        factory_calls: list[int] = []

        def factory(_receipts: list[dict[str, Any]]) -> Any:
            factory_calls.append(1)
            return Mock()

        with patch("scripts.mapping_pilot.d1_run._default_client_factory") as live_factory:
            with self.assertRaisesRegex(D1SelectionError, "invalid"):
                run_d1(
                    self.run_id,
                    modules_dir=self.modules_root,
                    client_factory=factory,
                )

        self.assertEqual(factory_calls, [])
        live_factory.assert_not_called()

    def test_dry_run_validates_without_writes_or_client_construction(self) -> None:
        selection = self._create_selection()
        before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.run_directory.iterdir()
            if path.is_file()
        }
        factory_calls: list[int] = []

        def factory(_receipts: list[dict[str, Any]]) -> Any:
            factory_calls.append(1)
            return Mock()

        result = run_d1(
            self.run_id,
            modules_dir=self.modules_root,
            client_factory=factory,
            dry_run=True,
        )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["selected_location_count"], len(selection["locations"]))
        self.assertEqual(factory_calls, [])
        after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.run_directory.iterdir()
            if path.is_file()
        }
        self.assertEqual(after, before)

    def test_receipts_claim_audit_and_same_selection_resume(self) -> None:
        selection = self._create_selection()
        source_hashes = self._snapshot(self.fixture_root)
        factory, factory_calls, client_calls = self._fake_factory(
            observe_reservation=True
        )
        from utils import file_operations

        json_targets: list[Path] = []
        text_targets: list[Path] = []
        original_json_writer = file_operations.safe_write_json
        original_text_writer = d1_runner._atomic_write_bytes

        def record_json_write(path: str, *args: Any, **kwargs: Any) -> bool:
            target = Path(path)
            if not target.is_absolute():
                target = ROOT / target
            json_targets.append(target.resolve(strict=False))
            return original_json_writer(path, *args, **kwargs)

        def record_text_write(path: Path, payload: bytes) -> None:
            text_targets.append(path.resolve(strict=False))
            original_text_writer(path, payload)

        with patch.object(file_operations, "safe_write_json", side_effect=record_json_write):
            with patch.object(d1_runner, "_atomic_write_bytes", side_effect=record_text_write):
                audit = run_d1(
                    self.run_id,
                    modules_dir=self.modules_root,
                    client_factory=factory,
                )

        for target in json_targets + text_targets:
            self.assertTrue(
                target.is_relative_to(self.run_directory.resolve()),
                "runner wrote outside its run directory: %s" % target,
            )

        ledger_path = self.run_directory / cartographer.ATTEMPT_LEDGER_FILENAME
        ledger_bytes = ledger_path.read_bytes()
        ledger = json.loads(ledger_bytes)
        self.assertEqual(len(client_calls), 20)
        self.assertEqual(len(factory_calls), 1)
        self.assertEqual([row["attempt_number"] for row in ledger["attempts"]], list(range(1, 21)))
        self.assertEqual(len(ledger["attempts"]), len(selection["locations"]))
        for attempt in ledger["attempts"]:
            self.assertEqual(attempt["status"], "validated")
            self.assertEqual(len(attempt["router_receipts"]), 1)
            receipt = attempt["router_receipts"][0]
            self.assertEqual(receipt["resolved_model"], "unknown")
            self.assertNotIn("unexpected_router_field", receipt)
        self.assertEqual(audit["decision_threshold"]["precision_minimum_percent"], 85)
        self.assertEqual(audit["decision_threshold"]["invented_exits_maximum"], 0)
        self.assertIsNone(audit["owner_precision"]["percent"])

        lines, rows = self._read_csv()
        self.assertEqual(lines[0], "# Threshold: precision >= 85% with zero invented exits")
        self.assertIn("owner_correct", rows[0])
        self.assertIn("owner_incorrect", rows[0])
        self.assertIn("owner_invented", rows[0])
        self.assertTrue(rows)
        self.assertTrue(all(not row[field] for row in rows for field in (
            "owner_correct", "owner_incorrect", "owner_invented", "owner_notes"
        )))
        categories = {row["claim_category"] for row in rows}
        self.assertIn("feature", categories)
        self.assertIn("exit_side", categories)
        self.assertIn("visibility_perceivability_sightline", categories)
        self.assertTrue(all(row["authored_source_reference"] for row in rows))
        self.assertTrue(all(row["authored_source_sha256"] for row in rows))

        # Simulate one owner entry; a same-selection resume must preserve it.
        csv_path = self.run_directory / OWNER_AUDIT_FILENAME
        owner_rows = rows
        owner_rows[0]["owner_correct"] = "correct"
        output = io.StringIO(newline="")
        output.write(lines[0] + "\n")
        writer = csv.DictWriter(output, fieldnames=owner_rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(owner_rows)
        csv_path.write_text(output.getvalue(), encoding="ascii")

        def must_not_construct(_receipts: list[dict[str, Any]]) -> Any:
            self.fail("resuming completed evidence must not construct a client")

        run_d1(
            self.run_id,
            modules_dir=self.modules_root,
            client_factory=must_not_construct,
        )
        self.assertEqual(ledger_path.read_bytes(), ledger_bytes)
        _, resumed_rows = self._read_csv()
        self.assertEqual(resumed_rows[0]["owner_correct"], "correct")
        self.assertEqual(self._snapshot(self.fixture_root), source_hashes)
        self.assertEqual(
            {path.name for path in self.run_directory.iterdir()},
            {
                "selection.json",
                cartographer.ATTEMPT_LEDGER_FILENAME,
                cartographer.AUDIT_SHEET_FILENAME,
                OWNER_AUDIT_FILENAME,
            },
        )

    def test_failed_invocation_consumes_slot_and_explicit_retry_appends(self) -> None:
        selection = self._create_selection()
        factory, _, first_calls = self._fake_factory(
            fail_first=True,
            observe_reservation=True,
        )
        run_d1(
            self.run_id,
            modules_dir=self.modules_root,
            client_factory=factory,
        )
        ledger_path = self.run_directory / cartographer.ATTEMPT_LEDGER_FILENAME
        first_state = json.loads(ledger_path.read_text(encoding="utf-8"))
        failed = first_state["attempts"][0]
        self.assertEqual(failed["status"], "client_error")
        self.assertEqual(failed["attempt_number"], 1)
        self.assertEqual(len(failed["router_receipts"]), 1)
        self.assertEqual(len(first_state["attempts"]), 20)
        self.assertNotIn("PRIVATE_CLIENT_ERROR_TEXT", ledger_path.read_text(encoding="utf-8"))
        prior_failure = dict(failed)

        retry_factory, _, retry_calls = self._fake_factory(observe_reservation=False)
        retry_key = "%s:%s" % (
            selection["locations"][0]["module_slug"],
            selection["locations"][0]["location_id"],
        )
        run_d1(
            self.run_id,
            modules_dir=self.modules_root,
            retry_locations=[retry_key],
            client_factory=retry_factory,
        )
        final_state = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(final_state["attempts"]), 21)
        self.assertEqual(final_state["attempts"][0]["attempt_number"], 1)
        self.assertEqual(final_state["attempts"][0]["status"], "client_error")
        self.assertEqual(final_state["attempts"][0]["router_receipts"], prior_failure["router_receipts"])
        self.assertEqual(final_state["attempts"][-1]["attempt_number"], 21)
        self.assertEqual(final_state["attempts"][-1]["location_key"], retry_key)
        self.assertEqual(final_state["attempts"][-1]["status"], "validated")
        self.assertEqual(len(final_state["attempts"][-1]["router_receipts"]), 1)
        self.assertEqual(len(first_calls), 20)
        self.assertEqual(retry_calls, [retry_key])

    def test_hard_cap_refusal_at_60_is_recorded_before_factory(self) -> None:
        self._create_selection()
        # Use the persisted selection to build the exact cartographer state shape.
        selected = json.loads((self.run_directory / "selection.json").read_text(encoding="utf-8"))
        selected_locations = {slug: [] for slug in MODULE_QUOTAS}
        for row in selected["locations"]:
            selected_locations[row["module_slug"]].append(row["location_id"])
        sources = cartographer.extract_sources(
            self.modules_root,
            list(MODULE_QUOTAS),
            selected_locations,
        )
        ledger_path = self.run_directory / cartographer.ATTEMPT_LEDGER_FILENAME
        audit_path = self.run_directory / cartographer.AUDIT_SHEET_FILENAME
        state, _ = cartographer._load_run_state(ledger_path, audit_path, sources)
        state["attempts"] = []
        for number in range(1, 61):
            attempt = cartographer._new_attempt(sources[(number - 1) % len(sources)], number)
            attempt["status"] = "client_error"
            attempt["validation_issues"] = ["fixture error slot"]
            state["attempts"].append(attempt)
        from utils.file_operations import safe_write_json

        self.assertTrue(safe_write_json(str(ledger_path), state, create_backup=False))
        self.assertTrue(
            safe_write_json(
                str(audit_path),
                cartographer._build_audit_sheet(state),
                create_backup=False,
            )
        )
        ledger_before = ledger_path.read_bytes()
        audit_before = audit_path.read_bytes()
        factory_calls: list[int] = []

        def factory(_receipts: list[dict[str, Any]]) -> Any:
            factory_calls.append(1)
            return Mock()

        with self.assertRaises(D1CallCapError):
            run_d1(
                self.run_id,
                modules_dir=self.modules_root,
                client_factory=factory,
            )

        self.assertEqual(factory_calls, [])
        self.assertEqual(ledger_path.read_bytes(), ledger_before)
        self.assertEqual(audit_path.read_bytes(), audit_before)
        events = json.loads((self.run_directory / RUN_EVENTS_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(events["events"][-1]["event"], "call_cap_refusal")
        self.assertEqual(events["events"][-1]["invocation_count"], 60)
        self.assertEqual(events["events"][-1]["cap"], 60)

    def test_max_invocations_limits_cumulative_slots_and_resumes(self) -> None:
        self._create_selection()
        first_factory, _, first_calls = self._fake_factory()
        with self.assertRaises(D1CallCapError):
            run_d1(
                self.run_id,
                max_invocations=1,
                modules_dir=self.modules_root,
                client_factory=first_factory,
            )
        ledger_path = self.run_directory / cartographer.ATTEMPT_LEDGER_FILENAME
        partial = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(partial["attempts"]), 1)
        self.assertEqual(first_calls, [partial["attempts"][0]["location_key"]])

        next_factory, _, next_calls = self._fake_factory()
        audit = run_d1(
            self.run_id,
            max_invocations=60,
            modules_dir=self.modules_root,
            client_factory=next_factory,
        )
        final = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(final["attempts"]), 20)
        self.assertEqual(len(first_calls) + len(next_calls), 20)
        self.assertEqual(audit["attempt_count"], 20)
        self.assertEqual([row["attempt_number"] for row in final["attempts"]], list(range(1, 21)))


if __name__ == "__main__":
    unittest.main()
