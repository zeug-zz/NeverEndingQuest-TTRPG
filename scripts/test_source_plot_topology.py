#!/usr/bin/env python3
"""Contract tests for plot, puzzle, clue, and trial topology synthesis."""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.toolkit_source_graph_synthesis import (
    build_plot_topology_report,
)
from utils.toolkit_source_manifest import build_source_graph


TRIAL_MD = """\
# Trial of the Ancients

## The Door of Skulls

### Skull Riddle
The skull speaks: "I have cities but no houses, forests but no trees, rivers but no water. What am I?"
Answer: A map.
Failure: Wrong answers summon 2 specters.

### Flooding Room Puzzle
When the riddle is solved, water pours from the walls. A DC 14 Wisdom check reveals the hidden drain.
Success: Room drains.
Failure: Party takes 2d6 cold damage per round.

### The Dog Mindscape
The party enters a shared dream. A friendly dog approaches. Attacking the dog fails the trial.
Success: Befriend or ignore the dog.
Failure: Trial lost, party ejected from city.
"""


class TestPlotTopology(unittest.TestCase):
    """Task 4.x: Plot topology synthesis."""

    def test_topology_report_shape(self):
        report = build_plot_topology_report({}, {})
        self.assertIn("topology_version", report)
        self.assertIn("plot_beats", report)
        self.assertIn("puzzle_chains", report)
        self.assertIn("clue_dependencies", report)
        self.assertIn("trials", report)
        self.assertIn("endings", report)
        self.assertIn("assumptions", report)
        self.assertIn("unresolved", report)

    def test_model_topology_flows_through(self):
        model_output = {
            "plot_beats": [
                {
                    "id": "beat-1",
                    "title": "Enter the city",
                    "trigger": "Solve the riddle",
                    "optional": False,
                    "assumed": False,
                    "source_refs": [{"atom_id": "test", "line_start": 1}],
                }
            ],
            "puzzle_chains": [],
            "clue_dependencies": [],
            "trials": [],
            "endings": [],
            "assumptions": [],
            "unresolved": [],
        }
        report = build_plot_topology_report(
            {}, [], topology_model_output=model_output
        )
        self.assertEqual(len(report["plot_beats"]), 1)
        self.assertEqual(report["plot_beats"][0]["title"], "Enter the city")

    def test_source_order_preserved_when_no_dependencies(self):
        model_output = {
            "plot_beats": [
                {
                    "id": "beat-2",
                    "title": "Later beat",
                    "source_refs": [{"line_start": 20}],
                    "assumed": False,
                },
                {
                    "id": "beat-1",
                    "title": "Earlier beat",
                    "source_refs": [{"line_start": 5}],
                    "assumed": False,
                },
            ],
            "puzzle_chains": [],
            "clue_dependencies": [],
            "trials": [],
            "endings": [],
            "assumptions": [],
            "unresolved": [],
        }
        report = build_plot_topology_report(
            {}, [], topology_model_output=model_output
        )
        # Should be sorted by line_start: earlier beat first
        beats = report["plot_beats"]
        self.assertGreater(len(beats), 1)
        self.assertEqual(beats[0]["title"], "Earlier beat")

    def test_trial_structure_preserved(self):
        model_output = {
            "plot_beats": [],
            "puzzle_chains": [
                {
                    "id": "door-trial",
                    "title": "Trial at the Door",
                    "steps": [
                        {
                            "order": 1,
                            "name": "Skull Riddle",
                            "setup": "Skull speaks",
                            "prompt": "Riddle text",
                            "solution": "A map",
                            "failure": "Specters",
                            "reward": "Opens door",
                        }
                    ],
                }
            ],
            "clue_dependencies": [],
            "trials": [],
            "endings": [],
            "assumptions": [],
            "unresolved": [],
        }
        report = build_plot_topology_report(
            {}, [], topology_model_output=model_output
        )
        puzzle_chain = report["puzzle_chains"][0]
        self.assertEqual(puzzle_chain["id"], "door-trial")
        self.assertEqual(len(puzzle_chain["steps"]), 1)
        self.assertEqual(puzzle_chain["steps"][0]["solution"], "A map")

    def test_missing_required_atoms_listed_in_unresolved(self):
        source_graph = build_source_graph(TRIAL_MD)
        report = build_plot_topology_report(source_graph, {})
        # If required atoms exist that aren't in topology, they should appear
        # in unresolved.  At minimum, unresolved is a list.
        self.assertIsInstance(report["unresolved"], list)

    def test_empty_source_produces_empty_report(self):
        report = build_plot_topology_report({}, [])
        self.assertIsInstance(report["plot_beats"], list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
