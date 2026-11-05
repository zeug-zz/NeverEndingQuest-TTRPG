# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Fixture-derived, shadow-only combat zone ledger for the mapping pilot.

This module accepts plain fixture and response data only. It has no imports from
the combat runtime and exposes no path that can approve, reject, or mutate a
gameplay action. Movement and narration findings are evidence in this ledger.
"""

from __future__ import annotations

import copy
import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from scripts.mapping_pilot.adapter import (
    MovementHintObservation,
    observe_movement_hint as parse_movement_hint,
)
from scripts.mapping_pilot.fixtures import load_verified_fixtures
from scripts.mapping_pilot.layout import normalize_fixture_layout
from scripts.mapping_pilot.manifest import (
    DEFAULT_PREREG_ROOT,
    PROJECT_ROOT,
    ManifestVerificationError,
    verify_manifest,
)


COMBAT_FIXTURE_ID = "combat_stage_tavern_zones"
MOVEMENT_OUTCOMES = frozenset(
    ("exact", "acceptable", "wrong", "refused", "clarified")
)
CONTRADICTION_CATEGORIES = frozenset(
    (
        "melee_across_non_engaged_zones",
        "ranged_through_cover_or_blocked_line_of_sight",
        "actor_assigned_two_zones",
        "movement_exceeds_allowance_or_non_adjacent",
        "enemy_zone_inconsistent_with_ledger",
        "false_elevation_cover_or_engagement_relation",
    )
)
_BAND_NAMES = ("Engaged", "Near", "Far", "Out of sight")
_BAND_DEFINITIONS = {
    "Engaged": "same fixture melee group; melee possible; leaving provokes",
    "Near": "not Engaged and one adjacency edge away; reachable with standard movement",
    "Far": "not Engaged and more than one adjacency edge away; ranged or extended movement only",
    "Out of sight": "pairwise line of sight is blocked; existence known only if previously perceived; overrides the other band labels",
}
_DISTANCE_POLICY = "schematic graph only; do not infer feet or other metric distance"
_MELEE_POLICY = (
    "At each enemy phase, each melee group selects the nearest reachable PC by "
    "shortest adjacency path. If already in a zone occupied by a PC in its "
    "engagement group, hold position. Otherwise advance exactly one adjacent "
    "zone step along a shortest path. If the group enters a PC-occupied zone, "
    "it joins that PC's engagement group for subsequent band calculations. Do "
    "not move through a non-adjacent zone."
)
_ARCHER_POLICY = (
    "Hold MPV2_Z_BALCONY and its authored half-cover relation; do not relocate "
    "unless a separately scripted event changes it."
)
_HINT_FIELDS = ("from", "to", "disengage", "cover_sought")


@dataclass(frozen=True)
class ZoneDefinition:
    """A fixture-authored zone and its schematic elevation."""

    zone_id: str
    name: str
    feature_id: str
    position: str
    elevation_level: str
    relative_levels_above_ground: int


@dataclass(frozen=True)
class CoverRelation:
    """Fixture-authored directional cover and line-of-sight facts."""

    zone_a: str
    zone_b: str
    cover_for_target_a_from_b: str
    cover_for_target_b_from_a: str
    line_of_sight: str


@dataclass(frozen=True)
class MovementHintValidation:
    """Result of validating an observation against the shadow ledger only."""

    actor_id: str
    status: str
    reason: Optional[str]
    movement_mode: str
    from_zone: Optional[str]
    to_zone: Optional[str]
    steps: Optional[int]
    path: tuple[str, ...]
    applied_to_shadow: bool


@dataclass(frozen=True)
class EnemyMoveObservation:
    """One deterministic fixture-policy movement or hold observation."""

    actor_id: str
    status: str
    from_zone: str
    to_zone: str
    target_actor_id: Optional[str]
    path: tuple[str, ...]
    reason: str


@dataclass
class ZoneLedger:
    """Mutable pilot evidence detached from every runtime-owned state object."""

    fixture_id: str
    party_size: int
    zones: dict[str, ZoneDefinition]
    adjacency: dict[str, tuple[str, ...]]
    cover_relations: tuple[CoverRelation, ...]
    band_definitions: dict[str, str]
    distance_policy: str
    positions: dict[str, str]
    initial_positions: dict[str, str]
    engagement_groups: dict[str, list[str]]
    actor_kinds: dict[str, str]
    actor_names: dict[str, str]
    pc_actor_ids: tuple[str, ...]
    enemy_group_actor_ids: tuple[str, ...]
    balcony_archer_actor_id: str
    movement_allowance_zone_steps: dict[str, int]
    target_tie_break_order: tuple[str, ...]
    path_tie_break_order: tuple[str, ...]
    enemy_movement_policy: dict[str, Any]
    authored_distances: tuple[dict[str, Any], ...]
    observations: list[dict[str, Any]] = field(default_factory=list)


def initialize_zone_ledger(
    party_size: int, prereg_root: Optional[Union[str, Path]] = None
) -> ZoneLedger:
    """Load verified frozen inputs and initialize a P1 or P4 shadow ledger.

    ``load_verified_fixtures`` verifies every manifest entry before reading the
    combat fixture. ``party_size`` must be exactly 1 or 4; no other party shape
    is inferred or synthesized.
    """
    party_key = _party_key(party_size)
    fixtures, _verified_hashes = load_verified_fixtures(prereg_root)
    fixture = fixtures.get(COMBAT_FIXTURE_ID)
    if not isinstance(fixture, Mapping):
        raise ValueError("verified combat fixture is missing")
    return _build_zone_ledger(fixture, party_size, party_key)


def zone_band(ledger: ZoneLedger, actor_a: str, actor_b: str) -> str:
    """Return one preregistered graph band; blocked sight overrides other bands."""
    zone_a = _actor_zone(ledger, actor_a)
    zone_b = _actor_zone(ledger, actor_b)
    sightline = line_of_sight_between(ledger, zone_a, zone_b)
    if sightline == "blocked":
        return "Out of sight"
    if zone_a == zone_b or _share_engagement_group(ledger, actor_a, actor_b):
        return "Engaged"
    path = _shortest_path(ledger, zone_a, zone_b)
    if path is None:
        return "Far"
    if len(path) - 1 <= 1:
        return "Near"
    return "Far"


def cover_between(
    ledger: ZoneLedger, source_zone_id: str, target_zone_id: str
) -> str:
    """Return the authored cover received by target from source."""
    _require_zone(ledger, source_zone_id)
    _require_zone(ledger, target_zone_id)
    if source_zone_id == target_zone_id:
        return "none"
    relation = _cover_relation(ledger, source_zone_id, target_zone_id)
    if source_zone_id == relation.zone_a:
        return relation.cover_for_target_b_from_a
    return relation.cover_for_target_a_from_b


def line_of_sight_between(
    ledger: ZoneLedger, source_zone_id: str, target_zone_id: str
) -> str:
    """Return fixture-authored line of sight; no geometry is inferred."""
    _require_zone(ledger, source_zone_id)
    _require_zone(ledger, target_zone_id)
    if source_zone_id == target_zone_id:
        return "clear"
    return _cover_relation(ledger, source_zone_id, target_zone_id).line_of_sight


def observe_movement_hint(
    ledger: ZoneLedger,
    actor_id: str,
    response: Any,
    movement_mode: str = "standard",
) -> MovementHintValidation:
    """Observe a response hint and, if valid, update only this ledger's PC copy.

    Standard movement permits at most one adjacent edge; extended movement
    permits at most two. The adapter's ``MovementHintObservation`` parser owns
    the response-shape contract. Missing, malformed, or illegal hints are logged
    as observations and never reject the response or its other fields.
    """
    if movement_mode not in ("standard", "extended"):
        raise ValueError("movement_mode must be 'standard' or 'extended'")
    parsed = parse_movement_hint(response)
    result: MovementHintValidation
    hint = parsed.hint
    if parsed.status != "valid" or hint is None:
        result = MovementHintValidation(
            actor_id=actor_id,
            status=parsed.status,
            reason=parsed.reason,
            movement_mode=movement_mode,
            from_zone=None,
            to_zone=None,
            steps=None,
            path=(),
            applied_to_shadow=False,
        )
    else:
        result = _validate_and_apply_hint(ledger, actor_id, hint, movement_mode)

    ledger.observations.append(
        {
            "kind": "movement_hint",
            "actor_id": actor_id,
            "status": result.status,
            "reason": result.reason,
            "movement_mode": result.movement_mode,
            "hint": copy.deepcopy(hint),
            "path": list(result.path),
            "steps": result.steps,
            "applied_to_shadow": result.applied_to_shadow,
        }
    )
    return result


def resolve_enemy_phase(ledger: ZoneLedger) -> tuple[EnemyMoveObservation, ...]:
    """Apply one deterministic fixture enemy phase to the shadow ledger.

    Melee groups are processed in fixture ``occupant_roles`` order. Each targets
    the nearest PC by shortest path, then ``target_tie_break_order``; among equal
    shortest paths, the next zone is selected by ``path_tie_break_order``. These
    explicit fixture orders are the complete tie-break policy. The authored
    balcony archer never moves and its cover table is never changed.
    """
    archer_initial_zone = ledger.initial_positions[ledger.balcony_archer_actor_id]
    if ledger.positions.get(ledger.balcony_archer_actor_id) != archer_initial_zone:
        raise ValueError("balcony archer position differs from authored fixture state")

    observations: list[EnemyMoveObservation] = []
    for actor_id in ledger.enemy_group_actor_ids:
        current_zone = ledger.positions[actor_id]
        current_group = _engagement_group_for(ledger, actor_id)
        same_group_pcs = [
            pc_id
            for pc_id in ledger.pc_actor_ids
            if _engagement_group_for(ledger, pc_id) == current_group
            and ledger.positions[pc_id] == current_zone
        ]
        if same_group_pcs:
            observation = EnemyMoveObservation(
                actor_id=actor_id,
                status="held",
                from_zone=current_zone,
                to_zone=current_zone,
                target_actor_id=_ordered_actor(same_group_pcs, ledger),
                path=(current_zone,),
                reason="already_in_zone_with_pc_in_engagement_group",
            )
            observations.append(observation)
            continue

        target_actor_id, path = _nearest_pc_path(ledger, current_zone)
        if not path:
            raise ValueError("fixture enemy policy has no reachable PC")
        if len(path) == 1:
            _join_engagement_group(ledger, actor_id, target_actor_id)
            observation = EnemyMoveObservation(
                actor_id=actor_id,
                status="joined",
                from_zone=current_zone,
                to_zone=current_zone,
                target_actor_id=target_actor_id,
                path=path,
                reason="already_in_pc_occupied_zone",
            )
            observations.append(observation)
            continue

        next_zone = path[1]
        ledger.positions[actor_id] = next_zone
        occupying_pcs = [
            pc_id
            for pc_id in ledger.pc_actor_ids
            if ledger.positions[pc_id] == next_zone
        ]
        if occupying_pcs:
            join_actor_id = _ordered_actor(occupying_pcs, ledger)
            _join_engagement_group(ledger, actor_id, join_actor_id)
            status = "moved_and_joined"
            reason = "entered_pc_occupied_zone"
        else:
            status = "moved"
            reason = "advanced_one_fixture_adjacency_step"
        observation = EnemyMoveObservation(
            actor_id=actor_id,
            status=status,
            from_zone=current_zone,
            to_zone=next_zone,
            target_actor_id=target_actor_id,
            path=path,
            reason=reason,
        )
        observations.append(observation)

    archer_id = ledger.balcony_archer_actor_id
    observations.append(
        EnemyMoveObservation(
            actor_id=archer_id,
            status="held",
            from_zone=archer_initial_zone,
            to_zone=archer_initial_zone,
            target_actor_id=None,
            path=(archer_initial_zone,),
            reason="fixture_policy_holds_authored_balcony_position_and_cover",
        )
    )
    for observation in observations:
        ledger.observations.append(_enemy_move_payload(observation))
    return tuple(observations)


def record_contradictions(
    ledger: ZoneLedger, claims: Sequence[Mapping[str, Any]]
) -> int:
    """Record explicit structured contradiction claims without reading prose.

    Each claim with ``contradiction is True`` counts as one observed event. A
    false claim is retained as a non-contradiction observation. Categories are
    the six preregistered combat contradiction groups represented by stable IDs.
    """
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
        raise ValueError("contradiction claims must be a sequence of objects")
    staged: list[dict[str, Any]] = []
    count = 0
    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            raise ValueError("contradiction claim %d must be an object" % index)
        category = claim.get("category")
        contradictory = claim.get("contradiction")
        if not isinstance(category, str) or category not in CONTRADICTION_CATEGORIES:
            raise ValueError("unknown contradiction category at claim %d" % index)
        if not isinstance(contradictory, bool):
            raise ValueError("contradiction claim %d needs a boolean contradiction" % index)
        copied_claim = copy.deepcopy(dict(claim))
        _ensure_json_data(copied_claim, "contradiction claim %d" % index)
        staged.append(
            {
                "kind": "contradiction_claim",
                "category": category,
                "contradiction": contradictory,
                "claim": copied_claim,
            }
        )
        count += int(contradictory)
    ledger.observations.extend(staged)
    return count


def count_contradictions(ledger: ZoneLedger) -> int:
    """Count recorded structured contradiction events."""
    return sum(
        1
        for observation in ledger.observations
        if observation.get("kind") == "contradiction_claim"
        and observation.get("contradiction") is True
    )


def load_script_intended_move(
    turn_id: str,
    party_size: int,
    prereg_root: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    """Return a detached expected movement hint from manifest-verified combat.json."""
    party_key = _party_key(party_size)
    root = _resolve_prereg_root(prereg_root)
    verified_hashes = verify_manifest(root)
    relative_path = "scripts/combat.json"
    if relative_path not in verified_hashes:
        raise ManifestVerificationError(relative_path, "combat script is not listed in manifest")
    try:
        script = json.loads((root / relative_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("cannot load verified combat script") from exc
    if not isinstance(script, Mapping) or not isinstance(script.get("turns"), list):
        raise ValueError("malformed verified combat script")
    matches = [
        turn
        for turn in script["turns"]
        if isinstance(turn, Mapping) and turn.get("id") == turn_id
    ]
    if len(matches) != 1:
        raise ValueError("combat script must contain exactly one turn %s" % turn_id)
    expected_hints = matches[0].get("expected_hint")
    if not isinstance(expected_hints, Mapping):
        raise ValueError("combat turn %s has no expected movement hint" % turn_id)
    intended = expected_hints.get(party_key)
    _normalize_intended_move(intended)
    return copy.deepcopy(dict(intended))


def classify_movement_parse_outcome(
    ledger: ZoneLedger,
    intended_move: Mapping[str, Any],
    observation: MovementHintObservation,
    adjudicated_outcome: Optional[str] = None,
) -> Optional[str]:
    """Classify only exact matches automatically; leave semantic cases unclassified.

    ``acceptable``, ``wrong``, ``refused``, and ``clarified`` can depend on
    narrative intent. They remain ``None`` unless a reviewer supplies an
    explicit preregistered outcome. No prose is parsed here.
    """
    intended = _normalize_intended_move(intended_move)
    if not isinstance(observation, MovementHintObservation):
        raise ValueError("observation must use the adapter MovementHintObservation type")
    if observation.hint is not None:
        _ensure_json_data(observation.hint, "movement observation")

    automatic = _is_exact_movement_match(ledger, intended, observation)
    if adjudicated_outcome is not None and (
        not isinstance(adjudicated_outcome, str)
        or adjudicated_outcome not in MOVEMENT_OUTCOMES
    ):
        raise ValueError("unknown adjudicated movement outcome")
    if adjudicated_outcome == "exact" and not automatic:
        raise ValueError("exact adjudication conflicts with the structured movement hint")
    if automatic and adjudicated_outcome not in (None, "exact"):
        raise ValueError("adjudicated outcome conflicts with exact structured match")
    classification = "exact" if automatic else adjudicated_outcome
    ledger.observations.append(
        {
            "kind": "movement_parse_outcome",
            "intended_move": intended,
            "observed": {
                "status": observation.status,
                "reason": observation.reason,
                "hint": copy.deepcopy(observation.hint),
            },
            "classification": classification,
        }
    )
    return classification


def serialize_ledger(ledger: ZoneLedger) -> str:
    """Serialize current fixture-derived shadow state with canonical JSON keys."""
    payload = {
        "fixture_id": ledger.fixture_id,
        "party_size": "P%d" % ledger.party_size,
        "zones": {zone_id: asdict(zone) for zone_id, zone in ledger.zones.items()},
        "adjacency": {
            zone_id: list(neighbors) for zone_id, neighbors in ledger.adjacency.items()
        },
        "pairwise_cover": [
            asdict(relation)
            for relation in sorted(
                ledger.cover_relations, key=lambda row: (row.zone_a, row.zone_b)
            )
        ],
        "bands": copy.deepcopy(ledger.band_definitions),
        "distance_policy": ledger.distance_policy,
        "positions": copy.deepcopy(ledger.positions),
        "initial_positions": copy.deepcopy(ledger.initial_positions),
        "engagement_groups": copy.deepcopy(ledger.engagement_groups),
        "actor_kinds": copy.deepcopy(ledger.actor_kinds),
        "actor_names": copy.deepcopy(ledger.actor_names),
        "movement_allowance_zone_steps": copy.deepcopy(
            ledger.movement_allowance_zone_steps
        ),
        "target_tie_break_order": list(ledger.target_tie_break_order),
        "path_tie_break_order": list(ledger.path_tie_break_order),
        "enemy_movement_policy": copy.deepcopy(ledger.enemy_movement_policy),
        "authored_distances": list(copy.deepcopy(ledger.authored_distances)),
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def serialize_observations(ledger: ZoneLedger) -> str:
    """Serialize chronological shadow observations with canonical JSON keys."""
    return json.dumps(
        copy.deepcopy(ledger.observations),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _build_zone_ledger(
    fixture: Mapping[str, Any], party_size: int, party_key: Optional[str] = None
) -> ZoneLedger:
    selected_party_key = party_key or _party_key(party_size)
    if not isinstance(fixture, Mapping):
        raise ValueError("malformed combat zone fixture: expected an object")
    try:
        detached = copy.deepcopy(dict(fixture))
        normalized = normalize_fixture_layout(detached)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed combat zone fixture: %s" % exc) from exc
    if normalized.get("fixture_id") != COMBAT_FIXTURE_ID:
        raise ValueError("malformed combat zone fixture: unexpected fixture_id")

    zones: dict[str, ZoneDefinition] = {}
    for row in _required_list(normalized, "zones"):
        if not isinstance(row, Mapping):
            raise ValueError("malformed combat zone fixture: zone must be an object")
        zone_id = _required_text(row, "zone_id")
        level = _required_text(row, "elevation_level")
        relative_level = row.get("relative_levels_above_ground")
        if not isinstance(relative_level, int) or isinstance(relative_level, bool):
            raise ValueError("malformed combat zone fixture: invalid relative elevation")
        zones[zone_id] = ZoneDefinition(
            zone_id=zone_id,
            name=_required_text(row, "name"),
            feature_id=_required_text(row, "feature_id"),
            position=_required_text(row, "position"),
            elevation_level=level,
            relative_levels_above_ground=relative_level,
        )
    if not zones:
        raise ValueError("malformed combat zone fixture: no zones")

    path_tie_break = _string_tuple(
        _required_mapping(normalized, "enemy_movement_policy").get(
            "path_tie_break_order"
        ),
        "path_tie_break_order",
    )
    if len(path_tie_break) != len(set(path_tie_break)) or set(path_tie_break) != set(zones):
        raise ValueError("malformed combat zone fixture: path tie-break must list every zone once")

    adjacency: dict[str, set[str]] = {zone_id: set() for zone_id in zones}
    seen_edges: set[frozenset[str]] = set()
    for pair in _required_list(normalized, "adjacency"):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(zone_id, str) or zone_id not in zones for zone_id in pair)
            or pair[0] == pair[1]
        ):
            raise ValueError("malformed combat zone fixture: invalid adjacency edge")
        edge = frozenset(pair)
        if edge in seen_edges:
            raise ValueError("malformed combat zone fixture: duplicate adjacency edge")
        seen_edges.add(edge)
        adjacency[pair[0]].add(pair[1])
        adjacency[pair[1]].add(pair[0])
    ordered_adjacency = {
        zone_id: tuple(sorted(neighbors, key=lambda item: path_tie_break.index(item)))
        for zone_id, neighbors in adjacency.items()
    }
    if any(not _connected(zones, ordered_adjacency, zone_id) for zone_id in zones):
        raise ValueError("malformed combat zone fixture: adjacency graph is disconnected")

    cover_relations = _parse_cover_relations(normalized, zones)
    band_payload = _required_mapping(normalized, "bands")
    if set(band_payload) != set(_BAND_NAMES) | {"distance_policy"}:
        raise ValueError("malformed combat zone fixture: unexpected band definitions")
    band_definitions = {
        name: _required_text(band_payload, name) for name in _BAND_NAMES
    }
    distance_policy = _required_text(band_payload, "distance_policy").lower()
    if band_definitions != _BAND_DEFINITIONS or distance_policy != _DISTANCE_POLICY:
        raise ValueError("malformed combat zone fixture: unsupported band or distance policy")

    placement_rules = _required_mapping(normalized, "initial_placement_rules")
    party_rules = placement_rules.get(selected_party_key)
    if not isinstance(party_rules, Mapping):
        raise ValueError("malformed combat zone fixture: missing %s placements" % selected_party_key)
    pc_placements = _string_zone_mapping(party_rules.get("pcs"), "party PCs", zones)
    enemy_placements = _string_zone_mapping(party_rules.get("enemies"), "party enemies", zones)
    if len(pc_placements) != party_size:
        raise ValueError("malformed combat zone fixture: P%d requires %d PC placements" % (party_size, party_size))

    actor_kinds: dict[str, str] = {}
    actor_names: dict[str, str] = {}
    role_rows = _required_list(normalized, "occupant_roles")
    for role in role_rows:
        if not isinstance(role, Mapping):
            raise ValueError("malformed combat zone fixture: occupant role must be an object")
        actor_id = _required_text(role, "actor_id")
        if actor_id in actor_kinds:
            raise ValueError("malformed combat zone fixture: duplicate occupant role %s" % actor_id)
        kind = _required_text(role, "kind")
        if kind not in ("enemy_group", "enemy"):
            raise ValueError("malformed combat zone fixture: unsupported occupant kind %s" % kind)
        actor_kinds[actor_id] = kind
        actor_names[actor_id] = _required_text(role, "name")
        if role.get("initial_zone_id") not in zones:
            raise ValueError("malformed combat zone fixture: occupant has unknown initial zone")
        if enemy_placements.get(actor_id) != role.get("initial_zone_id"):
            raise ValueError("malformed combat zone fixture: occupant placement disagrees with role")
    if set(enemy_placements) != set(actor_kinds):
        raise ValueError("malformed combat zone fixture: enemy placements do not match occupant roles")
    positions: dict[str, str] = dict(pc_placements)
    if set(positions) & set(enemy_placements):
        raise ValueError("malformed combat zone fixture: PC/enemy actor ID collision")
    positions.update(enemy_placements)
    initial_positions = copy.deepcopy(positions)

    groups_payload = party_rules.get("engagement_groups")
    if not isinstance(groups_payload, list):
        raise ValueError("malformed combat zone fixture: engagement_groups must be a list")
    engagement_groups: dict[str, list[str]] = {}
    seen_group_actors: set[str] = set()
    for group in groups_payload:
        if not isinstance(group, Mapping):
            raise ValueError("malformed combat zone fixture: engagement group must be an object")
        group_id = _required_text(group, "group_id")
        actors = group.get("actors")
        if not isinstance(actors, list) or not actors or any(not isinstance(item, str) for item in actors):
            raise ValueError("malformed combat zone fixture: invalid engagement group actors")
        if group_id in engagement_groups or len(actors) != len(set(actors)):
            raise ValueError("malformed combat zone fixture: duplicate engagement group data")
        if any(actor_id not in positions or actor_id in seen_group_actors for actor_id in actors):
            raise ValueError("malformed combat zone fixture: invalid engagement group member")
        engagement_groups[group_id] = copy.deepcopy(actors)
        seen_group_actors.update(actors)
    expected_group_members = set(pc_placements) | {
        actor_id for actor_id, kind in actor_kinds.items() if kind == "enemy_group"
    }
    if seen_group_actors != expected_group_members:
        raise ValueError("malformed combat zone fixture: engagement group membership is incomplete")

    movement_allowance = _required_mapping(normalized, "movement_allowance_zone_steps")
    movement_allowance_zone_steps = {
        "pc_standard_move": _required_int(movement_allowance, "pc_standard_move"),
        "pc_extended_move": _required_int(movement_allowance, "pc_extended_move"),
        "enemy_melee_group_per_enemy_phase": _required_int(
            movement_allowance, "enemy_melee_group_per_enemy_phase"
        ),
        "balcony_archer_per_enemy_phase": _required_int(
            movement_allowance, "balcony_archer_per_enemy_phase"
        ),
    }
    if movement_allowance_zone_steps != {
        "pc_standard_move": 1,
        "pc_extended_move": 2,
        "enemy_melee_group_per_enemy_phase": 1,
        "balcony_archer_per_enemy_phase": 0,
    } or movement_allowance.get("adjacency_is_required") is not True:
        raise ValueError("malformed combat zone fixture: unsupported movement allowances")

    policy = _required_mapping(normalized, "enemy_movement_policy")
    if (
        _required_text(policy, "melee_groups") != _MELEE_POLICY
        or _required_text(policy, "balcony_archer") != _ARCHER_POLICY
    ):
        raise ValueError("malformed combat zone fixture: unsupported enemy movement policy")
    target_tie_break = _string_tuple(policy.get("target_tie_break_order"), "target_tie_break_order")
    if len(target_tie_break) != len(set(target_tie_break)) or not set(pc_placements).issubset(target_tie_break):
        raise ValueError("malformed combat zone fixture: target tie-break omits a PC")
    archer_matches = [
        role
        for role in role_rows
        if isinstance(role, Mapping)
        and role.get("name") == "Balcony archer"
        and role.get("kind") == "enemy"
    ]
    if len(archer_matches) != 1:
        raise ValueError("malformed combat zone fixture: expected one balcony archer")
    balcony_archer_actor_id = archer_matches[0]["actor_id"]
    if balcony_archer_actor_id not in enemy_placements:
        raise ValueError("malformed combat zone fixture: balcony archer is not placed")
    archer_zone = zones[enemy_placements[balcony_archer_actor_id]]
    if archer_zone.elevation_level != "upper":
        raise ValueError("malformed combat zone fixture: balcony archer is not at upper elevation")
    authored_distances = normalized.get("authored_distances")
    if not isinstance(authored_distances, list) or authored_distances:
        raise ValueError("malformed combat zone fixture: graph bands cannot use authored distances")

    return ZoneLedger(
        fixture_id=COMBAT_FIXTURE_ID,
        party_size=party_size,
        zones=zones,
        adjacency=ordered_adjacency,
        cover_relations=cover_relations,
        band_definitions=band_definitions,
        distance_policy=distance_policy,
        positions=positions,
        initial_positions=initial_positions,
        engagement_groups=engagement_groups,
        actor_kinds=actor_kinds,
        actor_names=actor_names,
        pc_actor_ids=tuple(pc_placements),
        enemy_group_actor_ids=tuple(
            role["actor_id"]
            for role in role_rows
            if isinstance(role, Mapping) and role.get("kind") == "enemy_group"
        ),
        balcony_archer_actor_id=balcony_archer_actor_id,
        movement_allowance_zone_steps=movement_allowance_zone_steps,
        target_tie_break_order=target_tie_break,
        path_tie_break_order=path_tie_break,
        enemy_movement_policy=copy.deepcopy(dict(policy)),
        authored_distances=tuple(copy.deepcopy(authored_distances)),
    )


def _validate_and_apply_hint(
    ledger: ZoneLedger, actor_id: str, hint: Mapping[str, Any], movement_mode: str
) -> MovementHintValidation:
    from_zone = hint.get("from")
    to_zone = hint.get("to")
    if actor_id not in ledger.pc_actor_ids:
        return _invalid_hint(actor_id, hint, movement_mode, "unknown_pc_actor")
    if from_zone not in ledger.zones or to_zone not in ledger.zones:
        return _invalid_hint(actor_id, hint, movement_mode, "unknown_zone")
    if ledger.positions[actor_id] != from_zone:
        return _invalid_hint(actor_id, hint, movement_mode, "from_zone_does_not_match_shadow_position")
    path = _shortest_path(ledger, from_zone, to_zone)
    if path is None:
        return _invalid_hint(actor_id, hint, movement_mode, "no_adjacent_path")
    steps = len(path) - 1
    if steps == 0:
        return _invalid_hint(actor_id, hint, movement_mode, "movement_does_not_change_zone")
    allowance_key = "pc_standard_move" if movement_mode == "standard" else "pc_extended_move"
    max_steps = ledger.movement_allowance_zone_steps[allowance_key]
    if steps > max_steps:
        return MovementHintValidation(
            actor_id=actor_id,
            status="invalid",
            reason="movement_exceeds_allowance",
            movement_mode=movement_mode,
            from_zone=from_zone,
            to_zone=to_zone,
            steps=steps,
            path=path,
            applied_to_shadow=False,
        )
    ledger.positions[actor_id] = to_zone
    return MovementHintValidation(
        actor_id=actor_id,
        status="valid",
        reason=None,
        movement_mode=movement_mode,
        from_zone=from_zone,
        to_zone=to_zone,
        steps=steps,
        path=path,
        applied_to_shadow=True,
    )


def _invalid_hint(
    actor_id: str,
    hint: Mapping[str, Any],
    movement_mode: str,
    reason: str,
) -> MovementHintValidation:
    from_zone = hint.get("from")
    to_zone = hint.get("to")
    return MovementHintValidation(
        actor_id=actor_id,
        status="invalid",
        reason=reason,
        movement_mode=movement_mode,
        from_zone=from_zone if isinstance(from_zone, str) else None,
        to_zone=to_zone if isinstance(to_zone, str) else None,
        steps=None,
        path=(),
        applied_to_shadow=False,
    )


def _parse_cover_relations(
    fixture: Mapping[str, Any], zones: Mapping[str, ZoneDefinition]
) -> tuple[CoverRelation, ...]:
    rows = _required_list(fixture, "pairwise_cover")
    relations: list[CoverRelation] = []
    seen_pairs: set[frozenset[str]] = set()
    allowed_cover = {"none", "half", "three_quarters", "full"}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("malformed combat zone fixture: cover relation must be an object")
        zone_a = _required_text(row, "zone_a")
        zone_b = _required_text(row, "zone_b")
        if zone_a not in zones or zone_b not in zones or zone_a == zone_b:
            raise ValueError("malformed combat zone fixture: invalid cover zone pair")
        pair = frozenset((zone_a, zone_b))
        if pair in seen_pairs:
            raise ValueError("malformed combat zone fixture: duplicate pairwise cover relation")
        seen_pairs.add(pair)
        cover_a = _required_text(row, "cover_for_target_a_from_b")
        cover_b = _required_text(row, "cover_for_target_b_from_a")
        sight = _required_text(row, "line_of_sight")
        if cover_a not in allowed_cover or cover_b not in allowed_cover:
            raise ValueError("malformed combat zone fixture: unsupported cover value")
        if sight not in ("clear", "blocked"):
            raise ValueError("malformed combat zone fixture: unsupported line-of-sight value")
        relations.append(CoverRelation(zone_a, zone_b, cover_a, cover_b, sight))
    expected_pair_count = len(zones) * (len(zones) - 1) // 2
    if len(seen_pairs) != expected_pair_count:
        raise ValueError("malformed combat zone fixture: pairwise cover table is incomplete")
    return tuple(relations)


def _is_exact_movement_match(
    ledger: ZoneLedger,
    intended: Mapping[str, Any],
    observation: MovementHintObservation,
) -> bool:
    if observation.status != "valid" or not isinstance(observation.hint, Mapping):
        return False
    if any(observation.hint.get(field_name) != intended.get(field_name) for field_name in _HINT_FIELDS):
        return False
    from_zone = intended.get("from")
    to_zone = intended.get("to")
    if from_zone not in ledger.zones or to_zone not in ledger.zones:
        return False
    path = _shortest_path(ledger, from_zone, to_zone)
    if path is None:
        return False
    expected_steps = intended.get("zone_steps")
    return expected_steps is None or len(path) - 1 == expected_steps


def _normalize_intended_move(intended_move: Any) -> dict[str, Any]:
    if not isinstance(intended_move, Mapping):
        raise ValueError("intended movement hint must be an object")
    normalized: dict[str, Any] = {}
    for field_name in _HINT_FIELDS:
        if field_name not in intended_move:
            raise ValueError("intended movement hint is missing %s" % field_name)
    for field_name in ("from", "to"):
        value = intended_move.get(field_name)
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("intended movement hint has invalid %s" % field_name)
        normalized[field_name] = value
    disengage = intended_move.get("disengage")
    if not isinstance(disengage, bool):
        raise ValueError("intended movement hint has invalid disengage")
    normalized["disengage"] = disengage
    cover_sought = intended_move.get("cover_sought")
    if cover_sought is not None and (
        not isinstance(cover_sought, str)
        or not cover_sought
        or cover_sought != cover_sought.strip()
    ):
        raise ValueError("intended movement hint has invalid cover_sought")
    normalized["cover_sought"] = cover_sought
    if "zone_steps" in intended_move:
        zone_steps = intended_move.get("zone_steps")
        if not isinstance(zone_steps, int) or isinstance(zone_steps, bool) or zone_steps < 1:
            raise ValueError("intended movement hint has invalid zone_steps")
        normalized["zone_steps"] = zone_steps
    return normalized


def _nearest_pc_path(ledger: ZoneLedger, from_zone: str) -> tuple[str, tuple[str, ...]]:
    candidates: list[tuple[int, int, str, tuple[str, ...]]] = []
    target_order = {actor_id: index for index, actor_id in enumerate(ledger.target_tie_break_order)}
    for pc_id in ledger.pc_actor_ids:
        path = _shortest_path(ledger, from_zone, ledger.positions[pc_id])
        if path is None:
            continue
        candidates.append(
            (
                len(path) - 1,
                target_order.get(pc_id, len(target_order)),
                pc_id,
                path,
            )
        )
    if not candidates:
        raise ValueError("fixture enemy policy has no reachable PC")
    _distance, _tie_order, actor_id, path = min(candidates)
    return actor_id, path


def _ordered_actor(actor_ids: Sequence[str], ledger: ZoneLedger) -> str:
    rank = {actor_id: index for index, actor_id in enumerate(ledger.target_tie_break_order)}
    return min(actor_ids, key=lambda actor_id: (rank.get(actor_id, len(rank)), actor_id))


def _join_engagement_group(ledger: ZoneLedger, actor_id: str, pc_id: str) -> None:
    target_group = _engagement_group_for(ledger, pc_id)
    if target_group is None:
        raise ValueError("fixture PC has no engagement group")
    current_group = _engagement_group_for(ledger, actor_id)
    if current_group == target_group:
        return
    if current_group is not None:
        ledger.engagement_groups[current_group].remove(actor_id)
        if not ledger.engagement_groups[current_group]:
            del ledger.engagement_groups[current_group]
    ledger.engagement_groups[target_group].append(actor_id)


def _engagement_group_for(ledger: ZoneLedger, actor_id: str) -> Optional[str]:
    for group_id, actors in ledger.engagement_groups.items():
        if actor_id in actors:
            return group_id
    return None


def _share_engagement_group(ledger: ZoneLedger, actor_a: str, actor_b: str) -> bool:
    group_a = _engagement_group_for(ledger, actor_a)
    return group_a is not None and group_a == _engagement_group_for(ledger, actor_b)


def _actor_zone(ledger: ZoneLedger, actor_id: str) -> str:
    try:
        zone_id = ledger.positions[actor_id]
    except KeyError as exc:
        raise ValueError("unknown actor: %s" % actor_id) from exc
    _require_zone(ledger, zone_id)
    return zone_id


def _require_zone(ledger: ZoneLedger, zone_id: str) -> None:
    if zone_id not in ledger.zones:
        raise ValueError("unknown zone: %s" % zone_id)


def _cover_relation(
    ledger: ZoneLedger, source_zone_id: str, target_zone_id: str
) -> CoverRelation:
    for relation in ledger.cover_relations:
        if {source_zone_id, target_zone_id} == {relation.zone_a, relation.zone_b}:
            return relation
    raise ValueError("fixture has no pairwise cover relation for requested zones")


def _shortest_path(
    ledger: ZoneLedger, start: str, goal: str
) -> Optional[tuple[str, ...]]:
    if start not in ledger.zones or goal not in ledger.zones:
        return None
    if start == goal:
        return (start,)
    order = {zone_id: index for index, zone_id in enumerate(ledger.path_tie_break_order)}
    queue = deque([start])
    parent: dict[str, Optional[str]] = {start: None}
    while queue:
        current = queue.popleft()
        neighbors = sorted(
            ledger.adjacency[current],
            key=lambda zone_id: (order.get(zone_id, len(order)), zone_id),
        )
        for neighbor in neighbors:
            if neighbor in parent:
                continue
            parent[neighbor] = current
            if neighbor == goal:
                path = [goal]
                cursor: Optional[str] = current
                while cursor is not None:
                    path.append(cursor)
                    cursor = parent[cursor]
                path.reverse()
                return tuple(path)
            queue.append(neighbor)
    return None


def _connected(
    zones: Mapping[str, Any], adjacency: Mapping[str, Sequence[str]], start: str
) -> bool:
    visited = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited == set(zones)


def _enemy_move_payload(observation: EnemyMoveObservation) -> dict[str, Any]:
    payload = asdict(observation)
    payload["kind"] = "enemy_phase"
    payload["path"] = list(observation.path)
    return payload


def _party_key(party_size: int) -> str:
    if not isinstance(party_size, int) or isinstance(party_size, bool) or party_size not in (1, 4):
        raise ValueError("party_size must be exactly 1 or 4")
    return "party_%d" % party_size


def _resolve_prereg_root(prereg_root: Optional[Union[str, Path]]) -> Path:
    if prereg_root is None:
        return DEFAULT_PREREG_ROOT
    root = Path(prereg_root)
    return root if root.is_absolute() else PROJECT_ROOT / root


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError("malformed combat zone fixture: %s must be an object" % key)
    return value


def _required_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError("malformed combat zone fixture: %s must be a list" % key)
    return value


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("malformed combat zone fixture: %s must be non-empty text" % key)
    return value


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("malformed combat zone fixture: %s must be an integer" % key)
    return value


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("malformed combat zone fixture: %s must be a string list" % label)
    return tuple(value)


def _string_zone_mapping(
    value: Any, label: str, zones: Mapping[str, ZoneDefinition]
) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("malformed combat zone fixture: %s must be a non-empty object" % label)
    result: dict[str, str] = {}
    for actor_id, zone_id in value.items():
        if not isinstance(actor_id, str) or not actor_id or not isinstance(zone_id, str):
            raise ValueError("malformed combat zone fixture: invalid %s row" % label)
        if zone_id not in zones:
            raise ValueError("malformed combat zone fixture: %s references unknown zone" % label)
        result[actor_id] = zone_id
    return result


def _ensure_json_data(value: Any, label: str) -> None:
    try:
        json.dumps(value, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must contain JSON-compatible data" % label) from exc
