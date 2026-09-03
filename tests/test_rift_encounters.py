"""Tests for the rift encounter mechanics (add-rift-encounters task group 2).

Covers:
- finish_exploration no longer auto-triggers PvE; reward_data["pve_won"] stays
  False; base rewards are never modified by combat;
- _roll_encounters rate resolution (encounter_rate override, top-level
  fallback, non-exclusive simultaneous triggers, zero rates);
- answer_puzzle correct/wrong/invalid branches, attempt exhaustion, no pending;
- accept_beast_challenge win/lose/draw/no-pending/spawn-failure;
- challenge_rift_beast at the PvE layer, incl. the guardian_-prefixed enemy
  win/loss determination regression (design D5: explicit winner compare);
- accept_legacy_challenge win/lose/no-pending flow;
- GM force_* default contexts (design D4).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import load_module

_rift_mod = load_module("rift_manager_enc", "managers/rift_manager.py")
RiftManager = _rift_mod.RiftManager

_pve_mod = load_module("pve_combat_manager_enc", "managers/pve_combat_manager.py")
PVECombatManager = _pve_mod.PVECombatManager
RiftBeastResult = _pve_mod.RiftBeastResult

_cm_mod = load_module("combat_manager_enc", "managers/combat_manager.py")
CombatResult = _cm_mod.CombatResult

_enemy_mod = load_module("enemy_manager_enc", "managers/enemy_manager.py")
Enemy = _enemy_mod.Enemy

_store_mod = load_module("encounter_store_enc", "core/encounter_store.py")
EncounterStore = _store_mod.EncounterStore

_puzzle_mod = load_module("rift_puzzle_manager_enc", "core/rift_puzzle_manager.py")
RiftPuzzle = _puzzle_mod.RiftPuzzle

# The standalone rift shim registers models_extended under this name.
from models_extended import UserStatus  # noqa: E402

# Deterministic base config: all random encounter/legacy triggers off.
_BASE_CFG = {
    "puzzle_rate": 0.0,
    "beast_rate": 0.0,
    "legacy_chance": 0.0,
    "explore_events": [{"desc": "固定事件", "item_chance": 0}],
    "rifts": [],
}


class FakeRiftConfigManager:
    """Minimal ConfigManager stub carrying only what RiftManager reads."""

    def __init__(self, rift_config: dict):
        self.rift_config = rift_config

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"

    def is_pill(self, item_name: str) -> bool:
        return False


def _fake_db_rift(rift_id: int = 1, name: str = "青云秘境"):
    """DB-row stand-in for a rift (attributes + get_rewards)."""
    rift = MagicMock()
    rift.rift_id = rift_id
    rift.rift_name = name
    rift.required_level = 0
    rift.rift_level = 1
    rift.get_rewards.return_value = {"exp": [1000, 1000], "gold": [500, 500]}
    return rift


def _make_finished_rift_db(rift_id: int = 1):
    """DB mock positioned at a finished rift exploration for ``rift_id``."""
    db = MagicMock()
    cd = MagicMock()
    cd.type = UserStatus.EXPLORING
    cd.scheduled_time = 0
    cd.create_time = 0
    cd.get_extra_data.return_value = {"rift_id": rift_id, "rift_level": 1}
    db.ext.get_user_cd = AsyncMock(return_value=cd)
    db.ext.get_rift_by_id = AsyncMock(return_value=_fake_db_rift(rift_id))
    db.ext.set_user_free = AsyncMock()
    db.update_player = AsyncMock()
    player = MagicMock()
    player.user_id = "u1"
    player.user_name = "测试道友"
    player.level_index = 10
    player.experience = 0
    player.gold = 0
    player.hp = 500
    db.get_player_by_id = AsyncMock(return_value=player)
    return db


def _make_storage():
    """StorageRingManager mock that always succeeds storing items."""
    storage = MagicMock()
    storage.store_item = AsyncMock(return_value=(True, ""))
    return storage


def _make_mgr(db, cfg=None, storage=None, pve=None, store=None):
    """RiftManager wired with the deterministic base config."""
    mgr = RiftManager(
        db,
        FakeRiftConfigManager(cfg if cfg is not None else dict(_BASE_CFG)),
        storage,
        pve,
        encounter_store=store,
    )
    return mgr


def _pend_test_puzzle(
    mgr,
    user_id: str = "u1",
    answer: str = "土",
    attempts: int = 2,
    exp_base: int = 1000,
):
    """Pend a hand-built wuxing puzzle so the answer is known upfront."""
    puzzle = RiftPuzzle(
        family="wuxing",
        template="ke_break",
        question_text="题面",
        answer=answer,
        attempts_left=attempts,
    )
    mgr.encounter_store.pend(
        user_id,
        "puzzle",
        {"puzzle": puzzle, "rift_level": 1, "exp_base": exp_base},
        ttl=600,
    )
    return puzzle


# ===== finish_exploration：不再自动 PvE =====


@pytest.mark.asyncio
async def test_finish_exploration_no_auto_pve_and_pve_won_false():
    """结算不触发战斗，基础奖励不被修改，pve_won 恒 False（design D5）。"""
    db = _make_finished_rift_db(1)
    pve = MagicMock()
    mgr = _make_mgr(db, pve=pve)

    success, msg, reward_data = await mgr.finish_exploration("u1")

    assert success
    pve.trigger_pve_combat.assert_not_called()
    assert reward_data["pve_won"] is False
    # 固定区间奖励，无战斗修改（旧失败扣 exp×0.3/gold=0 语义一并移除）
    assert reward_data["exp"] == 1000
    assert reward_data["gold"] == 500
    player = db.get_player_by_id.return_value
    assert player.hp == 500  # 结算不再碰 hp


# ===== _roll_encounters 判定 =====


@pytest.mark.asyncio
async def test_encounter_rate_override_triggers_both_non_exclusive():
    """encounter_rate=1.0 覆盖两类判定且必触发；两类不互斥、同时挂起。"""
    cfg = dict(_BASE_CFG)
    cfg["rifts"] = [{"id": 1, "encounter_rate": 1.0, "enemy_group": "rift_test"}]
    store = EncounterStore()
    mgr = _make_mgr(_make_finished_rift_db(1), cfg=cfg, store=store)

    success, msg, _ = await mgr.finish_exploration("u1")

    assert success
    puzzle_entry = store.get_active("u1", "puzzle")
    beast_entry = store.get_active("u1", "beast")
    assert puzzle_entry is not None
    assert beast_entry is not None
    # 谜题 payload：当次结算修为为基数（design D6）
    assert puzzle_entry.payload["exp_base"] == 1000
    assert puzzle_entry.payload["rift_level"] == 1
    # 妖兽 payload：记录 rift_level 与 enemy_group 供迎战使用（design D5）
    assert beast_entry.payload["rift_level"] == 1
    assert beast_entry.payload["enemy_group"] == "rift_test"
    # 结算消息同时含题面与迎战提示
    assert "🧩" in msg and "探索秘境 破阵" in msg
    assert "⚔️" in msg and "探索秘境 迎战" in msg


@pytest.mark.asyncio
async def test_top_level_rates_apply_without_entry_override():
    """秘境条目无 encounter_rate 时用顶层 puzzle_rate/beast_rate。"""
    cfg = dict(_BASE_CFG, puzzle_rate=1.0, beast_rate=1.0, puzzle_attempts=3)
    store = EncounterStore()
    mgr = _make_mgr(_make_finished_rift_db(1), cfg=cfg, store=store)

    await mgr.finish_exploration("u1")

    puzzle_entry = store.get_active("u1", "puzzle")
    assert puzzle_entry is not None
    assert store.get_active("u1", "beast") is not None
    # 尝试次数来自配置 puzzle_attempts
    assert puzzle_entry.payload["puzzle"].attempts_left == 3


@pytest.mark.asyncio
async def test_zero_rates_trigger_nothing():
    store = EncounterStore()
    mgr = _make_mgr(_make_finished_rift_db(1), store=store)

    success, msg, _ = await mgr.finish_exploration("u1")

    assert success
    assert store.get_active("u1", "puzzle") is None
    assert store.get_active("u1", "beast") is None
    assert "🧩" not in msg and "⚔️" not in msg


@pytest.mark.asyncio
async def test_finish_exploration_pends_legacy_on_chance_hit():
    """命中 legacy_chance → 挂起来源 rift 的传承遭遇，不再内联挑战（design D8）。"""
    cfg = dict(_BASE_CFG, legacy_chance=1.0)
    store = EncounterStore()
    pve = MagicMock()
    mgr = _make_mgr(_make_finished_rift_db(1), cfg=cfg, pve=pve, store=store)
    mgr.impart_mgr = MagicMock()

    success, msg, _ = await mgr.finish_exploration("u1")

    assert success
    pve.challenge_legacy_guardian.assert_not_called()
    entry = store.get_active("u1", "legacy")
    assert entry is not None
    assert entry.payload["source"] == "rift"
    assert entry.payload["legacy_type"] == "rift"
    assert "传承之地" in msg and "探索秘境 传承" in msg


def test_pend_ttl_resolution():
    """TTL：读 config encounter_ttl_seconds，缺键回落 RIFT_CONFIG 默认 600。"""
    mgr = _make_mgr(MagicMock())
    mgr._pend_beast_encounter(SimpleNamespace(user_id="u1"), 1, None)
    entry = mgr.encounter_store.get_active("u1", "beast")
    assert entry.expires_at - entry.created_at == 600

    cfg = dict(_BASE_CFG, encounter_ttl_seconds=5)
    mgr = _make_mgr(MagicMock(), cfg=cfg)
    mgr._pend_beast_encounter(SimpleNamespace(user_id="u1"), 1, None)
    entry = mgr.encounter_store.get_active("u1", "beast")
    assert entry.expires_at - entry.created_at == 5


# ===== answer_puzzle =====


@pytest.mark.asyncio
async def test_answer_puzzle_correct_grants_exp_and_drops():
    db = _make_finished_rift_db(1)
    storage = _make_storage()
    mgr = _make_mgr(db, storage=storage)
    _pend_test_puzzle(mgr, answer="土", attempts=2, exp_base=1000)

    with patch.object(
        mgr, "_roll_rift_drops", new=AsyncMock(return_value=[("灵草", 2)])
    ) as roll:
        ok, msg = await mgr.answer_puzzle("u1", "土")

    assert ok
    player = db.get_player_by_id.return_value
    assert player.experience == 200  # 修为基数 1000 × 0.2
    roll.assert_awaited_once_with(player, 1, 100)
    storage.store_item.assert_awaited_once()
    db.update_player.assert_awaited()
    # 答对后谜题消耗
    assert mgr.encounter_store.get_active("u1", "puzzle") is None
    assert "古阵应声而解" in msg
    assert "+200" in msg and "灵草 x2" in msg


@pytest.mark.asyncio
async def test_answer_puzzle_wrong_consumes_attempt_then_exhausts():
    db = _make_finished_rift_db(1)
    mgr = _make_mgr(db)
    puzzle = _pend_test_puzzle(mgr, answer="土", attempts=2)

    ok, msg = await mgr.answer_puzzle("u1", "金")  # 合法但错误
    assert not ok
    assert "剩余机会：1" in msg
    assert puzzle.attempts_left == 1
    assert mgr.encounter_store.get_active("u1", "puzzle") is not None

    ok, msg = await mgr.answer_puzzle("u1", "金")
    assert not ok
    assert "机会耗尽" in msg
    # 机会耗尽关闭谜题、零惩罚（不发奖励、不落库）
    assert mgr.encounter_store.get_active("u1", "puzzle") is None
    db.update_player.assert_not_called()
    player = db.get_player_by_id.return_value
    assert player.experience == 0


@pytest.mark.asyncio
async def test_answer_puzzle_invalid_form_keeps_attempts():
    db = _make_finished_rift_db(1)
    mgr = _make_mgr(db)
    puzzle = _pend_test_puzzle(mgr, answer="土", attempts=2)

    ok, msg = await mgr.answer_puzzle("u1", "hello")

    assert not ok
    assert "不消耗" in msg
    assert puzzle.attempts_left == 2  # invalid 不耗次数
    assert mgr.encounter_store.get_active("u1", "puzzle") is not None


@pytest.mark.asyncio
async def test_answer_puzzle_no_pending_returns_gone_hint():
    db = _make_finished_rift_db(1)
    mgr = _make_mgr(db)

    ok, msg = await mgr.answer_puzzle("u1", "土")

    assert not ok
    assert "机缘已消散" in msg


@pytest.mark.asyncio
async def test_answer_puzzle_unknown_player():
    db = _make_finished_rift_db(1)
    db.get_player_by_id = AsyncMock(return_value=None)
    mgr = _make_mgr(db)

    ok, msg = await mgr.answer_puzzle("ghost", "土")

    assert not ok
    assert "还未踏入修仙之路" in msg


# ===== accept_beast_challenge =====


@pytest.mark.asyncio
async def test_accept_beast_challenge_win_grants_exp_drops_and_pve_won():
    db = _make_finished_rift_db(1)
    storage = _make_storage()
    pve = MagicMock()
    pve.challenge_rift_beast = AsyncMock(
        return_value=RiftBeastResult(True, False, "战报：胜利", 1234)
    )
    mgr = _make_mgr(db, storage=storage, pve=pve)
    mgr.encounter_store.pend(
        "u1", "beast", {"rift_level": 2, "enemy_group": "rift_test"}, ttl=600
    )

    with patch.object(
        mgr, "_roll_rift_drops", new=AsyncMock(return_value=[("玄铁", 2)])
    ) as roll:
        accepted, msg, data = await mgr.accept_beast_challenge("u1")

    assert accepted
    assert data["pve_won"] is True
    player = db.get_player_by_id.return_value
    # 定向组 key 透传到战斗层
    pve.challenge_rift_beast.assert_awaited_once_with(player, "rift_test")
    assert player.experience == 1234  # 敌人修为入账
    roll.assert_awaited_once_with(player, 2, 100)
    storage.store_item.assert_awaited_once()
    db.update_player.assert_awaited()
    assert mgr.encounter_store.get_active("u1", "beast") is None  # 机缘消耗
    assert "战报：胜利" in msg and "+1,234" in msg and "玄铁 x2" in msg


@pytest.mark.asyncio
async def test_accept_beast_challenge_loss_consumes_without_rewards():
    db = _make_finished_rift_db(1)
    pve = MagicMock()
    pve.challenge_rift_beast = AsyncMock(
        return_value=RiftBeastResult(False, False, "战报：战败", 1234)
    )
    mgr = _make_mgr(db, pve=pve)
    mgr.encounter_store.pend(
        "u1", "beast", {"rift_level": 1, "enemy_group": None}, ttl=600
    )

    with patch.object(mgr, "_roll_rift_drops", new=AsyncMock()) as roll:
        accepted, msg, data = await mgr.accept_beast_challenge("u1")

    assert accepted
    assert data["pve_won"] is False
    roll.assert_not_awaited()  # 失败无掉落
    player = db.get_player_by_id.return_value
    assert player.experience == 0  # 敌人修为不入账
    db.update_player.assert_awaited()  # hp=1（战斗层写回）落库
    assert mgr.encounter_store.get_active("u1", "beast") is None  # 机缘消耗
    assert "战报：战败" in msg and "机缘已消耗" in msg


@pytest.mark.asyncio
async def test_accept_beast_challenge_draw_treated_as_loss():
    db = _make_finished_rift_db(1)
    pve = MagicMock()
    pve.challenge_rift_beast = AsyncMock(
        return_value=RiftBeastResult(False, True, "战报：平手", 1234)
    )
    mgr = _make_mgr(db, pve=pve)
    mgr.encounter_store.pend(
        "u1", "beast", {"rift_level": 1, "enemy_group": None}, ttl=600
    )

    accepted, msg, data = await mgr.accept_beast_challenge("u1")

    assert accepted
    assert data["pve_won"] is False  # 平局视同挑战失败
    assert mgr.encounter_store.get_active("u1", "beast") is None
    player = db.get_player_by_id.return_value
    assert player.experience == 0


@pytest.mark.asyncio
async def test_accept_beast_challenge_no_pending_returns_gone_hint():
    db = _make_finished_rift_db(1)
    pve = MagicMock()
    mgr = _make_mgr(db, pve=pve)

    accepted, msg, data = await mgr.accept_beast_challenge("u1")

    assert not accepted
    assert data["pve_won"] is False
    assert "机缘已消散" in msg
    pve.challenge_rift_beast.assert_not_called()


@pytest.mark.asyncio
async def test_accept_beast_challenge_spawn_failure_keeps_pending():
    """敌人生成失败属系统异常：机缘保留，可稍后重试。"""
    db = _make_finished_rift_db(1)
    pve = MagicMock()
    pve.challenge_rift_beast = AsyncMock(return_value=None)
    mgr = _make_mgr(db, pve=pve)
    mgr.encounter_store.pend(
        "u1", "beast", {"rift_level": 1, "enemy_group": "rift_test"}, ttl=600
    )

    accepted, msg, data = await mgr.accept_beast_challenge("u1")

    assert not accepted
    assert data["pve_won"] is False
    assert "异常" in msg
    assert mgr.encounter_store.get_active("u1", "beast") is not None


# ===== challenge_rift_beast（PvE 层，含 guardian_ 前缀判定回归） =====


def _make_pve_env():
    """PVECombatManager with a mocked engine and a guardian_-prefixed enemy."""
    engine = MagicMock()
    engine.build_fighter_from_player = AsyncMock(
        side_effect=lambda p: MagicMock(user_id=p.user_id)
    )
    enemy_mgr = MagicMock()
    guardian = Enemy(
        user_id="guardian_stone_golem_1_ab12",
        name="石傀儡",
        hp=100,
        max_hp=100,
        damage=10,
        agility=5,
        speed=5,
        armor_value=0,
        exp=1234,
        crit_rate=0,
    )
    enemy_mgr.spawn_enemy_from_group.return_value = guardian
    pve = PVECombatManager(MagicMock(engine=engine), enemy_mgr)
    return pve, engine, enemy_mgr, guardian


def _combat_result(winner: str, player_hp: int = 300) -> CombatResult:
    return CombatResult(
        winner=winner,
        combat_log=["第1回合"],
        fighter1_final_hp=player_hp,
        fighter2_final_hp=0,
        rounds=1,
        total_actions=1,
    )


@pytest.mark.asyncio
async def test_challenge_rift_beast_directed_group_win():
    pve, engine, enemy_mgr, guardian = _make_pve_env()
    engine.resolve_combat.return_value = _combat_result("player_001")
    player = SimpleNamespace(user_id="player_001", level_index=10, hp=500)

    outcome = await pve.challenge_rift_beast(player, "rift_test")

    enemy_mgr.spawn_enemy_from_group.assert_called_once_with("rift_test", 10)
    enemy_mgr.spawn_enemy.assert_not_called()
    assert outcome.won is True and outcome.draw is False
    assert outcome.enemy_exp == 1234
    assert player.hp == 300  # 胜利按战斗结果写回
    assert "石傀儡" in outcome.battle_msg


@pytest.mark.asyncio
async def test_challenge_rift_beast_guardian_prefixed_enemy_win_is_loss():
    """回归：定向组敌人 user_id 是 guardian_ 前缀——enemy_ 前缀判定会把
    定向组获胜误判为玩家胜利（design D5），必须显式比较 winner。"""
    pve, engine, _, guardian = _make_pve_env()
    engine.resolve_combat.return_value = _combat_result(guardian.user_id, player_hp=0)
    player = SimpleNamespace(user_id="player_001", level_index=10, hp=500)

    outcome = await pve.challenge_rift_beast(player, "rift_test")

    assert outcome.won is False
    assert outcome.draw is False
    assert player.hp == 1  # 失败不致死但气血降为 1


@pytest.mark.asyncio
async def test_challenge_rift_beast_draw_is_not_a_win():
    pve, engine, _, _ = _make_pve_env()
    engine.resolve_combat.return_value = _combat_result("draw", player_hp=0)
    player = SimpleNamespace(user_id="player_001", level_index=10, hp=500)

    outcome = await pve.challenge_rift_beast(player, "rift_test")

    assert outcome.won is False
    assert outcome.draw is True  # 平局单列
    assert player.hp == 1


@pytest.mark.asyncio
async def test_challenge_rift_beast_fallback_to_global_pool():
    """无 enemy_group 时回落全局池，类别走秘境 low 难度分布（design D5）。"""
    pve, engine, enemy_mgr, _ = _make_pve_env()
    wolf = Enemy(
        user_id="enemy_wolf",
        name="疾风狼",
        hp=100,
        max_hp=100,
        damage=10,
        agility=5,
        speed=5,
        armor_value=0,
        exp=55,
        crit_rate=0,
    )
    enemy_mgr.spawn_enemy.return_value = wolf
    engine.resolve_combat.return_value = _combat_result("player_001")
    player = SimpleNamespace(user_id="player_001", level_index=10, hp=500)

    with patch.object(pve, "_select_enemy_category", return_value="normal") as sel:
        outcome = await pve.challenge_rift_beast(player, None)

    sel.assert_called_once_with("rift", "low")
    enemy_mgr.spawn_enemy.assert_called_once_with(10, "normal")
    enemy_mgr.spawn_enemy_from_group.assert_not_called()
    assert outcome.won is True
    assert outcome.enemy_exp == 55


@pytest.mark.asyncio
async def test_challenge_rift_beast_spawn_failure_returns_none():
    pve, _, enemy_mgr, _ = _make_pve_env()
    enemy_mgr.spawn_enemy_from_group.side_effect = ValueError("未知的定向敌人组")
    player = SimpleNamespace(user_id="player_001", level_index=10, hp=500)

    assert await pve.challenge_rift_beast(player, "rift_test") is None


# ===== accept_legacy_challenge =====


def _make_legacy_mgr(db, guardian_won: bool):
    """RiftManager wired with a stub guardian fight and a stub impart manager."""
    pve = MagicMock()
    pve.challenge_legacy_guardian = AsyncMock(
        return_value=(guardian_won, "守护者战斗详情")
    )
    impart = MagicMock()
    impart.create_legacy = AsyncMock(return_value=SimpleNamespace(id=42))
    impart.get_type_name = MagicMock(return_value="历练传承")
    mgr = _make_mgr(db, pve=pve)
    mgr.impart_mgr = impart
    return mgr, pve, impart


@pytest.mark.asyncio
async def test_accept_legacy_challenge_win_creates_legacy_by_pending_type():
    db = _make_finished_rift_db(1)
    mgr, _, impart = _make_legacy_mgr(db, guardian_won=True)
    mgr.encounter_store.pend(
        "u1", "legacy", {"legacy_type": "adventure", "source": "adventure"}, ttl=600
    )

    won, msg = await mgr.accept_legacy_challenge("u1")

    assert won
    # 按 pending 记录的 legacy_type 建实例，不自动激活（design D8）
    impart.create_legacy.assert_awaited_once_with("u1", "adventure", activate=False)
    db.update_player.assert_awaited()  # 守护战 hp 写回落库
    assert mgr.encounter_store.get_active("u1", "legacy") is None  # 机缘消耗
    # 沿用 legacy_encounter 模板簇 encounter_win 文案
    assert "战胜了守护者" in msg
    assert "获得【历练传承】#42" in msg
    assert not msg.startswith("\n")  # 独立回复无前导空行


@pytest.mark.asyncio
async def test_accept_legacy_challenge_lose_consumes_without_legacy():
    db = _make_finished_rift_db(1)
    mgr, _, impart = _make_legacy_mgr(db, guardian_won=False)
    mgr.encounter_store.pend(
        "u1", "legacy", {"legacy_type": "rift", "source": "rift"}, ttl=600
    )

    won, msg = await mgr.accept_legacy_challenge("u1")

    assert not won
    impart.create_legacy.assert_not_called()
    db.update_player.assert_awaited()
    assert mgr.encounter_store.get_active("u1", "legacy") is None  # 机缘消耗
    assert "未能战胜守护者" in msg


@pytest.mark.asyncio
async def test_accept_legacy_challenge_no_pending_returns_gone_hint():
    db = _make_finished_rift_db(1)
    mgr, pve, _ = _make_legacy_mgr(db, guardian_won=True)

    won, msg = await mgr.accept_legacy_challenge("u1")

    assert not won
    assert "机缘已消散" in msg
    pve.challenge_legacy_guardian.assert_not_called()


# ===== GM 强制触发（缺省上下文，design D4） =====


@pytest.mark.asyncio
async def test_force_puzzle_encounter_defaults_and_returns_question():
    db = _make_finished_rift_db(1)
    mgr = _make_mgr(db)

    ok, msg = await mgr.force_puzzle_encounter("u1")

    assert ok
    entry = mgr.encounter_store.get_active("u1", "puzzle")
    assert entry is not None
    assert entry.payload["rift_level"] == 1
    assert entry.payload["exp_base"] == 1000  # 秘境 1 级 exp_range 固定 [1000,1000]
    # GM 需要看到题面
    assert entry.payload["puzzle"].question_text in msg


@pytest.mark.asyncio
async def test_force_beast_encounter_defaults():
    db = _make_finished_rift_db(1)
    mgr = _make_mgr(db)

    ok, msg = await mgr.force_beast_encounter("u1")

    assert ok
    entry = mgr.encounter_store.get_active("u1", "beast")
    assert entry is not None
    assert entry.payload["rift_level"] == 1
    assert entry.payload["enemy_group"] is None  # 回落全局池
    assert "迎战" in msg


@pytest.mark.asyncio
async def test_force_legacy_encounter_defaults():
    db = _make_finished_rift_db(1)
    mgr = _make_mgr(db)

    ok, msg = await mgr.force_legacy_encounter("u1")

    assert ok
    entry = mgr.encounter_store.get_active("u1", "legacy")
    assert entry is not None
    assert entry.payload["legacy_type"] == "rift"
    assert entry.payload["source"] == "rift"
    assert "传承" in msg


@pytest.mark.asyncio
async def test_force_encounters_unknown_player():
    db = _make_finished_rift_db(1)
    db.get_player_by_id = AsyncMock(return_value=None)
    mgr = _make_mgr(db)

    for force in (
        mgr.force_puzzle_encounter,
        mgr.force_beast_encounter,
        mgr.force_legacy_encounter,
    ):
        ok, msg = await force("ghost")
        assert not ok
        assert "尚未踏入修仙之路" in msg
