"""Tests for block-rate armor source separation (spec: combat-core 格挡率来源分离).

Covers:
- Aggregation layer: ``Player.get_total_attributes`` exposes ``block_armor_value``
  = innate armor + weapon-slot armor (route-multiplied); armor/technique/heart
  slots excluded (design D1).
- FighterState carries the separated value on the player build path and falls
  back to merged armor on cfg/enemy build paths (design D2).
- ``_calc_block_rate`` uses only ``block_armor_value``; reduction settlement
  still uses merged ``armor_value``; block stays an independent settlement
  layer beyond the 40% reduction cap (design D3, spec scenarios).
"""

import asyncio
import random as _random
import sys
import types
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from tests.helpers import load_module, load_package_module  # noqa: E402

_models_mod = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models")
Player = _models_mod.Player
Item = _models_mod.Item

_combat_mod = load_module("combat_manager", "managers/combat_manager.py")
CombatEngine = _combat_mod.CombatEngine
FighterState = _combat_mod.FighterState

_pve_mod = load_module("pve_combat_manager", "managers/pve_combat_manager.py")
PVECombatManager = _pve_mod.PVECombatManager


class FakeConfigManager:
    """Minimal fake config manager for tests."""

    def __init__(self, game_config=None):
        self.game_config = game_config or {}
        self.items_data = {}
        self.weapons_data = {}
        self.heart_methods_data = {}


class FakeSkillManager:
    """Minimal fake skill manager for tests."""

    async def get_battle_loadout(self, player):
        return {
            "trigger_skills": [],
            "ultimates": [],
            "heart_method_passive": {},
            "weapon_coefficient_k": 1.0,
            "base_damage": 0,
            "armor_value": 0,
        }


def make_engine(cfg=None):
    """Build a CombatEngine with minimal fake config/skill managers."""
    return CombatEngine(FakeConfigManager(cfg or {}), FakeSkillManager())


def make_item(name, item_type, armor=0, route_multiplier="{}", **kwargs):
    """Build an Item with sane defaults for attribute-sum tests."""
    return Item(
        item_id=name,
        name=name,
        item_type=item_type,
        armor_value=armor,
        route_multiplier=route_multiplier,
        **kwargs,
    )


def make_fighter(name, hp, damage, agility, speed, armor=0, block_armor=None, **kw):
    """Direct FighterState builder; block_armor defaults to armor (cfg semantics)."""
    if block_armor is None:
        block_armor = armor
    return FighterState(
        user_id=name,
        name=name,
        hp=hp,
        max_hp=hp,
        damage=damage,
        agility=agility,
        speed=speed,
        armor_value=armor,
        block_armor_value=block_armor,
        **kw,
    )


# ------------------------------------------------------------------
# 1. Aggregation layer (models.get_total_attributes)
# ------------------------------------------------------------------


class TestBlockArmorAggregation:
    """block_armor_value = innate + weapon-slot armor, route-multiplied (D1)."""

    def test_weapon_counts_armor_slot_excluded(self):
        """Same total armor, different source: only innate + weapon feed block."""
        player = Player(user_id="u1", cultivation_type="灵修", armor_value=5)
        weapon = make_item("测试剑", "weapon", armor=15)
        armor = make_item("测试甲", "armor", armor=100)

        total = player.get_total_attributes([weapon, armor])

        # Reduction settlement keeps the merged value; block sees innate + weapon.
        assert total["armor_value"] == 5 + 15 + 100
        assert total["block_armor_value"] == 5 + 15

    def test_weapon_armor_goes_through_route_multiplier(self):
        """Weapon armor contributes route-multiplied to the block source."""
        player = Player(user_id="u1", cultivation_type="体修", armor_value=5)
        weapon = make_item(
            "体修重剑", "weapon", armor=15, route_multiplier='{"体修": 1.5}'
        )
        armor = make_item(
            "测试甲", "armor", armor=100, route_multiplier='{"体修": 1.5}'
        )

        total = player.get_total_attributes([weapon, armor])

        assert total["armor_value"] == 5 + int(15 * 1.5) + int(100 * 1.5)
        # int(15 * 1.5) = 22, armor slot excluded
        assert total["block_armor_value"] == 5 + 22

    def test_heart_method_and_technique_armor_excluded(self):
        """功法/防具槽护甲（含心法被动 armor_value）不进格挡来源。"""
        player = Player(user_id="u1", cultivation_type="灵修", armor_value=5)
        technique = make_item("测试功法", "technique", armor=30)
        heart = Item(
            item_id="h1",
            name="测试心法",
            item_type="main_technique",
            armor_value=20,
            passive_bonus='{"armor_value": 10}',
            route_multiplier='{"灵修": 1.0}',
        )

        total = player.get_total_attributes([technique, heart])

        assert total["armor_value"] == 5 + 30 + 20 + 10
        assert total["block_armor_value"] == 5

    def test_pill_multiplier_does_not_scale_block_source(self):
        """丹药护甲乘区只作用合并护甲；格挡来源严格为天生+武器（spec）。"""
        player = Player(user_id="u1", cultivation_type="灵修", armor_value=10)
        weapon = make_item("测试剑", "weapon", armor=15)

        total = player.get_total_attributes(
            [weapon], pill_multipliers={"armor_value": 2.0}
        )

        assert total["armor_value"] == 50  # (10 + 15) * 2.0
        # 丹药既非天生亦非武器，不进格挡来源（防未来接战静默增益）
        assert total["block_armor_value"] == 25  # 10 + 15，不随丹药缩放


# ------------------------------------------------------------------
# 2. FighterState build paths
# ------------------------------------------------------------------


class TestFighterStateBuildPaths:
    """Player path carries separated value; cfg/enemy paths fall back (D2)."""

    @pytest.mark.asyncio
    async def test_player_path_uses_block_armor_value(self):
        """build_fighter_from_player wires total_attrs['block_armor_value']."""
        fake_cfg = FakeConfigManager()
        fake_cfg.items_data = {
            "剑": {"type": "法器", "subtype": "武器", "damage": 10, "armor_value": 15},
            "甲": {"type": "法器", "subtype": "防具", "armor_value": 100},
        }
        engine = CombatEngine(fake_cfg, FakeSkillManager())
        player = Player(
            user_id="u1",
            user_name="测试者",
            cultivation_type="灵修",
            armor_value=5,
            weapon="剑",
            armor="甲",
        )

        fighter = await engine.build_fighter_from_player(player)

        assert fighter.armor_value == 120  # 5 + 15 + 100
        assert fighter.block_armor_value == 20  # 5 + 15（防具槽不计）
        assert make_engine()._calc_block_rate(fighter) == pytest.approx(0.07)

    def test_player_path_legacy_dict_falls_back_to_merged_armor(self):
        """Mock/legacy players without the new key keep old behavior (design D2)."""

        class LegacyPlayer:
            user_id = "u1"
            user_name = "旧"
            level_index = 1
            weapon = ""
            armor = ""
            main_technique = ""

            def get_techniques_list(self):
                return []

            def get_total_attributes(self, equipped_items, pill_multipliers=None):
                return {
                    "damage": 10,
                    "agility": 5,
                    "speed": 5,
                    "hp": 100,
                    "armor_value": 80,
                    "exp_multiplier": 0.0,
                }

        engine = make_engine()
        fighter = asyncio.run(engine.build_fighter_from_player(LegacyPlayer()))

        assert fighter.block_armor_value == 80  # 回退 = 合并护甲
        assert make_engine()._calc_block_rate(fighter) == pytest.approx(
            0.05 + 80 * 0.001
        )

    def test_pve_enemy_builder_falls_back_to_armor(self):
        """cfg/enemy 构建路径 block_armor_value == armor_value（现网行为不变）。"""
        enemy = types.SimpleNamespace(
            user_id="e1",
            name="妖狼",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=5,
            armor_value=40,
        )
        # Method body only reads `enemy`; safe to call with a bare instance.
        fighter = PVECombatManager._build_enemy_fighter(
            object.__new__(PVECombatManager), enemy
        )

        assert fighter.armor_value == 40
        assert fighter.block_armor_value == 40
        assert make_engine()._calc_block_rate(fighter) == pytest.approx(0.09)


# ------------------------------------------------------------------
# 3. _calc_block_rate and settlement layer (spec scenarios)
# ------------------------------------------------------------------


class TestBlockRateScenarios:
    """Spec: combat-core「格挡率来源分离」三个 Scenario。"""

    def test_scenario_armor_only_does_not_raise_block(self):
        """Scenario 1：仅防具护甲 100 → 格挡率为基础值 5%。"""
        engine = make_engine()
        defender = make_fighter("D", 1000, 10, 5, 10, armor=100, block_armor=0)
        assert engine._calc_block_rate(defender) == pytest.approx(0.05)

    def test_scenario_weapon_armor_feeds_block(self):
        """Scenario 2：天生 5 + 武器 15 → 5% + 20×0.001 = 7%。"""
        engine = make_engine()
        defender = make_fighter("D", 1000, 10, 5, 10, armor=120, block_armor=20)
        assert engine._calc_block_rate(defender) == pytest.approx(0.07)

    def test_block_still_capped_by_block_cap(self):
        """block_cap 上限不变（默认 30%）。"""
        engine = make_engine()
        defender = make_fighter("D", 1000, 10, 5, 10, armor=99999, block_armor=99999)
        assert engine._calc_block_rate(defender) == pytest.approx(0.3)

    def test_reduction_still_uses_merged_armor(self):
        """护甲减伤按合并 armor_value 结算，与格挡来源无关（减伤公式不变）。"""
        engine = make_engine(
            {"combat": {"armor_k_base": 100, "armor_k_level_coeff": 10}}
        )
        # K = 100 + 10*1 = 110; armor 55 → rate = 55/165 = 1/3 < 40% cap
        with_block_src = make_fighter("D", 1000, 10, 5, 10, armor=55, block_armor=55)
        without_block_src = make_fighter("D", 1000, 10, 5, 10, armor=55, block_armor=0)
        assert engine._apply_armor_and_reduction(with_block_src, 300) == 200
        # Same total armor, different block source → identical reduction
        assert engine._apply_armor_and_reduction(without_block_src, 300) == 200

    def test_scenario_block_beyond_reduction_cap(self):
        """Scenario 3：减伤顶到 40% 上限后，格挡仍在结果基础上再减半。"""
        engine = make_engine({"combat": {"damage_reduction_cap": 0.4}})
        # raw = (base_damage 100 + damage 100 * weapon_k 1.0) * 1.0 = 200
        attacker = make_fighter("A", 1000, 100, 5, 10, base_damage=100)
        attacker.crit_rate = 0.0
        # Huge armor → reduction clamped at the 40% cap
        defender_unblocked = make_fighter("D", 10000, 10, 5, 5, armor=100000)
        defender_blocked = make_fighter("D", 10000, 10, 5, 5, armor=100000)

        original_random = _random.random
        original_uniform = _random.uniform
        _random.uniform = lambda a, b: 1.0
        try:
            # dodge fail(0.9), block fail(0.9), crit(0.9 vs rate 0 → fail)
            _random.random = lambda: 0.9
            engine._resolve_attack(
                attacker,
                defender_unblocked,
                dodge_cap=0.0,
                crit_multiplier=1.5,
                log=[],
            )
            # dodge fail(0.9), block hit(0.0 < 0.3), crit fail(0.9)
            seq = iter([0.9, 0.0, 0.9])
            _random.random = lambda: next(seq)
            engine._resolve_attack(
                attacker,
                defender_blocked,
                dodge_cap=0.0,
                crit_multiplier=1.5,
                log=[],
            )
        finally:
            _random.random = original_random
            _random.uniform = original_uniform

        dmg_unblocked = 10000 - defender_unblocked.hp
        dmg_blocked = 10000 - defender_blocked.hp
        # Capped reduction: 200 * 0.6 = 120; block halves raw first: 100 * 0.6 = 60
        assert dmg_unblocked == 120
        assert dmg_blocked == 60
