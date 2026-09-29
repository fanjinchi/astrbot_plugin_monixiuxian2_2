"""Regression guard: calibration sims keep the block-rate armor source split.

Covers bd 8dm: ``sim_balance_regression.py`` / ``rebalance_equipment.py`` used
to hard-couple ``block_armor_value`` to the merged ``armor_value``. Under the
block-source split (spec combat-core 「格挡率来源分离」) armor-slot armor
(armor-content-design) must feed percent reduction only — a re-coupled sim
would silently overcount block and distort TTK/win-rate conclusions.

Locked contracts:
1. Both local ``_make_fighter`` builders accept an independent
   ``block_armor_value`` and pass it through verbatim (plumbing decoupled).
2. The omitted-parameter fallback keeps the legacy block==armor behavior, so
   weapon-only sims (no armor slot) stay numerically unchanged.
3. The sim_route_matchup loadout path excludes the armor-slot piece from
   block (semantic guard against re-coupling the very scenario bd 8dm cares
   about).
"""


from tests.helpers import load_module

_reg_mod = load_module(
    "sim_balance_regression_t",
    "design_docs/attribute-growth/sim_balance_regression.py",
)
_rebal_mod = load_module(
    "rebalance_equipment_t", "design_docs/attribute-growth/rebalance_equipment.py"
)
_matchup_mod = load_module(
    "sim_route_matchup_t", "design_docs/attribute-growth/sim_route_matchup.py"
)

FighterState = _reg_mod.FighterState


def test_balance_regression_make_fighter_honors_independent_block_source():
    """Explicit block_armor_value passes through; merged armor stays separate."""
    fs = _reg_mod._make_fighter(
        hp=100,
        damage=10,
        agility=5,
        speed=5,
        armor_value=50,
        block_armor_value=5,
        level_index=10,
    )
    assert fs.armor_value == 50
    assert fs.block_armor_value == 5


def test_balance_regression_make_fighter_fallback_keeps_legacy_semantics():
    """Omitting block_armor_value preserves the weapon-only block==armor behavior."""
    fs = _reg_mod._make_fighter(
        hp=100, damage=10, agility=5, speed=5, armor_value=50, level_index=10
    )
    assert fs.block_armor_value == fs.armor_value == 50


def test_rebalance_equipment_make_fighter_honors_independent_block_source():
    """rebalance_equipment exposes the same decoupled plumbing."""
    weapon = _rebal_mod._SampleWeapon(
        category="heavy",
        weapon_k=0.6,
        base_damage=30,
        armor_value=40,
        level_index=10,
    )
    fs = _rebal_mod._make_fighter("甲", 10, weapon, FighterState, block_armor_value=7)
    assert fs.armor_value == 40
    assert fs.block_armor_value == 7

    fs_default = _rebal_mod._make_fighter("乙", 10, weapon, FighterState)
    assert fs_default.block_armor_value == fs_default.armor_value == 40


def test_loadout_fighter_excludes_armor_slot_from_block():
    """armor-content-design acceptance path: piece armor never enters block."""
    by_family = _matchup_mod.load_armor_pieces()
    weapons = _matchup_mod.load_standard_weapons()
    level = 40
    fs = _matchup_mod.build_loadout_fighter("体修", level, by_family, weapons)

    innate = int(_matchup_mod.expected_route_attrs("体修", level)["armor_value"])
    weapon = _matchup_mod.pick_standard_weapon(weapons, level)
    piece = _matchup_mod.pick_armor(by_family, "重甲", level)

    assert fs.armor_value == innate + int(weapon["armor_value"]) + int(
        piece["armor_value"]
    )
    assert fs.block_armor_value == innate + int(weapon["armor_value"])
    assert int(piece["armor_value"]) > 0  # guard is meaningful: piece exists


def test_shared_make_fighter_default_falls_back_to_merged_armor():
    """sim_xiuxian_turns.make_fighter keeps its documented None fallback."""
    fs = _matchup_mod.make_fighter(
        hp=100, damage=10, agility=5, speed=5, armor_value=30, level_index=10
    )
    assert fs.block_armor_value == 30
    fs_split = _matchup_mod.make_fighter(
        hp=100,
        damage=10,
        agility=5,
        speed=5,
        armor_value=30,
        block_armor_value=3,
        level_index=10,
    )
    assert fs_split.block_armor_value == 3
