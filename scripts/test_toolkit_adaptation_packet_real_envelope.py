# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free packet-builder verification for the REAL runtime envelope
(task 6.1 of toolkit-llm-adaptation-runtime-unification).

The suite proves that ``run_toolkit_homebrew_packet_build`` accepts the real
runtime-shaped dossier/provenance/staging envelope produced by BOTH live input
boundaries and preserves the completed scaffold contracts:

  * the real upload boundary (``build_upload_adaptation_handoff`` +
    ``run_upload_adaptation_authoring`` + the route provenance builder +
    a real reserved staging target) reaches the packet builder with the
    Python-validated dossier, source hash, attempt/job/revision identity,
    rights metadata, world-context provenance, adaptation route, staging
    root, and reserved staging target all preserved (never relabeled);
  * the real text-description boundary (the task 5.1 seam + real attempt
    workspace) reaches the packet builder with the same identity coherence;
  * fresh semantic revisions use a DISTINCT project-relative isolated
    staging target and retain the prior attempt's staging and attempt
    artifacts (no overwrite, no direct ``modules/<name>`` write, no
    registry/campaign publication at the packet-builder boundary);
  * source-lock separation: adaptation builder inputs never carry the legacy
    ``source_*``/``blueprint`` source-lock fields and never produce the
    ``SOURCE LOCK CONTEXT`` prompt block, while legacy/default calls keep
    their exact prior result shapes and keep the bounded source-lock fields
    in the legacy channel only;
  * no raw source, credentials, or absolute paths reach the adaptation
    fields of builder input, output, reports, or attempt/staging metadata.

Isolation and path policy
-------------------------

All fixtures and generated scratch live under the project-local scratch root
``tmp/toolkit_adaptation_packet_real_envelope/<uuid>/`` and are removed via
addCleanup. No OS temp directory, no provider/network calls, no live
model_config dependency (flags are patched explicitly), and no real
``modules/``, registry, campaign, or runtime mutation: the module output and
the reserved staging targets stay inside the per-test scratch, and real
module/registry/campaign sentinels are byte-checked. Deterministic injected
builder/executor/gate seams are used (captured executor, patched monster
closure / spatial repair / calendar normalization / build fidelity / gate
composer).
"""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_config as model_config_module
import web.extensions.toolkit_text_adaptation_worker as text_worker
import web.extensions.toolkit_homebrew_packet_builder as packet_builder
import web.routes.toolkit_homebrew_routes as routes_module
from web.extensions.toolkit_adaptation_runtime import adaptation_convergence_callback
from utils.toolkit_adaptation_config import (
    BUILD_MODE_LLM_ADAPTATION,
    LEGACY_ACCURATE_INGEST_BUILD_MODES,
)
from utils.toolkit_adaptation_dossier import (
    RIGHTS_CLASS_USER_AUTHORED,
    validate_adaptation_dossier,
)
from utils.toolkit_adaptation_staging import (
    create_adaptation_staging_target,
)
from utils.file_operations import safe_write_json
from utils.toolkit_homebrew_upload_contract import (
    REVIEW_DECISION_APPROVE,
    SOURCE_RIGHTS_USER_AUTHORED,
    build_review_snapshot,
    ensure_workspace_placeholders,
    get_workspace_files,
    persist_normalized_packet_artifact,
    persist_review_snapshot_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "tmp" / "toolkit_adaptation_packet_real_envelope"
FIXTURE_DOSSIER_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)
MODULE_NAME = "Sunken_Lighthouse"
JOB_ID = "packet-real-envelope-job"
ATTEMPT_NUMBER = 1

FIXTURE_TEXT = (
    "# Sunken Lighthouse\n\n"
    "Room 1: The keeper's quarters with a rusted spyglass.\n"
    "Room 2: The flooded stairs descending into the dark.\n"
    "Room 3: The drowned bell chamber.\n"
)
FIXTURE_HASH = hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest()

_PASS_GATES: Dict[str, Any] = {
    "status": "pass",
    "playable_status": "pass",
    "candidate_eligible": True,
    "python_authoritative": True,
    "publication": {
        "authority": "python",
        "attempted": False,
        "allowed": True,
    },
    "errors": [],
}

_PACKET_FILES = (
    "normalized_packet.json",
    "ui_review_snapshot.json",
    "builder_narrative.txt",
)


def _load_fixture_dossier() -> Dict[str, Any]:
    """Load the repository's validated build-ready dossier fixture."""
    with FIXTURE_DOSSIER_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _dossier_for_attempt(attempt_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Build a schema-valid dossier whose Python-owned identity matches the
    attempt metadata produced by the authoring preflight."""
    dossier = deepcopy(_load_fixture_dossier())
    dossier["source_hash"] = attempt_metadata["source_hash"]
    dossier["source_title"] = attempt_metadata["source_title"]
    dossier["source_profile"] = attempt_metadata["source_profile"]
    dossier["rights_class"] = attempt_metadata["rights_class"]
    dossier["rights_basis"] = attempt_metadata["rights_basis"]
    dossier["rights_review_required"] = attempt_metadata["rights_review_required"]
    dossier["rights_review_status"] = attempt_metadata["rights_review_status"]
    dossier["adaptation_mode"] = "llm_adaptation"
    return dossier


class FakeAuthorRunner:
    """Deterministic injectable author runner (never touches a provider)."""

    def __init__(
        self,
        *,
        dossier_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        error: Optional[Exception] = None,
        refused: bool = False,
        invalid_dossier: bool = False,
    ) -> None:
        self.calls: list = []
        self.dossier_builder = dossier_builder
        self.error = error
        self.refused = refused
        self.invalid_dossier = invalid_dossier

    def __call__(
        self,
        source_context: Any,
        attempt_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append((deepcopy(dict(attempt_metadata or {})), dict(kwargs)))
        if self.error is not None:
            raise self.error
        if self.refused:
            return {
                "status": "refused",
                "outcome": "explicit_refusal",
                "ok": False,
                "failure_class": "refusal",
                "diagnostics": [
                    {"code": "dossier_refused", "message": "adaptation author refused the source"}
                ],
                "dossier": None,
            }
        if self.invalid_dossier:
            return {
                "status": "success",
                "outcome": "valid",
                "ok": True,
                "failure_class": "none",
                "dossier": {"status": "ready", "adapted_title": "not a real dossier"},
                "diagnostics": [],
            }
        dossier = (
            self.dossier_builder(dict(attempt_metadata or {}))
            if self.dossier_builder
            else None
        )
        return {
            "status": "success",
            "outcome": "valid",
            "ok": True,
            "failure_class": "none",
            "dossier": dossier,
            "diagnostics": [],
            "response_metadata": {"model": "mock-adaptation-model", "request_id": "req-packet-6-1"},
            "params_used": {"reasoning_effort": "medium", "temperature": 0.2},
        }


def _make_upload_workspace(scratch: Path, source_hash: str) -> Path:
    """Create an approved upload workspace inside the scratch root."""
    workspace = scratch / "workspace"
    ensure_workspace_placeholders(workspace)
    files = get_workspace_files(workspace)
    packet: Dict[str, Any] = {
        "packet_version": "v1",
        "normalization_state": "normalized",
        "source_path": "uploads/fixture.md",
        "source_hash": source_hash,
        "title": "Sunken Lighthouse",
        "author": "",
        "description": "A bounded adventure about a sunken lighthouse.",
        "adventure_summary": "The keeper's quarters and the flooded stairs.",
        "module_tone": "haunted",
        "acts": [{"name": "Descent", "summary": "Into the dark."}],
        "locations": [
            {
                "name": "Keeper's Quarters",
                "location": "tower",
                "description": "Rusted spyglass.",
            }
        ],
        "npc_seeds": [
            {"name": "Keeper Elowen", "role": "witness", "description": "Haunted keeper."}
        ],
        "encounter_seeds": [
            {"name": "Drowned Bell Guard", "description": "Undead guardian."}
        ],
        "assumptions": ["Fixture packet for the task 6.1 real envelope tests."],
        "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
    }
    persist_normalized_packet_artifact(workspace, packet)
    snapshot = build_review_snapshot(
        job_id=JOB_ID,
        decision=REVIEW_DECISION_APPROVE,
        packet=packet,
        source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
    )
    persist_review_snapshot_artifact(workspace, snapshot)
    files["source_original"].write_text(FIXTURE_TEXT, encoding="utf-8")
    files["builder_narrative"].write_text(
        "Build a lighthouse-centered adaptation.", encoding="utf-8"
    )
    return workspace


class _PacketScratchMixin:
    """Provide a unique project-local scratch dir removed after each test."""

    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / str(uuid.uuid4())
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.staging_root = (
            "tmp/toolkit_adaptation_packet_real_envelope"
            + "/"
            + self.scratch.name
            + "/staging"
        )
        self.workspaces_root = (
            "tmp/toolkit_adaptation_packet_real_envelope"
            + "/"
            + self.scratch.name
            + "/workspaces"
        )

    def _run_packet_build(
        self,
        workspace: Any,
        job_id: str,
        *,
        captured: List[Dict[str, Any]],
        adaptation_kwargs: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
        legacy_flags: bool = False,
    ) -> Dict[str, Any]:
        """Run the REAL packet builder with deterministic injected seams."""
        def _capture(builder_input: Dict[str, Any], progress_callback: Any = None) -> None:
            captured.append(builder_input)
            # The real adaptation finalizer intentionally consumes the staged
            # module artifacts produced by ModuleBuilder.  Keep this seam
            # provider-free while materializing the smallest project-local,
            # atomic artifact envelope it needs; a marker-only executor would
            # incorrectly test the hard finalization gate rather than the real
            # packet envelope.
            staging = builder_input.get("staging_target")
            if not isinstance(staging, Mapping):
                # Legacy/default calls intentionally have no adaptation
                # staging target and must retain their original fixture shape.
                return
            staging_path = (REPO_ROOT / str(staging.get("path") or "")).resolve()
            if REPO_ROOT not in staging_path.parents:
                raise AssertionError("fixture staging target escaped project root")
            if "modules" in staging_path.relative_to(REPO_ROOT).parts:
                raise AssertionError("fixture staging target entered live modules")
            adaptation = builder_input.get("llm_adaptation")
            adaptation = adaptation if isinstance(adaptation, Mapping) else {}
            dossier = adaptation.get("dossier")
            dossier = dossier if isinstance(dossier, Mapping) else {}
            provenance = adaptation.get("provenance")
            provenance = provenance if isinstance(provenance, Mapping) else {}
            identity = {
                "module_name": MODULE_NAME,
                "module_slug": MODULE_NAME,
                "adaptation_mode": BUILD_MODE_LLM_ADAPTATION,
                "source_hash": dossier.get("source_hash") or provenance.get("source_hash"),
                "attempt_id": provenance.get("attempt_id"),
                "attempt_number": provenance.get("attempt_number"),
                "revision_number": provenance.get("revision_number"),
            }
            context = {
                "name": MODULE_NAME,
                "module_name": MODULE_NAME,
                "adaptation": identity,
            }
            plot = {
                "module_name": MODULE_NAME,
                "adaptation": identity,
                "plotPoints": [],
            }
            staging_path.mkdir(parents=True, exist_ok=True)
            if not safe_write_json(str(staging_path / "module_context.json"), context):
                raise AssertionError("module_context fixture write failed")
            if not safe_write_json(str(staging_path / "module_plot.json"), plot):
                raise AssertionError("module_plot fixture write failed")

        patch_items = [
            patch.object(packet_builder, "ENABLE_LLM_ADAPTATION", enabled),
            patch(
                "utils.toolkit_adaptation_monster_guardrail.build_adaptation_monster_guardrail_report",
                return_value={
                    "version": "toolkit_adaptation_monster_guardrail.v1",
                    "report_version": "toolkit_adaptation_monster_guardrail.v1",
                    "status": "pass",
                    "monsters_unresolved": 0,
                    "encounters_unresolved": 0,
                    "encounters_unbound": 0,
                    "unresolved_refs": [],
                },
            ),
            patch(
                "utils.monster_reference_closure.ensure_monster_reference_closure",
                return_value={
                    "required": 0,
                    "existing_before": 0,
                    "generated": 0,
                    "unresolved": 0,
                    "ambiguous_npc_like": [],
                },
            ),
            patch(
                "utils.spatial_repair.repair_module_spatial",
                return_value={"status": "pass", "input_location_count": 0},
            ),
            patch(
                "utils.calendar_normalization.normalize_party_calendar",
                return_value={"status": "pass"},
            ),
            patch(
                "utils.toolkit_build_fidelity.ENABLE_ACCURATE_INGEST_BUILD_FIDELITY_GATES",
                False,
            ),
            patch(
                "utils.toolkit_adaptation_gate_composer.run_adaptation_gate_composer",
                return_value=deepcopy(_PASS_GATES),
            ),
        ]
        if legacy_flags:
            patch_items.append(
                patch.object(
                    packet_builder, "ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD", False
                )
            )
            patch_items.append(
                patch.object(
                    packet_builder, "ENABLE_ACCURATE_INGEST_SEED_WRITER_FALLBACK", False
                )
            )
        with patch_items[0]:
            for item in patch_items[1:]:
                item.start()
            try:
                kwargs = dict(adaptation_kwargs or {})
                if kwargs.get("adaptation_route") == BUILD_MODE_LLM_ADAPTATION:
                    kwargs.setdefault(
                        "adaptation_convergence_callback",
                        adaptation_convergence_callback,
                    )
                return packet_builder.run_toolkit_homebrew_packet_build(
                    workspace,
                    job_id,
                    builder_executor=_capture,
                    **kwargs,
                )
            finally:
                for item in reversed(patch_items[1:]):
                    item.stop()

    def _workspace_rel(self, workspace: Path) -> Path:
        """Return the project-relative workspace path used for the packet
        build, mirroring the host route which stores relative workspace
        references (``user_uploads/toolkit/homebrew_md/<job_id>``)."""
        relative = workspace.relative_to(REPO_ROOT).as_posix()
        return Path(relative)

    def _reserve_staging(
        self,
        source_hash: str,
        *,
        attempt_id: str,
        revision_number: int,
        module_slug: str = MODULE_NAME,
        job_id: str = JOB_ID,
        source_path: str = "",
    ) -> Dict[str, Any]:
        return create_adaptation_staging_target(
            source_hash,
            attempt_id=attempt_id,
            attempt_number=ATTEMPT_NUMBER,
            revision_number=revision_number,
            job_id=job_id,
            source_path=source_path,
            module_slug=module_slug,
            staging_root=self.staging_root,
        )

    def _real_module_sentinels(self) -> Dict[str, Any]:
        """Snapshot real modules/ listing plus registry/campaign bytes."""
        modules_dir = REPO_ROOT / "modules"
        listing: list = []
        if modules_dir.exists():
            listing = sorted(
                str(p.relative_to(REPO_ROOT))
                for p in modules_dir.rglob("*")
                if p.is_file()
            )
        registry_path = REPO_ROOT / "modules" / "world_registry.json"
        campaign_path = REPO_ROOT / "modules" / "campaign.json"
        registry_bytes = registry_path.read_bytes() if registry_path.exists() else None
        campaign_bytes = campaign_path.read_bytes() if campaign_path.exists() else None
        return {
            "listing": listing,
            "registry_bytes": registry_bytes,
            "campaign_bytes": campaign_bytes,
        }

    def _assert_real_sentinels_unchanged(self, snapshot: Dict[str, Any]) -> None:
        modules_dir = REPO_ROOT / "modules"
        listing = (
            sorted(str(p.relative_to(REPO_ROOT)) for p in modules_dir.rglob("*") if p.is_file())
            if modules_dir.exists()
            else []
        )
        self.assertEqual(listing, snapshot["listing"])
        registry_path = REPO_ROOT / "modules" / "world_registry.json"
        campaign_path = REPO_ROOT / "modules" / "campaign.json"
        self.assertEqual(
            registry_path.read_bytes() if registry_path.exists() else None,
            snapshot["registry_bytes"],
        )
        self.assertEqual(
            campaign_path.read_bytes() if campaign_path.exists() else None,
            snapshot["campaign_bytes"],
        )
        self.assertFalse((REPO_ROOT / "modules" / MODULE_NAME).exists())

    def _serialized_adaptation_fields(self, builder_input: Dict[str, Any], result: Dict[str, Any]) -> str:
        """Serialize ONLY the adaptation-bearing fields for leakage scans."""
        fields: List[Any] = []
        for key in ("llm_adaptation", "staging_target", "world_context_provenance"):
            if key in builder_input:
                fields.append(builder_input[key])
        for key in (
            "staging_target",
            "world_context_provenance",
            "adaptation_route_resolution",
            "adaptation_gates",
            "adaptation_attempt_report",
            "adaptation_artifact_workspace",
            "adaptation_provenance",
        ):
            if key in result:
                fields.append(result[key])
        return json.dumps(fields, sort_keys=True, default=str)


class TestRealUploadEnvelopePacketBuild(_PacketScratchMixin, unittest.TestCase):
    """The real upload boundary envelope is accepted without relabeling."""

    def _real_upload_authoring(self, source_kind: str = "markdown") -> Dict[str, Any]:
        """Run the REAL upload handoff + authoring adapters with an injected
        runner and return the ready authoring result."""
        workspace = _make_upload_workspace(self.scratch, FIXTURE_HASH)
        handoff = (
            __import__(
                "web.extensions.toolkit_adaptation_runtime",
                fromlist=["build_upload_adaptation_handoff"],
            ).build_upload_adaptation_handoff(
                workspace,
                source_kind=source_kind,
                source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
                review_state="approved_for_build",
                job_id=JOB_ID,
                attempt_number=ATTEMPT_NUMBER,
            )
        )
        self.assertEqual(handoff.get("status"), "ready", handoff.get("diagnostics"))
        authoring = __import__(
            "web.extensions.toolkit_adaptation_runtime",
            fromlist=["run_upload_adaptation_authoring"],
        ).run_upload_adaptation_authoring(
            handoff,
            workspace=workspace,
            author_runner=FakeAuthorRunner(dossier_builder=_dossier_for_attempt),
            model="mock-adaptation-model",
        )
        self.assertTrue(authoring.get("ok"), authoring.get("diagnostics"))
        dossier = authoring.get("dossier")
        dossier_validation = (
            validate_adaptation_dossier(dossier)
            if isinstance(dossier, Mapping)
            else {"valid": False}
        )
        self.assertTrue(dossier_validation.get("valid"))
        self.assertTrue(dossier_validation.get("build_ready"))
        return authoring

    def test_upload_markdown_envelope_reaches_packet_build_identity_preserved(self):
        """The full real upload envelope arrives at the packet builder with
        every Python-owned identity field intact and never relabeled."""
        authoring = self._real_upload_authoring("markdown")
        dossier = authoring["dossier"]
        provenance = routes_module._build_adaptation_route_provenance(authoring)
        attempt_id = str(authoring["attempt"]["attempt_id"])
        source_path = str(authoring["source_identity"].get("source_path") or "")
        staging_target = self._reserve_staging(
            FIXTURE_HASH,
            attempt_id=attempt_id,
            revision_number=0,
            source_path=source_path,
        )

        captured: List[Dict[str, Any]] = []
        result = self._run_packet_build(
            self._workspace_rel(self.scratch / "workspace"),
            JOB_ID,
            captured=captured,
            adaptation_kwargs={
                "adaptation_route": BUILD_MODE_LLM_ADAPTATION,
                "adaptation_dossier": dossier,
                "adaptation_provenance": provenance,
                "adaptation_staging_root": self.staging_root,
                "adaptation_staging_target": staging_target,
            },
        )

        self.assertEqual(result["status"], "success", result.get("error"))
        self.assertEqual(result["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        self.assertTrue(captured)
        builder_input = captured[0]

        # -- Builder input carries the validated dossier envelope ------------
        self.assertEqual(builder_input["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        handoff_dossier = builder_input["llm_adaptation"]["dossier"]
        self.assertEqual(handoff_dossier["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff_dossier["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(
            handoff_dossier["adaptation_mode"], BUILD_MODE_LLM_ADAPTATION
        )
        handoff_provenance = builder_input["llm_adaptation"]["provenance"]
        self.assertEqual(handoff_provenance["attempt_id"], attempt_id)
        self.assertEqual(handoff_provenance["attempt_number"], ATTEMPT_NUMBER)
        self.assertEqual(handoff_provenance["revision_number"], 0)
        self.assertEqual(handoff_provenance["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff_provenance["source_format"], "upload_markdown")
        self.assertEqual(handoff_provenance["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(handoff_provenance["rights_review_required"], False)
        self.assertEqual(handoff_provenance["rights_review_status"], "not_required")
        world = handoff_provenance["world_context_provenance"]
        self.assertEqual(world["fallback_status"], "seed_data_unavailable")
        self.assertIs(world["read_only"], True)
        self.assertEqual(world["world_seed_status"], "unavailable")
        self.assertEqual(builder_input["world_context_provenance"], world)

        # -- Staging identity preserved (reserved target used, no new one) ---
        staging = builder_input["staging_target"]
        self.assertEqual(staging["path"], staging_target["path"])
        self.assertEqual(staging["stage_id"], staging_target["stage_id"])
        self.assertEqual(staging["attempt_id"], attempt_id)
        self.assertEqual(staging["revision_number"], 0)
        self.assertTrue(str(staging["path"]).startswith(self.staging_root + "/"))
        self.assertNotIn("modules/", str(staging["path"]))

        # -- Result surfaces carry the adaptation context --------------------
        self.assertEqual(result["staging_target"]["path"], staging_target["path"])
        self.assertEqual(result["staging_target"]["completion_state"], "completed")
        self.assertEqual(result["world_context_provenance"]["fallback_status"], "seed_data_unavailable")
        self.assertEqual(
            result["adaptation_route_resolution"]["status"], "enabled"
        )
        self.assertEqual(result["adaptation_route_resolution"]["mode"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(result["adaptation_gates"]["playable_status"], "pass")
        self.assertIs(
            result["adaptation_gates"]["publication"]["attempted"], False,
            "the packet-builder boundary never publishes",
        )
        attempt_report = result["adaptation_attempt_report"]
        self.assertEqual(attempt_report["status"], "persisted")
        self.assertEqual(attempt_report["attempt_id"], attempt_id)
        self.assertEqual(attempt_report["revision_number"], 0)
        self.assertNotIn("modules/", str(attempt_report.get("path") or ""))

        # -- Source-lock separation: no legacy lock fields on adaptation -----
        for legacy_field in (
            "source_npc_names",
            "source_location_names",
            "source_puzzle_ids",
            "source_tone",
            "source_monster_refs",
            "source_encounter_seeds",
            "blueprint",
            "handoff_mode",
        ):
            self.assertNotIn(legacy_field, builder_input)
        self.assertEqual(packet_builder._build_module_builder_source_context(builder_input), "")

        # -- No raw source / credentials / absolute paths --------------------
        serialized = self._serialized_adaptation_fields(builder_input, result)
        self.assertNotIn("rusted spyglass", serialized)
        self.assertNotIn("sk-", serialized)
        self.assertNotIn("Bearer ", serialized)
        self.assertNotIn(str(REPO_ROOT), serialized)
        self.assertNotIn("Source LOCK CONTEXT", serialized)

        self._assert_real_sentinels_unchanged(self._real_module_sentinels())

    def test_upload_pdf_kind_preserved_in_packet_envelope(self):
        """PDF uploads keep their normalized kind through the packet builder."""
        authoring = self._real_upload_authoring("pdf")
        self.assertEqual(authoring["input_kind"], "upload_pdf")
        dossier = authoring["dossier"]
        provenance = routes_module._build_adaptation_route_provenance(authoring)
        attempt_id = str(authoring["attempt"]["attempt_id"])
        source_path = str(authoring["source_identity"].get("source_path") or "")
        staging_target = self._reserve_staging(
            FIXTURE_HASH,
            attempt_id=attempt_id,
            revision_number=0,
            source_path=source_path,
        )

        captured: List[Dict[str, Any]] = []
        result = self._run_packet_build(
            self._workspace_rel(self.scratch / "workspace"),
            JOB_ID,
            captured=captured,
            adaptation_kwargs={
                "adaptation_route": BUILD_MODE_LLM_ADAPTATION,
                "adaptation_dossier": dossier,
                "adaptation_provenance": provenance,
                "adaptation_staging_root": self.staging_root,
                "adaptation_staging_target": staging_target,
            },
        )
        self.assertEqual(result["status"], "success", result.get("error"))
        builder_input = captured[0]
        self.assertEqual(
            builder_input["llm_adaptation"]["provenance"]["source_format"],
            "upload_pdf",
        )
        self.assertEqual(builder_input["llm_adaptation"]["dossier"]["source_hash"], FIXTURE_HASH)

    def test_handoff_never_relabels_python_owned_dossier_identity(self):
        """A supplied provenance cannot relabel the dossier identity at the
        packet-builder boundary: the validated dossier stays authoritative."""
        dossier = _load_fixture_dossier()
        tampered = dict(dossier)
        tampered["source_hash"] = FIXTURE_HASH
        handoff = packet_builder.build_llm_adaptation_handoff(
            tampered,
            {
                "attempt_id": "relabel-attempt",
                "source_hash": "b" * 64,
                "source_title": "Attacker Title",
                "rights_class": "third_party_copyright_restricted",
                "rights_review_required": True,
                "rights_review_status": "pending",
            },
        )
        self.assertEqual(handoff["dossier"]["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff["provenance"]["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff["dossier"]["source_title"], dossier["source_title"])
        self.assertEqual(handoff["dossier"]["rights_class"], dossier["rights_class"])
        self.assertEqual(handoff["provenance"]["rights_class"], dossier["rights_class"])
        self.assertEqual(handoff["provenance"]["attempt_id"], "relabel-attempt")
        self.assertNotIn("source_npc_names", handoff)
        self.assertNotIn("source_location_names", handoff)


class TestRealTextEnvelopePacketBuild(_PacketScratchMixin, unittest.TestCase):
    """The real text-description seam envelope is accepted by the packet
    builder with the same identity coherence as uploads."""

    _REAL_WORKSPACE_BUILDER = text_worker.build_text_description_attempt_workspace
    _REAL_STAGING_CREATOR = text_worker.create_adaptation_staging_target

    def _run_real_seam(self) -> Dict[str, Any]:
        """Run the REAL task 5.1 seam with scratch-redirected workspace and
        staging builders plus an injected author runner.

        The captured builder references are plain functions stored as class
        attributes; they are accessed through ``type(self)`` (not ``self``)
        so the descriptor protocol does not bind them as methods and inject
        ``self`` as an extra positional argument.
        """
        real_workspace_builder = type(self)._REAL_WORKSPACE_BUILDER
        real_staging_creator = type(self)._REAL_STAGING_CREATOR

        def _build_ws_into_scratch(module_name, concept, **kw):
            return real_workspace_builder(
                module_name,
                concept,
                workspace_root=self.workspaces_root,
                staging_root=self.staging_root,
                **kw,
            )

        def _create_staging_into_scratch(source_hash, **kw):
            kw.pop("staging_root", None)
            return real_staging_creator(
                source_hash,
                staging_root=self.staging_root,
                **kw,
            )

        with patch.object(
            model_config_module, "ENABLE_LLM_ADAPTATION", True
        ), patch.object(
            text_worker,
            "build_text_description_attempt_workspace",
            side_effect=_build_ws_into_scratch,
        ), patch.object(
            text_worker,
            "create_adaptation_staging_target",
            side_effect=_create_staging_into_scratch,
        ):
            seam_result = text_worker.run_text_description_adaptation_seam(
                MODULE_NAME,
                FIXTURE_TEXT,
                {"job_id": JOB_ID},
                author_runner=FakeAuthorRunner(dossier_builder=_dossier_for_attempt),
                model="mock-adaptation-model",
            )
        self.assertIsNotNone(seam_result)
        self.assertEqual(seam_result["outcome"], "authoring_ready_pending_publication")
        return seam_result

    def test_text_seam_envelope_reaches_packet_build_identity_preserved(self):
        """The real text seam handoff feeds the packet builder exactly as the
        task 5.2 publication transaction does, with identity preserved."""
        seam_result = self._run_real_seam()
        handoff = seam_result["adaptation_handoff"]
        workspace_path = str(handoff["workspace_path"])
        self.assertFalse(Path(workspace_path).is_absolute())

        captured: List[Dict[str, Any]] = []
        result = self._run_packet_build(
            Path(workspace_path),
            JOB_ID,
            captured=captured,
            adaptation_kwargs={
                "adaptation_route": BUILD_MODE_LLM_ADAPTATION,
                "adaptation_dossier": handoff["dossier"],
                "adaptation_provenance": handoff["provenance"],
                "adaptation_staging_root": handoff["staging_root"],
                "adaptation_staging_target": handoff["staging_target"],
            },
        )

        self.assertEqual(result["status"], "success", result.get("error"))
        self.assertEqual(result["build_mode"], BUILD_MODE_LLM_ADAPTATION)
        self.assertEqual(result["module_name"], MODULE_NAME)
        self.assertTrue(captured)
        builder_input = captured[0]

        # -- Identity coherence across the real seam envelope ----------------
        handoff_dossier = builder_input["llm_adaptation"]["dossier"]
        self.assertEqual(handoff_dossier["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff_dossier["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(
            handoff_dossier["adaptation_mode"], BUILD_MODE_LLM_ADAPTATION
        )
        handoff_provenance = builder_input["llm_adaptation"]["provenance"]
        attempt_metadata = handoff["provenance"]["attempt_metadata"]
        self.assertEqual(handoff_provenance["attempt_id"], attempt_metadata["attempt_id"])
        self.assertEqual(handoff_provenance["attempt_number"], attempt_metadata["attempt_number"])
        self.assertEqual(handoff_provenance["revision_number"], attempt_metadata["revision_number"])
        self.assertEqual(attempt_metadata["job_id"], JOB_ID)
        self.assertEqual(result["job_id"], JOB_ID)
        self.assertEqual(handoff_provenance["source_hash"], FIXTURE_HASH)
        self.assertEqual(handoff_provenance["source_format"], "text_description")
        self.assertEqual(handoff_provenance["rights_class"], RIGHTS_CLASS_USER_AUTHORED)
        self.assertEqual(handoff_provenance["rights_review_status"], "not_required")
        world = handoff_provenance["world_context_provenance"]
        self.assertEqual(world["fallback_status"], "seed_data_unavailable")
        self.assertIs(world["read_only"], True)

        # -- Staging target is the seam-reserved one, isolated --------------
        staging = builder_input["staging_target"]
        self.assertEqual(staging["path"], handoff["staging_target"]["path"])
        self.assertEqual(staging["attempt_id"], attempt_metadata["attempt_id"])
        self.assertTrue(str(staging["path"]).startswith(self.staging_root + "/"))
        self.assertNotIn("modules/", str(staging["path"]))

        # -- Result surfaces ------------------------------------------------
        self.assertEqual(result["staging_target"]["completion_state"], "completed")
        self.assertEqual(
            result["adaptation_route_resolution"]["status"], "enabled"
        )
        self.assertEqual(result["adaptation_gates"]["playable_status"], "pass")
        attempt_report = result["adaptation_attempt_report"]
        self.assertEqual(attempt_report["status"], "persisted")
        self.assertEqual(attempt_report["attempt_id"], attempt_metadata["attempt_id"])
        self.assertEqual(attempt_report["revision_number"], 0)

        # -- Source-lock separation + no leakage ----------------------------
        for legacy_field in (
            "source_npc_names",
            "source_location_names",
            "source_puzzle_ids",
            "source_tone",
            "source_monster_refs",
            "source_encounter_seeds",
            "blueprint",
            "handoff_mode",
        ):
            self.assertNotIn(legacy_field, builder_input)
        self.assertEqual(packet_builder._build_module_builder_source_context(builder_input), "")
        serialized = self._serialized_adaptation_fields(builder_input, result)
        self.assertNotIn("rusted spyglass", serialized)
        self.assertNotIn("sk-", serialized)
        self.assertNotIn("Bearer ", serialized)
        self.assertNotIn(str(REPO_ROOT), serialized)

        self._assert_real_sentinels_unchanged(self._real_module_sentinels())


class TestFreshRevisionIsolation(_PacketScratchMixin, unittest.TestCase):
    """Fresh semantic revisions use distinct isolated staging targets and
    retain prior attempt diagnostics."""

    def _ready_envelope(self) -> Dict[str, Any]:
        workspace = _make_upload_workspace(self.scratch, FIXTURE_HASH)
        runtime = __import__(
            "web.extensions.toolkit_adaptation_runtime",
            fromlist=["build_upload_adaptation_handoff", "run_upload_adaptation_authoring"],
        )
        handoff = runtime.build_upload_adaptation_handoff(
            workspace,
            source_kind="markdown",
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
            review_state="approved_for_build",
            job_id=JOB_ID,
            attempt_number=ATTEMPT_NUMBER,
        )
        self.assertEqual(handoff.get("status"), "ready", handoff.get("diagnostics"))
        authoring = runtime.run_upload_adaptation_authoring(
            handoff,
            workspace=workspace,
            author_runner=FakeAuthorRunner(dossier_builder=_dossier_for_attempt),
            model="mock-adaptation-model",
        )
        self.assertTrue(authoring.get("ok"), authoring.get("diagnostics"))
        provenance = routes_module._build_adaptation_route_provenance(authoring)
        return {
            "workspace": workspace,
            "dossier": authoring["dossier"],
            "provenance": provenance,
            "attempt_id": str(authoring["attempt"]["attempt_id"]),
            "source_path": str(authoring["source_identity"].get("source_path") or ""),
        }

    def test_fresh_revision_targets_distinct_staging_and_retains_prior_attempt(self):
        """Revision 1 reserves a DIFFERENT staging target than revision 0,
        never overwrites it, and keeps the prior attempt artifacts."""
        envelope = self._ready_envelope()
        workspace = envelope["workspace"]
        dossier = envelope["dossier"]
        attempt_id = envelope["attempt_id"]

        target_zero = self._reserve_staging(
            FIXTURE_HASH,
            attempt_id=attempt_id,
            revision_number=0,
            source_path=envelope["source_path"],
        )
        provenance_zero = envelope["provenance"]
        captured_zero: List[Dict[str, Any]] = []
        result_zero = self._run_packet_build(
            self._workspace_rel(workspace),
            JOB_ID,
            captured=captured_zero,
            adaptation_kwargs={
                "adaptation_route": BUILD_MODE_LLM_ADAPTATION,
                "adaptation_dossier": dossier,
                "adaptation_provenance": provenance_zero,
                "adaptation_staging_root": self.staging_root,
                "adaptation_staging_target": target_zero,
            },
        )
        self.assertEqual(result_zero["status"], "success", result_zero.get("error"))
        self.assertEqual(result_zero["staging_target"]["revision_number"], 0)

        # A fresh semantic revision reuses the same attempt with revision 1.
        provenance_one = deepcopy(provenance_zero)
        provenance_one["attempt_metadata"]["revision_number"] = 1
        target_one = self._reserve_staging(
            FIXTURE_HASH,
            attempt_id=attempt_id,
            revision_number=1,
            source_path=envelope["source_path"],
        )
        captured_one: List[Dict[str, Any]] = []
        result_one = self._run_packet_build(
            self._workspace_rel(workspace),
            JOB_ID,
            captured=captured_one,
            adaptation_kwargs={
                "adaptation_route": BUILD_MODE_LLM_ADAPTATION,
                "adaptation_dossier": dossier,
                "adaptation_provenance": provenance_one,
                "adaptation_staging_root": self.staging_root,
                "adaptation_staging_target": target_one,
            },
        )
        self.assertEqual(result_one["status"], "success", result_one.get("error"))
        self.assertEqual(result_one["staging_target"]["revision_number"], 1)

        # -- Distinct isolated project-relative staging targets --------------
        path_zero = str(target_zero["path"])
        path_one = str(target_one["path"])
        self.assertNotEqual(path_zero, path_one)
        self.assertIn("revision_000", path_zero)
        self.assertIn("revision_001", path_one)
        for path in (path_zero, path_one):
            self.assertTrue(path.startswith(self.staging_root + "/"))
            self.assertNotIn("modules/", path)

        # -- Fresh reservation proves no overwrite of the prior target -------
        staging_root_dir = Path(self.staging_root)
        attempt_dir = staging_root_dir / attempt_id
        self.assertTrue((attempt_dir / "revision_000").is_dir())
        self.assertTrue((attempt_dir / "revision_001").is_dir())
        prior_metadata = attempt_dir / "revision_000" / "staging_metadata.json"
        fresh_metadata = attempt_dir / "revision_001" / "staging_metadata.json"
        self.assertTrue(prior_metadata.exists())
        self.assertTrue(fresh_metadata.exists())
        prior_state = json.loads(prior_metadata.read_text(encoding="utf-8"))["completion_state"]
        self.assertEqual(prior_state, "completed")
        self.assertEqual(
            json.loads(fresh_metadata.read_text(encoding="utf-8"))["completion_state"],
            "completed",
        )
        # The revision-0 builder input used the prior target; revision 1 used
        # the fresh one.
        self.assertEqual(captured_zero[0]["staging_target"]["path"], path_zero)
        self.assertEqual(captured_one[0]["staging_target"]["path"], path_one)

        # -- Prior attempt diagnostics retained ------------------------------
        attempt_root = workspace / "adaptation_attempts" / attempt_id
        self.assertTrue((attempt_root / "build_result.json").exists())
        self.assertTrue(
            (attempt_root / "revisions" / "revision_001" / "build_result.json").exists()
        )
        prior_report = json.loads(
            (attempt_root / "build_result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(prior_report["revision_number"], 0)

        # -- No direct module write, no registry/campaign publication --------
        self.assertFalse((REPO_ROOT / "modules" / MODULE_NAME).exists())
        self._assert_real_sentinels_unchanged(self._real_module_sentinels())
        self.assertEqual(
            result_one["adaptation_gates"]["publication"]["attempted"], False
        )


class TestLegacyAndDefaultShapesPreserved(_PacketScratchMixin, unittest.TestCase):
    """Default and legacy calls keep their exact prior result shapes and keep
    source-lock fields in the legacy channel only."""

    _VALID_V2_VERSION = "source_faithful_builder_blueprint.v2"

    def _legacy_workspace_with_blueprint(self) -> Path:
        workspace = self.scratch / "legacy_workspace"
        ensure_workspace_placeholders(workspace)
        files = get_workspace_files(workspace)
        packet: Dict[str, Any] = {
            "packet_version": "v1",
            "normalization_state": "normalized",
            "source_path": "uploads/legacy.md",
            "source_hash": FIXTURE_HASH,
            "title": "Sunken Lighthouse",
            "author": "",
            "description": "A legacy fixture with authored source locks.",
            "adventure_summary": "Locks must stay in the legacy channel.",
            "module_tone": "haunted",
            "acts": [{"name": "Descent", "summary": "Into the dark."}],
            "locations": [
                {
                    "name": "Keeper's Quarters",
                    "location": "tower",
                    "description": "Rusted spyglass.",
                }
            ],
            "npc_seeds": [],
            "encounter_seeds": ["Drowned Bell Guard"],
            "monster_refs": ["Drowned Bell Guard"],
            "assumptions": ["Legacy source-lock separation fixture."],
            "source_rights_class": SOURCE_RIGHTS_USER_AUTHORED,
        }
        persist_normalized_packet_artifact(workspace, packet)
        snapshot = build_review_snapshot(
            job_id="legacy-packet-job",
            decision=REVIEW_DECISION_APPROVE,
            packet=packet,
            source_rights_class=SOURCE_RIGHTS_USER_AUTHORED,
        )
        persist_review_snapshot_artifact(workspace, snapshot)
        blueprint: Dict[str, Any] = {
            "blueprint_version": self._VALID_V2_VERSION,
            "blueprint_status": "ready",
            "module": {"title": "Sunken Lighthouse", "summary": "fixture"},
            "source_lock": {
                "canonical_names_locked": True,
                "invented_major_entities_forbidden": True,
            },
            "area_plan": [],
            "location_roster": [
                {"name": "Keeper's Quarters", "display_name": "Keeper's Quarters"},
                {"name": "Flooded Stairs", "display_name": "Flooded Stairs"},
            ],
            "npc_roster": [
                {"name": "Keeper Elowen", "display_name": "Keeper Elowen"},
                {"name": "Drowned Bell Guard", "display_name": "Drowned Bell Guard"},
            ],
            "plot_graph": [],
            "puzzle_graph": [
                {"puzzle_id": "skull_riddle", "chain_id": "pz-1", "title": "Skull Riddle"}
            ],
            "clue_graph": [],
            "encounter_plan": [],
            "item_roster": [],
            "tone_requirements": ["haunted maritime dread"],
            "source_refs": [],
            "warnings": [],
            "coverage": {},
            "enrichment_allowlist": {},
            "artifact_refs": {},
            "blockers": [],
        }
        (files["builder_blueprint"]).write_text(
            json.dumps(blueprint), encoding="utf-8"
        )
        (files["builder_blueprint_report"]).write_text(
            json.dumps(
                {"blueprint_status": "ready", "fidelity_status": "pass"}
            ),
            encoding="utf-8",
        )
        files["builder_narrative"].write_text(
            "Build the lighthouse module from the blueprint.", encoding="utf-8"
        )
        return workspace

    def test_default_call_preserves_legacy_shape_and_keeps_source_locks(self):
        """A default call (no adaptation arguments) keeps the legacy result
        shape, carries the bounded source-lock fields in the legacy channel,
        and carries NO adaptation markers."""
        workspace = self._legacy_workspace_with_blueprint()
        captured: List[Dict[str, Any]] = []
        result = self._run_packet_build(
            workspace,
            "legacy-packet-job",
            captured=captured,
            adaptation_kwargs={},
            legacy_flags=True,
        )

        self.assertEqual(result["status"], "success", result.get("error"))
        self.assertEqual(result["build_mode"], "source_enhanced_modulebuilder")
        self.assertIn(result["build_mode"], LEGACY_ACCURATE_INGEST_BUILD_MODES)
        for legacy_key in (
            "status",
            "stage",
            "job_id",
            "build_mode",
            "module_name",
            "output_directory",
            "builder_input_path",
            "build_result_path",
        ):
            self.assertIn(legacy_key, result)
        # No adaptation markers on a default/legacy result.
        for adaptation_key in (
            "adaptation_route_resolution",
            "adaptation_gates",
            "adaptation_attempt_report",
            "adaptation_provenance",
            "world_context_provenance",
            "llm_adaptation",
        ):
            self.assertNotIn(adaptation_key, result)
        self.assertIsNone(result.get("staging_target"))

        self.assertTrue(captured)
        builder_input = captured[0]
        self.assertNotIn("llm_adaptation", builder_input)
        self.assertNotIn("world_context_provenance", builder_input)
        # The bounded source-lock fields stay in the legacy channel.
        self.assertEqual(
            builder_input.get("source_npc_names"),
            ["Keeper Elowen", "Drowned Bell Guard"],
        )
        self.assertEqual(
            builder_input.get("source_location_names"),
            ["Keeper's Quarters", "Flooded Stairs"],
        )
        self.assertEqual(builder_input.get("source_puzzle_ids"), ["skull_riddle"])
        self.assertEqual(builder_input.get("source_tone"), ["haunted maritime dread"])
        self.assertEqual(builder_input.get("handoff_mode"), "source_blueprint")
        self.assertIn("blueprint", builder_input)

        # The bounded source-lock prompt block is produced for legacy input.
        source_context = packet_builder._build_module_builder_source_context(builder_input)
        self.assertIn("=== SOURCE LOCK CONTEXT ===", source_context)
        self.assertIn("NPCS: Keeper Elowen, Drowned Bell Guard", source_context)
        self.assertIn("SOURCE_LOCKS: canonical_names_locked, invented_major_entities_forbidden", source_context)
        self.assertNotIn("rusted spyglass", source_context)
        self.assertLess(len(source_context), 2048)

    def test_requested_adaptation_while_disabled_keeps_legacy_result(self):
        """A requested adaptation route with the flag disabled resolves to
        legacy and never relabels the result or builder input."""
        workspace = self._legacy_workspace_with_blueprint()
        captured: List[Dict[str, Any]] = []
        result = self._run_packet_build(
            workspace,
            "legacy-packet-job",
            captured=captured,
            adaptation_kwargs={
                "adaptation_route": BUILD_MODE_LLM_ADAPTATION,
                "adaptation_dossier": _load_fixture_dossier(),
            },
            enabled=False,
            legacy_flags=True,
        )
        self.assertEqual(result["status"], "success", result.get("error"))
        self.assertEqual(
            result["adaptation_route_resolution"]["status"], "legacy"
        )
        self.assertEqual(
            result["adaptation_route_resolution"]["mode"],
            "accurate_ingest_legacy",
        )
        self.assertIn(result["build_mode"], LEGACY_ACCURATE_INGEST_BUILD_MODES)
        self.assertNotIn("llm_adaptation", captured[0])
        self.assertNotIn("adaptation_gates", result)
        self.assertNotIn("adaptation_attempt_report", result)


class TestPacketRealEnvelopeHygiene(_PacketScratchMixin, unittest.TestCase):
    """Changed files follow SPDX/ASCII rules and stay OS-temp free."""

    def test_own_file_is_ascii_and_spdx(self):
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText", text)
        self.assertIn("SPDX-License-Identifier", text)
        non_ascii = [ch for ch in text if ord(ch) >= 128]
        self.assertEqual(non_ascii, [])

    def test_no_os_temp_or_absolute_scratch_paths(self):
        own_source = Path(__file__).read_text(encoding="utf-8")
        scan = own_source.split("def test_no_os_temp_or_absolute_scratch_paths", 1)[0]
        for token in ("tempfile", "TemporaryDirectory", "/tmp", "/var/folders"):
            with self.subTest(token=token):
                self.assertNotIn(token, scan)

    def test_scratch_is_project_relative(self):
        self.assertTrue(str(SCRATCH_ROOT).startswith(str(REPO_ROOT)))
        own_source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("toolkit_adaptation_packet_real_envelope", own_source)


if __name__ == "__main__":
    unittest.main()
