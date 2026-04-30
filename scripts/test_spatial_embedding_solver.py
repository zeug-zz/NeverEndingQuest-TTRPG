# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""Regression tests for spatial constraint solver (Tier 1-3).

Tests cover:
  - Tier 1 constraint solver (bread loaf, star, chain, triangle)
  - Tier 1 guards (wall-clock timeout, recursion depth)
  - Tier 2 cell-expansion + swap optimization
  - Tier 3 linear layout as diagnostic-only fallback
  - Tiered solver report diagnostics and failure handling
"""

import time
import unittest
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.remediate_module_coordinates import (
    _solve_grid_embedding,
    _is_fully_adjacent,
    _relax_with_expansion,
    _build_linear_layout,
    _build_tiered_spatial_report,
    _bfs_order,
    _count_adjacent_connected_pairs,
    _swap_optimize,
    _cardinal_intersection,
)
from utils.spatial_contract import parse_coordinate


class TestTier1ConstraintSolver(unittest.TestCase):

    def test_bread_loaf_graph(self):
        g = {
            'G01': ['G02'], 'G02': ['G01', 'G03', 'G05'],
            'G03': ['G02', 'G04'], 'G04': ['G03', 'G05'],
            'G05': ['G02', 'G04'],
        }
        result = _solve_grid_embedding(g)
        self.assertIsNotNone(result)
        self.assertTrue(_is_fully_adjacent(result, g))

    def test_star_graph(self):
        g = {'H': ['A', 'B', 'C', 'D'],
             'A': ['H'], 'B': ['H'], 'C': ['H'], 'D': ['H']}
        result = _solve_grid_embedding(g)
        self.assertIsNotNone(result)
        self.assertTrue(_is_fully_adjacent(result, g))

    def test_15_room_chain_speed(self):
        g = {}
        for i in range(1, 16):
            g[f'R{i}'] = []
        for i in range(1, 15):
            g[f'R{i}'].append(f'R{i+1}')
            g[f'R{i+1}'].append(f'R{i}')
        start = time.perf_counter()
        result = _solve_grid_embedding(g)
        elapsed = (time.perf_counter() - start) * 1000
        self.assertIsNotNone(result)
        self.assertTrue(_is_fully_adjacent(result, g))
        self.assertLess(elapsed, 100, f'15-room chain took {elapsed:.1f}ms')

    def test_triangle_returns_none(self):
        g = {'A': ['B', 'C'], 'B': ['A', 'C'], 'C': ['A', 'B']}
        result = _solve_grid_embedding(g)
        self.assertIsNone(result)

    def test_wall_clock_guard_fires(self):
        # Build a 15-room graph that stresses backtracking (fully connected hub)
        N = 8
        g = {}
        for i in range(N):
            g[f'R{i}'] = []
        # Make every room connected to every other room (impossible to embed)
        for i in range(N):
            for j in range(i + 1, N):
                g[f'R{i}'].append(f'R{j}')
                g[f'R{j}'].append(f'R{i}')
        # Should exhaust roots and return None before timing out
        start = time.perf_counter()
        result = _solve_grid_embedding(g)
        elapsed = (time.perf_counter() - start) * 1000
        self.assertIsNone(result)
        # Even for an impossible graph, solver should bail quickly
        self.assertLess(elapsed, 500, f'Impossible graph took {elapsed:.1f}ms')

    def test_recursion_depth_guard(self):
        # A graph that forces deep backtracking
        N = 20
        g = {}
        for i in range(N):
            g[f'R{i}'] = []
        # Fully connected — impossible to embed on grid
        for i in range(N):
            for j in range(i + 1, N):
                g[f'R{i}'].append(f'R{j}')
                g[f'R{j}'].append(f'R{i}')
        result = _solve_grid_embedding(g)
        self.assertIsNone(result)  # Should bail via guard, not crash


class TestTier2CellExpansion(unittest.TestCase):

    def test_buffer_cell_added(self):
        bad = {'A': 'X10Y10', 'B': 'X12Y10', 'C': 'X10Y11'}
        g = {'A': ['B'], 'B': ['A'], 'C': []}
        expanded = _relax_with_expansion(dict(bad), g)
        self.assertTrue(any(k.startswith('_buf_') for k in expanded))

    def test_20_room_graph_timing(self):
        # 20-room chain, tested through cell-expansion path
        N = 20
        g = {}
        for i in range(N):
            g[f'R{i}'] = []
        for i in range(N - 1):
            g[f'R{i}'].append(f'R{i+1}')
            g[f'R{i+1}'].append(f'R{i}')
        # Build bad coordinates (all rooms at same y, staggered x — some non-adjacent)
        bad = {f'R{i}': f'X{10 + i*2}Y10' for i in range(N)}
        start = time.perf_counter()
        expanded = _relax_with_expansion(dict(bad), g)
        elapsed = (time.perf_counter() - start) * 1000
        self.assertLess(elapsed, 1000, f'Tier 2 20-room took {elapsed:.1f}ms')
        # At minimum, shouldn't crash and should return something deterministic
        self.assertGreater(len(expanded), 0)

    def test_swap_non_decreasing(self):
        s = {'A': 'X10Y12', 'B': 'X10Y10'}
        g = {'A': ['B'], 'B': ['A']}
        before = _count_adjacent_connected_pairs(s, g)
        _swap_optimize(s, g)
        after = _count_adjacent_connected_pairs(s, g)
        self.assertGreaterEqual(after, before)


class TestTier3LinearLayout(unittest.TestCase):

    def test_chain_all_edges_close(self):
        chain = {}
        for i in range(10):
            chain[f'R{i}'] = []
        for i in range(9):
            chain[f'R{i}'].append(f'R{i+1}')
            chain[f'R{i+1}'].append(f'R{i}')
        linear = _build_linear_layout(chain)
        xy = {rid: parse_coordinate(cs) for rid, cs in linear.items()}
        self.assertEqual(len(xy), 10)
        distinct = len(set(xy.values()))
        self.assertEqual(distinct, 10)
        self.assertEqual(set(xy), set(chain))

    def test_disconnected_graph_all_nodes_covered(self):
        disco = {'A': ['B'], 'B': ['A'], 'C': ['D', 'E'], 'D': ['C'], 'E': ['C']}
        linear = _build_linear_layout(disco)
        xy = {rid: parse_coordinate(cs) for rid, cs in linear.items()}
        self.assertEqual(len(xy), 5)

    def test_triangle_linear_layout_does_not_false_pass(self):
        triangle = {'A': ['B', 'C'], 'B': ['A', 'C'], 'C': ['A', 'B']}
        linear = _build_linear_layout(triangle)
        xy = {rid: parse_coordinate(cs) for rid, cs in linear.items()}
        self.assertFalse(_is_fully_adjacent(xy, triangle))

    def test_tiered_report_marks_false_fallback_as_failed(self):
        triangle = {'A': ['B', 'C'], 'B': ['A', 'C'], 'C': ['A', 'B']}
        report = _build_tiered_spatial_report(triangle)
        self.assertEqual(report['status'], 'failed')
        codes = {item.get('code') for item in report['diagnostics']}
        self.assertIn('fallback_unvalidated', codes)

    def test_linear_layout_no_crash_on_empty(self):
        self.assertEqual(_build_linear_layout({}), {})


class TestBFSOrder(unittest.TestCase):

    def test_bfs_covers_all_components(self):
        g = {'A': ['B'], 'B': ['A'], 'C': ['D'], 'D': ['C']}
        order = _bfs_order(g, 'A')
        self.assertEqual(set(order), {'A', 'B', 'C', 'D'})

    def test_bfs_wrong_root_still_works(self):
        g = {'C': ['D'], 'D': ['C']}
        order = _bfs_order(g, 'A')  # 'A' not in graph
        self.assertEqual(set(order), {'C', 'D'})


class TestHelpers(unittest.TestCase):

    def test_cardinal_intersection(self):
        coords = {'A': (10, 10), 'B': (12, 10)}
        result = _cardinal_intersection(['A', 'B'], coords)
        self.assertEqual(result, {(11, 10)})

    def test_fully_adjacent_true(self):
        coords = {'A': (10, 10), 'B': (11, 10), 'C': (12, 10)}
        g = {'A': ['B'], 'B': ['A', 'C'], 'C': ['B']}
        self.assertTrue(_is_fully_adjacent(coords, g))

    def test_fully_adjacent_false(self):
        coords = {'A': (10, 10), 'B': (12, 10)}
        g = {'A': ['B'], 'B': ['A']}
        self.assertFalse(_is_fully_adjacent(coords, g))


class TestCellExpansionSmoke(unittest.TestCase):

    def test_fully_connected_impossible(self):
        # K5: 5-room complete graph (impossible on grid)
        g = {}
        for i in range(5):
            g[f'R{i}'] = []
        for i in range(5):
            for j in range(i + 1, 5):
                g[f'R{i}'].append(f'R{j}')
                g[f'R{j}'].append(f'R{i}')
        # Should complete without crash and return a deterministic seed layout
        from scripts.remediate_module_coordinates import _build_force_relayout_coordinates
        locations = [{'locationId': f'R{i}', 'connectivity': g[f'R{i}']} for i in range(5)]
        result = _build_force_relayout_coordinates(locations)
        self.assertEqual(len(result), 5)
        # All coords are distinct
        coords_set = set(result.values())
        self.assertEqual(len(coords_set), 5)


if __name__ == '__main__':
    unittest.main()
