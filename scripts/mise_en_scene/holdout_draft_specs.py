"""Reviewed, provider-free source-grounded specs for the six holdout drafts."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from . import evaluation
from .holdout_fixtures import make_projection_pair


_REPO_ROOT = Path(__file__).resolve().parents[2]
_NUMILLIAN_AREA = "modules/The_Hidden_City_of_Numillian/areas/A000_BU.json"
_NUMILLIAN_PLOT = "modules/The_Hidden_City_of_Numillian/module_plot_BU.json"


def _entity(module_id: str, local_id: str) -> str:
    return module_id + ":entity:" + local_id


def _fact_id(module_id: str, local_id: str) -> str:
    return module_id + ":fact:" + local_id


def _known(
    module_id: str,
    scene_id: str,
    local_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    value: str,
    source_paths: tuple[str, ...],
    *,
    authorship: str = "source",
    audience: str = "public",
) -> dict[str, Any]:
    provenance_class = "source_extracted" if authorship == "source" else "builder_authored"
    return {
        "id": _fact_id(module_id, local_id),
        "scene_id": scene_id,
        "subject_id": subject_id,
        "predicate": predicate,
        "object_id": object_id,
        "status": "known",
        "knowledge_status": "known",
        "audience": audience,
        "value": value,
        "authorship": authorship,
        "provenance": {
            "class": provenance_class,
            "source_refs": ["source:" + path for path in source_paths],
        },
    }


def _unknown(
    module_id: str,
    scene_id: str,
    local_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    *,
    audience: str = "public",
) -> dict[str, Any]:
    return {
        "id": _fact_id(module_id, local_id),
        "scene_id": scene_id,
        "subject_id": subject_id,
        "predicate": predicate,
        "object_id": object_id,
        "status": "unknown",
        "knowledge_status": "known",
        "audience": audience,
        "value": None,
        "provenance": {"class": "unknown", "source_refs": []},
    }


def _node(scene_id: str, label: str, knowledge_status: str = "known") -> dict[str, str]:
    return {"id": scene_id, "label": label, "knowledge_status": knowledge_status}


def _link(fact_id: str, from_scene_id: str, to_scene_id: str, relation: str) -> dict[str, str]:
    return {
        "id": fact_id,
        "from_scene_id": from_scene_id,
        "to_scene_id": to_scene_id,
        "relation": relation,
    }


def _layout(
    scene_id: str, anchor_id: str, label: str, row: int, column: int
) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "anchor_id": anchor_id,
        "label": label,
        "row": row,
        "column": column,
    }


def _spec(
    scene_id: str,
    facts: list[dict[str, Any]],
    scene_nodes: list[dict[str, str]],
    links: list[dict[str, str]],
    schematic_layout: list[dict[str, Any]],
    public_scene_ids: list[str],
    public_link_ids: list[str],
    public_anchor_ids: list[str],
    arrival_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    topology = {
        "scene_nodes": scene_nodes,
        "links": links,
        "schematic_layout": schematic_layout,
    }
    return {
        "schema_version": 1,
        "fixture_id": scene_id,
        "facts": facts,
        "topology": topology,
        "topology_scope": {
            "public": {
                "scene_nodes": public_scene_ids,
                "links": public_link_ids,
                "schematic_layout": public_anchor_ids,
            },
            "gm_narrator": {
                "scene_nodes": [item["id"] for item in scene_nodes],
                "links": [item["id"] for item in links],
                "schematic_layout": [item["anchor_id"] for item in schematic_layout],
            },
        },
        "arrival_segments": arrival_segments,
    }


def _scene_record(
    scene_id: str,
    source_identity: str,
    source_files: tuple[tuple[str, str], ...],
    source_text_sha256: str,
    source_spans: tuple[tuple[str, str, str, str], ...],
    spec: dict[str, Any],
    *,
    source_field_refs: tuple[tuple[str | None, str, str], ...] = (),
) -> dict[str, Any]:
    paths = [path for path, _ in source_files]
    span_names = [
        path + "#" + collection + "[" + id_key + "=" + record_id + "]"
        for path, collection, id_key, record_id in source_spans
    ]
    return {
        "scene_id": scene_id,
        "source_identity": source_identity,
        "source_files": [
            {"path": path, "sha256": digest} for path, digest in source_files
        ],
        "source_text_sha256": source_text_sha256,
        "source_spans": source_spans,
        "source_ref": ";".join(span_names),
        "source_field_refs": [
            {"fact_id": fact_id, "path": path, "field": field}
            for fact_id, path, field in source_field_refs
        ],
        "lineage_status": "independent",
        "adaptation_lineage": [],
        "selected_source_paths": paths,
        "spec": spec,
    }


_MURDER = "modules/Murder_at_the_Drowning_Lass/areas/WM001_BU.json"
_ANCIENTS = "modules/The_Ancients_Lab/areas/BA001_BU.json"
_DEEPVAULT = "modules/Into_the_Deepvault/areas/RF004_BU.json"
_XHALRUUNS = "modules/Xhalruuns_Masquerade/areas/TPG001_BU.json"
_GARDEN = "modules/The_Garden_of_Demons/areas/GV001_BU.json"


def _build_scene_records() -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []

    # Shrouded Lantern Encampment: source facts stay separate from staged cells.
    module_id = "murder_at_the_drowning_lass"
    scene = module_id + ":scene:shrouded-lantern-encampment"
    trail = _entity(module_id, "animal-trail")
    camp_edge = _entity(module_id, "camp-edge")
    lanterns = _entity(module_id, "camp-lanterns")
    bedrolls = _entity(module_id, "bedrolls")
    cookware = _entity(module_id, "cookware")
    crates = _entity(module_id, "crates")
    scouts = _entity(module_id, "red-maw-scouts")
    secret = _entity(module_id, "guarded-compartment")
    h02 = module_id + ":scene:crooked-cairn-hill"
    h03 = module_id + ":scene:witchlight-standing-stone"
    camp_facts = [
        _known(module_id, scene, "camp_identity", scene, "selected_location", scene,
               "The selected source location is Shrouded Lantern Encampment.", (_MURDER,)),
        _known(module_id, scene, "camp_setting", scene, "camp_setting", camp_edge,
               "The makeshift campsite is nestled amidst the mist-draped tussocks of the Widdershins Moor.", (_MURDER,)),
        _known(module_id, scene, "animal_trail_access", trail, "source_access", scene,
               "The campsite is easily accessed from the main animal trail.", (_MURDER,)),
        _known(module_id, scene, "camp_lanterns", scene, "contains_anchor", lanterns,
               "The campsite is marked by the eerie glow of oil lanterns.", (_MURDER,)),
        _known(module_id, scene, "camp_lantern_appearance", lanterns, "visible_appearance", scene,
               "The oil lanterns have glass panes painted with smudges of ash to diffuse the light.", (_MURDER,)),
        _known(module_id, scene, "camp_contents", scene, "contains_camp_contents", bedrolls,
               "Tattered bedrolls, battered cookware, and a circle of upturned crates mark the campsite.", (_MURDER,)),
        _known(module_id, scene, "scouts_present", scene, "has_mobile_occupant", scouts,
               "Red Maw scouts are present at the campsite.", (_MURDER,)),
        _known(module_id, scene, "lantern_visibility_dusk", lanterns, "visible_at_dusk", scene,
               "The source says the lanterns can be seen from several hundred feet away at dusk.", (_MURDER,)),
        _known(module_id, scene, "connection_h02", scene, "listed_connection", h02,
               "The source lists H02 as connected to H01 without assigning a direction here.", (_MURDER,)),
        _known(module_id, scene, "connection_h03", scene, "listed_connection", h03,
               "The source lists H03 as connected to H01 without assigning a direction here.", (_MURDER,)),
        _known(module_id, scene, "camp_edge_builder_feature", camp_edge, "builder_authored_feature", scene,
               "Builder-authored arrival threshold feature at the campsite edge.", (_MURDER,), authorship="builder"),
        _known(module_id, scene, "stage_approach", trail, "approach_to_threshold", camp_edge,
               "Builder-authored arrival relation from the main animal trail to the campsite edge; no route metric is stated.", (_MURDER,), authorship="builder"),
        _known(module_id, scene, "stage_threshold", camp_edge, "threshold_to_camp_contents", bedrolls,
               "Builder-authored threshold relation places the bedrolls and crates beyond the campsite edge.", (_MURDER,), authorship="builder"),
        _known(module_id, scene, "stage_focal", camp_edge, "focal_anchor_assignment", lanterns,
               "Builder-authored focal relation highlights the oil lanterns at the campsite.", (_MURDER,), authorship="builder"),
        _known(module_id, scene, "lantern_invitation", lanterns, "visible_affordance", scene,
               "The oil lanterns offer a visible point of interest on arrival.", (_MURDER,), authorship="builder"),
        _known(module_id, scene, "scout_start_position", scouts, "initial_schematic_position", camp_edge,
               "Builder-authored initial placement at the camp edge; source gives no starting position.", (_MURDER,), authorship="builder"),
        _known(module_id, scene, "schematic_cells_authored", camp_edge, "schematic_layout_authorship", scene,
               "Builder-authored schematic cells are a review layout only, not compass, distance, access, or mechanics.", (_MURDER,), authorship="builder"),
        _known(module_id, scene, "guarded_compartment", scene, "guarded_discovery", secret,
               "GM-only: an Investigation check can reveal a hidden compartment beneath a loose flagstone containing the Red Maw token.", (_MURDER,), audience="gm_only"),
        _unknown(module_id, scene, "guarded_effect_unknown", secret, "guarded_effect_outcome", scene, audience="gm_only"),
        _unknown(module_id, scene, "compass_unknown", scene, "compass_bearing", camp_edge),
        _unknown(module_id, scene, "route_distance_unknown", trail, "approach_route_length", camp_edge),
        _unknown(module_id, scene, "light_gradient_unknown", trail, "light_gradient", lanterns),
        _unknown(module_id, scene, "sound_gradient_unknown", trail, "sound_gradient", camp_edge),
        _unknown(module_id, scene, "weather_gradient_unknown", trail, "weather_gradient", camp_edge),
    ]
    camp_layout = [
        _layout(scene, trail, "approach", 0, 0),
        _layout(scene, camp_edge, "threshold", 0, 1),
        _layout(scene, lanterns, "lantern", 0, 2),
        _layout(scene, bedrolls, "bedrolls", 1, 1),
        _layout(scene, cookware, "cookware", 1, 2),
        _layout(scene, crates, "crates", 2, 1),
        _layout(scene, scouts, "scouts", 1, 0),
        _layout(scene, secret, "guarded_compartment", 3, 1),
    ]
    camp_nodes = [
        _node(scene, "Shrouded Lantern Encampment"),
        _node(h02, "Crooked Cairn Hill"),
        _node(h03, "Witchlight Standing Stone"),
    ]
    camp_links = [
        _link(_fact_id(module_id, "connection_h02"), scene, h02, "listed_connection"),
        _link(_fact_id(module_id, "connection_h03"), scene, h03, "listed_connection"),
    ]
    camp_arrival = [
        {"id": "arrival-approach", "role": "approach", "text": "Among the mist-draped tussocks of Widdershins Moor, the main animal trail offers access to the makeshift campsite.", "fact_ids": [_fact_id(module_id, "camp_setting"), _fact_id(module_id, "animal_trail_access"), _fact_id(module_id, "stage_approach")]},
        {"id": "arrival-threshold", "role": "threshold", "text": "Tattered bedrolls and battered cookware lie beside a circle of upturned crates at the camp edge.", "fact_ids": [_fact_id(module_id, "camp_contents"), _fact_id(module_id, "camp_edge_builder_feature"), _fact_id(module_id, "stage_threshold")]},
        {"id": "arrival-focal", "role": "focal", "text": "Oil lanterns glow through ash-smudged glass panes that diffuse their light; their eerie glow offers a visible point of interest.", "fact_ids": [_fact_id(module_id, "camp_lanterns"), _fact_id(module_id, "camp_lantern_appearance"), _fact_id(module_id, "stage_focal"), _fact_id(module_id, "lantern_invitation")]},
    ]
    records.append(_scene_record(
        scene, "published-module:Murder_at_the_Drowning_Lass:WM001:H01",
        ((_MURDER, "4f0752953d710d1c0d345c55d529656273cb1963be237dfe0512b2151817e412"),),
        "2c3d4bc25fac9a645533d942021b95d315ef255dec5913ec87ba0bc3c597d261",
        ((_MURDER, "locations", "locationId", "H01"),),
        _spec(scene, camp_facts, camp_nodes, camp_links, camp_layout,
              [scene, h02, h03], [item["id"] for item in camp_links],
              [item["anchor_id"] for item in camp_layout if item["anchor_id"] != secret], camp_arrival),
    ))

    # Abyssal Fracture: explicitly authored multi-cell extents and usable space.
    module_id = "the_ancients_lab"
    scene = module_id + ":scene:abyssal-fracture"
    approach_a = _entity(module_id, "moor-path-cell-a")
    approach_b = _entity(module_id, "moor-path-cell-b")
    rim = _entity(module_id, "ravine-rim")
    ravine = _entity(module_id, "ravine-extent")
    ravine_a = _entity(module_id, "ravine-cell-a")
    ravine_b = _entity(module_id, "ravine-cell-b")
    boundary_a = _entity(module_id, "rim-boundary-cell-a")
    boundary_b = _entity(module_id, "rim-boundary-cell-b")
    usable_a = _entity(module_id, "rim-usable-cell-a")
    usable_b = _entity(module_id, "rim-usable-cell-b")
    stream = _entity(module_id, "bottom-stream")
    runes = _entity(module_id, "exposed-runes")
    brambles = _entity(module_id, "concealed-brambles")
    i01 = module_id + ":scene:shattered-forge-approach"
    lab_facts = [
        _known(module_id, scene, "ravine_splits_moor", scene, "contains_ravine", ravine,
               "A jagged rift splits the moor.", (_ANCIENTS,)),
        _known(module_id, scene, "ravine_basalt_sides", ravine, "terrain_appearance", scene,
               "The ravine has basalt sides that plunge toward its bottom.", (_ANCIENTS,)),
        _known(module_id, scene, "stream_at_bottom", scene, "stream_at_ravine_bottom", stream,
               "A narrow, mist-choked stream lies at the bottom of the ravine.", (_ANCIENTS,)),
        _known(module_id, scene, "runes_on_rock", scene, "runes_on_exposed_rock", runes,
               "Strange runes are carved on exposed rock, half-eroded by centuries of rain.", (_ANCIENTS,)),
        _known(module_id, scene, "mist_at_bottom", scene, "mist_at_ravine_bottom", ravine,
               "The ravine bottom is perpetually shrouded in thin, swirling mist.", (_ANCIENTS,)),
        _known(module_id, scene, "connection_i01", scene, "listed_connection", i01,
               "The source lists I01 as connected; it does not establish a compass bearing here.", (_ANCIENTS,)),
        _known(module_id, scene, "moor_path_builder_feature", approach_a, "builder_authored_feature", approach_b,
               "Builder-authored moor-side approach path represented by two schematic cells.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "ravine_rim_builder_feature", rim, "builder_authored_feature", ravine,
               "Builder-authored ravine rim feature used as the arrival threshold.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "stage_approach", approach_b, "approach_to_threshold", rim,
               "Builder-authored relation assigns the moor-side path as an approach to the ravine rim; no route length or access rule is implied.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "stage_threshold", rim, "threshold_to_ravine", ravine,
               "Builder-authored threshold relation connects the ravine rim to the ravine below.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "stage_focal", rim, "focal_anchor_assignment", runes,
               "Builder-authored focal relation highlights the exposed runes.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "runes_invitation", runes, "visible_affordance", scene,
               "The exposed runes offer a visible detail for closer inspection.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "path_extent_authored", approach_a, "schematic_path_extent", approach_b,
               "Builder-authored path extent uses two schematic cells only.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "ravine_extent_authored", ravine_a, "schematic_terrain_extent", ravine_b,
               "Builder-authored ravine terrain extent uses two schematic cells only.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "boundary_extent_authored", boundary_a, "schematic_boundary_extent", boundary_b,
               "Builder-authored ravine boundary extent uses two schematic cells only.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "usable_space_authored", usable_a, "schematic_usable_space", usable_b,
               "Builder-authored rim space is a usable-space candidate, not a movement or legality claim.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "schematic_cells_authored", rim, "schematic_layout_authorship", scene,
               "Builder-authored schematic cells have no compass, metric, access, or rules meaning.", (_ANCIENTS,), authorship="builder"),
        _known(module_id, scene, "guarded_bramble_trap", scene, "guarded_hazard", brambles,
               "GM-only: the source describes concealed sharp brambles at the bottom and a 1d4 piercing trap effect.", (_ANCIENTS,), audience="gm_only"),
        _unknown(module_id, scene, "guarded_additional_effect_unknown", brambles, "additional_guarded_effect", scene, audience="gm_only"),
        _unknown(module_id, scene, "compass_unknown", scene, "compass_bearing", rim),
        _unknown(module_id, scene, "route_distance_unknown", approach_a, "approach_route_length", rim),
        _unknown(module_id, scene, "light_gradient_unknown", rim, "light_gradient", runes),
        _unknown(module_id, scene, "sound_gradient_unknown", rim, "sound_gradient", stream),
        _unknown(module_id, scene, "weather_gradient_unknown", rim, "weather_gradient", ravine),
        _unknown(module_id, scene, "movement_cost_unknown", approach_a, "movement_cost", rim),
    ]
    lab_layout = [
        _layout(scene, approach_a, "path", 0, 0), _layout(scene, approach_b, "path", 0, 1),
        _layout(scene, rim, "threshold", 0, 2), _layout(scene, ravine, "ravine_extent", 1, 0),
        _layout(scene, ravine_a, "ravine", 1, 1),
        _layout(scene, ravine_b, "ravine", 1, 2), _layout(scene, boundary_a, "boundary", 2, 1),
        _layout(scene, boundary_b, "boundary", 2, 2), _layout(scene, usable_a, "usable_space", 0, 2),
        _layout(scene, usable_b, "usable_space", 1, 2), _layout(scene, stream, "stream", 2, 3),
        _layout(scene, runes, "runes", 1, 3), _layout(scene, brambles, "brambles", 3, 2),
    ]
    lab_nodes = [_node(scene, "Abyssal Fracture"), _node(i01, "Shattered Forge Approach")]
    lab_links = [_link(_fact_id(module_id, "connection_i01"), scene, i01, "listed_connection")]
    lab_public_layout = [item["anchor_id"] for item in lab_layout if item["anchor_id"] != brambles]
    lab_arrival = [
        {"id": "arrival-approach", "role": "approach", "text": "A moor-side path reaches the rim of a jagged rift splitting the moor.", "fact_ids": [_fact_id(module_id, "moor_path_builder_feature"), _fact_id(module_id, "stage_approach"), _fact_id(module_id, "ravine_splits_moor")]},
        {"id": "arrival-threshold", "role": "threshold", "text": "From the rim, basalt sides descend to a narrow stream veiled in thin, swirling mist.", "fact_ids": [_fact_id(module_id, "ravine_rim_builder_feature"), _fact_id(module_id, "stage_threshold"), _fact_id(module_id, "ravine_basalt_sides"), _fact_id(module_id, "stream_at_bottom"), _fact_id(module_id, "mist_at_bottom")]},
        {"id": "arrival-focal", "role": "focal", "text": "Rain-worn runes mark the exposed rock, offering a visible detail to inspect.", "fact_ids": [_fact_id(module_id, "stage_focal"), _fact_id(module_id, "runes_on_rock"), _fact_id(module_id, "runes_invitation")]},
    ]
    records.append(_scene_record(
        scene, "published-module:The_Ancients_Lab:BA001:I02",
        ((_ANCIENTS, "f269385e6b9bd112d4fee82beda801fe2cf5c20f5eb9202df5a59687cdffe8b0"),),
        "97b698883f33c62d653402b6a5593a7d294e1f8cba22674673e3bd7cc2eacd8f",
        ((_ANCIENTS, "locations", "locationId", "I02"),),
        _spec(scene, lab_facts, lab_nodes, lab_links, lab_layout, [scene, i01],
              [item["id"] for item in lab_links], lab_public_layout, lab_arrival),
    ))

    # Shattered Anvil Crossing: source connections are not assigned to doors.
    module_id = "into_the_deepvault"
    scene = module_id + ":scene:shattered-anvil-crossing"
    approach = _entity(module_id, "corridor-approach")
    east_arch = _entity(module_id, "east-archway")
    west_door = _entity(module_id, "west-door")
    anvil = _entity(module_id, "shattered-anvil")
    golem = _entity(module_id, "molten-bone-golem")
    trap_plate = _entity(module_id, "guarded-rune-plate")
    secret_compartment = _entity(module_id, "guarded-compartment")
    i02 = module_id + ":scene:ember-scarred-watchpost"
    i03 = module_id + ":scene:forgotten-smiths-refuge"
    forge_facts = [
        _known(module_id, scene, "anvil_central", scene, "has_focal_feature", anvil,
               "The massive remains of an ancient anvil lie broken at the center, its surface etched with runes now split and steaming.", (_DEEPVAULT,)),
        _known(module_id, scene, "crossing_access", scene, "source_access", approach,
               "Normal access to the crossing is via adjoining corridors.", (_DEEPVAULT,)),
        _known(module_id, scene, "east_archway_present", scene, "contains_feature", east_arch,
               "The East Archway is a scorched stone archway with a split, blackened keystone; its faded runes still faintly pulse.", (_DEEPVAULT,)),
        _known(module_id, scene, "west_door_present", scene, "contains_feature", west_door,
               "A locked West Door is listed as a separate source feature.", (_DEEPVAULT,)),
        _known(module_id, scene, "golem_present", scene, "has_mobile_occupant", golem,
               "A hostile Molten Bone Golem patrols the crossing.", (_DEEPVAULT,)),
        _known(module_id, scene, "connection_i02", scene, "listed_connection", i02,
               "The source lists a connection to I02 without assigning it to a named door.", (_DEEPVAULT,)),
        _known(module_id, scene, "connection_i03", scene, "listed_connection", i03,
               "The source lists a connection to I03 without assigning it to a named door.", (_DEEPVAULT,)),
        _known(module_id, scene, "crossing_floor_appearance", scene, "visible_appearance", scene,
               "Chunks of blackened anvil-stone are scattered across the crossing floor, and ash drifts thickly.", (_DEEPVAULT,)),
        _known(module_id, scene, "crossing_vault_appearance", scene, "visible_appearance", scene,
               "Jagged vaulting and melted iron beams criss-cross overhead, casting complex shadows in drifting ash.", (_DEEPVAULT,)),
        _known(module_id, scene, "crossing_hammer_echoes", scene, "sound_detail", scene,
               "Strange echoes of hammer-strikes ring from nowhere.", (_DEEPVAULT,)),
        _known(module_id, scene, "crossing_approach_builder_feature", approach, "builder_authored_feature", scene,
               "Builder-authored adjoining-corridor approach feature for the initial crossing view.", (_DEEPVAULT,), authorship="builder"),
        _known(module_id, scene, "stage_approach", approach, "approach_to_threshold", east_arch,
               "Builder-authored visual approach relation places the source-listed East Archway in the approach view; it is not mapped to either listed connection.", (_DEEPVAULT,), authorship="builder"),
        _known(module_id, scene, "stage_threshold", east_arch, "threshold_to_focal", anvil,
               "Builder-authored visual relation places the source-described central anvil in the East Archway arrival view; no access claim is added.", (_DEEPVAULT,), authorship="builder"),
        _known(module_id, scene, "stage_focal", scene, "focal_anchor_assignment", anvil,
               "Builder-authored focal relation highlights the shattered anvil.", (_DEEPVAULT,), authorship="builder"),
        _known(module_id, scene, "anvil_invitation", anvil, "visible_affordance", scene,
               "The anvil's split, steaming runes offer a visible detail to inspect.", (_DEEPVAULT,), authorship="builder"),
        _known(module_id, scene, "golem_start_position", golem, "initial_schematic_position", scene,
               "Builder-authored initial schematic placement; the source gives no exact patrol position.", (_DEEPVAULT,), authorship="builder"),
        _known(module_id, scene, "schematic_cells_authored", approach, "schematic_layout_authorship", scene,
               "Builder-authored schematic cells do not establish compass, connection, access, or mechanics.", (_DEEPVAULT,), authorship="builder"),
        _known(module_id, scene, "guarded_rune_trap", scene, "guarded_trap_effect", trap_plate,
               "GM-only: the source lists embers and 2d6 fire damage from a rune-inscribed plate.", (_DEEPVAULT,), audience="gm_only"),
        _known(module_id, scene, "guarded_compartment", scene, "guarded_discovery", secret_compartment,
               "GM-only: an Investigation check can locate a concealed compartment beneath the shattered anvil.", (_DEEPVAULT,), audience="gm_only"),
        _unknown(module_id, scene, "guarded_additional_effect_unknown", trap_plate, "additional_guarded_effect", scene, audience="gm_only"),
        _unknown(module_id, scene, "compass_unknown", scene, "compass_bearing", east_arch),
        _unknown(module_id, scene, "route_distance_unknown", approach, "approach_route_length", east_arch),
        _unknown(module_id, scene, "crossing_width_unknown", scene, "crossing_width", scene),
        _unknown(module_id, scene, "light_gradient_unknown", approach, "light_gradient", anvil),
        _unknown(module_id, scene, "sound_gradient_unknown", approach, "sound_gradient", anvil),
        _unknown(module_id, scene, "weather_gradient_unknown", approach, "weather_gradient", anvil),
    ]
    forge_layout = [
        _layout(scene, approach, "approach", 0, 0), _layout(scene, east_arch, "east_archway", 0, 1),
        _layout(scene, west_door, "west_door", 0, 2), _layout(scene, anvil, "anvil", 1, 1),
        _layout(scene, golem, "construct", 1, 2), _layout(scene, trap_plate, "guarded_plate", 2, 1),
        _layout(scene, secret_compartment, "guarded_compartment", 2, 2),
    ]
    forge_nodes = [_node(scene, "Shattered Anvil Crossing"), _node(i02, "Ember-Scarred Watchpost"), _node(i03, "Forgotten Smith's Refuge")]
    forge_links = [
        _link(_fact_id(module_id, "connection_i02"), scene, i02, "listed_connection"),
        _link(_fact_id(module_id, "connection_i03"), scene, i03, "listed_connection"),
    ]
    forge_public_layout = [item["anchor_id"] for item in forge_layout if item["anchor_id"] not in (trap_plate, secret_compartment)]
    forge_arrival = [
        {"id": "arrival-approach", "role": "approach", "text": "A corridor approach frames the scorched East Archway, its split, blackened keystone bearing faded runes that still faintly pulse.", "fact_ids": [_fact_id(module_id, "crossing_approach_builder_feature"), _fact_id(module_id, "crossing_access"), _fact_id(module_id, "stage_approach"), _fact_id(module_id, "east_archway_present")]},
        {"id": "arrival-threshold", "role": "threshold", "text": "Blackened anvil-stone lies scattered across the floor; the massive shattered anvil rests at the crossing's center, etched with split, steaming runes.", "fact_ids": [_fact_id(module_id, "stage_threshold"), _fact_id(module_id, "crossing_floor_appearance"), _fact_id(module_id, "anvil_central")]},
        {"id": "arrival-focal", "role": "focal", "text": "Jagged vaulting and melted iron beams cast complex shadows in the drifting ash as strange hammer-strike echoes ring from nowhere. The anvil's runes offer a visible detail to inspect.", "fact_ids": [_fact_id(module_id, "crossing_vault_appearance"), _fact_id(module_id, "crossing_hammer_echoes"), _fact_id(module_id, "crossing_floor_appearance"), _fact_id(module_id, "anvil_invitation")]},
    ]
    records.append(_scene_record(
        scene, "published-module:Into_the_Deepvault:RF004:I01",
        ((_DEEPVAULT, "73645a36281c96b3718aad2c2cba3384afb1185913f5c8a2bd45ed381355d1ec"),),
        "67a17e8bd101030c56c1659c035063862e265fc2b301e84717dd725e3c89759a",
        ((_DEEPVAULT, "locations", "locationId", "I01"),),
        _spec(scene, forge_facts, forge_nodes, forge_links, forge_layout, [scene, i02, i03],
              [item["id"] for item in forge_links], forge_public_layout, forge_arrival),
    ))

    # Sanctum of Fractured Truths: linked views share one authored place identity.
    module_id = "xhalruuns_masquerade"
    scene = module_id + ":scene:sanctum-of-fractured-truths"
    entry_view = module_id + ":scene:sanctum-entry-view"
    altar_view = module_id + ":scene:sanctum-altar-view"
    approach = _entity(module_id, "entry-approach")
    south_entrance = _entity(module_id, "south-entrance")
    altar = _entity(module_id, "crystal-altar")
    lanterns = _entity(module_id, "lanterns")
    mosaics = _entity(module_id, "mirrored-mosaics")
    keeper = _entity(module_id, "keeper-veyron")
    vestry = _entity(module_id, "guarded-vestry-door")
    ak02 = module_id + ":scene:miragebound-exchange"
    temple_facts = [
        _known(module_id, scene, "location_identity", scene, "selected_location", scene,
               "The selected module record names one Sanctum of Fractured Truths location.", (_XHALRUUNS,)),
        _known(module_id, scene, "source_entrance", scene, "contains_feature", south_entrance,
               "Tall oak double doors carved with paradoxical symbols form the South Entrance, flanked by flickering lanterns.", (_XHALRUUNS,)),
        _known(module_id, scene, "source_temple_appearance", scene, "visible_appearance", scene,
               "The temple is domed marble with shifting, mirrored mosaics.", (_XHALRUUNS,)),
        _known(module_id, scene, "source_lanterns", scene, "visible_appearance", scene,
               "Flickering lanterns project strange, overlapping shadows across the floor.", (_XHALRUUNS,)),
        _known(module_id, scene, "source_altar", scene, "contains_feature", altar,
               "At the temple's center, an altar of fractured crystal sits among ritual implements and an offering bowl, bathed in rainbow light.", (_XHALRUUNS,)),
        _known(module_id, scene, "source_mosaics", scene, "contains_feature", mosaics,
               "Mirrored mosaics subtly shift, sometimes showing different scenes to different viewers.", (_XHALRUUNS,)),
        _known(module_id, scene, "keeper_present", scene, "has_mobile_occupant", keeper,
               "Keeper Veyron is present at the temple location.", (_XHALRUUNS,)),
        _known(module_id, scene, "connection_ak02", scene, "listed_connection", ak02,
               "The source lists connectivity to AK02 without a view bearing.", (_XHALRUUNS,)),
        _known(module_id, scene, "entry_view_identity", entry_view, "view_of_shared_location", scene,
               "Builder-authored entry view references the one selected source location identity.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "altar_view_identity", altar_view, "view_of_shared_location", scene,
               "Builder-authored altar view references the same selected source location identity.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "shared_view_identity", entry_view, "shared_identity_across_views", altar_view,
               "The two Builder-authored views share one place identity; this makes no separate-frontage claim.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "entry_approach_builder_feature", approach, "builder_authored_feature", south_entrance,
               "Builder-authored entry approach feature for the source-listed South Entrance.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "stage_approach", approach, "approach_to_threshold", south_entrance,
               "Builder-authored visual approach relation places the source-listed South Entrance in the arrival view without a compass frame.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "stage_threshold", south_entrance, "threshold_to_focal", altar,
               "Builder-authored visual staging relates the South Entrance threshold to the central altar without implying entry or access.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "stage_focal", scene, "focal_anchor_assignment", altar,
               "Builder-authored focal relation highlights the central crystal altar.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "mosaic_invitation", mosaics, "visible_affordance", scene,
               "The shifting mosaics offer changing visible details to notice.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "keeper_start_position", keeper, "initial_schematic_position", altar_view,
               "Builder-authored schematic placement; the source does not specify Keeper Veyron's position.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "schematic_cells_authored", approach, "schematic_layout_authorship", scene,
               "Builder-authored schematic cells do not establish compass, metric, access, or separate frontages.", (_XHALRUUNS,), authorship="builder"),
        _known(module_id, scene, "guarded_vestry", scene, "guarded_feature", vestry,
               "GM-only: a hidden locked vestry door is described behind the central altar.", (_XHALRUUNS,), audience="gm_only"),
        _known(module_id, scene, "keeper_guarded_knowledge", keeper, "guarded_knowledge", scene,
               "GM-only: the source says Keeper Veyron is concealing information about the altar.", (_XHALRUUNS,), audience="gm_only"),
        _unknown(module_id, scene, "guarded_knowledge_outcome_unknown", keeper, "guarded_effect_outcome", scene, audience="gm_only"),
        _unknown(module_id, scene, "compass_unknown", scene, "compass_bearing", south_entrance),
        _unknown(module_id, scene, "approach_distance_unknown", approach, "approach_route_length", south_entrance),
        _unknown(module_id, scene, "view_bearing_unknown", entry_view, "view_bearing", altar_view),
        _unknown(module_id, scene, "light_gradient_unknown", approach, "light_gradient", altar),
        _unknown(module_id, scene, "sound_gradient_unknown", approach, "sound_gradient", altar),
        _unknown(module_id, scene, "weather_gradient_unknown", approach, "weather_gradient", altar),
    ]
    temple_nodes = [
        _node(scene, "Sanctum of Fractured Truths"), _node(entry_view, "Entry view of shared location"),
        _node(altar_view, "Altar view of shared location"), _node(ak02, "Miragebound Exchange"),
    ]
    temple_links = [
        _link(_fact_id(module_id, "entry_view_identity"), entry_view, scene, "same_location_view"),
        _link(_fact_id(module_id, "altar_view_identity"), altar_view, scene, "same_location_view"),
        _link(_fact_id(module_id, "connection_ak02"), scene, ak02, "listed_connection"),
    ]
    temple_layout = [
        _layout(entry_view, approach, "approach", 0, 0),
        _layout(entry_view, south_entrance, "entrance", 0, 1),
        _layout(altar_view, altar, "altar", 1, 1),
        _layout(altar_view, lanterns, "lanterns", 1, 0),
        _layout(altar_view, mosaics, "mosaics", 2, 1),
        _layout(altar_view, keeper, "keeper", 1, 2),
        _layout(altar_view, vestry, "guarded_vestry", 2, 2),
    ]
    temple_arrival = [
        {"id": "arrival-approach", "role": "approach", "text": "Tall oak double doors carved with paradoxical symbols mark the South Entrance, flanked by flickering lanterns.", "fact_ids": [_fact_id(module_id, "entry_approach_builder_feature"), _fact_id(module_id, "stage_approach"), _fact_id(module_id, "source_entrance"), _fact_id(module_id, "source_lanterns")]},
        {"id": "arrival-threshold", "role": "threshold", "text": "At the South Entrance, the domed marble temple's mirrored mosaics subtly shift; at its center, a fractured-crystal altar sits among ritual implements and an offering bowl.", "fact_ids": [_fact_id(module_id, "stage_threshold"), _fact_id(module_id, "source_temple_appearance"), _fact_id(module_id, "source_mosaics"), _fact_id(module_id, "source_altar")]},
        {"id": "arrival-focal", "role": "focal", "text": "Flickering lanterns cast strange overlapping shadows as rainbow light refracts across the crystal altar. The shifting mosaics offer changing details to notice.", "fact_ids": [_fact_id(module_id, "source_lanterns"), _fact_id(module_id, "source_altar"), _fact_id(module_id, "source_mosaics"), _fact_id(module_id, "stage_focal"), _fact_id(module_id, "mosaic_invitation")]},
    ]
    temple_public_scene_ids = [scene, entry_view, altar_view, ak02]
    temple_public_link_ids = [item["id"] for item in temple_links]
    temple_public_layout = [item["anchor_id"] for item in temple_layout if item["anchor_id"] != vestry]
    records.append(_scene_record(
        scene, "published-module:Xhalruuns_Masquerade:TPG001:AK01",
        ((_XHALRUUNS, "8c1271cee7c9db9f82665a2204b5c35f6259336f11b5c949240290965b1afca0"),),
        "a9239061ad1981e68eaef0d1611283cae9c79514802d6f3d3ceb952d7fd37d98",
        ((_XHALRUUNS, "locations", "locationId", "AK01"),),
        _spec(scene, temple_facts, temple_nodes, temple_links, temple_layout,
              temple_public_scene_ids, temple_public_link_ids, temple_public_layout, temple_arrival),
    ))

    # Fogroot Barrow Stalls: authored path, boundary, extent, and usable ring.
    module_id = "the_garden_of_demons"
    scene = module_id + ":scene:fogroot-barrow-stalls"
    path_a = _entity(module_id, "gravel-path-cell-a")
    path_b = _entity(module_id, "gravel-path-cell-b")
    threshold = _entity(module_id, "market-stalls")
    stalls_a = _entity(module_id, "stall-boundary-cell-a")
    stalls_b = _entity(module_id, "stall-boundary-cell-b")
    barrow = _entity(module_id, "fogroot-barrow")
    barrow_a = _entity(module_id, "barrow-boundary-cell-a")
    barrow_b = _entity(module_id, "barrow-boundary-cell-b")
    ring_a = _entity(module_id, "stone-ring-cell-a")
    ring_b = _entity(module_id, "stone-ring-cell-b")
    child = _entity(module_id, "spectral-child")
    secret_cache = _entity(module_id, "guarded-cache")
    h02 = module_id + ":scene:withered-lantern-square"
    wilds = module_id + ":scene:thornwound-wilds"
    garden_facts = [
        _known(module_id, scene, "path_from_square", path_a, "source_named_approach", scene,
               "The location is accessible by following a gravel path from the village square; the ground is soft and muddy, but passable.", (_GARDEN,)),
        _known(module_id, scene, "market_stalls_present", scene, "contains_feature", threshold,
               "Several market stalls cluster around a low barrow mound covered in tangled fogroot.", (_GARDEN,)),
        _known(module_id, scene, "stalls_around_barrow", scene, "stalls_cluster_around", barrow,
               "Several market stalls cluster around a low barrow mound covered in tangled fogroot.", (_GARDEN,)),
        _known(module_id, scene, "market_goods", threshold, "visible_contents", scene,
               "Vendors hawk root vegetables, carved charms, and old relics unearthed from the barrow itself.", (_GARDEN,)),
        _known(module_id, scene, "stone_ring_gathering", scene, "contains_gathering_space", ring_a,
               "A ring of stones is a gathering place for villagers.", (_GARDEN,)),
        _known(module_id, scene, "child_among_stalls", scene, "has_mobile_occupant", child,
               "The Spectral Child wanders among the stalls at dusk.", (_GARDEN,)),
        _known(module_id, scene, "cool_persistent_mist", scene, "weather_condition", barrow,
               "The air is described as cool and perpetually misty.", (_GARDEN,)),
        _known(module_id, scene, "connection_h02", scene, "listed_connection", h02,
               "The source lists H02 as connected to H03.", (_GARDEN,)),
        _known(module_id, scene, "connection_wilds", scene, "listed_area_connection", wilds,
               "The source lists a connection to the Thornwound Wilds.", (_GARDEN,)),
        _known(module_id, scene, "gravel_path_builder_feature", path_a, "builder_authored_feature", path_b,
               "Builder-authored gravel path approach represented by two schematic cells.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "stage_approach", path_b, "approach_to_threshold", threshold,
               "Builder-authored relation connects the gravel path approach to the source-listed market stalls; no route length is stated.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "stage_threshold", threshold, "threshold_to_focal", barrow,
               "Builder-authored threshold relation connects the market stalls to the low barrow mound.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "stage_focal", scene, "focal_anchor_assignment", barrow,
               "Builder-authored focal relation highlights the low barrow mound.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "path_extent_authored", path_a, "schematic_path_extent", path_b,
               "Builder-authored gravel approach extent uses two schematic cells only.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "stall_boundary_authored", stalls_a, "schematic_boundary_extent", stalls_b,
               "Builder-authored stall boundary uses two schematic cells only.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "barrow_boundary_authored", barrow_a, "schematic_terrain_extent", barrow_b,
               "Builder-authored barrow terrain extent uses two schematic cells only.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "ring_usable_space_authored", ring_a, "schematic_usable_space", ring_b,
               "Builder-authored stone-ring cells represent usable gathering space, not movement or access.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "market_goods_invitation", threshold, "visible_affordance", scene,
               "The displayed charms and relics offer a visible invitation to browse.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "child_start_position", child, "initial_schematic_position", stalls_a,
               "Builder-authored initial schematic placement among stalls; exact position is not source-specified.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "schematic_cells_authored", threshold, "schematic_layout_authorship", scene,
               "Builder-authored schematic cells have no compass, metric, access, or mechanics meaning.", (_GARDEN,), authorship="builder"),
        _known(module_id, scene, "guarded_cache_hook", scene, "guarded_discovery", secret_cache,
               "GM-only: the source describes a hidden cache beneath the barrow and a clue from the child.", (_GARDEN,), audience="gm_only"),
        _known(module_id, scene, "guarded_silver_trail", child, "guarded_clue", barrow,
               "GM-only: a Perception check can reveal a faint silver trail behind the barrow.", (_GARDEN,), audience="gm_only"),
        _unknown(module_id, scene, "guarded_outcome_unknown", secret_cache, "guarded_effect_outcome", scene, audience="gm_only"),
        _unknown(module_id, scene, "compass_unknown", scene, "compass_bearing", threshold),
        _unknown(module_id, scene, "route_distance_unknown", path_a, "approach_route_length", threshold),
        _unknown(module_id, scene, "light_gradient_unknown", path_a, "light_gradient", barrow),
        _unknown(module_id, scene, "sound_gradient_unknown", path_a, "sound_gradient", barrow),
        _unknown(module_id, scene, "weather_gradient_unknown", path_a, "weather_gradient", barrow),
    ]
    garden_nodes = [_node(scene, "Fogroot Barrow Stalls"), _node(h02, "Withered Lantern Square"), _node(wilds, "Thornwound Wilds")]
    garden_links = [
        _link(_fact_id(module_id, "connection_h02"), scene, h02, "listed_connection"),
        _link(_fact_id(module_id, "connection_wilds"), scene, wilds, "listed_area_connection"),
    ]
    garden_layout = [
        _layout(scene, path_a, "path", 0, 0), _layout(scene, path_b, "path", 0, 1),
        _layout(scene, threshold, "threshold", 0, 2), _layout(scene, stalls_a, "stall_boundary", 1, 1),
        _layout(scene, stalls_b, "stall_boundary", 1, 2), _layout(scene, barrow, "barrow", 2, 1),
        _layout(scene, barrow_a, "barrow_terrain", 2, 0), _layout(scene, barrow_b, "barrow_terrain", 2, 2),
        _layout(scene, ring_a, "usable_space", 3, 1), _layout(scene, ring_b, "usable_space", 3, 2),
        _layout(scene, child, "spectral_child", 1, 0), _layout(scene, secret_cache, "guarded_cache", 3, 0),
    ]
    garden_public_layout = [item["anchor_id"] for item in garden_layout if item["anchor_id"] != secret_cache]
    garden_arrival = [
        {"id": "arrival-approach", "role": "approach", "text": "A gravel path from the village square meets several market stalls clustered around a low barrow mound covered in tangled fogroot.", "fact_ids": [_fact_id(module_id, "gravel_path_builder_feature"), _fact_id(module_id, "path_from_square"), _fact_id(module_id, "stage_approach"), _fact_id(module_id, "market_stalls_present")]},
        {"id": "arrival-threshold", "role": "threshold", "text": "Among the stalls, the low mound is covered in tangled fogroot; the air is cool and perpetually misty.", "fact_ids": [_fact_id(module_id, "stage_threshold"), _fact_id(module_id, "stalls_around_barrow"), _fact_id(module_id, "cool_persistent_mist")]},
        {"id": "arrival-focal", "role": "focal", "text": "Vendors hawk root vegetables, carved charms, and old relics unearthed from the barrow; the charms and relics invite a closer look.", "fact_ids": [_fact_id(module_id, "stage_focal"), _fact_id(module_id, "market_goods"), _fact_id(module_id, "market_goods_invitation")]},
    ]
    records.append(_scene_record(
        scene, "published-module:The_Garden_of_Demons:GV001:H03",
        ((_GARDEN, "9176a18c58394ac47bb101f3e43a112fcb9454024ea0d38cdc70e91553893407"),),
        "945728477f2ac06ea120463cb31486ff88cc019d98127b291ca85de1d7d1bda5",
        ((_GARDEN, "locations", "locationId", "H03"),),
        _spec(scene, garden_facts, garden_nodes, garden_links, garden_layout, [scene, h02, wilds],
              [item["id"] for item in garden_links], garden_public_layout, garden_arrival),
    ))

    # Trial at the Door: keep the illusory threshold and conditional outcomes GM-only.
    module_id = "the_hidden_city_of_numillian"
    scene = module_id + ":scene:trial-at-the-door"
    approach = _entity(module_id, "party-approach")
    threshold = _entity(module_id, "rubble-and-overgrown-vegetation")
    tower = _entity(module_id, "stone-watchtower")
    shuluth = _entity(module_id, "shuluth")
    guarded_wall = _entity(module_id, "guarded-illusory-wall")
    guarded_trial = module_id + ":scene:trial-one-gm-view"
    area_source = _NUMILLIAN_AREA
    plot_source = _NUMILLIAN_PLOT
    numillian_facts = [
        _known(module_id, scene, "location_identity", scene, "selected_location", scene,
               "A01 is named Numillian / The Hidden City.", (area_source,)),
        _known(module_id, scene, "source_visible_rubble_vegetation", scene, "visible_appearance", threshold,
               "Rubble and impenetrable vegetation confront the approaching party.", (plot_source,)),
        _known(module_id, scene, "source_watchtower", scene, "named_sequence_anchor", tower,
               "A small stone watchtower is the destination of the approach sequence.", (plot_source,)),
        _known(module_id, scene, "source_shuluth_meets_party", scene, "has_mobile_occupant", shuluth,
               "The plot point says Shuluth walks out to meet the party.", (plot_source,)),
        _known(module_id, scene, "source_shuluth_leads_party", shuluth, "leads_party_to", tower,
               "Shuluth leads the party to a small stone watchtower.", (plot_source,)),
        _known(module_id, scene, "source_connection_a02", scene, "listed_connection", module_id + ":scene:stone-watchtower",
               "The A01 source record lists a connection to A02.", (area_source,)),
        _known(module_id, scene, "stage_approach", approach, "approach_to_threshold", threshold,
               "The plot point describes characters approaching the rubble and impenetrable vegetation.", (plot_source,)),
        _known(module_id, scene, "stage_threshold", threshold, "threshold_to_focal", tower,
               "Shuluth walks out to meet the party and leads them from the approach to a small stone watchtower.", (plot_source,)),
        _known(module_id, scene, "stage_focal", scene, "focal_anchor_assignment", tower,
               "The small stone watchtower is the focal destination of Shuluth's approach sequence.", (plot_source,)),
        _known(module_id, scene, "shuluth_arrival_position", shuluth, "arrival_schematic_position", threshold,
               "Builder-authored schematic placement at the visible rubble-and-vegetation meeting point; it does not claim Shuluth's unobserved starting point.", (plot_source,), authorship="builder"),
        _known(module_id, scene, "schematic_cells_authored", approach, "schematic_layout_authorship", scene,
               "Builder-authored cells are schematic only and imply no compass, metric, route, or access.", (area_source, plot_source), authorship="builder"),
        _known(module_id, scene, "guarded_illusory_wall", scene, "guarded_secret", guarded_wall,
               "GM-only: rubble and vegetation conceal an illusory wall hiding a 20-foot stone wall with anti-flight wards; a DC 16 Perception check reveals it.", (plot_source,), audience="gm_only"),
        _known(module_id, scene, "guarded_conditional_trial", scene, "guarded_conditional_sequence", guarded_trial,
               "GM-only: after agreement, Shuluth bars the tower door and begins the mindscape sequence leading to TRIAL001.", (plot_source,), audience="gm_only"),
        _unknown(module_id, scene, "guarded_trial_outcome_unknown", guarded_trial, "guarded_effect_outcome", scene, audience="gm_only"),
        _unknown(module_id, scene, "compass_unknown", scene, "compass_bearing", threshold),
        _unknown(module_id, scene, "approach_distance_unknown", approach, "approach_route_length", threshold),
        _unknown(module_id, scene, "tower_route_unknown", threshold, "route_geometry_to_watchtower", tower),
        _unknown(module_id, scene, "light_gradient_unknown", approach, "light_gradient", tower),
        _unknown(module_id, scene, "sound_gradient_unknown", approach, "sound_gradient", tower),
        _unknown(module_id, scene, "weather_gradient_unknown", approach, "weather_gradient", tower),
    ]
    a02 = module_id + ":scene:stone-watchtower"
    numillian_nodes = [
        _node(scene, "Numillian / The Hidden City"), _node(a02, "Stone Watchtower"),
        _node(guarded_trial, "Trial sequence (GM only)", "known"),
    ]
    numillian_links = [
        _link(_fact_id(module_id, "source_connection_a02"), scene, a02, "listed_connection"),
        _link(_fact_id(module_id, "guarded_conditional_trial"), scene, guarded_trial, "guarded_next_sequence"),
    ]
    numillian_layout = [
        _layout(scene, approach, "approach", 0, 0), _layout(scene, threshold, "threshold", 0, 1),
        _layout(scene, tower, "watchtower", 0, 2), _layout(scene, shuluth, "shuluth", 1, 1),
        _layout(scene, guarded_wall, "guarded_wall", 2, 1),
    ]
    numillian_arrival = [
        {"id": "arrival-approach", "role": "approach", "text": "At Numillian, rubble and impenetrable vegetation confront the party's approach.", "fact_ids": [_fact_id(module_id, "location_identity"), _fact_id(module_id, "source_visible_rubble_vegetation"), _fact_id(module_id, "stage_approach")]},
        {"id": "arrival-threshold", "role": "threshold", "text": "Rubble and impenetrable vegetation confront the party; Shuluth walks out to meet them.", "fact_ids": [_fact_id(module_id, "source_visible_rubble_vegetation"), _fact_id(module_id, "stage_approach"), _fact_id(module_id, "source_shuluth_meets_party")]},
        {"id": "arrival-focal", "role": "focal", "text": "Shuluth leads the party to a small stone watchtower.", "fact_ids": [_fact_id(module_id, "source_shuluth_leads_party"), _fact_id(module_id, "stage_threshold"), _fact_id(module_id, "stage_focal"), _fact_id(module_id, "source_watchtower")]},
    ]
    numillian_public_nodes = [scene, a02]
    numillian_public_links = [_fact_id(module_id, "source_connection_a02")]
    numillian_public_layout = [item["anchor_id"] for item in numillian_layout if item["anchor_id"] != guarded_wall]
    records.append(_scene_record(
        scene, "published-module:The_Hidden_City_of_Numillian:A000:A01:TRIAL000",
        (
            (area_source, "cb36dfe6ebe2eccc679d9ba9b218da00cf686bef3d06dd5bf3d5eedff4208900"),
            (plot_source, "1ddddc7b10f063f7a18cabfc9e31a13acd8534cc0981e906a53a83510c781ee1"),
        ),
        "96d0ef1579a7a80d05df443f375acbb1030e28825af546e2c8776f8b78c9fce9",
        (
            (area_source, "map.rooms", "id", "A01"),
            (area_source, "locations", "locationId", "A01"),
            (plot_source, "plotPoints", "id", "TRIAL000"),
        ),
        _spec(scene, numillian_facts, numillian_nodes, numillian_links, numillian_layout,
              numillian_public_nodes, numillian_public_links, numillian_public_layout, numillian_arrival),
        source_field_refs=(
            (_fact_id(module_id, "location_identity"), area_source, "map.rooms[id=A01].name"),
            (_fact_id(module_id, "location_identity"), area_source, "locations[locationId=A01].name"),
            (None, area_source, "locations[locationId=A01].description (empty; no scene fact extracted)"),
            (_fact_id(module_id, "source_connection_a02"), area_source, "map.rooms[id=A01].connections"),
            (_fact_id(module_id, "source_connection_a02"), area_source, "locations[locationId=A01].connectivity"),
            (_fact_id(module_id, "source_visible_rubble_vegetation"), plot_source, "plotPoints[id=TRIAL000].description"),
            (_fact_id(module_id, "stage_approach"), plot_source, "plotPoints[id=TRIAL000].description"),
            (_fact_id(module_id, "source_shuluth_meets_party"), plot_source, "plotPoints[id=TRIAL000].description"),
            (_fact_id(module_id, "source_shuluth_leads_party"), plot_source, "plotPoints[id=TRIAL000].description"),
            (_fact_id(module_id, "source_watchtower"), plot_source, "plotPoints[id=TRIAL000].description"),
            (_fact_id(module_id, "stage_threshold"), plot_source, "plotPoints[id=TRIAL000].description"),
            (_fact_id(module_id, "stage_focal"), plot_source, "plotPoints[id=TRIAL000].description"),
            (_fact_id(module_id, "guarded_illusory_wall"), plot_source, "plotPoints[id=TRIAL000].description"),
            (_fact_id(module_id, "guarded_conditional_trial"), plot_source, "plotPoints[id=TRIAL000].description"),
        ),
    ))
    return tuple(records)


SCENE_SPECS = _build_scene_records()


def _raw_array_object(
    raw_text: str, collection: str, id_key: str, record_id: str
) -> str:
    decoder = json.JSONDecoder()
    scope_text = raw_text
    collection_parts = collection.split(".")
    for parent in collection_parts[:-1]:
        parent_marker = re.search(
            r'"' + re.escape(parent) + r'"\s*:\s*\{', scope_text
        )
        if parent_marker is None:
            raise ValueError("selected source object missing: " + parent)
        object_start = parent_marker.end() - 1
        parent_object, object_end = decoder.raw_decode(scope_text, object_start)
        if type(parent_object) is not dict:
            raise ValueError("selected source object is not an object: " + parent)
        scope_text = scope_text[object_start:object_end]
    marker = re.search(
        r'"' + re.escape(collection_parts[-1]) + r'"\s*:\s*\[', scope_text
    )
    if marker is None:
        raise ValueError("selected source array missing: " + collection)
    position = marker.end()
    while position < len(scope_text):
        while position < len(scope_text) and (scope_text[position].isspace() or scope_text[position] == ","):
            position += 1
        if position >= len(scope_text) or scope_text[position] == "]":
            break
        start = position
        item, end = decoder.raw_decode(scope_text, position)
        if type(item) is dict and item.get(id_key) == record_id:
            return scope_text[start:end]
        position = end
    raise ValueError("selected source record missing: " + collection + "[" + record_id + "]")


def _load_source_text(record: dict[str, Any]) -> str:
    spans: list[str] = []
    actual_files: dict[str, str] = {}
    for source_file in record["source_files"]:
        path = source_file["path"]
        raw = (_REPO_ROOT / path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != source_file["sha256"]:
            raise ValueError("selected source file hash changed: " + path)
        actual_files[path] = raw.decode("utf-8")
    for path, collection, id_key, record_id in record["source_spans"]:
        spans.append(_raw_array_object(actual_files[path], collection, id_key, record_id))
    source_text = "".join(spans)
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if digest != record["source_text_sha256"]:
        raise ValueError("selected source-text hash changed: " + record["scene_id"])
    return source_text


def build_scene_inputs() -> list[dict[str, Any]]:
    """Load and validate the six selected source spans and build projection pairs."""

    scenes: list[dict[str, Any]] = []
    for record in SCENE_SPECS:
        source_text = _load_source_text(record)
        candidate, reference = make_projection_pair(copy.deepcopy(record["spec"]))
        fingerprints = evaluation.fingerprint_source_text(source_text)
        scenes.append(
            {
                "scene_id": record["scene_id"],
                "source_identity": record["source_identity"],
                "source_ref": record["source_ref"],
                "source_text": source_text,
                "lineage_status": record["lineage_status"],
                "adaptation_lineage": list(record["adaptation_lineage"]),
                "layout_tokens": fingerprints["layout_tokens"],
                "feature_tokens": fingerprints["feature_tokens"],
                "projection_candidate": candidate,
                "projection_reference": reference,
            }
        )
    return scenes


def selected_source_hashes() -> dict[str, str]:
    """Return the pinned source hashes from the reviewed selection draft."""

    return {
        source_file["path"]: source_file["sha256"]
        for record in SCENE_SPECS
        for source_file in record["source_files"]
    }
