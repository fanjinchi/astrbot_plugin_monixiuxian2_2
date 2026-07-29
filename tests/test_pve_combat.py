"""Tests for PVECombatManager - encounter probability, enemy category distribution,
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

_cm_mod = load_module("combat_manager", "managers/combat_manager.py")
CombatResult = _cm_mod.CombatResult

_enemy_mod = load_module("enemy_manager", "managers/enemy_manager.py")
Enemy = _enemy_mod.Enemy

_model_mod = load_module("models", "models.py")
Player = _model_mod.Player

# Managers that depend on DataBase/StorageRingManager (loaded with fallback imports)
_adv_mod = load_module("adventure_manager", "managers/adventure_manager.py")
AdventureManager = _adv_mod.AdventureManager

_rift_mod = load_module("rift_manager", "managers/rift_manager.py")
RiftManager = _rift_mod.RiftManager


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_combat_engine():
    """A fake combat engine returning deterministic results."""
    engine = MagicMock()
    engine.build_fighter_from_player = AsyncMock(
        side_effect=lambda p: MagicMock(
            user_id=p.user_id,
            name=p.user_name or p.name,
            hp=p.hp,
            damage=getattr(p, "damage", 10),
            agility=getattr(p, "agility", 5),
            speed=getattr(p, "speed", 5),
            armor_value=getattr(p, "armor_value", 0),
        )
    )
    engine.resolve_combat.return_value = CombatResult(
        winner="player_001",
        combat_log=["第1回合", "玩家攻击"],
        fighter1_final_hp=350,
        fighter2_final_hp=0,
        rounds=1,
        total_actions=1,
    )
    return engine


@pytest.fixture
def mock_combat_manager(mock_combat_engine):
    """CombatManager-like mock exposing the fake engine."""
    mgr = MagicMock()
    mgr.engine = mock_combat_engine
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
        damage=30,
        agility=10,
        speed=10,
        armor_value=5,
        exp=8500,
        crit_rate=10,
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
    player.hp = 500
    player.damage = 50
    player.agility = 15
    player.speed = 15
    player.armor_value = 0
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
            ("adventure", "low", 0.30),
            ("adventure", "mid", 0.45),
            ("adventure", "high", 0.65),
            ("adventure", "extreme", 0.75),
            ("rift", "low", 0.50),
            ("rift", "mid", 0.70),
            ("rift", "high", 0.90),
            ("rift", "extreme", 0.95),
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
            damage=20,
            agility=5,
            speed=5,
            armor_value=5,
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
        result = {"winner": "draw"}
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
        rewards = self.calculate_rewards(
            pve_manager, result, base, self.make_enemy(exp=999_999)
        )
        assert rewards["exp"] == int(10_000_000 * 1.2)
        assert rewards["bonus_exp"] == 999_999
        assert rewards["gold"] == 5_000_000

    @staticmethod
    def calculate_rewards(pve_manager, result, base, enemy):
        """Helper to access private method in tests."""
        return pve_manager._calculate_rewards(result, base, enemy)


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
        """Weapon physical/magic defense is not counted."""
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
# Integration with unified combat engine
# ──────────────────────────────────────────────────────────────────────


class TestPveEngineIntegration:
    """trigger_pve_combat delegates to CombatEngine.resolve_combat."""

    @pytest.mark.asyncio
    async def test_calls_resolve_combat_and_writes_back_hp(
        self, pve_manager, mock_combat_engine, mock_player
    ):
        """After combat, player.hp is updated from the engine result."""
        with patch.object(pve_manager, "_should_trigger_combat", return_value=True):
            with patch.object(
                pve_manager, "_select_enemy_category", return_value="normal"
            ):
                msg, rewards = await pve_manager.trigger_pve_combat(
                    mock_player,
                    scene="adventure",
                    difficulty="mid",
                    base_rewards={"exp": 100, "gold": 50},
                )

        mock_combat_engine.resolve_combat.assert_called_once()
        assert mock_player.hp == 350
        assert "胜利" in msg
        assert rewards["bonus_exp"] == 8500

    @pytest.mark.asyncio
    async def test_no_encounter_returns_none(self, pve_manager, mock_player):
        """When _should_trigger_combat returns False, returns None."""
        with patch.object(pve_manager, "_should_trigger_combat", return_value=False):
            result = await pve_manager.trigger_pve_combat(
                mock_player, scene="adventure", difficulty="mid"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_spawn_enemy_failure_returns_none(
        self, pve_manager, mock_player
    ):
        """When spawn_enemy raises, trigger_pve_combat returns None."""
        pve_manager.enemy_mgr.spawn_enemy.side_effect = ValueError(
            "未找到敌人模板配置"
        )
        with patch.object(pve_manager, "_should_trigger_combat", return_value=True):
            with patch.object(
                pve_manager, "_select_enemy_category", return_value="normal"
            ):
                result = await pve_manager.trigger_pve_combat(
                    mock_player, scene="adventure", difficulty="mid"
                )
        assert result is None

    @pytest.mark.asyncio
    async def test_loss_marks_hp_penalty(
        self, pve_manager, mock_combat_engine, mock_player
    ):
        """When the enemy wins, hp_penalty is set."""
        mock_combat_engine.resolve_combat.return_value = CombatResult(
            winner="enemy_wolf",
            combat_log=["第1回合", "敌人攻击"],
            fighter1_final_hp=0,
            fighter2_final_hp=100,
            rounds=1,
            total_actions=1,
        )
        with patch.object(pve_manager, "_should_trigger_combat", return_value=True):
            with patch.object(
                pve_manager, "_select_enemy_category", return_value="elite"
            ):
                msg, rewards = await pve_manager.trigger_pve_combat(
                    mock_player,
                    scene="adventure",
                    difficulty="high",
                    base_rewards={"exp": 200, "gold": 100},
                )

        assert "战败" in msg
        assert rewards["exp"] == int(200 * 0.3)
        assert rewards["gold"] == 0
        assert rewards["hp_penalty"]


# ──────────────────────────────────────────────────────────────────────
# Format combat result
# ──────────────────────────────────────────────────────────────────────


class TestFormatCombatResult:
    """_format_combat_result message formatting."""

    def make_enemy(self, exp=8500):
        return Enemy(
            user_id="enemy_wolf",
            name="狼",
            hp=100,
            max_hp=100,
            damage=20,
            agility=5,
            speed=5,
            armor_value=5,
            exp=exp,
        )

    def test_victory_format(self, pve_manager):
        result = {
            "winner": "player_001",
            "combat_log": ["第1回合", "玩家攻击"],
            "player_final_hp": 300,
            "player_final_mp": 300,
        }
        rewards = {"exp": 120, "bonus_exp": 8500, "gold": 50, "hp_penalty": False}
        msg = pve_manager._format_combat_result(result, self.make_enemy(), rewards)
        assert "胜利" in msg
        assert "修为：+120" in msg
        assert "额外修为：+8500" in msg
        assert "灵石：+50" in msg
        assert "剩余气血：300" in msg

    def test_loss_format(self, pve_manager):
        result = {
            "winner": "enemy_wolf",
            "combat_log": ["Boss反击"],
            "player_final_hp": 1,
            "player_final_mp": 1,
        }
        rewards = {"exp": 30, "bonus_exp": 0, "gold": 0, "hp_penalty": True}
        msg = pve_manager._format_combat_result(result, self.make_enemy(), rewards)
        assert "战败" in msg
        assert "气血受损" in msg

    def test_draw_format(self, pve_manager):
        result = {
            "winner": "draw",
            "combat_log": ["激烈交战"],
            "player_final_hp": 100,
            "player_final_mp": 100,
        }
        rewards = {"exp": 100, "bonus_exp": 0, "gold": 50, "hp_penalty": False}
        msg = pve_manager._format_combat_result(result, self.make_enemy(), rewards)
        assert "平局" in msg


# ──────────────────────────────────────────────────────────────────────
# Fixtures for downstream manager tests
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
    from models_extended import UserStatus

    cd = MagicMock()
    cd.type = UserStatus.ADVENTURING
    cd.scheduled_time = 0
    cd.create_time = 0
    cd.get_extra_data.return_value = {"route_key": "scout"}
    return cd


@pytest.fixture
def finished_user_cd_rift():
    """UserCd for a finished rift exploration."""
    from models_extended import UserStatus

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
