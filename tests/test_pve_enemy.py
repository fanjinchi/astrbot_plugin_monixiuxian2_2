"""
Tests for EnemyManager - enemy spawning, group selection, stat calculation, name composition.
"""

from unittest.mock import mock_open, patch

import pytest

from tests.helpers import load_module

_enemy_mgr_mod = load_module("enemy_manager", "managers/enemy_manager.py")
Enemy = _enemy_mgr_mod.Enemy
EnemyManager = _enemy_mgr_mod.EnemyManager

# ──────────────────────────────────────────────────────────────────────
# Sample config mirroring the real config/enemies.json structure
# ──────────────────────────────────────────────────────────────────────
SAMPLE_ENEMIES_CONFIG = {
    "enemy_groups": [
        {
            "key": "low",
            "name": "低阶妖域",
            "level_range": [0, 12],
            "templates": [
                {
                    "key": "wolf",
                    "name": "疾风狼",
                    "elite_prefixes": ["历战的", "强壮的", "变异的", "狂暴的"],
                    "boss_names": ["苍月狼王", "疾风狼王", "啸月狼尊"],
                    "hp_mult": 0.6,
                    "atk_mult": 0.85,
                    "defense": 3,
                    "crit_rate": 10,
                },
                {
                    "key": "snake",
                    "name": "赤炼蛇",
                    "elite_prefixes": ["历战的", "强壮的", "变异的", "狂暴的"],
                    "boss_names": ["赤炼蛇王", "噬心蛇尊", "九节毒龙"],
                    "hp_mult": 0.65,
                    "atk_mult": 0.8,
                    "defense": 5,
                    "crit_rate": 8,
                },
            ],
            "elite": {
                "hp_mult": 0.9,
                "atk_mult": 1.0,
                "defense_bonus": 5,
                "crit_rate_bonus": 5,
            },
            "boss": {
                "hp_mult": 1.2,
                "atk_mult": 1.2,
                "defense_bonus": 15,
                "crit_rate_bonus": 10,
            },
            "drop_tier": "low",
        },
        {
            "key": "mid",
            "name": "中阶妖域",
            "level_range": [13, 18],
            "templates": [
                {
                    "key": "tiger",
                    "name": "裂地虎",
                    "elite_prefixes": ["强大的", "铁甲的", "血瞳的", "吞噬的"],
                    "boss_names": ["裂地虎尊", "血瞳虎王", "噬天虎妖"],
                    "hp_mult": 0.7,
                    "atk_mult": 1.0,
                    "defense": 10,
                    "crit_rate": 15,
                }
            ],
            "elite": {
                "hp_mult": 1.1,
                "atk_mult": 1.1,
                "defense_bonus": 8,
                "crit_rate_bonus": 5,
            },
            "boss": {
                "hp_mult": 1.2,
                "atk_mult": 1.4,
                "defense_bonus": 20,
                "crit_rate_bonus": 8,
            },
            "drop_tier": "mid",
        },
        {
            "key": "high",
            "name": "高阶妖域",
            "level_range": [19, 27],
            "templates": [
                {
                    "key": "jiao",
                    "name": "玄水蛟",
                    "elite_prefixes": ["天灾级的", "上古的", "深渊的", "混沌的"],
                    "boss_names": ["覆海蛟魔", "深渊龙君", "玄冥蛟皇"],
                    "hp_mult": 0.8,
                    "atk_mult": 1.1,
                    "defense": 20,
                    "crit_rate": 15,
                }
            ],
            "elite": {
                "hp_mult": 1.1,
                "atk_mult": 1.3,
                "defense_bonus": 12,
                "crit_rate_bonus": 5,
            },
            "boss": {
                "hp_mult": 1.3,
                "atk_mult": 1.6,
                "defense_bonus": 30,
                "crit_rate_bonus": 5,
            },
            "drop_tier": "high",
        },
        {
            "key": "top",
            "name": "顶级妖域",
            "level_range": [28, 31],
            "templates": [
                {
                    "key": "dragon",
                    "name": "苍龙",
                    "elite_prefixes": ["天灾级的", "太古的", "洪荒的", "混沌的"],
                    "boss_names": ["五爪金龙", "太古苍龙", "混沌龙祖"],
                    "hp_mult": 0.9,
                    "atk_mult": 1.2,
                    "defense": 35,
                    "crit_rate": 20,
                }
            ],
            "elite": {
                "hp_mult": 1.1,
                "atk_mult": 1.5,
                "defense_bonus": 15,
                "crit_rate_bonus": 5,
            },
            "boss": {
                "hp_mult": 1.3,
                "atk_mult": 1.8,
                "defense_bonus": 40,
                "crit_rate_bonus": 5,
            },
            "drop_tier": "top",
        },
    ],
    "difficulty_coefficients": {
        "normal": 0.85,
        "elite": 1.0,
        "boss": 1.2,
    },
    "naming": {
        "normal": "{name}",
        "elite": "{prefix}{name}",
        "boss": "{boss_name}",
    },
}


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def enemy_manager():
    """Create an EnemyManager with mocked file loading."""
    with patch("builtins.open", mock_open(read_data="{}")):
        with patch("enemy_manager.json.load") as mock_load:
            mock_load.return_value = SAMPLE_ENEMIES_CONFIG
            mgr = EnemyManager("dummy.json")
            return mgr


# ──────────────────────────────────────────────────────────────────────
# Group selection tests
# ──────────────────────────────────────────────────────────────────────


class TestGroupSelection:
    """_get_group_by_level boundary conditions."""

    @pytest.mark.parametrize(
        "level,expected_key",
        [
            (0, "low"),
            (12, "low"),
            (13, "mid"),
            (18, "mid"),
            (19, "high"),
            (27, "high"),
            (28, "top"),
            (31, "top"),
        ],
    )
    def test_boundaries(self, enemy_manager, level, expected_key):
        """Each level boundary maps to the correct enemy group."""
        group = enemy_manager._get_group_by_level(level)
        assert group["key"] == expected_key, (
            f"Expected group '{expected_key}' for level {level}, got '{group['key']}'"
        )

    @pytest.mark.parametrize("level", [32, 50, 100, 999])
    def test_above_max_uses_last_group(self, enemy_manager, level):
        """Levels above the highest range (31) fall back to the last group."""
        group = enemy_manager._get_group_by_level(level)
        assert group["key"] == "top", (
            f"Expected fallback to 'top' for level {level}, got '{group['key']}'"
        )

    def test_empty_groups_returns_empty_dict(self):
        """When no groups exist, returns empty dict."""
        config = SAMPLE_ENEMIES_CONFIG.copy()
        config["enemy_groups"] = []
        with patch("builtins.open", mock_open(read_data="{}")):
            with patch("enemy_manager.json.load") as mock_load:
                mock_load.return_value = config
                mgr = EnemyManager("dummy.json")
                group = mgr._get_group_by_level(5)
                assert group == {}


# ──────────────────────────────────────────────────────────────────────
# Stat calculation tests
# ──────────────────────────────────────────────────────────────────────


class TestStatCalculation:
    """Verify spawn_enemy stat formulas."""

    def test_normal_stats(self, enemy_manager):
        """Normal enemy: base_exp = player_exp * 0.85;
        HP = (base_exp//2)*hp_mult; ATK = (base_exp//10)*atk_mult."""
        with patch("random.choice") as mock_choice:
            mock_choice.return_value = SAMPLE_ENEMIES_CONFIG["enemy_groups"][0][
                "templates"
            ][0]  # "wolf" template

            enemy = enemy_manager.spawn_enemy(
                player_level=10, player_exp=10000, category="normal"
            )

            # difficulty_coefficients["normal"] = 0.85
            base_exp = int(10000 * 0.85)
            assert enemy.exp == base_exp

            # wolf: hp_mult=0.6, atk_mult=0.85, defense=3, crit_rate=10
            expected_hp = int((base_exp // 2) * 0.6)
            expected_atk = int((base_exp // 10) * 0.85)
            assert enemy.hp == expected_hp
            assert enemy.max_hp == expected_hp
            assert enemy.atk == expected_atk
            assert enemy.mp == base_exp
            assert enemy.max_mp == base_exp
            assert enemy.defense == 3
            assert enemy.crit_rate == 10

    def test_elite_stats(self, enemy_manager):
        """Elite enemy applies elite multiplier bonuses on top of base template."""
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = [
                SAMPLE_ENEMIES_CONFIG["enemy_groups"][0]["templates"][0],
                "历战的",
            ]

            enemy = enemy_manager.spawn_enemy(
                player_level=10, player_exp=10000, category="elite"
            )

            # difficulty_coefficients["elite"] = 1.0
            base_exp = int(10000 * 1.0)
            assert enemy.exp == base_exp

            # wolf: hp_mult=0.6, atk_mult=0.85
            # elite: hp_mult *= 0.9, atk_mult *= 1.0, defense_bonus=5, crit_rate_bonus=5
            expected_hp = int((base_exp // 2) * 0.6 * 0.9)
            expected_atk = int((base_exp // 10) * 0.85 * 1.0)
            assert enemy.hp == expected_hp
            assert enemy.atk == expected_atk
            assert enemy.defense == 3 + 5
            assert enemy.crit_rate == 10 + 5

    def test_boss_stats(self, enemy_manager):
        """Boss enemy applies boss multiplier bonuses on top of base template."""
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = [
                SAMPLE_ENEMIES_CONFIG["enemy_groups"][0]["templates"][0],
                "苍月狼王",
            ]

            enemy = enemy_manager.spawn_enemy(
                player_level=10, player_exp=10000, category="boss"
            )

            # difficulty_coefficients["boss"] = 1.2
            base_exp = int(10000 * 1.2)
            assert enemy.exp == base_exp

            # wolf: hp_mult=0.6, atk_mult=0.85
            # boss: hp_mult *= 1.2, atk_mult *= 1.2, defense_bonus=15, crit_rate_bonus=10
            expected_hp = int((base_exp // 2) * 0.6 * 1.2)
            expected_atk = int((base_exp // 10) * 0.85 * 1.2)
            assert enemy.hp == expected_hp
            assert enemy.atk == expected_atk
            assert enemy.defense == 3 + 15
            assert enemy.crit_rate == 10 + 10

    def test_different_levels_and_exp(self, enemy_manager):
        """Stat calculation works across level groups."""
        cases = [
            (1, 500, "low"),
            (15, 50_000, "mid"),
            (25, 200_000, "high"),
            (30, 500_000, "top"),
        ]
        for level, exp, _group_key in cases:
            with patch("random.choice") as mock_choice:
                mock_choice.side_effect = lambda lst: lst[0]
                enemy = enemy_manager.spawn_enemy(
                    player_level=level, player_exp=exp, category="normal"
                )
                assert enemy.exp > 0
                assert enemy.hp > 0
                assert enemy.atk > 0
                assert enemy.mp > 0
                assert enemy.user_id.startswith("enemy_")

    def test_minimal_exp(self, enemy_manager):
        """With very low exp, enemy still has valid stats (at least 0 or 1)."""
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = lambda lst: lst[0]
            enemy = enemy_manager.spawn_enemy(
                player_level=1, player_exp=1, category="normal"
            )
            # base_exp = int(1 * 0.85) = 0
            # hp = int((0 // 2) * mult) = 0
            # atk = int((0 // 10) * mult) = 0
            assert enemy.exp == 0
            assert enemy.hp == 0
            assert enemy.atk == 0


# ──────────────────────────────────────────────────────────────────────
# Name composition tests
# ──────────────────────────────────────────────────────────────────────


class TestNameComposition:
    """Enemy naming follows category-specific rules."""

    def test_normal_name(self, enemy_manager):
        """Normal enemy uses template name directly via {name} format."""
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = lambda lst: lst[0]
            enemy = enemy_manager.spawn_enemy(10, 10000, "normal")
            assert enemy.name == "疾风狼"

    def test_elite_name(self, enemy_manager):
        """Elite enemy = prefix + name via {prefix}{name} format."""
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = [
                SAMPLE_ENEMIES_CONFIG["enemy_groups"][0]["templates"][0],
                "强壮的",
            ]
            enemy = enemy_manager.spawn_enemy(10, 10000, "elite")
            assert enemy.name == "强壮的疾风狼"

    def test_boss_name(self, enemy_manager):
        """Boss enemy uses boss_name from template via {boss_name} format."""
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = [
                SAMPLE_ENEMIES_CONFIG["enemy_groups"][0]["templates"][0],
                "啸月狼尊",
            ]
            enemy = enemy_manager.spawn_enemy(10, 10000, "boss")
            assert enemy.name == "啸月狼尊"

    def test_invalid_category_falls_to_template_name(self, enemy_manager):
        """Invalid category returns the template name as-is."""
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = lambda lst: lst[0]
            enemy = enemy_manager.spawn_enemy(
                10, 10000, category="invalid_category"
            )
            assert enemy.name == "疾风狼"
            assert enemy.exp == int(10000 * 0.85)


# ──────────────────────────────────────────────────────────────────────
# Error handling tests
# ──────────────────────────────────────────────────────────────────────


class TestErrorHandling:
    """Edge cases and error conditions."""

    def test_no_templates_raises(self, enemy_manager):
        """ValueError when group has no templates."""
        original_groups = enemy_manager.enemy_groups
        enemy_manager.enemy_groups = [
            {
                "key": "empty",
                "level_range": [0, 100],
                "templates": [],
                "elite": {},
                "boss": {},
                "drop_tier": "low",
            }
        ]
        with pytest.raises(ValueError, match="未找到敌人模板配置"):
            enemy_manager.spawn_enemy(
                player_level=5, player_exp=1000, category="normal"
            )
        enemy_manager.enemy_groups = original_groups

    def test_missing_difficulty_coefficient(self, enemy_manager):
        """Unknown category uses default coefficient of 0.85."""
        enemy_manager.difficulty_coefficients = {}
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = lambda lst: lst[0]
            enemy = enemy_manager.spawn_enemy(
                player_level=10, player_exp=10000, category="normal"
            )
            assert enemy.exp == int(10000 * 0.85)

    def test_missing_naming_config(self, enemy_manager):
        """Missing naming config uses default format strings."""
        enemy_manager.naming = {}
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = lambda lst: lst[0]
            enemy = enemy_manager.spawn_enemy(
                player_level=10, player_exp=10000, category="normal"
            )
            assert enemy.name == "疾风狼"

    def test_template_missing_name_field(self, enemy_manager):
        """Template without 'name' uses '未知妖兽'."""
        with patch("random.choice") as mock_choice:
            mock_choice.side_effect = lambda lst: {
                "key": "mystery",
                "hp_mult": 0.5,
                "atk_mult": 0.5,
            }
            enemy = enemy_manager.spawn_enemy(
                player_level=10, player_exp=10000, category="normal"
            )
            assert enemy.name == "未知妖兽"
            assert enemy.user_id == "enemy_mystery"


# ──────────────────────────────────────────────────────────────────────
# Drop items (placeholder)
# ──────────────────────────────────────────────────────────────────────


class TestDropItems:
    """get_drop_items is a placeholder returning [].

    Phase 2 of PVE combat will implement actual loot tables.
    """

    def test_returns_empty_list(self, enemy_manager):
        for tier in ["low", "mid", "high", "top"]:
            assert enemy_manager.get_drop_items(tier) == []


# ──────────────────────────────────────────────────────────────────────
# Enemy dataclass
# ──────────────────────────────────────────────────────────────────────


class TestEnemyDataclass:
    """Enemy dataclass field defaults."""

    def test_required_only(self):
        enemy = Enemy(
            user_id="enemy_test",
            name="Test",
            hp=100,
            max_hp=100,
            mp=50,
            max_mp=50,
            atk=20,
        )
        assert enemy.defense == 0
        assert enemy.crit_rate == 0
        assert enemy.exp == 0

    def test_all_fields(self):
        enemy = Enemy(
            user_id="enemy_test",
            name="Test",
            hp=100,
            max_hp=100,
            mp=50,
            max_mp=50,
            atk=20,
            defense=10,
            crit_rate=15,
            exp=5000,
        )
        assert enemy.defense == 10
        assert enemy.crit_rate == 15
        assert enemy.exp == 5000
