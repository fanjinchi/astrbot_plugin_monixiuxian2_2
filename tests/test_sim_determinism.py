"""Determinism guard for sim_route_matchup battle seeding (bd 9j1).

Before per-battle seeding, the engine-global RNG made every rerun of the
same cell drift by ~±2pp at 3000 battles, so committed CSV/report baselines
could not distinguish noise from real regressions. These tests lock the
seeding contract: identical battle counts produce identical aggregates on
repeat runs, for both the plain matchup grid and the loadout acceptance grid.
"""

from tests.helpers import load_module

_mod = load_module(
    "sim_route_matchup_det", "design_docs/attribute-growth/sim_route_matchup.py"
)


def test_matchup_cells_are_reproducible():
    """run_matchup_cells: same battles -> byte-identical rows across reruns."""
    rows_a = _mod.run_matchup_cells(battles=20)
    rows_b = _mod.run_matchup_cells(battles=20)
    assert rows_a == rows_b


def test_loadout_cells_are_reproducible():
    """run_loadout_cells: mirror and cross grids both reproduce exactly."""
    mirror_a, cross_a = _mod.run_loadout_cells(battles=20)
    mirror_b, cross_b = _mod.run_loadout_cells(battles=20)
    assert mirror_a == mirror_b
    assert cross_a == cross_b
