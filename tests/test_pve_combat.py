"""
Tests for PVECombatManager - encounter probability, enemy category distribution,
reward calculation, equipment defense, and the full trigger_pve_combat flow.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import load_module

# Load modules via importlib.util, bypassing managers/__init__.py
_pve_mod = load_module("pve_combat_manager", "managers/pve_combat_manager.py")
PVECombatManager = _pve_mod.PVECombatManager
calculate_equipment_defense = _pve_mod.calculate_equipment_defense
calculate_equipment_atk_bonus = _pve_mod.calculate_equipment_atk_bonus
RIFT_LEVEL_DIFFICULTY_MAP = _pve_mod.RIFT_LEVEL_DIFFICULTY_MAP

# Load supporting types (they don't trigger the problematic __init__.py chain)
_cm_mod = load_module("combat_manager", "managers/combat_manager.py")
CombatManager = _cm_mod.CombatManager
CombatStats = _cm_mod.CombatStats

_enemy_mod = load_module("enemy_manager", "managers/enemy_manager.py")
Enemy = _enemy_mod.Enemy

_model_mod = load_module("models", "models.py")
Player = _model_mod.Player
_mde_mod = load_module("models_extended", "models_extended.py")
UserStatus = _mde_mod.UserStatus

# Managers that depend on DataBase/StorageRingManager (loaded with fallback imports)
_adv_mod = load_module("adventure_manager", "managers/adventure_manager.py")
AdventureManager = _adv_mod.AdventureManager

_rift_mod = load_module("rift_manager", "managers/rift_manager.py")
RiftManager = _rift_mod.RiftManager

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_combat_manager():
    """CombatManager mock with basic stat-calc stubs."""
    mgr = MagicMock(spec=CombatManager)
    mgr.calculate_hp_mp.return_value = (500, 1000)
    mgr.calculate_atk.return_value = 100
    return mgr


@pytest.fixture
def mock_enemy_manager():
    """EnemyManager mock returning a standard enemy."""
    mgr = MagicMock()
    enemy = Enemy(
        user_id="enemy_wolf",
        name="疾风狼",
        hp=200,
        max_hp=200,
        mp=400,
        max_mp=400,
        atk=30,
        defense=5,
        crit_rate=10,
        exp=8500,
    )
    mgr.spawn_enemy.return_value = enemy
    return mgr


@pytest.fixture
def mock_player():
    """Standard Player mock."""
    player = MagicMock(spec=Player)
    player.user_id = "player_001"
    player.user_name = "测试道友"
    player.level_index = 10
    player.experience = 10000
    player.atkpractice = 5
    player.hp = 100
    player.mp = 200
    player.weapon = ""
    player.armor = ""
    return player


@pytest.fixture
def mock_config_manager():
    """ConfigManager mock with item/weapon data."""
    mgr = MagicMock()
    mgr.weapons_data = {}
    mgr.items_data = {}
    return mgr


@pytest.fixture
def pve_manager(mock_combat_manager, mock_enemy_manager):
    """PVECombatManager without config_manager."""
    return PVECombatManager(mock_combat_manager, mock_enemy_manager)


@pytest.fixture
def pve_manager_with_config(
    mock_combat_manager, mock_enemy_manager, mock_config_manager
):
    """PVECombatManager with config_manager."""
    return PVECombatManager(
        mock_combat_manager, mock_enemy_manager, mock_config_manager
    )


# ──────────────────────────────────────────────────────────────────────
# Encounter probability (statistical)
# ──────────────────────────────────────────────────────────────────────


class TestEncounterProbability:
    """_should_trigger_combat statistical verification (±5% tolerance, 1000 trials)."""

    TRIALS = 1000
    TOLERANCE = 0.05

    @pytest.mark.parametrize(
        "scene,difficulty,expected",
        [
            ("adventure", "low", 0.10),
            ("adventure", "mid", 0.25),
            ("adventure", "high", 0.45),
            ("adventure", "extreme", 0.55),
            ("rift", "low", 0.30),
            ("rift", "mid", 0.50),
            ("rift", "high", 0.70),
            ("rift", "extreme", 0.85),
        ],
    )
    def test_encounter_rate(self, pve_manager, scene, difficulty, expected):
        """Observed encounter rate is within ±5% of the configured rate."""
        hits = sum(
            pve_manager._should_trigger_combat(scene, difficulty)
            for _ in range(self.TRIALS)
        )
        observed = hits / self.TRIALS
        assert abs(observed - expected) <= self.TOLERANCE, (
            f"[{scene}/{difficulty}] expected {expected:.2f}, "
            f"observed {observed:.2f} ({hits}/{self.TRIALS})"
        )

    def test_unknown_scene_returns_false(self, pve_manager):
        """Unknown scene/difficulty should never trigger combat (rate=0.0)."""
        assert not pve_manager._should_trigger_combat("unknown", "low")
        assert not pve_manager._should_trigger_combat("adventure", "unknown")


# ──────────────────────────────────────────────────────────────────────
# Enemy category distribution (statistical)
# ──────────────────────────────────────────────────────────────────────


class TestEnemyCategoryDistribution:
    """_select_enemy_category statistical verification (±5% tolerance, 1000 trials)."""

    TRIALS = 1000
    TOLERANCE = 0.05

    @pytest.mark.parametrize(
        "scene,difficulty,expected",
        [
            ("adventure", "mid", (0.70, 0.25, 0.05)),
            ("adventure", "high", (0.40, 0.40, 0.20)),
            ("adventure", "extreme", (0.30, 0.35, 0.35)),
            ("rift", "low", (0.80, 0.20, 0.00)),
            ("rift", "mid", (0.50, 0.35, 0.15)),
            ("rift", "high", (0.30, 0.40, 0.30)),
            ("rift", "extreme", (0.20, 0.40, 0.40)),
        ],
    )
    def test_category_distribution(self, pve_manager, scene, difficulty, expected):
        """Observed category proportions are within ±5% of configured rates."""
        counts = {"normal": 0, "elite": 0, "boss": 0}
        for _ in range(self.TRIALS):
            cat = pve_manager._select_enemy_category(scene, difficulty)
            counts[cat] += 1

        exp_norm, exp_elite, exp_boss = expected
        obs_norm = counts["normal"] / self.TRIALS
        obs_elite = counts["elite"] / self.TRIALS
        obs_boss = counts["boss"] / self.TRIALS

        assert abs(obs_norm - exp_norm) <= self.TOLERANCE, (
            f"[{scene}/{difficulty}/normal] expected {exp_norm:.2f}, "
            f"observed {obs_norm:.2f} ({counts['normal']}/{self.TRIALS})"
        )
        assert abs(obs_elite - exp_elite) <= self.TOLERANCE, (
            f"[{scene}/{difficulty}/elite] expected {exp_elite:.2f}, "
            f"observed {obs_elite:.2f} ({counts['elite']}/{self.TRIALS})"
        )
        assert abs(obs_boss - exp_boss) <= self.TOLERANCE, (
            f"[{scene}/{difficulty}/boss] expected {exp_boss:.2f}, "
            f"observed {obs_boss:.2f} ({counts['boss']}/{self.TRIALS})"
        )

    def test_adventure_low_always_normal(self, pve_manager):
        """Adventure low difficulty always returns 'normal'."""
        for _ in range(100):
            assert pve_manager._select_enemy_category("adventure", "low") == "normal"

    def test_unknown_defaults_to_normal(self, pve_manager):
        """Unknown scene/difficulty returns 'normal'."""
        assert pve_manager._select_enemy_category("unknown", "mid") == "normal"


# ──────────────────────────────────────────────────────────────────────
# Rift difficulty mapping
# ──────────────────────────────────────────────────────────────────────


class TestRiftDifficultyMap:
    """RIFT_LEVEL_DIFFICULTY_MAP covers levels 1-5 and falls back to low."""

    def test_levels_1_to_3_unchanged(self):
        """Existing rift levels keep their original difficulties."""
        assert RIFT_LEVEL_DIFFICULTY_MAP[1] == "low"
        assert RIFT_LEVEL_DIFFICULTY_MAP[2] == "mid"
        assert RIFT_LEVEL_DIFFICULTY_MAP[3] == "high"

    def test_levels_4_and_5_are_extreme(self):
        """Rift levels 4 and 5 map to extreme difficulty."""
        assert RIFT_LEVEL_DIFFICULTY_MAP[4] == "extreme"
        assert RIFT_LEVEL_DIFFICULTY_MAP[5] == "extreme"

    def test_unknown_level_defaults_to_low(self):
        """Unmapped levels fall back to 'low' when using .get()."""
        assert RIFT_LEVEL_DIFFICULTY_MAP.get(99, "low") == "low"


# ──────────────────────────────────────────────────────────────────────
# Reward calculation
# ──────────────────────────────────────────────────────────────────────


class TestRewardCalculation:
    """_calculate_rewards for victory / loss / draw outcomes."""

    def make_enemy(self, exp=8500):
        return Enemy(
            user_id="enemy_wolf",
            name="狼",
            hp=100,
            max_hp=100,
            mp=50,
            max_mp=50,
            atk=20,
            defense=5,
            crit_rate=10,
            exp=exp,
        )

    def test_victory(self, pve_manager):
        """Victory: exp × 1.2 + bonus_exp (= enemy.exp)."""
        result = {"winner": "player_001"}
        base = {"exp": 100, "gold": 50}
        rewards = pve_manager._calculate_rewards(result, base, self.make_enemy())
        assert rewards["exp"] == int(100 * 1.2)
        assert rewards["bonus_exp"] == 8500
        assert rewards["gold"] == 50
        assert not rewards["hp_penalty"]

    def test_loss(self, pve_manager):
        """Loss: exp × 0.3, gold = 0, hp_penalty = True."""
        result = {"winner": "enemy_wolf"}
        base = {"exp": 100, "gold": 50}
        rewards = pve_manager._calculate_rewards(result, base, self.make_enemy())
        assert rewards["exp"] == int(100 * 0.3)
        assert rewards["gold"] == 0
        assert rewards["hp_penalty"]
        assert rewards["bonus_exp"] == 0

    def test_loss_with_consolation_reward(self, pve_manager):
        """Loss with result['reward'] adds the consolation value to gold."""
        result = {"winner": "enemy_wolf", "reward": 25}
        base = {"exp": 100, "gold": 50}
        rewards = pve_manager._calculate_rewards(result, base, self.make_enemy())
        assert rewards["exp"] == int(100 * 0.3)
        assert rewards["gold"] == 25
        assert rewards["hp_penalty"]
        assert rewards["bonus_exp"] == 0

    def test_victory_ignores_result_reward(self, pve_manager):
        """Victory does not apply result['reward']; base gold is kept."""
        result = {"winner": "player_001", "reward": 999}
        base = {"exp": 100, "gold": 50}
        rewards = pve_manager._calculate_rewards(result, base, self.make_enemy())
        assert rewards["exp"] == int(100 * 1.2)
        assert rewards["gold"] == 50
        assert not rewards["hp_penalty"]
        assert rewards["bonus_exp"] == 8500

    def test_draw(self, pve_manager):
        """Draw: no changes to rewards."""
        result = {"winner": "平局"}
        base = {"exp": 100, "gold": 50}
        rewards = pve_manager._calculate_rewards(result, base, self.make_enemy())
        assert rewards["exp"] == 100
        assert rewards["gold"] == 50
        assert rewards["bonus_exp"] == 0
        assert not rewards["hp_penalty"]

    def test_zero_base_rewards_on_loss(self, pve_manager):
        """Loss with zero base rewards still produces correct structure."""
        result = {"winner": "enemy_wolf"}
        base = {"exp": 0, "gold": 0}
        rewards = pve_manager._calculate_rewards(result, base, self.make_enemy())
        assert rewards["exp"] == 0
        assert rewards["gold"] == 0
        assert rewards["hp_penalty"]

    def test_victory_large_numbers(self, pve_manager):
        """Large exp values are handled without overflow."""
        result = {"winner": "player_001"}
        base = {"exp": 10_000_000, "gold": 5_000_000}
        rewards = pve_manager._calculate_rewards(
            result, base, self.make_enemy(exp=999_999)
        )
        assert rewards["exp"] == int(10_000_000 * 1.2)
        assert rewards["bonus_exp"] == 999_999
        assert rewards["gold"] == 5_000_000


# ──────────────────────────────────────────────────────────────────────
# Equipment defense helper
# ──────────────────────────────────────────────────────────────────────


class TestCalculateEquipmentDefense:
    """calculate_equipment_defense standalone function."""

    def test_no_config_manager(self, mock_player):
        """Returns 0 when config_manager is None."""
        assert calculate_equipment_defense(mock_player, None) == 0

    def test_no_equipment(self, mock_player, mock_config_manager):
        """Returns 0 when player has no weapon/armor."""
        mock_player.weapon = ""
        mock_player.armor = ""
        assert calculate_equipment_defense(mock_player, mock_config_manager) == 0

    def test_weapon_defense_not_counted(self, mock_player, mock_config_manager):
        """Weapon physical/magic defense is not counted (aligned with _prepare_combat_stats)."""
        mock_player.weapon = "玄铁剑"
        mock_player.armor = ""
        mock_config_manager.weapons_data = {
            "玄铁剑": {"physical_defense": 15, "magic_defense": 5}
        }
        assert calculate_equipment_defense(mock_player, mock_config_manager) == 0

    def test_armor_defense(self, mock_player, mock_config_manager):
        """Armor with defenses contributes to total."""
        mock_player.weapon = ""
        mock_player.armor = "金蚕丝甲"
        mock_config_manager.items_data = {
            "金蚕丝甲": {"physical_defense": 30, "magic_defense": 10}
        }
        assert calculate_equipment_defense(mock_player, mock_config_manager) == 40

    def test_weapon_and_armor(self, mock_player, mock_config_manager):
        """Only armor defenses are summed; weapon defenses are ignored."""
        mock_player.weapon = "玄铁剑"
        mock_player.armor = "金蚕丝甲"
        mock_config_manager.weapons_data = {
            "玄铁剑": {"physical_defense": 15, "magic_defense": 5}
        }
        mock_config_manager.items_data = {
            "金蚕丝甲": {"physical_defense": 30, "magic_defense": 10}
        }
        assert calculate_equipment_defense(mock_player, mock_config_manager) == 40

    def test_missing_weapon_in_data(self, mock_player, mock_config_manager):
        """When weapon name not in data, it is skipped without error."""
        mock_player.weapon = "不存在之剑"
        mock_player.armor = ""
        assert calculate_equipment_defense(mock_player, mock_config_manager) == 0

    def test_defense_fields_missing(self, mock_player, mock_config_manager):
        """Weapon data without defense keys returns 0 for that item."""
        mock_player.weapon = "木剑"
        mock_player.armor = ""
        mock_config_manager.weapons_data = {"木剑": {"atk": 5}}
        assert calculate_equipment_defense(mock_player, mock_config_manager) == 0

    def test_config_manager_none_with_equipment(self, mock_player):
        """Returns 0 when config_manager is None even if player has equipment."""
        mock_player.weapon = "玄铁剑"
        mock_player.armor = "金蚕丝甲"
        assert calculate_equipment_defense(mock_player, None) == 0


# ──────────────────────────────────────────────────────────────────────
# Equipment attack bonus helper
# ──────────────────────────────────────────────────────────────────────


class TestCalculateEquipmentAtkBonus:
    """calculate_equipment_atk_bonus standalone function."""

    def test_no_config_manager(self, mock_player):
        """Returns 0 when config_manager is None."""
        assert calculate_equipment_atk_bonus(mock_player, None) == 0

    def test_no_weapon(self, mock_player, mock_config_manager):
        """Returns 0 when player has no weapon."""
        mock_player.weapon = ""
        assert calculate_equipment_atk_bonus(mock_player, mock_config_manager) == 0

    def test_weapon_atk_bonus(self, mock_player, mock_config_manager):
        """Weapon atk contributes to attack bonus."""
        mock_player.weapon = "玄铁剑"
        mock_config_manager.weapons_data = {"玄铁剑": {"atk": 25}}
        assert calculate_equipment_atk_bonus(mock_player, mock_config_manager) == 25

    def test_weapon_physical_damage_bonus(self, mock_player, mock_config_manager):
        """Weapon physical_damage contributes to attack bonus."""
        mock_player.weapon = "玄铁剑"
        mock_config_manager.weapons_data = {"玄铁剑": {"physical_damage": 10}}
        assert calculate_equipment_atk_bonus(mock_player, mock_config_manager) == 10

    def test_weapon_magic_damage_bonus(self, mock_player, mock_config_manager):
        """Weapon magic_damage contributes to attack bonus."""
        mock_player.weapon = "玄铁剑"
        mock_config_manager.weapons_data = {"玄铁剑": {"magic_damage": 12}}
        assert calculate_equipment_atk_bonus(mock_player, mock_config_manager) == 12

    def test_weapon_all_atk_fields_summed(self, mock_player, mock_config_manager):
        """Weapon atk + physical_damage + magic_damage are summed."""
        mock_player.weapon = "玄铁剑"
        mock_config_manager.weapons_data = {
            "玄铁剑": {"atk": 20, "physical_damage": 8, "magic_damage": 7}
        }
        assert calculate_equipment_atk_bonus(mock_player, mock_config_manager) == 35

    def test_missing_weapon_in_data(self, mock_player, mock_config_manager):
        """When weapon name not in data, it is skipped without error."""
        mock_player.weapon = "不存在之剑"
        assert calculate_equipment_atk_bonus(mock_player, mock_config_manager) == 0


# ──────────────────────────────────────────────────────────────────────
# Build player combat stats
# ──────────────────────────────────────────────────────────────────────


class TestBuildPlayerCombatStats:
    """_build_player_combat_stats formula alignment with _prepare_combat_stats."""

    @pytest.mark.asyncio
    async def test_uses_current_hp_mp(self, pve_manager_with_config, mock_player):
        """CombatStats.hp/mp are initialized from player.hp/mp, not recalculated."""
        mock_player.hp = 123
        mock_player.mp = 456
        stats = await pve_manager_with_config._build_player_combat_stats(mock_player)
        assert stats.hp == 123
        assert stats.mp == 456

    @pytest.mark.asyncio
    async def test_max_hp_mp_from_experience(
        self, pve_manager_with_config, mock_player, mock_combat_manager
    ):
        """CombatStats.max_hp/max_mp come from calculate_hp_mp(player.experience, ...)."""
        mock_combat_manager.calculate_hp_mp.return_value = (500, 1000)
        stats = await pve_manager_with_config._build_player_combat_stats(mock_player)
        assert stats.max_hp == 500
        assert stats.max_mp == 1000
        mock_combat_manager.calculate_hp_mp.assert_called_once_with(
            mock_player.experience, 0.0, 0.0
        )

    @pytest.mark.asyncio
    async def test_atk_includes_base_and_equipment(
        self,
        pve_manager_with_config,
        mock_player,
        mock_combat_manager,
        mock_config_manager,
    ):
        """ATK = calculate_atk(...) + weapon atk + physical_damage + magic_damage."""
        mock_combat_manager.calculate_atk.return_value = 100
        mock_player.weapon = "玄铁剑"
        mock_config_manager.weapons_data = {
            "玄铁剑": {"atk": 10, "physical_damage": 5, "magic_damage": 3}
        }
        stats = await pve_manager_with_config._build_player_combat_stats(mock_player)
        assert stats.atk == 118
        mock_combat_manager.calculate_atk.assert_called_once_with(
            mock_player.experience, mock_player.atkpractice, 0.0
        )

    @pytest.mark.asyncio
    async def test_defense_is_equipment_defense_only(
        self, pve_manager_with_config, mock_player, mock_config_manager
    ):
        """DEF equals calculate_equipment_defense (armor only), ignoring base player defense."""
        mock_player.armor = "金蚕丝甲"
        mock_config_manager.items_data = {
            "金蚕丝甲": {"physical_defense": 30, "magic_defense": 10}
        }
        stats = await pve_manager_with_config._build_player_combat_stats(mock_player)
        assert stats.defense == 40

    @pytest.mark.asyncio
    async def test_no_equipment_bonus_when_no_config(
        self, pve_manager, mock_player, mock_combat_manager
    ):
        """Without config_manager, ATK is base only and DEF is 0."""
        mock_combat_manager.calculate_atk.return_value = 80
        stats = await pve_manager._build_player_combat_stats(mock_player)
        assert stats.atk == 80
        assert stats.defense == 0


# ──────────────────────────────────────────────────────────────────────
# CombatManager crit-rate bounds and conversion
# ──────────────────────────────────────────────────────────────────────


class TestCombatManagerCritRate:
    """calculate_turn_attack crit-roll behaviour for boundary crit rates."""

    TRIALS = 1000

    def test_crit_rate_zero_never_crits(self):
        """crit_rate=0 must produce zero crits across many trials."""
        crits = sum(
            CombatManager.calculate_turn_attack(100, crit_rate=0)[0]
            for _ in range(self.TRIALS)
        )
        assert crits == 0

    def test_crit_rate_hundred_always_crits(self):
        """crit_rate=100 must produce a crit on every trial."""
        crits = sum(
            CombatManager.calculate_turn_attack(100, crit_rate=100)[0]
            for _ in range(self.TRIALS)
        )
        assert crits == self.TRIALS


class TestBuildPlayerCombatStatsCritConversion:
    """Fractional impart_know_per is converted to integer percentage crit_rate."""

    @pytest.mark.asyncio
    async def test_fractional_crit_rate_buff_converted_to_percent(
        self, mock_combat_manager, mock_enemy_manager, mock_player
    ):
        """impart_know_per=0.1 means +10% crit rate."""
        config_manager = MagicMock()
        config_manager.db.ext.get_impart_info = AsyncMock(
            return_value=MagicMock(
                impart_hp_per=0.0,
                impart_mp_per=0.0,
                impart_atk_per=0.0,
                impart_know_per=0.1,
            )
        )

        manager = PVECombatManager(
            mock_combat_manager, mock_enemy_manager, config_manager
        )
        stats = await manager._build_player_combat_stats(mock_player)

        assert stats.crit_rate == 10


# ──────────────────────────────────────────────────────────────────────
# trigger_pve_combat integration flow
# ──────────────────────────────────────────────────────────────────────


class TestTriggerPVECombat:
    """End-to-end flow of trigger_pve_combat with mocked internals."""

    @pytest.mark.asyncio
    async def test_writes_back_hp_mp_after_combat(
        self,
        pve_manager_with_config,
        mock_player,
        mock_combat_manager,
        mock_config_manager,
    ):
        """After combat, player.hp/mp are updated from combat_stats.hp/mp."""
        mock_player.hp = 500
        mock_player.mp = 1000
        mock_combat_manager.calculate_hp_mp.return_value = (600, 1200)
        mock_combat_manager.calculate_atk.return_value = 100

        enemy = Enemy(
            user_id="enemy_wolf",
            name="疾风狼",
            hp=200,
            max_hp=200,
            mp=400,
            max_mp=400,
            atk=30,
            defense=5,
            crit_rate=10,
            exp=8500,
        )
        pve_manager_with_config.enemy_mgr.spawn_enemy.return_value = enemy

        def mutate_and_return(player_stats, _enemy_stats):
            player_stats.hp = 250
            player_stats.mp = 800
            return {
                "winner": "player_001",
                "combat_log": [],
                "player_final_hp": 250,
                "player_final_mp": 800,
            }

        mock_combat_manager.player_vs_boss.side_effect = mutate_and_return

        with (
            patch.object(
                pve_manager_with_config, "_should_trigger_combat", return_value=True
            ),
            patch.object(
                pve_manager_with_config, "_select_enemy_category", return_value="normal"
            ),
        ):
            await pve_manager_with_config.trigger_pve_combat(
                mock_player,
                scene="adventure",
                difficulty="mid",
                base_rewards={"exp": 100, "gold": 50},
            )

        assert mock_player.hp == 250
        assert mock_player.mp == 800

    @pytest.mark.asyncio
    async def test_no_encounter_returns_none(self, pve_manager, mock_player):
        """When _should_trigger_combat returns False, returns None."""
        with patch.object(pve_manager, "_should_trigger_combat", return_value=False):
            result = await pve_manager.trigger_pve_combat(
                mock_player, scene="adventure", difficulty="mid"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_full_flow_victory(
        self, pve_manager, mock_player, mock_combat_manager
    ):
        """Victory flow returns (message_str, rewards_dict)."""
        enemy = Enemy(
            user_id="enemy_wolf",
            name="疾风狼",
            hp=200,
            max_hp=200,
            mp=400,
            max_mp=400,
            atk=30,
            defense=5,
            crit_rate=10,
            exp=8500,
        )
        pve_manager.enemy_mgr.spawn_enemy.return_value = enemy

        combat_stats = CombatStats(
            user_id="player_001",
            name="测试道友",
            hp=500,
            max_hp=500,
            mp=1000,
            max_mp=1000,
            atk=100,
            defense=0,
            crit_rate=0,
            exp=10000,
        )

        combat_result = {
            "winner": "player_001",
            "combat_log": ["玩家攻击", "Boss受伤"],
            "player_final_hp": 350,
            "player_final_mp": 800,
        }
        mock_combat_manager.player_vs_boss.return_value = combat_result

        with (
            patch.object(pve_manager, "_should_trigger_combat", return_value=True),
            patch.object(pve_manager, "_select_enemy_category", return_value="normal"),
            patch.object(
                pve_manager,
                "_build_player_combat_stats",
                return_value=combat_stats,
            ),
        ):
            result = await pve_manager.trigger_pve_combat(
                mock_player,
                scene="adventure",
                difficulty="mid",
                base_rewards={"exp": 100, "gold": 50},
            )

        assert result is not None
        msg, rewards = result
        assert isinstance(msg, str)
        assert "胜利" in msg
        assert rewards["exp"] == int(100 * 1.2)
        assert rewards["bonus_exp"] == 8500

    @pytest.mark.asyncio
    async def test_full_flow_loss(self, pve_manager, mock_player, mock_combat_manager):
        """Loss flow marks hp_penalty."""
        enemy = Enemy(
            user_id="enemy_wolf",
            name="疾风狼",
            hp=200,
            max_hp=200,
            mp=400,
            max_mp=400,
            atk=30,
            defense=5,
            crit_rate=10,
            exp=8500,
        )
        pve_manager.enemy_mgr.spawn_enemy.return_value = enemy

        combat_stats = CombatStats(
            user_id="player_001",
            name="测试道友",
            hp=500,
            max_hp=500,
            mp=1000,
            max_mp=1000,
            atk=100,
            defense=0,
            crit_rate=0,
            exp=10000,
        )

        combat_result = {
            "winner": "enemy_wolf",
            "combat_log": ["玩家攻击", "Boss反击"],
            "player_final_hp": 1,
            "player_final_mp": 200,
        }
        mock_combat_manager.player_vs_boss.return_value = combat_result

        with (
            patch.object(pve_manager, "_should_trigger_combat", return_value=True),
            patch.object(pve_manager, "_select_enemy_category", return_value="elite"),
            patch.object(
                pve_manager,
                "_build_player_combat_stats",
                return_value=combat_stats,
            ),
        ):
            result = await pve_manager.trigger_pve_combat(
                mock_player,
                scene="adventure",
                difficulty="high",
                base_rewards={"exp": 200, "gold": 100},
            )

        assert result is not None
        msg, rewards = result
        assert "战败" in msg
        assert rewards["exp"] == int(200 * 0.3)
        assert rewards["gold"] == 0
        assert rewards["hp_penalty"]

    @pytest.mark.asyncio
    async def test_default_base_rewards(
        self, pve_manager, mock_player, mock_combat_manager
    ):
        """When base_rewards is None, defaults to {'exp': 100, 'gold': 50}."""
        combat_stats = CombatStats(
            user_id="player_001",
            name="测试道友",
            hp=500,
            max_hp=500,
            mp=1000,
            max_mp=1000,
            atk=100,
            defense=0,
            crit_rate=0,
            exp=10000,
        )
        combat_result = {
            "winner": "player_001",
            "combat_log": [],
            "player_final_hp": 500,
            "player_final_mp": 1000,
        }
        mock_combat_manager.player_vs_boss.return_value = combat_result

        with (
            patch.object(pve_manager, "_should_trigger_combat", return_value=True),
            patch.object(pve_manager, "_select_enemy_category", return_value="normal"),
            patch.object(
                pve_manager,
                "_build_player_combat_stats",
                return_value=combat_stats,
            ),
        ):
            result = await pve_manager.trigger_pve_combat(
                mock_player, scene="adventure", difficulty="low"
            )

        assert result is not None
        _msg, rewards = result
        assert rewards["exp"] == int(100 * 1.2)
        assert rewards["gold"] == 50

    @pytest.mark.asyncio
    async def test_spawn_enemy_failure_returns_none(self, pve_manager, mock_player):
        """When spawn_enemy raises, trigger_pve_combat returns None."""
        pve_manager.enemy_mgr.spawn_enemy.side_effect = ValueError("未找到敌人模板配置")

        combat_stats = CombatStats(
            user_id="player_001",
            name="测试道友",
            hp=500,
            max_hp=500,
            mp=1000,
            max_mp=1000,
            atk=100,
            defense=0,
            crit_rate=0,
            exp=10000,
        )

        with (
            patch.object(pve_manager, "_should_trigger_combat", return_value=True),
            patch.object(pve_manager, "_select_enemy_category", return_value="normal"),
            patch.object(
                pve_manager,
                "_build_player_combat_stats",
                return_value=combat_stats,
            ),
        ):
            result = await pve_manager.trigger_pve_combat(
                mock_player, scene="adventure", difficulty="mid"
            )
        assert result is None


# ──────────────────────────────────────────────────────────────────────
# Format combat result
# ──────────────────────────────────────────────────────────────────────


class TestFormatCombatResult:
    """_format_combat_result message formatting."""

    def test_victory_format(self, pve_manager):
        result = {
            "winner": "player_001",
            "combat_log": ["第1回合", "玩家攻击"],
            "player_final_hp": 300,
            "player_final_mp": 600,
        }
        enemy = Enemy(
            user_id="enemy_wolf",
            name="狼",
            hp=100,
            max_hp=100,
            mp=50,
            max_mp=50,
            atk=20,
        )
        rewards = {"exp": 120, "bonus_exp": 8500, "gold": 50, "hp_penalty": False}
        msg = pve_manager._format_combat_result(result, enemy, rewards)
        assert "胜利" in msg
        assert "修为：+120" in msg
        assert "额外修为：+8500" in msg
        assert "灵石：+50" in msg
        assert "剩余气血：300" in msg
        assert "剩余真元：600" in msg

    def test_loss_format(self, pve_manager):
        result = {
            "winner": "enemy_wolf",
            "combat_log": ["Boss反击"],
            "player_final_hp": 1,
            "player_final_mp": 200,
        }
        enemy = Enemy(
            user_id="enemy_wolf",
            name="狼",
            hp=100,
            max_hp=100,
            mp=50,
            max_mp=50,
            atk=20,
        )
        rewards = {"exp": 30, "bonus_exp": 0, "gold": 0, "hp_penalty": True}
        msg = pve_manager._format_combat_result(result, enemy, rewards)
        assert "战败" in msg
        assert "气血受损" in msg

    def test_draw_format(self, pve_manager):
        result = {
            "winner": "平局",
            "combat_log": ["激烈交战"],
            "player_final_hp": 100,
            "player_final_mp": 50,
        }
        enemy = Enemy(
            user_id="enemy_wolf",
            name="狼",
            hp=100,
            max_hp=100,
            mp=50,
            max_mp=50,
            atk=20,
        )
        rewards = {"exp": 100, "bonus_exp": 0, "gold": 50, "hp_penalty": False}
        msg = pve_manager._format_combat_result(result, enemy, rewards)
        assert "平局" in msg


# ──────────────────────────────────────────────────────────────────────
# Drop skipping on defeat (AdventureManager & RiftManager)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    """Database mock with async extension methods."""
    db = MagicMock()
    db.ext = MagicMock()
    db.ext.get_user_cd = AsyncMock()
    db.ext.get_rift_by_id = AsyncMock(return_value=None)
    db.ext.set_user_free = AsyncMock()
    db.update_player = AsyncMock()
    db.get_player_by_id = AsyncMock()
    return db


@pytest.fixture
def mock_storage_ring_manager():
    """StorageRingManager mock that always succeeds storing items."""
    mgr = MagicMock()
    mgr.store_item = AsyncMock(return_value=(True, ""))
    return mgr


@pytest.fixture
def mock_pve_combat_mgr():
    """PVECombatManager mock."""
    return MagicMock()


@pytest.fixture
def adventure_manager(mock_db, mock_storage_ring_manager, mock_pve_combat_mgr):
    """AdventureManager with mocked dependencies."""
    return AdventureManager(mock_db, mock_storage_ring_manager, mock_pve_combat_mgr)


@pytest.fixture
def rift_manager(mock_db, mock_storage_ring_manager, mock_pve_combat_mgr):
    """RiftManager with mocked dependencies."""
    return RiftManager(mock_db, None, mock_storage_ring_manager, mock_pve_combat_mgr)


@pytest.fixture
def finished_user_cd_adventure():
    """UserCd for a finished adventure on the default 'scout' route."""
    cd = MagicMock()
    cd.type = UserStatus.ADVENTURING
    cd.scheduled_time = 0
    cd.create_time = 0
    cd.get_extra_data.return_value = {"route_key": "scout"}
    return cd


@pytest.fixture
def finished_user_cd_rift():
    """UserCd for a finished rift exploration."""
    cd = MagicMock()
    cd.type = UserStatus.EXPLORING
    cd.scheduled_time = 0
    cd.create_time = 0
    cd.get_extra_data.return_value = {"rift_id": 1, "rift_level": 1}
    return cd


class TestAdventureDropSkipping:
    """AdventureManager skips _handle_drops when combat rewards carry hp_penalty."""

    @pytest.mark.asyncio
    async def test_skips_drops_on_defeat(
        self,
        adventure_manager,
        mock_db,
        mock_pve_combat_mgr,
        mock_player,
        finished_user_cd_adventure,
    ):
        """hp_penalty=True means _handle_drops is not awaited and no items drop."""
        mock_db.ext.get_user_cd.return_value = finished_user_cd_adventure
        mock_db.get_player_by_id.return_value = mock_player
        mock_player.experience = 0
        mock_player.gold = 0
        mock_pve_combat_mgr.trigger_pve_combat = AsyncMock(
            return_value=("战败", {"exp": 60, "gold": 0, "hp_penalty": True})
        )

        with patch.object(
            adventure_manager, "_handle_drops", new=AsyncMock(return_value=([], ""))
        ) as mock_handle:
            success, _msg, reward_data = await adventure_manager.finish_adventure(
                "player_001"
            )

        assert success
        mock_handle.assert_not_awaited()
        assert reward_data["items"] == []

    @pytest.mark.asyncio
    async def test_proceeds_drops_on_victory(
        self,
        adventure_manager,
        mock_db,
        mock_pve_combat_mgr,
        mock_player,
        finished_user_cd_adventure,
    ):
        """hp_penalty=False means _handle_drops is awaited normally."""
        mock_db.ext.get_user_cd.return_value = finished_user_cd_adventure
        mock_db.get_player_by_id.return_value = mock_player
        mock_player.experience = 0
        mock_player.gold = 0
        mock_pve_combat_mgr.trigger_pve_combat = AsyncMock(
            return_value=("胜利", {"exp": 200, "gold": 100, "hp_penalty": False})
        )

        with patch.object(
            adventure_manager,
            "_handle_drops",
            new=AsyncMock(return_value=([("灵草", 2)], "\n\n📦 获得物品")),
        ) as mock_handle:
            success, _msg, reward_data = await adventure_manager.finish_adventure(
                "player_001"
            )

        assert success
        mock_handle.assert_awaited_once()
        assert reward_data["items"] == [("灵草", 2)]


class TestRiftDropSkipping:
    """RiftManager skips _roll_rift_drops when combat rewards carry hp_penalty."""

    @pytest.mark.asyncio
    async def test_skips_drops_on_defeat(
        self,
        rift_manager,
        mock_db,
        mock_pve_combat_mgr,
        mock_player,
        finished_user_cd_rift,
    ):
        """hp_penalty=True means _roll_rift_drops is not awaited and no items drop."""
        mock_db.ext.get_user_cd.return_value = finished_user_cd_rift
        mock_db.get_player_by_id.return_value = mock_player
        mock_player.experience = 0
        mock_player.gold = 0
        mock_pve_combat_mgr.trigger_pve_combat = AsyncMock(
            return_value=("战败", {"exp": 1000, "gold": 500, "hp_penalty": True})
        )

        with patch.object(
            rift_manager, "_roll_rift_drops", new=AsyncMock(return_value=[])
        ) as mock_roll:
            success, _msg, reward_data = await rift_manager.finish_exploration(
                "player_001"
            )

        assert success
        mock_roll.assert_not_awaited()
        assert reward_data["items"] == []

    @pytest.mark.asyncio
    async def test_proceeds_drops_on_victory(
        self,
        rift_manager,
        mock_db,
        mock_pve_combat_mgr,
        mock_player,
        finished_user_cd_rift,
    ):
        """hp_penalty=False means _roll_rift_drops is awaited normally."""
        mock_db.ext.get_user_cd.return_value = finished_user_cd_rift
        mock_db.get_player_by_id.return_value = mock_player
        mock_player.experience = 0
        mock_player.gold = 0
        mock_pve_combat_mgr.trigger_pve_combat = AsyncMock(
            return_value=("胜利", {"exp": 3000, "gold": 1500, "hp_penalty": False})
        )

        with patch.object(
            rift_manager,
            "_roll_rift_drops",
            new=AsyncMock(return_value=[("灵草", 3)]),
        ) as mock_roll:
            success, _msg, reward_data = await rift_manager.finish_exploration(
                "player_001"
            )

        assert success
        mock_roll.assert_awaited_once()
        assert reward_data["items"] == [("灵草", 3)]
