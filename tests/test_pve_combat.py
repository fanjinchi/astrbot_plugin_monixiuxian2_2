"""Tests for PVECombatManager - encounter probability, enemy category distribution,
reward calculation, and the full trigger_pve_combat flow.
"""

import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import load_module

# Load modules via importlib.util, bypassing managers/__init__.py
_pve_mod = load_module("pve_combat_manager", "managers/pve_combat_manager.py")
PVECombatManager = _pve_mod.PVECombatManager
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


@pytest.fixture(autouse=True)
def _restore_global_rng_state():
    """Restore the global RNG stream after each test in this module.

    The statistical cases below seed ``random`` to make their own draw reproducible and
    order-independent. Without restoring the stream afterwards that seeding would leak
    into every later test that consumes the global RNG (attribute-growth roulette, loot
    rolls, other breakthrough panels), just moving the coupling instead of removing it.
    """
    state = random.getstate()
    yield
    random.setstate(state)


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
# Encounter probability (frozen seed, exact hit-count pins)
# ──────────────────────────────────────────────────────────────────────


class TestEncounterProbability:
    """_should_trigger_combat exact-draw verification (frozen seed, pinned hit count).

    Each cell owns its seed, so the 1000 draws are one *fixed* sample rather than a
    fresh statistical experiment. The contract is therefore the exact number of hits
    that sample produces under the current encounter table -- a tripwire on the table
    and on the RNG call sequence, not a confidence band.

    Why not a z-test (bd -ju1 review round 3, H1): with n=1000 the smallest detectable
    shift is 4 sigma = 4*sqrt(p(1-p)/1000) = 5.48~6.32pp for every cell between
    p=0.30 and p=0.75 (only p=0.90 -> 3.79pp and p=0.95 -> 2.76pp are tighter), i.e.
    wider than the ±5% band it replaced. Measured on this frozen sample: shifting the
    whole encounter table by +1pp or +2pp lights up 0 of 8 cells under either retired
    band but 8 of 8 under these pins (+3pp still only catches 1 of 8 there), which is
    why the band was dropped instead of re-tuned.
    """

    TRIALS = 1000

    # (scene, difficulty, configured rate, hits under the frozen seed below).
    # Re-pin by reading the count from the assertion message after an intentional table
    # change; the rate column is kept only so the message can quote the design value.
    @pytest.mark.parametrize(
        "scene,difficulty,rate,expected_hits",
        [
            ("adventure", "low", 0.30, 291),
            ("adventure", "mid", 0.45, 431),
            ("adventure", "high", 0.65, 638),
            ("adventure", "extreme", 0.75, 747),
            ("rift", "low", 0.50, 505),
            ("rift", "mid", 0.70, 717),
            ("rift", "high", 0.90, 902),
            ("rift", "extreme", 0.95, 952),
        ],
    )
    def test_encounter_rate(self, pve_manager, scene, difficulty, rate, expected_hits):
        """The frozen seed must reproduce the pinned hit count exactly."""
        # Statistical assertions must own their seed: this test samples the global
        # ``random`` stream, so any other case that consumes RNG (e.g. breakthrough
        # panels) would shift it. The retired ±5% band made that coupling visible -- a
        # 5pp miss is only 3.45σ at p=0.70, so a perturbed draw could fall outside the
        # band and turn an unrelated ordering change into a red test. Exact pins remove
        # the band: the seed *is* the contract, so nothing drifts with execution order.
        random.seed(f"encounter:{scene}:{difficulty}")
        hits = sum(
            pve_manager._should_trigger_combat(scene, difficulty)
            for _ in range(self.TRIALS)
        )
        assert hits == expected_hits, (
            f"[{scene}/{difficulty}] pinned draw changed: seed "
            f"'encounter:{scene}:{difficulty}' hit {hits}/{self.TRIALS} "
            f"(= {hits / self.TRIALS:.2%}), the pin says {expected_hits} "
            f"(configured rate {rate:.2%}). This is the exact sample of a frozen seed, "
            "not a tolerance band: any intentional change to the encounter table, or to "
            "how often _should_trigger_combat draws from `random`, must be re-pinned "
            "here with the new count."
        )

    def test_unknown_scene_returns_false(self, pve_manager):
        """Unknown scene/difficulty should never trigger combat (rate=0.0)."""
        assert not pve_manager._should_trigger_combat("unknown", "low")
        assert not pve_manager._should_trigger_combat("adventure", "unknown")


# ──────────────────────────────────────────────────────────────────────
# Enemy category distribution (frozen seed, exact hit-count pins)
# ──────────────────────────────────────────────────────────────────────


class TestEnemyCategoryDistribution:
    """_select_enemy_category exact-draw verification (frozen seed, pinned counts).

    Same contract as :class:`TestEncounterProbability`: one owned seed per cell, and the
    assertion is the exact per-category hit vector of that frozen sample. See that class
    docstring for why the z-test band was dropped (a 4σ band detects ≥5.5pp shifts, so
    a 1~2pp drift of the category table stayed green).
    """

    TRIALS = 1000

    # (scene, difficulty, configured (normal, elite, boss) rates, exact hits per label
    # under random.seed(f"category:{scene}:{difficulty}")). Re-pin by reading the counts
    # from the assertion message after an intentional table change.
    @pytest.mark.parametrize(
        "scene,difficulty,rates,expected_counts",
        [
            ("adventure", "mid", (0.70, 0.25, 0.05), (709, 249, 42)),
            ("adventure", "high", (0.40, 0.40, 0.20), (370, 431, 199)),
            ("adventure", "extreme", (0.30, 0.35, 0.35), (298, 351, 351)),
            ("rift", "low", (0.80, 0.20, 0.00), (789, 211, 0)),
            ("rift", "mid", (0.50, 0.35, 0.15), (513, 331, 156)),
            ("rift", "high", (0.30, 0.40, 0.30), (295, 394, 311)),
            ("rift", "extreme", (0.20, 0.40, 0.40), (177, 430, 393)),
        ],
    )
    def test_category_distribution(
        self, pve_manager, scene, difficulty, rates, expected_counts
    ):
        """The frozen seed must reproduce the pinned per-category counts exactly."""
        # Seed ownership: see test_encounter_rate (global ``random`` stream).
        random.seed(f"category:{scene}:{difficulty}")
        counts = {"normal": 0, "elite": 0, "boss": 0}
        for _ in range(self.TRIALS):
            cat = pve_manager._select_enemy_category(scene, difficulty)
            counts[cat] += 1

        # One loop instead of three near-identical asserts, so the table stays the single
        # source of truth for the (normal, elite, boss) order.
        for label, rate, pinned in zip(
            ("normal", "elite", "boss"), rates, expected_counts, strict=True
        ):
            if rate == 0.0:
                # A configured 0.0 has no sampling variance, so its pin must be exactly 0
                # -- the retired ±5% band allowed 50 hits on such a cell.
                assert pinned == 0, (
                    f"table error: [{scene}/{difficulty}/{label}] is configured 0.0 "
                    f"but pinned to {pinned} hits"
                )
            assert counts[label] == pinned, (
                f"[{scene}/{difficulty}/{label}] pinned draw changed: seed "
                f"'category:{scene}:{difficulty}' hit {counts[label]}/{self.TRIALS} "
                f"(= {counts[label] / self.TRIALS:.2%}), the pin says {pinned} "
                f"(configured rate {rate:.2%}). This is the exact sample of a frozen "
                "seed, not a tolerance band: any intentional change to the category "
                "table, or to how often _select_enemy_category draws from `random`, "
                "must be re-pinned here with the new counts."
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
    async def test_spawn_enemy_failure_returns_none(self, pve_manager, mock_player):
        """When spawn_enemy raises, trigger_pve_combat returns None."""
        pve_manager.enemy_mgr.spawn_enemy.side_effect = ValueError("未找到敌人模板配置")
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


class TestRiftSettlementNoAutoPve:
    """finish_exploration 不再自动触发 PvE（add-rift-encounters design D5）。

    新契约：结算奖励不被战斗修改（旧失败扣 exp×0.3/gold=0/hp=1 语义移除），
    掉落恒按事件 item_chance roll，pve_won 恒 False，hp 不被结算触碰。
    """

    @pytest.mark.asyncio
    async def test_settlement_does_not_trigger_pve_and_rolls_drops(
        self,
        rift_manager,
        mock_db,
        mock_pve_combat_mgr,
        mock_player,
        finished_user_cd_rift,
    ):
        """结算不调用 trigger_pve_combat；掉落照常 roll 并入库。"""
        mock_db.ext.get_user_cd.return_value = finished_user_cd_rift
        mock_db.get_player_by_id.return_value = mock_player
        mock_player.experience = 0
        mock_player.gold = 0
        # 关闭随机遭遇判定，聚焦结算本体
        rift_manager.config = {
            "puzzle_rate": 0.0,
            "beast_rate": 0.0,
            "legacy_chance": 0.0,
            "explore_events": [{"desc": "固定事件", "item_chance": 100}],
        }

        with patch.object(
            rift_manager,
            "_roll_rift_drops",
            new=AsyncMock(return_value=[("灵草", 3)]),
        ) as mock_roll:
            success, _msg, reward_data = await rift_manager.finish_exploration(
                "player_001"
            )

        assert success
        mock_pve_combat_mgr.trigger_pve_combat.assert_not_called()
        mock_roll.assert_awaited_once()
        assert reward_data["items"] == [("灵草", 3)]
        assert reward_data["pve_won"] is False

    @pytest.mark.asyncio
    async def test_settlement_keeps_hp_and_full_base_rewards(
        self,
        rift_manager,
        mock_db,
        mock_pve_combat_mgr,
        mock_player,
        finished_user_cd_rift,
    ):
        """无战斗则 hp 不动、基础修为/灵石不打折（旧失败惩罚随自动 PvE 移除）。"""
        mock_db.ext.get_user_cd.return_value = finished_user_cd_rift
        mock_db.get_player_by_id.return_value = mock_player
        mock_player.experience = 0
        mock_player.gold = 0
        mock_player.hp = 500
        rift_manager.config = {
            "puzzle_rate": 0.0,
            "beast_rate": 0.0,
            "legacy_chance": 0.0,
            "explore_events": [{"desc": "固定事件", "item_chance": 0}],
        }

        with patch.object(
            rift_manager, "_roll_rift_drops", new=AsyncMock(return_value=[])
        ) as mock_roll:
            success, _msg, reward_data = await rift_manager.finish_exploration(
                "player_001"
            )

        assert success
        mock_pve_combat_mgr.trigger_pve_combat.assert_not_called()
        # 掉落不再因战斗失败被跳过，恒按 item_chance 判定
        mock_roll.assert_awaited_once()
        assert reward_data["exp"] > 0 and reward_data["gold"] > 0
        assert reward_data["pve_won"] is False
        assert mock_player.hp == 500
