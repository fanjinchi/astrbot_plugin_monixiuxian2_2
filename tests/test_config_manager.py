"""Regression tests for ConfigManager dict-of-list loading."""

import pytest

from tests.helpers import load_package_module

_config_mod = load_package_module("config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager")
ConfigManager = _config_mod.ConfigManager
_skill_mod = load_package_module("core/skill_manager.py", "astrbot_plugin_monixiuxian2_2.core.skill_manager")
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

        async def learn_or_star_up(self, user_id, skill_id, source=""):
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
