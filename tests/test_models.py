"""Regression tests for models.py heart-method route_multiplier application."""

from tests.helpers import load_package_module

_models_mod = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models")
Player = _models_mod.Player
Item = _models_mod.Item


def test_heart_method_route_multiplier_one_behaves_like_legacy():
    """Route multiplier 1.0 must produce identical results to pre-route_mult logic."""
    player = Player(
        user_id="u1",
        cultivation_type="灵修",
        damage=100,
        agility=50,
        speed=50,
        hp=200,
        armor_value=30,
    )
    heart = Item(
        item_id="h1",
        name="测试心法",
        item_type="main_technique",
        passive_bonus='{"damage_percent": 0.1, "hp_percent": 0.05, "armor_value": 10}',
        exp_multiplier=0.1,
        route_multiplier='{"灵修": 1.0, "体修": 1.0}',
    )
    total = player.get_total_attributes([heart])
    assert total["damage"] == 110  # 100 * (1 + 0.1 * 1.0)
    assert total["hp"] == 210  # 200 * (1 + 0.05 * 1.0)
    assert total["armor_value"] == 40  # 30 + int(10 * 1.0)
    assert total["exp_multiplier"] == 0.1


def test_heart_method_route_multiplier_amplifies_passive_and_armor():
    """A 1.2x route multiplier must amplify percent passives and armor_value."""
    player = Player(
        user_id="u1",
        cultivation_type="体修",
        damage=100,
        agility=50,
        speed=50,
        hp=200,
        armor_value=30,
    )
    heart = Item(
        item_id="h1",
        name="体修心法",
        item_type="main_technique",
        passive_bonus='{"damage_percent": 0.1, "hp_percent": 0.05, "armor_value": 10}',
        exp_multiplier=0.1,
        route_multiplier='{"灵修": 1.0, "体修": 1.2}',
    )
    total = player.get_total_attributes([heart])
    assert total["damage"] == 112  # 100 * (1 + 0.1 * 1.2)
    assert total["hp"] == 212  # 200 * (1 + 0.05 * 1.2)
    assert total["armor_value"] == 42  # 30 + int(10 * 1.2)
    assert total["exp_multiplier"] == 0.1  # exp_multiplier NOT multiplied


def test_heart_method_route_multiplier_defaults_to_one():
    """Missing or invalid route_multiplier falls back to 1.0 without error."""
    player = Player(
        user_id="u1",
        cultivation_type="灵修",
        damage=100,
        agility=50,
        speed=50,
        hp=200,
        armor_value=30,
    )
    # Explicit empty JSON object
    heart_empty = Item(
        item_id="h1",
        name="空倍率心法",
        item_type="main_technique",
        passive_bonus='{"damage_percent": 0.1}',
        route_multiplier="{}",
    )
    total = player.get_total_attributes([heart_empty])
    assert total["damage"] == 110

    # Invalid JSON string
    heart_bad = Item(
        item_id="h2",
        name="坏倍率心法",
        item_type="main_technique",
        passive_bonus='{"damage_percent": 0.1}',
        route_multiplier="not-json",
    )
    total = player.get_total_attributes([heart_bad])
    assert total["damage"] == 110

    # Missing route_multiplier field entirely (uses default "{}")
    heart_missing = Item(
        item_id="h3",
        name="缺省倍率心法",
        item_type="main_technique",
        passive_bonus='{"damage_percent": 0.1}',
    )
    total = player.get_total_attributes([heart_missing])
    assert total["damage"] == 110
