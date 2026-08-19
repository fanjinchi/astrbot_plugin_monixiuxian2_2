"""Regression tests for ConfigManager dict-of-list loading."""

import pytest

from tests.helpers import load_package_module

_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager
_skill_mod = load_package_module(
    "core/skill_manager.py", "astrbot_plugin_monixiuxian2_2.core.skill_manager"
)
SkillManager = _skill_mod.SkillManager

PLUGIN_ROOT = _config_mod.Path(__file__).resolve().parent.parent


@pytest.fixture
def config_manager():
    return ConfigManager(PLUGIN_ROOT)


def test_config_manager_loads_skills_data(config_manager):
    """skills.json dict-of-list must be flattened into name->definition."""
    assert len(config_manager.skills_data) > 0
    assert "基础吐纳" in config_manager.skills_data
    assert config_manager.skills_data["基础吐纳"].get("_group") == "通用功法池"


def test_config_manager_loads_heart_methods_data(config_manager):
    """heart_methods.json dict-of-list must be flattened into name->definition."""
    assert len(config_manager.heart_methods_data) > 0
    assert "长春功" in config_manager.heart_methods_data


def test_config_manager_loads_weapon_coefficient_k(config_manager):
    """weapons.json must expose weapon_coefficient_k for the combat engine."""
    assert "青铜剑" in config_manager.weapons_data
    assert config_manager.weapons_data["青铜剑"].get("weapon_coefficient_k") is not None


@pytest.mark.asyncio
async def test_skill_manager_works_with_flattened_skills(config_manager):
    """SkillManager must not mix universal skills into the main pool."""

    class FakeDbExt:
        async def is_skill_learned(self, user_id, skill_id):
            return False

        async def learn_or_star_up(
            self, user_id, skill_id, source="", max_star=3, max_star_exp_compensation=0
        ):
            return True, 1

    class FakeDb:
        def __init__(self):
            self.ext = FakeDbExt()

    mgr = SkillManager(config_manager, FakeDb())

    class FakePlayer:
        user_id = "test"
        main_technique = ""
        study_target = ""

        def get_techniques_list(self):
            return []

    pool = await mgr._build_comprehension_pool(FakePlayer(), "breakthrough_success")
    assert not any(entry["source"] == "universal" for entry in pool)

    # Universal fallback is provided separately for breakthrough without heart method.
    import random as _random

    original_random = _random.random
    try:
        _random.random = lambda: 0.01  # below 3% fallback rate
        result = await mgr.roll_universal_pool_breakthrough(FakePlayer(), success=True)
        if result is not None:
            assert "id" in result
    finally:
        _random.random = original_random


class TestLevelConfigCentralApi:
    """Tests for the new level progression central API."""

    def test_level_data_shim_has_no_base_attributes(self, config_manager):
        """The synthesized per-level list must not contain legacy base_* fields."""
        assert len(config_manager.level_data) == 99
        assert all("base_damage" not in entry for entry in config_manager.level_data)
        assert all("base_hp" not in entry for entry in config_manager.level_data)

    def test_get_level_name_normal_and_initial(self, config_manager):
        """Normal levels are named {realm}{stage}阶; every 10th level is {next realm}初期."""
        assert config_manager.get_level_name(1) == "练气一阶"
        assert config_manager.get_level_name(9) == "练气九阶"
        assert config_manager.get_level_name(10) == "筑基初期"
        assert config_manager.get_level_name(15) == "筑基五阶"
        assert config_manager.get_level_name(40) == "化神初期"
        assert config_manager.get_level_name(99) == "地仙九阶"

    def test_get_level_name_out_of_bounds(self, config_manager):
        """Out-of-range levels fall back to a numeric label instead of crashing."""
        assert config_manager.get_level_name(0) == "境界0"
        assert config_manager.get_level_name(100) == "境界100"
        assert config_manager.get_level_name(200) == "境界200"

    def test_get_level_name_body_route(self, config_manager):
        """体修 names are resolved from the independent body realm list."""
        assert config_manager.get_level_name(1, "体修") == "锻体一阶"
        assert config_manager.get_level_name(10, "体修") == "铜皮初期"
        assert config_manager.get_level_name(99, "体修") == "地仙体魄九阶"

    def test_exp_curve_pivots_are_continuous(self, config_manager):
        """The three-segment curve must match exactly at the segment boundaries."""
        at_10 = config_manager.get_exp_needed(10)
        at_50 = config_manager.get_exp_needed(50)
        # Linear segment at 10 equals the early-curve segment at 10.
        assert at_10 == int(1800 * (10**1.5))
        assert config_manager.get_exp_needed(11) == int(at_10 * 1.1)
        # Late segment at 50 equals the linear segment at 50.
        assert at_50 == int(at_10 * 5)
        assert config_manager.get_exp_needed(51) == int(at_50 * ((51 / 50) ** 1.7))

    def test_get_success_rate_by_target_realm(self, config_manager):
        """Success rates are looked up by the target level's realm."""
        assert config_manager.get_success_rate(1) == 1.0
        assert config_manager.get_success_rate(10) == 0.8
        assert config_manager.get_success_rate(11) == 0.8
        assert config_manager.get_success_rate(70) == 0.4
        assert config_manager.get_success_rate(99) == 0.4

    def test_get_max_level(self, config_manager):
        """Max level is derived from the realm list length."""
        assert config_manager.get_max_level() == 99
        assert config_manager.get_max_level("体修") == 99

    def test_get_exp_needed_body_route(self, config_manager):
        """Body route uses its own config but the same formula parameters."""
        spirit = config_manager.get_exp_needed(1, "灵修")
        body = config_manager.get_exp_needed(1, "体修")
        assert body == spirit
        assert config_manager.get_exp_needed(10, "体修") == int(1800 * (10**1.5))

    def test_get_success_rate_level_zero(self, config_manager):
        """An invalid level below 1 returns a safe default rate."""
        assert config_manager.get_success_rate(0) == 0.0
        assert config_manager.get_success_rate(-5) == 0.0

    def test_get_level_index_by_name(self, config_manager):
        """Reverse lookup resolves display names back to 1-based indices."""
        assert config_manager.get_level_index_by_name("练气一阶") == 1
        assert config_manager.get_level_index_by_name("筑基初期") == 10
        assert config_manager.get_level_index_by_name("地仙九阶") == 99
        assert config_manager.get_level_index_by_name("不存在") is None
        assert config_manager.get_level_index_by_name("锻体一阶", "体修") == 1
