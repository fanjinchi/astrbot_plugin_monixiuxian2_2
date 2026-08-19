"""Tests for BossManager - new four-main-attribute stat generation and combat."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_module

_boss_mod = load_module("boss_manager", "managers/boss_manager.py")
BossManager = _boss_mod.BossManager

_model_mod = load_module("models", "models.py")
Player = _model_mod.Player

_ext_mod = load_module("models_extended", "models_extended.py")
Boss = _ext_mod.Boss
UserStatus = _ext_mod.UserStatus

_cm_mod = load_module("combat_manager", "managers/combat_manager.py")
CombatResult = _cm_mod.CombatResult
FighterState = _cm_mod.FighterState


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_level_config():
    """Sample level_config with the new four-main-attribute fields."""
    return [
        {
            "level": 1,
            "level_name": "练气一阶",
            "exp_needed": 0,
            "base_damage": 10,
            "base_agility": 5,
            "base_speed": 5,
            "base_hp": 100,
        },
        {
            "level": 10,
            "level_name": "筑基初期",
            "exp_needed": 16000,
            "base_damage": 37,
            "base_agility": 14,
            "base_speed": 9,
            "base_hp": 235,
        },
        {
            "level": 20,
            "level_name": "金丹初期",
            "exp_needed": 6000000,
            "base_damage": 67,
            "base_agility": 24,
            "base_speed": 14,
            "base_hp": 370,
        },
    ]


@pytest.fixture
def mock_config_manager(sample_level_config):
    """ConfigManager mock with level data and PvE difficulty multiplier."""
    mgr = MagicMock()
    mgr.get_level_data.return_value = sample_level_config
    mgr.game_config = {"pve": {"difficulty_multiplier": 1.0}}
    mgr.boss_config = {}
    return mgr


@pytest.fixture
def mock_combat_engine():
    """CombatEngine mock with deterministic build_fighter and resolve_combat."""
    engine = MagicMock()
    engine.build_fighter_from_player = AsyncMock(
        side_effect=lambda p: FighterState(
            user_id=p.user_id,
            name=p.user_name or p.user_id,
            hp=p.hp,
            max_hp=p.hp,
            damage=p.damage,
            agility=p.agility,
            speed=p.speed,
            armor_value=p.armor_value,
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
    """CombatManager-like mock exposing the engine."""
    mgr = MagicMock()
    mgr.engine = mock_combat_engine
    return mgr


@pytest.fixture
def mock_db():
    """Database mock with async Boss/UserCd/Player methods."""
    db = MagicMock()
    db.ext = MagicMock()
    db.ext.get_active_boss = AsyncMock(return_value=None)
    db.ext.create_boss = AsyncMock(return_value=1)
    db.ext.defeat_boss = AsyncMock()
    db.ext.update_boss = AsyncMock()
    db.ext.get_user_cd = AsyncMock(return_value=None)
    db.ext.create_user_cd = AsyncMock()
    db.get_player_by_id = AsyncMock()
    db.get_all_players = AsyncMock(return_value=[])
    db.update_player = AsyncMock()
    return db


@pytest.fixture
def mock_storage_ring_manager():
    """StorageRingManager mock that always succeeds storing items."""
    mgr = MagicMock()
    mgr.store_item = AsyncMock(return_value=(True, ""))
    return mgr


@pytest.fixture
def boss_manager(mock_db, mock_combat_manager, mock_config_manager):
    """BossManager with mocked dependencies and deterministic HP variance."""
    mgr = BossManager(mock_db, mock_combat_manager, mock_config_manager, None)
    mgr._resolve_boss_stats = lambda level_config: mgr._generate_boss_stats(
        level_config
    )
    return mgr


@pytest.fixture
def player_idle():
    """Idle player ready for boss challenge."""
    p = Player(
        user_id="player_001",
        user_name="测试道友",
        level_index=20,
        damage=100,
        agility=30,
        speed=20,
        hp=1000,
        armor_value=10,
        gold=0,
    )
    return p


@pytest.fixture
def user_cd_idle():
    """UserCd in idle state."""
    cd = MagicMock()
    cd.type = UserStatus.IDLE
    return cd


# ──────────────────────────────────────────────────────────────────────
# Stat generation tests
# ──────────────────────────────────────────────────────────────────────


class TestBossStatGeneration:
    """Boss stats are generated from level_config base values."""

    def test_stats_from_level_config(self, boss_manager, mock_config_manager):
        """Boss stats = base * multipliers * difficulty_multiplier."""
        level_config = {
            "name": "筑基",
            "level_index": 10,
            "hp_mult": 1.5,
            "atk_mult": 1.2,
            "reward_mult": 1.5,
            "armor_value": 10,
        }
        stats = boss_manager._generate_boss_stats(level_config)
        # base values from sample_level_config level 10
        assert stats["damage"] == int(37 * 1.2 * 1.0)
        assert stats["agility"] == int(14 * 1.0)
        assert stats["speed"] == int(9 * 1.0)
        assert stats["hp"] == int(235 * 1.5 * 1.0)
        assert stats["armor_value"] == int(10 * 1.0)

    def test_difficulty_multiplier_scales_stats(self, mock_db, mock_combat_manager):
        """Raising pve.difficulty_multiplier scales all boss stats."""
        config = MagicMock()
        config.get_level_data.return_value = [
            {
                "level": 10,
                "level_name": "筑基初期",
                "exp_needed": 16000,
                "base_damage": 40,
                "base_agility": 15,
                "base_speed": 10,
                "base_hp": 250,
            }
        ]
        config.game_config = {"pve": {"difficulty_multiplier": 2.0}}
        config.boss_config = {}
        mgr = BossManager(mock_db, mock_combat_manager, config, None)
        level_config = {
            "name": "筑基",
            "level_index": 10,
            "hp_mult": 1.5,
            "atk_mult": 1.2,
            "reward_mult": 1.5,
            "armor_value": 10,
        }
        stats = mgr._generate_boss_stats(level_config)
        assert stats["damage"] == int(40 * 1.2 * 2.0)
        assert stats["agility"] == int(15 * 2.0)
        assert stats["speed"] == int(10 * 2.0)
        assert stats["hp"] == int(250 * 1.5 * 2.0)
        assert stats["armor_value"] == int(10 * 2.0)

    def test_fallback_when_base_attributes_missing(self, mock_db, mock_combat_manager):
        """If level_config lacks new base fields, fall back to exp_needed."""
        config = MagicMock()
        config.get_level_data.return_value = [
            {
                "level": 10,
                "level_name": "筑基初期",
                "exp_needed": 1000,
            }
        ]
        config.game_config = {"pve": {"difficulty_multiplier": 1.0}}
        config.boss_config = {}
        mgr = BossManager(mock_db, mock_combat_manager, config, None)
        level_config = {
            "name": "筑基",
            "level_index": 10,
            "hp_mult": 1.0,
            "atk_mult": 1.0,
            "reward_mult": 1.0,
            "armor_value": 0,
        }
        stats = mgr._generate_boss_stats(level_config)
        assert stats["damage"] == max(1, 1000 // 10)
        assert stats["hp"] == max(1, 1000 // 2)
        assert stats["agility"] == max(1, stats["damage"] // 2)
        assert stats["speed"] == max(1, stats["damage"] // 2)

    def test_legacy_level_indices_normalized(self, mock_db, mock_combat_manager):
        """Old 36-level indices are normalized to decimal realm levels."""
        config = MagicMock()
        config.get_level_data.return_value = [
            {
                "level": 1,
                "level_name": "练气一阶",
                "exp_needed": 0,
                "base_damage": 10,
                "base_agility": 5,
                "base_speed": 5,
                "base_hp": 100,
            }
        ]
        config.game_config = {"pve": {"difficulty_multiplier": 1.0}}
        config.boss_config = {
            "levels": [
                {
                    "name": "练气",
                    "level_index": 0,  # legacy index
                    "hp_mult": 1.0,
                    "atk_mult": 1.0,
                    "reward_mult": 1.0,
                    "armor_value": 0,
                }
            ]
        }
        mgr = BossManager(mock_db, mock_combat_manager, config, None)
        assert mgr.levels[0]["level_index"] == 1


# ──────────────────────────────────────────────────────────────────────
# Spawn tests
# ──────────────────────────────────────────────────────────────────────


class TestSpawnBoss:
    """Boss spawn flow and messages."""

    @pytest.mark.asyncio
    async def test_spawn_boss_creates_boss_with_new_stats(self, boss_manager, mock_db):
        """spawn_boss returns a Boss with hp/atk/defense from new stats."""
        level_config = boss_manager.levels[1]  # 筑基
        success, msg, boss = await boss_manager.spawn_boss(level_config=level_config)
        assert success
        assert boss is not None
        # HP is base 235 * 1.5 = 352 (with variance disabled in fixture)
        assert boss.hp == int(235 * 1.5)
        assert boss.max_hp == boss.hp
        # atk proxies damage, defense proxies armor_value
        assert boss.atk == int(37 * 1.2)
        assert boss.defense == 0
        assert "伤害" in msg
        assert "身法" in msg
        assert "迅捷" in msg
        assert "护甲" in msg

    @pytest.mark.asyncio
    async def test_spawn_boss_refuses_when_active_boss_exists(
        self, boss_manager, mock_db
    ):
        """Cannot spawn a new boss while one is already active."""
        existing = Boss(
            boss_id=1,
            boss_name=" existing",
            boss_level="练气",
            hp=100,
            max_hp=100,
            atk=10,
        )
        mock_db.ext.get_active_boss.return_value = existing
        success, msg, boss = await boss_manager.spawn_boss()
        assert not success
        assert "已有Boss" in msg
        assert boss is None

    @pytest.mark.asyncio
    async def test_spawn_boss_random_level(self, boss_manager):
        """spawn_boss without level_config picks a random tier."""
        success, _msg, boss = await boss_manager.spawn_boss()
        assert success
        assert boss.boss_level in {cfg["name"] for cfg in boss_manager.levels}


# ──────────────────────────────────────────────────────────────────────
# Challenge tests
# ──────────────────────────────────────────────────────────────────────


class TestChallengeBoss:
    """Boss challenge flow through the unified combat engine."""

    @pytest.mark.asyncio
    async def test_challenge_victory(
        self,
        boss_manager,
        mock_db,
        mock_combat_engine,
        player_idle,
        user_cd_idle,
    ):
        """Player victory defeats boss, grants stone reward, and drops items."""
        mock_db.ext.get_user_cd.return_value = user_cd_idle
        mock_db.get_player_by_id.return_value = player_idle
        mock_combat_engine.resolve_combat.return_value = CombatResult(
            winner="player_001",
            combat_log=["胜利"],
            fighter1_final_hp=800,
            fighter2_final_hp=0,
            rounds=3,
            total_actions=3,
        )

        boss = Boss(
            boss_id=1,
            boss_name="血魔·金丹境",
            boss_level="金丹",
            hp=100,
            max_hp=100,
            atk=10,
            defense=0,
            stone_reward=1000,
        )
        mock_db.ext.get_active_boss.return_value = boss

        success, msg, result = await boss_manager.challenge_boss("player_001")
        assert success
        assert "挑战成功" in msg
        assert result["winner"] == "player_001"
        assert player_idle.gold == 1000
        mock_db.ext.defeat_boss.assert_awaited_once_with(1)
        mock_db.update_player.assert_awaited_once()
        assert player_idle.hp == 800

    @pytest.mark.asyncio
    async def test_challenge_defeat(
        self,
        boss_manager,
        mock_db,
        mock_combat_engine,
        player_idle,
        user_cd_idle,
    ):
        """Player defeat gives consolation reward and updates boss HP."""
        mock_db.ext.get_user_cd.return_value = user_cd_idle
        mock_db.get_player_by_id.return_value = player_idle
        mock_combat_engine.resolve_combat.return_value = CombatResult(
            winner="1",
            combat_log=["失败"],
            fighter1_final_hp=0,
            fighter2_final_hp=50,
            rounds=3,
            total_actions=3,
        )

        boss = Boss(
            boss_id=1,
            boss_name="血魔·金丹境",
            boss_level="金丹",
            hp=100,
            max_hp=100,
            atk=10,
            defense=0,
            stone_reward=1000,
        )
        mock_db.ext.get_active_boss.return_value = boss

        success, msg, result = await boss_manager.challenge_boss("player_001")
        assert success
        assert "挑战失败" in msg
        # Damage dealt = 50 / 100 = 50%, consolation = 50% of 1000 = 500
        assert result["reward"] == 500
        assert player_idle.gold == 500
        mock_db.ext.update_boss.assert_awaited_once()
        assert boss.hp == 50

    @pytest.mark.asyncio
    async def test_challenge_draw(
        self,
        boss_manager,
        mock_db,
        mock_combat_engine,
        player_idle,
        user_cd_idle,
    ):
        """Draw outcome gives a reduced consolation reward."""
        mock_db.ext.get_user_cd.return_value = user_cd_idle
        mock_db.get_player_by_id.return_value = player_idle
        mock_combat_engine.resolve_combat.return_value = CombatResult(
            winner="draw",
            combat_log=["平局"],
            fighter1_final_hp=100,
            fighter2_final_hp=50,
            rounds=200,
            total_actions=200,
        )

        boss = Boss(
            boss_id=1,
            boss_name="血魔·金丹境",
            boss_level="金丹",
            hp=100,
            max_hp=100,
            atk=10,
            defense=0,
            stone_reward=1000,
        )
        mock_db.ext.get_active_boss.return_value = boss

        success, _msg, result = await boss_manager.challenge_boss("player_001")
        assert success
        # Damage dealt 50%, draw halves consolation: 250
        assert result["reward"] == 250
        assert player_idle.gold == 250

    @pytest.mark.asyncio
    async def test_challenge_no_player(self, boss_manager, mock_db):
        """Challenge fails when player does not exist."""
        mock_db.get_player_by_id.return_value = None
        success, msg, _result = await boss_manager.challenge_boss("ghost")
        assert not success
        assert "还未踏入修仙之路" in msg

    @pytest.mark.asyncio
    async def test_challenge_no_boss(self, boss_manager, mock_db, player_idle):
        """Challenge fails when there is no active boss."""
        mock_db.get_player_by_id.return_value = player_idle
        mock_db.ext.get_active_boss.return_value = None
        success, msg, _result = await boss_manager.challenge_boss("player_001")
        assert not success
        assert "没有Boss" in msg

    @pytest.mark.asyncio
    async def test_challenge_busy_player(self, boss_manager, mock_db, player_idle):
        """Challenge fails when player is busy."""
        boss = Boss(
            boss_id=1,
            boss_name="血魔·金丹境",
            boss_level="金丹",
            hp=100,
            max_hp=100,
            atk=10,
            defense=0,
            stone_reward=1000,
        )
        mock_db.get_player_by_id.return_value = player_idle
        mock_db.ext.get_active_boss.return_value = boss
        busy_cd = MagicMock()
        busy_cd.type = UserStatus.CULTIVATING
        mock_db.ext.get_user_cd.return_value = busy_cd
        success, msg, _result = await boss_manager.challenge_boss("player_001")
        assert not success
        assert "正忙" in msg


# ──────────────────────────────────────────────────────────────────────
# Info and auto-spawn tests
# ──────────────────────────────────────────────────────────────────────


class TestBossInfoAndAutoSpawn:
    """get_boss_info and auto_spawn_boss behavior."""

    @pytest.mark.asyncio
    async def test_get_boss_info_shows_four_attributes(self, boss_manager, mock_db):
        """Boss info displays damage, agility, speed, and armor."""
        boss = Boss(
            boss_id=1,
            boss_name="血魔·筑基境",
            boss_level="筑基",
            hp=352,
            max_hp=352,
            atk=44,
            defense=0,
            stone_reward=100,
        )
        mock_db.ext.get_active_boss.return_value = boss
        success, msg, _boss = await boss_manager.get_boss_info()
        assert success
        assert "伤害" in msg
        assert "身法" in msg
        assert "迅捷" in msg
        assert "护甲" in msg

    @pytest.mark.asyncio
    async def test_get_boss_info_no_boss(self, boss_manager, mock_db):
        """get_boss_info reports no active boss."""
        mock_db.ext.get_active_boss.return_value = None
        success, msg, _boss = await boss_manager.get_boss_info()
        assert not success
        assert "没有Boss" in msg

    @pytest.mark.asyncio
    async def test_auto_spawn_boss_by_average_level(self, boss_manager, mock_db):
        """auto_spawn_boss picks a tier matching the average player level."""
        p1 = Player(user_id="a", level_index=8, hp=100, damage=10)
        p2 = Player(user_id="b", level_index=12, hp=100, damage=10)
        mock_db.get_all_players.return_value = [p1, p2]
        success, _msg, boss = await boss_manager.auto_spawn_boss()
        assert success
        avg = (8 + 12) // 2
        # 练气 level 1 <= 10, 筑基 level 10 <= 15 (avg+5)
        selected = [
            cfg for cfg in boss_manager.levels if cfg["level_index"] <= avg + 5
        ][-1]
        assert boss.boss_level == selected["name"]

    @pytest.mark.asyncio
    async def test_auto_spawn_boss_no_players(self, boss_manager, mock_db):
        """auto_spawn_boss defaults to the lowest tier when no players exist."""
        success, _msg, boss = await boss_manager.auto_spawn_boss()
        assert success
        assert boss.boss_level == boss_manager.levels[0]["name"]

    @pytest.mark.asyncio
    async def test_auto_spawn_boss_refuses_existing(self, boss_manager, mock_db):
        """auto_spawn_boss refuses when a boss already exists."""
        existing = Boss(
            boss_id=1,
            boss_name="existing",
            boss_level="练气",
            hp=100,
            max_hp=100,
            atk=10,
        )
        mock_db.ext.get_active_boss.return_value = existing
        success, msg, boss = await boss_manager.auto_spawn_boss()
        assert not success
        assert "已有Boss" in msg or "存在" in msg
        assert boss is None
