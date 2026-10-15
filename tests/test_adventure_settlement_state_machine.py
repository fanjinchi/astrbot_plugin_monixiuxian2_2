"""Child C (10-10-pve-adventure-settlement) 历练结算状态机验收测试。

覆盖 design §7 要求的验收面：

- AC1 结算单：开始历练即落 ``adventuring`` 行、``adventure_run_id`` 每轮唯一、
  历史在途单在 ``finish_adventure`` 补建，绝不产生第二条事实。
- AC2 高/极高风险遇敌停在 ``pending_choice``，「迎战」「逃跑」两个出口；未抉择
  不发任何奖励、保留忙碌；``flee.enabled=false``（kill switch）时不产生 pending。
- AC3 逃跑公式锚点（身法相当→95%、2 倍→100%、一半→60% 保底）。
- AC4 掉落跟随胜败（战败不掉落）；气血只跟随引擎终值，战败按动态上限 1% 保底。
- AC5 重放/并发不重复发奖，重放不推进悬赏与师承进度（``reward_data=None``）。
- AC6 全局休整窗口（乙案：跨路线同样拦、重启照拦）、战败额外休整、忙碌期照旧回血。
- AC7 崩溃点恢复（推进后崩溃 / 提交后未 claim）、事务原子性、效果故障可见。

真库测试：本文件用真实 ``DataBase(":memory:")`` + 真实 ``AdventureManager``——
状态机与幂等恰恰是最不能在 mock 数据库上验的东西。时间一律用真实时钟配合
直接改写 ``user_cd`` 时间戳，不 sleep。
"""

import asyncio
import json
import math
import random
import sqlite3
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from tests.helpers import load_module, load_package_module, make_busy_state

_adv_mod = load_module("adventure_manager_settle", "managers/adventure_manager.py")
AdventureManager = _adv_mod.AdventureManager
DEFAULT_FLEE_PARAMS = _adv_mod.DEFAULT_FLEE_PARAMS
DEFEAT_FATIGUE_EXTRA_SECONDS = _adv_mod.DEFEAT_FATIGUE_EXTRA_SECONDS
DEFEAT_HP_FLOOR_RATIO = _adv_mod.DEFEAT_HP_FLOOR_RATIO
TIME_SKIP_ENTRIES = _adv_mod.TIME_SKIP_ENTRIES
compute_flee_chance = _adv_mod.compute_flee_chance

_pve_mod = load_module("pve_combat_manager_settle", "managers/pve_combat_manager.py")
PVECombatManager = _pve_mod.PVECombatManager

_combat_mod = load_module("combat_manager_settle", "managers/combat_manager.py")
CombatResult = _combat_mod.CombatResult
FighterState = _combat_mod.FighterState
CombatEngine = _combat_mod.CombatEngine

_enemy_mod = load_module("enemy_manager_settle", "managers/enemy_manager.py")
Enemy = _enemy_mod.Enemy

_data_mod = load_package_module(
    "data/data_manager.py", "astrbot_plugin_monixiuxian2_2.data.data_manager"
)
DataBase = _data_mod.DataBase

_migration_mod = load_package_module(
    "data/migration.py", "astrbot_plugin_monixiuxian2_2.data.migration"
)
MigrationManager = _migration_mod.MigrationManager

_repo_mod = load_package_module(
    "data/pve_repository.py", "astrbot_plugin_monixiuxian2_2.data.pve_repository"
)
AdventureRepository = _repo_mod.AdventureRepository
snapshot_text = _repo_mod.snapshot_text
STATE_ADVENTURING = _repo_mod.STATE_ADVENTURING
STATE_PENDING_CHOICE = _repo_mod.STATE_PENDING_CHOICE
STATE_READY_COMBAT = _repo_mod.STATE_READY_COMBAT
STATE_RESOLVED_WIN = _repo_mod.STATE_RESOLVED_WIN
STATE_RESOLVED_LOSS = _repo_mod.STATE_RESOLVED_LOSS
STATE_RESOLVED_FLED = _repo_mod.STATE_RESOLVED_FLED

_models_mod = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models")
Player = _models_mod.Player

_me_mod = load_package_module(
    "models_extended.py", "astrbot_plugin_monixiuxian2_2.models_extended"
)
UserStatus = _me_mod.UserStatus

_health_mod = load_package_module(
    "core/health.py", "astrbot_plugin_monixiuxian2_2.core.health"
)
HealthService = _health_mod.HealthService

_eq_mod = load_package_module(
    "core/equipment_manager.py", "astrbot_plugin_monixiuxian2_2.core.equipment_manager"
)
EquipmentManager = _eq_mod.EquipmentManager

_utils_mod = load_package_module(
    "handlers/utils.py", "astrbot_plugin_monixiuxian2_2.handlers.utils"
)
_busy_mod = load_package_module(
    "core/busy_state.py", "astrbot_plugin_monixiuxian2_2.core.busy_state"
)
BUSY_STATE_ALLOWED_COMMANDS = _utils_mod.BUSY_STATE_ALLOWED_COMMANDS
_is_command_allowed = _utils_mod._is_command_allowed
_pending_choice_hint = _utils_mod.pending_choice_hint

USER = "settle-user"

# 路线数值：有效时长固定 600 秒 = 10 分钟 → 基础收益 1000 修为 / 200 灵石；
# 敌人固定 200 修为本体（bonus_exp），胜利倍率 1.2，战败 0.3 且灵石归零。
BASE_EXP = 1000
BASE_GOLD = 200
WIN_EXP = int(BASE_EXP * 1.2) + 200
LOSE_EXP = int(BASE_EXP * 0.3)
LOW_ROUTE = "probe_low"
HIGH_ROUTE = "probe_high"
LOW_FATIGUE = 300
HIGH_FATIGUE = 900


class StubConfigManager:
    """Config-manager stand-in exposing only what migration/health read."""

    def __init__(self):
        self.items_data = {}
        self.weapons_data = {}
        self.heart_methods_data = {}
        # CombatEngine 构造时读这两段（真实引擎用例要用）；空段即全部走默认值。
        self.game_config: dict = {}


class ScriptedEngine:
    """Combat engine double with a scripted winner that *consumes* global RNG.

    故意从全局随机流取一个值并写进战报：历练结算的确定性必须证明「同一份
    snapshot 重放出同一份战报」（``_roll_combat`` 的 save→seed→restore 窗口），
    返回常量的替身验不出这件事。
    """

    def __init__(self, *, outcome="win", final_hp=500, player_agility=100):
        self.outcome = outcome
        self.final_hp = final_hp
        self.player_agility = player_agility
        self.calls = 0
        self.probes = []

    async def build_fighter_from_player(self, player):
        """Map the player onto a FighterState carrying the scripted 身法."""
        return FighterState(
            user_id=player.user_id,
            name=player.user_name or player.user_id,
            hp=int(player.current_hp or 0),
            max_hp=int(player.base_hp or 0),
            damage=100,
            agility=self.player_agility,
            speed=50,
            armor_value=0,
        )

    def resolve_combat(self, fighter1, fighter2, combat_type="pve"):
        """Return the scripted result, stamped with a global-RNG probe."""
        self.calls += 1
        probe = random.random()
        self.probes.append(probe)
        side = {"win": "fighter1", "lose": "fighter2", "draw": "draw"}[self.outcome]
        winner_id = {
            "fighter1": fighter1.user_id,
            "fighter2": fighter2.user_id,
            "draw": None,
        }[side]
        return CombatResult(
            winner_side=side,
            winner_id=winner_id,
            combat_log=[f"⚔️ 第 1 回合交手（{probe:.12f}）"],
            fighter1_final_hp=self.final_hp,
            fighter2_final_hp=0,
            rounds=1,
            total_actions=2,
        )


class FakeEnemyMgr:
    """EnemyManager double returning a fixed-stat roster enemy."""

    def __init__(self, *, name="噬骨妖狼", agility=100, exp=200):
        self.name = name
        self.agility = agility
        self.exp = exp
        self.spawned = 0

    def spawn_enemy(self, player_level, category):
        """Spawn the scripted enemy and count the roll."""
        self.spawned += 1
        return Enemy(
            user_id=f"enemy:{self.spawned}",
            name=self.name,
            hp=1000,
            max_hp=1000,
            damage=100,
            agility=self.agility,
            speed=50,
            armor_value=0,
            exp=self.exp,
            level_index=player_level,
        )


def _route(key, risk, *, fatigue, drop_tier="low"):
    """Build one minimal route config entry for the settlement harness."""
    return {
        "key": key,
        "name": f"{key}线",
        "description": "测试路线",
        "risk": risk,
        "duration": 600,
        "min_level": 0,
        "base_exp_per_min": 100,
        "base_gold_per_min": 20,
        "level_bonus_exp": 0,
        "level_bonus_gold": 0,
        "completion_bonus": {"exp": 0, "gold": 0},
        "fatigue_cooldown": fatigue,
        "drop_tier": drop_tier,
        "bounty_tag": f"bounty_{key}",
        "bounty_progress": 1,
        "event_weights": {"standard": 100},
    }


def _event(item_chance=0, injury=False):
    """Build one deterministic event (item_chance=0 keeps drops off)."""
    event = {
        "key": "calm",
        "name": "风平浪静",
        "desc": "一路无事，安然归来。",
        "exp_mult": 1.0,
        "gold_mult": 1.0,
        "item_chance": item_chance,
        "bonus_progress": 0,
    }
    if injury:
        event["injury"] = True
    return event


class Env:
    """Wiring bundle: database + manager + doubles for one test."""

    def __init__(self, db, mgr, engine, enemy_mgr, ring, health):
        self.db = db
        self.mgr = mgr
        self.engine = engine
        self.enemy_mgr = enemy_mgr
        self.ring = ring
        self.health = health

    @property
    def repo(self):
        """A settlement repository over the live connection (per-use)."""
        return AdventureRepository(self.db.conn)

    async def settlement_id(self):
        """Return the newest settlement id of the test player ('' when none)."""
        async with self.db.conn.execute(
            "SELECT settlement_id FROM adventure_settlements WHERE user_id = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (USER,),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else ""

    async def row(self):
        """Return the newest settlement row as a dict (``None`` when absent)."""
        sid = await self.settlement_id()
        if not sid:
            return None
        return await self.repo.get_settlement(sid)

    async def snapshot(self):
        """Return the locked snapshot dict of the newest settlement."""
        return json.loads(snapshot_text((await self.row())["snapshot"]))

    async def claims(self):
        """Return the effect-claim rows of the newest settlement."""
        sid = await self.settlement_id()
        if not sid:
            return []
        return await self.repo.list_effect_claims(sid)

    async def player(self):
        """Return the persisted player object."""
        return await self.db.get_player_by_id(USER)

    async def fatigue_until(self):
        """Return the persisted global fatigue deadline (0 when none)."""
        row = await self.repo.get_fatigue(USER)
        return int((row or {}).get("fatigue_until") or 0)

    async def user_cd_type(self):
        """Return the persisted ``user_cd.type`` (None when no row)."""
        cd = await self.db.ext.get_user_cd(USER)
        return None if cd is None else int(cd.type)

    async def set_hp(self, current, anchor=None):
        """Rewrite persisted 气血 / recovery anchor behind the manager's back."""
        if anchor is None:
            await self.db.conn.execute(
                "UPDATE players SET current_hp = ? WHERE user_id = ?",
                (current, USER),
            )
        else:
            await self.db.conn.execute(
                "UPDATE players SET current_hp = ?, health_recovered_at = ? "
                "WHERE user_id = ?",
                (current, anchor, USER),
            )
        await self.db.conn.commit()


def _configure(mgr):
    """Install the deterministic routes / events / drops the harness relies on."""
    mgr.routes = {
        LOW_ROUTE: _route(LOW_ROUTE, "低", fatigue=LOW_FATIGUE),
        HIGH_ROUTE: _route(HIGH_ROUTE, "高", fatigue=HIGH_FATIGUE),
    }
    mgr.default_route_key = LOW_ROUTE
    mgr.route_alias_index = {key: key for key in mgr.routes}
    mgr.event_groups = {"standard": [_event()]}
    mgr.drop_tables = {
        "low": [{"name": "灵草", "weight": 100, "min": 1, "max": 1}],
        "mid": [{"name": "妖丹", "weight": 100, "min": 1, "max": 1}],
        "high": [{"name": "残页", "weight": 100, "min": 1, "max": 1}],
    }
    mgr.legacy_chance = 0.0


def build_env(db, *, outcome="win", final_hp=500, player_agility=100, enemy_agility=100):
    """Assemble a real AdventureManager over the shared in-memory database.

    Args:
        db: 已建好最新 schema 的 ``DataBase``。
        outcome: 脚本战斗结果（``win``/``lose``/``draw``）。
        final_hp: 引擎给出的玩家终值气血。
        player_agility: 玩家参战身法（逃跑概率的分子）。
        enemy_agility: 敌人身法（逃跑概率的分母）。

    Returns:
        :class:`Env`。
    """
    engine = ScriptedEngine(
        outcome=outcome, final_hp=final_hp, player_agility=player_agility
    )
    enemy_mgr = FakeEnemyMgr(agility=enemy_agility)
    pve = PVECombatManager(engine, enemy_mgr)
    # 遭遇必触发：让「有没有仗打」由测试决定，而不是靠随机数赌
    pve._should_trigger_combat = lambda scene, difficulty: True
    pve._select_enemy_category = lambda scene, difficulty: "normal"
    ring = MagicMock()
    ring.store_item = AsyncMock(return_value=(True, ""))
    health = HealthService(
        db, StubConfigManager(), equipment_manager=EquipmentManager(db=None)
    )
    mgr = AdventureManager(db, ring, pve, busy_state=make_busy_state(db), health_service=health)
    _configure(mgr)
    return Env(db, mgr, engine, enemy_mgr, ring, health)


@pytest_asyncio.fixture
async def db():
    """Real in-memory database on the latest schema, with one 练气玩家."""
    database = DataBase(":memory:")
    await database.connect()
    await MigrationManager(database.conn, StubConfigManager()).migrate_or_reset()
    await database.create_player(
        Player(
            user_id=USER,
            user_name="结算测试",
            level_index=12,
            cultivation_type="体修",
            base_hp=1000,
            current_hp=1000,
            experience=0,
            gold=0,
            agility=100,
        )
    )
    yield database
    await database.close()


@pytest_asyncio.fixture
async def env(db):
    """Manager harness whose scripted engine wins by default."""
    return build_env(db)


async def start_run(mgr, route=LOW_ROUTE):
    """Start a run and rewind its clock so the route counts as finished.

    时长回拨 600 秒（``create_time``）并把到期时间挪到过去（``scheduled_time``），
    使 ``finish_adventure`` 的「尚未完成」闸门通过，同时有效时长按计划时长取整
    ——测试因此不需要 sleep。
    """
    # 同一玩家在一场用例里跑多场：上一场留下的休整与本场无关，先抹掉。
    await mgr.db.conn.execute(
        "DELETE FROM adventure_fatigue WHERE user_id = ?", (USER,)
    )
    await mgr.db.conn.commit()
    ok, msg = await mgr.start_adventure(USER, route)
    assert ok, msg
    now = int(time.time())
    await mgr.db.conn.execute(
        "UPDATE user_cd SET create_time = ?, scheduled_time = ? WHERE user_id = ?",
        (now - 601, now - 1, USER),
    )
    await mgr.db.conn.commit()
    return msg


# ---------------------------------------------------------------------------
# AC3 — 逃跑概率公式（design §3 锚点；数值未封板见 bd monixiuxian2-2/-9hq）
# ---------------------------------------------------------------------------


def test_flee_chance_formula_anchors():
    """PRD AC3 anchors: 身法相当→95%、两倍→100%、一半→60% 保底."""
    assert compute_flee_chance(100, 100) == pytest.approx(0.95)
    assert compute_flee_chance(200, 100) == pytest.approx(1.00)
    assert compute_flee_chance(50, 100) == pytest.approx(0.60)


def test_flee_chance_monotonic_and_clamped():
    """概率随身法单调上升，且始终落在 [floor, cap]；脏数据不抛异常."""
    samples = [compute_flee_chance(a, 100) for a in (1, 10, 30, 50, 100, 150, 200, 900)]
    assert samples == sorted(samples)
    assert min(samples) >= DEFAULT_FLEE_PARAMS["floor"]
    assert max(samples) <= DEFAULT_FLEE_PARAMS["cap"]
    # 敌方身法非正（脏数据）→ 直接封顶，不做除法
    assert compute_flee_chance(1, 0) == pytest.approx(DEFAULT_FLEE_PARAMS["cap"])


def test_flee_config_missing_section_keeps_temporary_defaults():
    """配置缺段/坏值时整段回退临时默认，而不是把功能关掉（fail-closed 到默认）."""
    assert AdventureManager._parse_flee_params({}) == dict(DEFAULT_FLEE_PARAMS)
    assert AdventureManager._parse_flee_params({})["enabled"] is True
    broken = {"flee": {"enabled": True, "base_rate": "0.95"}}
    assert AdventureManager._parse_flee_params(broken) == dict(DEFAULT_FLEE_PARAMS)
    full = {
        "flee": {
            "enabled": True,
            "base_rate": 0.5,
            "slope_up": 0.1,
            "slope_down": 0.2,
            "floor": 0.1,
            "cap": 0.9,
        }
    }
    assert AdventureManager._parse_flee_params(full)["base_rate"] == 0.5


# ---------------------------------------------------------------------------
# AC1 — 结算单与状态机主路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_adventuring_row_with_unique_run_id(env):
    """开始历练即落 ``adventuring`` 行；每轮 run id 唯一（PRD R1）."""
    await start_run(env.mgr, LOW_ROUTE)
    row = await env.row()
    assert row["state"] == STATE_ADVENTURING
    assert row["route_key"] == LOW_ROUTE
    assert row["adventure_run_id"].startswith(f"adventure:{USER}:")
    assert row["outcome"] == ""

    ok, msg, reward_data = await env.mgr.resolve_adventure_choice(USER, flee=True)
    assert not ok and reward_data is None
    assert "还没有完成" in msg
    assert (await env.row())["state"] == STATE_ADVENTURING

    await env.mgr.finish_adventure(USER)
    first_run = row["adventure_run_id"]
    assert await env.mgr.clear_fatigue(USER) is True
    await start_run(env.mgr, LOW_ROUTE)
    second = await env.row()
    assert second["adventure_run_id"] != first_run


@pytest.mark.asyncio
async def test_low_risk_finish_settles_win_without_pending(env):
    """低风险不停在抉择：直接 ``resolved_win``；未触发战斗不产生击败事实."""
    env.mgr.pve_combat_mgr._should_trigger_combat = lambda scene, difficulty: False
    await start_run(env.mgr, LOW_ROUTE)
    ok, msg, reward_data = await env.mgr.finish_adventure(USER)
    assert ok and "历练归来" in msg
    row = await env.row()
    assert row["state"] == STATE_RESOLVED_WIN
    assert row["outcome"] == "win"
    assert int(row["defeated"]) == 0 and int(row["fled"]) == 0
    assert reward_data["pve_won"] is False
    assert reward_data["exp_reward"] == BASE_EXP
    assert await env.user_cd_type() == int(UserStatus.IDLE)
    player = await env.player()
    assert player.experience == BASE_EXP and player.gold == BASE_GOLD
    # 三项效果各自 claim 恰好一次
    claims = await env.claims()
    assert len(claims) == 3
    assert {c["effect_type"] for c in claims} == {
        "base_reward",
        "route_drops",
        "legacy_trigger",
    }


@pytest.mark.asyncio
async def test_finish_backfills_missing_run_row(env):
    """历史在途单（改动前就开跑的忙碌行 / 开始插入失败）补建同一张事实."""
    await start_run(env.mgr, LOW_ROUTE)
    sid = await env.settlement_id()
    await env.db.conn.execute(
        "DELETE FROM adventure_effects WHERE settlement_id = ?", (sid,)
    )
    await env.db.conn.execute(
        "DELETE FROM adventure_settlements WHERE settlement_id = ?", (sid,)
    )
    await env.db.conn.commit()
    assert await env.row() is None

    ok, msg, reward_data = await env.mgr.finish_adventure(USER)
    assert ok, msg
    assert (await env.row())["state"] == STATE_RESOLVED_WIN
    assert reward_data is not None
    assert (await env.player()).experience == WIN_EXP

    await env.mgr.finish_adventure(USER)
    async with env.db.conn.execute(
        "SELECT COUNT(*) FROM adventure_settlements WHERE user_id = ?", (USER,)
    ) as cursor:
        count = (await cursor.fetchone())[0]
    assert count == 1
    assert (await env.player()).experience == WIN_EXP


@pytest.mark.asyncio
async def test_state_check_constraint_rejects_unknown_state(env):
    """``state`` 的 CHECK 约束就是取值域守卫（SQLite 原生拦截非法值）."""
    with pytest.raises(sqlite3.IntegrityError):
        await env.db.conn.execute(
            "INSERT INTO adventure_settlements "
            "(settlement_id, adventure_run_id, user_id, state) "
            "VALUES ('s-bad', 'r-bad', ?, 'bogus_state')",
            (USER,),
        )
    await env.db.conn.rollback()


# ---------------------------------------------------------------------------
# AC2 — pending_choice 与「迎战 / 逃跑」两个出口
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_high_risk_finish_parks_pending_and_grants_nothing(env):
    """高风险遇敌停在 pending：提示敌人身份与两个出口，零发奖、保留忙碌."""
    await start_run(env.mgr, HIGH_ROUTE)
    ok, msg, reward_data = await env.mgr.finish_adventure(USER)
    assert ok and reward_data is None
    assert "迎战" in msg and "逃跑" in msg
    assert "噬骨妖狼" in msg  # 甲案①：内联敌人身份
    assert "不会结算" in msg

    row = await env.row()
    assert row["state"] == STATE_PENDING_CHOICE
    assert await env.claims() == []
    assert (await env.player()).experience == 0
    assert await env.fatigue_until() == 0
    assert await env.user_cd_type() == int(UserStatus.ADVENTURING)
    assert env.enemy_mgr.spawned == 1

    # 再点「完成历练」只重放同一份锁定：不重掷敌人、不发奖
    first_snapshot = row["snapshot"]
    ok2, msg2, reward2 = await env.mgr.finish_adventure(USER)
    assert ok2 and "迎战" in msg2 and reward2 is None
    assert (await env.row())["snapshot"] == first_snapshot
    assert env.enemy_mgr.spawned == 1
    assert (await env.player()).experience == 0


@pytest.mark.asyncio
async def test_pending_fight_grants_once_and_replay_is_inert(env):
    """迎战→``resolved_win``+发奖；终态后再点既不再发奖也不重开战斗（AC5）."""
    await start_run(env.mgr, HIGH_ROUTE)
    await env.mgr.finish_adventure(USER)

    ok, msg, reward_data = await env.mgr.resolve_adventure_choice(USER, flee=False)
    assert ok, msg
    row = await env.row()
    assert row["state"] == STATE_RESOLVED_WIN
    assert int(row["defeated"]) == 1
    assert await env.user_cd_type() == int(UserStatus.IDLE)
    assert (await env.player()).experience == WIN_EXP
    assert reward_data["pve_won"] is True
    assert len(await env.claims()) == 3
    fights_before = env.engine.calls

    # 忙碌行随终态一起清：重复「完成历练」只会被普通拒绝，claim 一条不增。
    ok2, msg2, reward2 = await env.mgr.finish_adventure(USER)
    assert not ok2 and "不在历练中" in msg2 and reward2 is None
    assert (await env.player()).experience == WIN_EXP
    assert len(await env.claims()) == 3

    # 重复「迎战」同理：只查未终结的单子，找不到就说没有。
    ok3, msg3, reward3 = await env.mgr.resolve_adventure_choice(USER, flee=False)
    assert not ok3 and "没有待抉择" in msg3 and reward3 is None
    assert env.engine.calls == fights_before
    assert (await env.player()).experience == WIN_EXP


@pytest.mark.asyncio
async def test_pending_choice_survives_restart(env):
    """进程重启后 pending 仍在：同一张单子、同一只敌人、不重掷."""
    await start_run(env.mgr, HIGH_ROUTE)
    await env.mgr.finish_adventure(USER)
    snapshot_before = (await env.row())["snapshot"]

    revived = build_env(env.db)
    ok, msg, reward_data = await revived.mgr.finish_adventure(USER)
    assert ok and reward_data is None and "迎战" in msg
    assert (await env.row())["snapshot"] == snapshot_before
    assert revived.enemy_mgr.spawned == 0


@pytest.mark.asyncio
async def test_kill_switch_skips_pending_entirely(env):
    """``flee.enabled=false`` 不产生 pending（人工 kill switch，design §1）."""
    env.mgr.flee_params = {**DEFAULT_FLEE_PARAMS, "enabled": False}
    await start_run(env.mgr, HIGH_ROUTE)
    ok, msg, reward_data = await env.mgr.finish_adventure(USER)
    assert ok and reward_data is not None
    assert "迎战" not in msg
    assert (await env.row())["state"] == STATE_RESOLVED_WIN


@pytest.mark.asyncio
async def test_flee_success_records_fled_without_hp_loss(db):
    """身法两倍→必定脱身：``resolved_fled``、气血原样、基础收益照常."""
    harness = build_env(
        db, outcome="lose", final_hp=0, player_agility=200, enemy_agility=100
    )
    await start_run(harness.mgr, HIGH_ROUTE)
    await harness.mgr.finish_adventure(USER)

    ok, msg, reward_data = await harness.mgr.resolve_adventure_choice(USER, flee=True)
    assert ok, msg
    assert "历练脱身" in msg
    row = await harness.row()
    assert row["state"] == STATE_RESOLVED_FLED
    assert row["outcome"] == "flee"
    assert int(row["fled"]) == 1 and int(row["defeated"]) == 0
    assert harness.engine.calls == 0  # 脱身不进战斗
    assert int(row["hp_after"]) == 1000
    assert (await harness.player()).current_hp == 1000
    assert reward_data["exp_reward"] == BASE_EXP  # 基础收益，无胜利倍率
    assert reward_data["pve_won"] is False
    assert len(await harness.claims()) == 3
    # 只有基础休整，没有战败追加休整
    remaining = await harness.fatigue_until() - int(time.time())
    assert HIGH_FATIGUE - 5 <= remaining <= HIGH_FATIGUE


@pytest.mark.asyncio
async def test_flee_failure_fights_once_and_no_second_chance(env):
    """逃跑失败即应战；同一轮不给第二次逃跑机会."""
    harness = build_env(env.db, outcome="lose", final_hp=0)
    harness.mgr._flee_succeeded = lambda snapshot: False
    await start_run(harness.mgr, HIGH_ROUTE)
    await harness.mgr.finish_adventure(USER)

    ok, msg, reward_data = await harness.mgr.resolve_adventure_choice(USER, flee=True)
    assert ok, msg
    assert (await harness.row())["state"] == STATE_RESOLVED_LOSS
    assert harness.engine.calls == 1
    assert reward_data["pve_won"] is False

    ok2, msg2, reward2 = await harness.mgr.resolve_adventure_choice(USER, flee=True)
    assert not ok2 and "没有待抉择" in msg2 and reward2 is None
    assert harness.engine.calls == 1
    assert (await harness.player()).experience == LOSE_EXP


@pytest.mark.asyncio
async def test_choice_commands_reachable_while_busy(env):
    """迎战/逃跑在忙碌白名单里（结算指令不经 @player_required）；提示只在 pending 出现."""
    assert _is_command_allowed("迎战", BUSY_STATE_ALLOWED_COMMANDS)
    assert _is_command_allowed("逃跑", BUSY_STATE_ALLOWED_COMMANDS)
    assert not _is_command_allowed("闭关", BUSY_STATE_ALLOWED_COMMANDS)
    # 「结束历练」这条指令根本不存在，白名单里也不该留着它
    assert "结束历练" not in BUSY_STATE_ALLOWED_COMMANDS

    await start_run(env.mgr, HIGH_ROUTE)
    assert await _pending_choice_hint(env.db, USER) == ""
    await env.mgr.finish_adventure(USER)
    hint = await _pending_choice_hint(env.db, USER)
    assert "迎战" in hint and "逃跑" in hint
    await env.mgr.resolve_adventure_choice(USER, flee=False)
    assert await _pending_choice_hint(env.db, USER) == ""


@pytest.mark.asyncio
async def test_busy_rejections_offer_choice_exit_while_pending(env):
    """AC11：忙碌拒绝文案自带出路——含走 assert_idle 自定义模板的入口.

    「开始历练」这类指令不经过 ``@player_required`` 拦截器（main.py 只挂
    ``@require_whitelist``），文案来自 ``BusyState.assert_idle`` 的模板；挂
    pending 时同样必须给出两条出路，否则玩家被自己的忙碌锁死。
    """
    await start_run(env.mgr, HIGH_ROUTE)
    await env.mgr.finish_adventure(USER)
    assert (await env.row())["state"] == STATE_PENDING_CHOICE

    started, busy_msg = await env.mgr.start_adventure(USER, LOW_ROUTE)
    assert not started
    assert "你当前正历练中" in busy_msg
    assert "迎战" in busy_msg and "逃跑" in busy_msg
    # 两条渲染路径共用 BusyState 的同一常量，防文案漂移
    assert busy_msg.endswith(_busy_mod.PENDING_CHOICE_HINT)


@pytest.mark.asyncio
async def test_other_busy_status_copy_unchanged(env):
    """非历练忙碌（闭关）文案逐字不变：提示只在 pending 场景追加（AC11 后半句）."""
    player = await env.db.get_player_by_id(USER)
    await env.mgr.busy_state.set_busy(
        player, UserStatus.CULTIVATING, int(time.time()) + 600
    )
    msg = await env.mgr.busy_state.assert_idle(USER)
    assert msg == _busy_mod.DEFAULT.format(
        status=UserStatus.get_name(UserStatus.CULTIVATING)
    )
    assert "迎战" not in msg and "逃跑" not in msg


@pytest.mark.asyncio
async def test_flee_records_settlement_time_hp(db):
    """逃跑的 hp_after 记结算时刻真实气血，不是锁定值（R6 全时段回血）.

    玩家挂 pending 的几分钟里气血照常在回，账本若记 ``hp_before`` 就是过期
    数字；``hp_after - hp_before`` 仍不等于「战斗损耗」，所以差值不作为损耗
    口径——这里钉的是绝对值必须等于落定后的实时气血。
    """
    harness = build_env(db, outcome="win")
    harness.mgr._flee_succeeded = lambda snapshot: True
    await start_run(harness.mgr, HIGH_ROUTE)
    await harness.mgr.finish_adventure(USER)
    assert (await harness.row())["state"] == STATE_PENDING_CHOICE

    await harness.set_hp(500, anchor=int(time.time()) - 600)
    ok, msg, _ = await harness.mgr.resolve_adventure_choice(USER, flee=True)
    assert ok, msg

    row = await harness.row()
    assert row["state"] == STATE_RESOLVED_FLED
    live = await harness.player()
    assert row["hp_after"] == live.current_hp
    assert row["hp_after"] > 500, "pending 期间的恢复必须体现在账本终值上"


@pytest.mark.asyncio
async def test_settled_at_is_written_at_terminal(env):
    """开单行 settled_at 是落单时刻、终态 CAS 覆写为结算时刻（判断只看 state）."""
    await start_run(env.mgr, HIGH_ROUTE)
    opened = await env.row()
    assert opened["state"] == STATE_ADVENTURING
    assert opened["settled_at"] > 0  # 落单时刻，非 0：别拿它当「已结算」判据

    await env.mgr.finish_adventure(USER)
    await env.mgr.resolve_adventure_choice(USER, flee=False)
    settled = await env.row()
    assert settled["state"] == STATE_RESOLVED_WIN
    assert settled["settled_at"] >= opened["settled_at"]


def test_flee_chance_self_agility_zero_returns_floor():
    """自身身法 ≤ 0 不再除零，按保底口径返回 floor（慢很多＝floor）."""
    floor = DEFAULT_FLEE_PARAMS["floor"]
    assert compute_flee_chance(0, 100) == floor
    assert compute_flee_chance(-5, 100) == floor


@pytest.mark.asyncio
async def test_legacy_encounter_id_identity(env):
    """名册未获批时 encounter_id 记 legacy 身份（名称+境界+锁定 seed），留空合法."""
    await start_run(env.mgr, HIGH_ROUTE)
    await env.mgr.finish_adventure(USER)
    row = await env.row()
    snapshot = await env.snapshot()
    assert row["profile_id"] == "" and int(row["profile_version"]) == 0
    assert row["encounter_id"] == (
        f"legacy:噬骨妖狼@L{snapshot['enemy']['level_index']}"
        f"#S{snapshot['rng_seed']:x}"
    )


@pytest.mark.asyncio
async def test_settlement_row_failure_degrades_to_message(env, monkeypatch):
    """结算单写不进去时回中文提示，不把异常抛给指令入口（AstrBot 不能崩）."""

    async def boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    await start_run(env.mgr, HIGH_ROUTE)
    monkeypatch.setattr(type(env.mgr.settlements), "insert_settlement", boom)
    monkeypatch.setattr(
        type(env.mgr.settlements), "get_settlement_by_run", AsyncMock(return_value=None)
    )
    ok, msg, reward_data = await env.mgr.finish_adventure(USER)
    assert not ok and reward_data is None
    assert msg.startswith("❌ ") and "稍后再试" in msg


# ---------------------------------------------------------------------------
# AC4 / AC6 — 气血地板、掉落跟随胜败、全局休整窗口
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_defeat_floors_hp_at_one_percent_of_dynamic_max(db):
    """战败地板是动态上限的 1%（不是绝对 1 点）；胜场不保底，引擎给多少算多少."""
    harness = build_env(db, outcome="lose", final_hp=0)
    await harness.db.conn.execute(
        "UPDATE players SET base_hp = 9800 WHERE user_id = ?", (USER,)
    )
    await harness.db.conn.commit()
    floor = math.ceil(9800 * DEFEAT_HP_FLOOR_RATIO)
    assert floor == 98 and floor > 1

    await harness.set_hp(30)
    await start_run(harness.mgr, HIGH_ROUTE)
    await harness.mgr.finish_adventure(USER)
    ok, msg, _ = await harness.mgr.resolve_adventure_choice(USER, flee=False)
    assert ok, msg
    assert (await harness.player()).current_hp == floor
    row = await harness.row()
    assert row["state"] == STATE_RESOLVED_LOSS
    assert int(row["hp_after"]) == floor

    # 胜场：终值 7 点原样落地，地板不参与
    winner = build_env(db, outcome="win", final_hp=7)
    await winner.mgr.clear_fatigue(USER)
    await winner.set_hp(700)
    await start_run(winner.mgr, HIGH_ROUTE)
    await winner.mgr.finish_adventure(USER)
    await winner.mgr.resolve_adventure_choice(USER, flee=False)
    assert (await winner.player()).current_hp == 7


@pytest.mark.asyncio
async def test_drops_follow_victory_and_are_skipped_on_defeat(env, db):
    """胜利照常掉落、战败什么都不掉，且机会被 claim 消耗（重放不补发）."""
    env.mgr.event_groups = {"standard": [_event(item_chance=100)]}
    await start_run(env.mgr, LOW_ROUTE)
    await env.mgr.finish_adventure(USER)
    assert env.ring.store_item.await_count == 1

    loss = build_env(db, outcome="lose", final_hp=1)
    loss.mgr.event_groups = {"standard": [_event(item_chance=100)]}
    await start_run(loss.mgr, HIGH_ROUTE)
    await loss.mgr.finish_adventure(USER)
    await loss.mgr.resolve_adventure_choice(USER, flee=False)
    assert loss.ring.store_item.await_count == 0
    await loss.mgr.finish_adventure(USER)  # 重放
    assert loss.ring.store_item.await_count == 0


@pytest.mark.asyncio
async def test_injury_event_no_longer_damages_player(env):
    """injury 只剩内容标记：代码分支已删，气血只跟随战斗终值."""
    harness = build_env(env.db, outcome="win", final_hp=424)
    harness.mgr.event_groups = {"standard": [_event(injury=True)]}
    await start_run(harness.mgr, LOW_ROUTE)
    ok, msg, _ = await harness.mgr.finish_adventure(USER)
    assert ok
    assert (await harness.player()).current_hp == 424
    assert "受创" not in msg


@pytest.mark.asyncio
async def test_defeat_adds_extra_fatigue_only_on_loss(env, db):
    """败场休整 = 路线休整 + 战败追加；胜场只有路线休整（PRD R4）."""
    await start_run(env.mgr, LOW_ROUTE)
    await env.mgr.finish_adventure(USER)
    assert LOW_FATIGUE - 5 <= await env.fatigue_until() - int(time.time()) <= LOW_FATIGUE

    loss = build_env(db, outcome="lose", final_hp=1)
    await start_run(loss.mgr, HIGH_ROUTE)
    await loss.mgr.finish_adventure(USER)
    await loss.mgr.resolve_adventure_choice(USER, flee=False)
    remaining = await loss.fatigue_until() - int(time.time())
    expected = HIGH_FATIGUE + DEFEAT_FATIGUE_EXTRA_SECONDS
    assert expected - 5 <= remaining <= expected


@pytest.mark.asyncio
async def test_global_fatigue_blocks_cross_route(env, db):
    """乙案：休整是全局窗口，换路线同样拦，重启后照拦，GM 清完才能再开."""
    await start_run(env.mgr, LOW_ROUTE)
    await env.mgr.finish_adventure(USER)

    ok, msg = await env.mgr.start_adventure(USER, HIGH_ROUTE)
    assert not ok and "你刚历练回来，还需休整" in msg
    assert "巡山" not in msg and "probe_low" not in msg  # 文案不带路线名

    revived = build_env(db)
    ok2, msg2 = await revived.mgr.start_adventure(USER, LOW_ROUTE)
    assert not ok2 and "还需休整" in msg2

    assert await revived.mgr.clear_fatigue(USER) is True
    ok3, _ = await revived.mgr.start_adventure(USER, HIGH_ROUTE)
    assert ok3
    # 休整已被消费，重复清返回 False（没有可清的窗口）
    assert await revived.mgr.clear_fatigue(USER) is False


@pytest.mark.asyncio
async def test_recovery_heals_during_pending_choice(db):
    """忙碌期照旧回血：pending 挂起时时间恢复继续生效（Q4/R6）."""
    harness = build_env(db, outcome="lose", final_hp=100)
    await harness.set_hp(100, anchor=int(time.time()) - 600)
    await start_run(harness.mgr, HIGH_ROUTE)
    await harness.mgr.finish_adventure(USER)
    assert (await harness.row())["state"] == STATE_PENDING_CHOICE

    healed = await harness.health.settle(USER)
    assert healed > 100
    assert healed <= harness.health.compute_max_hp(await harness.player())


# ---------------------------------------------------------------------------
# AC7 — 并发、崩溃点与故障注入
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_double_click_grants_once(env):
    """双击「迎战/逃跑」：CAS 只让一份结算成立，效果不双发."""
    env.mgr._flee_succeeded = lambda snapshot: False  # 让两个入口都走向同一场战斗
    await start_run(env.mgr, HIGH_ROUTE)
    await env.mgr.finish_adventure(USER)

    results = await asyncio.gather(
        env.mgr.resolve_adventure_choice(USER, flee=False),
        env.mgr.resolve_adventure_choice(USER, flee=True),
    )
    assert all(ok for ok, _, _ in results)
    row = await env.row()
    assert row["state"] == STATE_RESOLVED_WIN
    assert (await env.player()).experience == WIN_EXP  # 不是两倍
    assert len(await env.claims()) == 3


@pytest.mark.asyncio
async def test_concurrent_choice_does_not_rewrite_terminal(env):
    """并发「迎战」：终态 CAS 只跳一级，败者走重放而不是二次覆写（P1 回归钉子）.

    复刻的是 `_advance_state` 的 CAS 输家：它拿到赢家已提交的行，若赢家已打完落终态，
    它会带着这张**终态**行走到 `_finalize`。那里 `expected_state=row["state"]` 是同态
    覆盖，`cas_version` 也已被读成最新值，于是双条件 CAS 失效、同一行被再写一遍。
    修复前实测 6/6：cas_version 多跳一级、hp_after 被覆写、两个调用方都收到「全新结算」
    文案（没有重放提示）。上面那条 `test_concurrent_double_click_grants_once` 的三项
    断言在 bug 存在时**全绿**，所以本用例专门钉 `cas_version` 增量。
    """
    for _ in range(6):
        await start_run(env.mgr, HIGH_ROUTE)
        await env.mgr.finish_adventure(USER)
        pre = int((await env.row())["cas_version"])

        results = await asyncio.gather(
            env.mgr.resolve_adventure_choice(USER, flee=False),
            env.mgr.resolve_adventure_choice(USER, flee=False),
            return_exceptions=True,
        )
        assert not any(isinstance(r, Exception) for r in results), results
        assert all(ok for ok, _, _ in results)

        row = await env.row()
        assert row["state"] == STATE_RESOLVED_WIN
        # 恰好两级：pending_choice →(CAS)→ ready_combat →(CAS)→ 终态。
        assert int(row["cas_version"]) - pre == 2, (
            f"终态被二次覆写：cas_version 跳了 {int(row['cas_version']) - pre} 级"
        )
        # 只有一份事实、一份收益（覆写路径会多跑一次战斗引擎与发奖路径）
        rows = await env.db.conn.execute_fetchall(
            "SELECT COUNT(*) FROM adventure_settlements WHERE user_id = ?", (USER,)
        )
        assert rows[0][0] == 1
        assert len(await env.claims()) == 3
        # 复位，下一轮重新开一场
        await env.db.conn.execute("DELETE FROM adventure_settlements")
        await env.db.conn.execute("DELETE FROM adventure_effects")
        await env.db.conn.execute("DELETE FROM user_cd")
        await env.db.conn.commit()


@pytest.mark.asyncio
async def test_real_engine_starts_the_fight_from_recovered_hp(db):
    """真实战斗引擎必须以**回血后**的气血参战（钉 settle 契约，非脚本替身）.

    这条口径容易两头都搞错，所以用**真实 CombatEngine**（接线 health_service）钉死：
    R6 起恢复与忙碌无关，挂 pending 到满血的玩家参战时应当已经是满血
    （`build_fighter_from_player` → `get_health_snapshot` 会先 settle）。引擎终值是
    真实战后剩余，胜场可以远低于战前（打到残血也是赢），所以**不得**对终值取 max
    去「保底」，那与 AC4「胜场按引擎实际剩余写回」冲突。

    为什么不用本文件的 `ScriptedEngine`：它的 `build_fighter_from_player` 直接读
    `player.current_hp`，**没有** `get_health_snapshot`，所以这条契约在替身上验不了
    （删掉真实引擎里的 settle，用例照样绿 = 假钉子）。另外，取「期望值」的那次
    `get_health_snapshot` 会**就地改写** `player.current_hp`，若拿它当期望再让替身
    去读同一个对象，断言就成了自证；因此这里改用**独立读库**拿期望值。
    """
    engine = CombatEngine(StubConfigManager(), health_service=None)
    health = HealthService(
        db, StubConfigManager(), equipment_manager=EquipmentManager(db=None)
    )
    engine.health_service = health  # 接线后才具备 settle 语义

    player = await db.get_player_by_id(USER)
    now = int(time.time())
    await db.conn.execute(
        "UPDATE players SET current_hp = ?, health_recovered_at = ? WHERE user_id = ?",
        (100, now - 6000, USER),
    )
    await db.conn.commit()
    # 期望值独立从库里取（不经过会被就地改写的 player 对象）
    rows = await db.conn.execute_fetchall(
        "SELECT current_hp FROM players WHERE user_id = ?", (USER,)
    )
    assert int(rows[0][0]) == 100, "前置条件：库里此刻是残血"
    # 把内存对象按库里现值摆成「陈旧残血」：这样只有**真的 settle** 才能算出回血，
    # 否则「直接读 player.current_hp」的退化实现会拿到 100 而被本用例抓住。
    player.current_hp = 100

    fighter = await engine.build_fighter_from_player(player)
    # 真实引擎应当把「100 + 等待期恢复」算出来（1% × max_hp/分钟，回拨 6000s）
    assert fighter.hp > 100, (
        f"真实引擎没有按回血后的气血参战：fighter.hp={fighter.hp}（期望 > 100）"
    )
    assert fighter.hp == fighter.max_hp, (
        f"回拨 6000s 应回满：fighter.hp={fighter.hp} max_hp={fighter.max_hp}"
    )


@pytest.mark.asyncio
async def test_replay_renders_authoritative_hp(env):
    """重放/并发败者必须显示**账本里的**气血，而不是调用方手里的陈旧对象.

    并发迎战时败者的 `player` 是进函数前读的，早于赢家 `_write_hp`；直接拿去渲染会
    显示陈旧气血（修复前实测并发迎战 10 次命中 1 次：消息显示 1,000 而库与账本都是
    500）。终态行的 `hp_after` 才是权威事实列，重放前先对齐。
    """
    import re

    await start_run(env.mgr, HIGH_ROUTE)
    assert (await env.mgr.finish_adventure(USER))[0]
    await env.mgr.resolve_adventure_choice(USER, flee=False)
    row = await env.row()
    truth = int(row["hp_after"])

    # 刻意把内存对象摆成陈旧值：只有从账本同步才能渲染出真值
    stale = await env.player()
    stale.current_hp = truth + 12345
    ok, msg, _ = await env.mgr._replay_terminal(
        stale, row, env.mgr.routes[HIGH_ROUTE], None, int(time.time())
    )
    assert ok
    shown = int(re.search(r"当前气血：([\d,]+)", msg).group(1).replace(",", ""))
    assert shown == truth, f"重放显示了陈旧气血 {shown}，账本真值 {truth}"


@pytest.mark.asyncio
async def test_concurrent_finish_cas_is_exactly_two(env):
    """并发「完成历练」（低风险）CAS 恰好两级，不产生第二份事实.

    注意这条**不是**终态覆写的回归钉子：低风险路线 `_offers_choice=False`，直接进
    `ready_combat`，并发败者在 `finish_adventure` 的重放分支（:527 附近）就被分流，
    **根本走不到 `_finalize`**，所以那条路径原本就没有二次覆写问题（实测删掉
    `_finalize` 的终态守护，本用例照样绿）。它守的是「低风险完成路径恰好一次锁敌人 +
    一次结算、只有一份事实」这个更宽的不变式。终态覆写的钉子见
    `test_concurrent_choice_does_not_rewrite_terminal`。"""
    await start_run(env.mgr, LOW_ROUTE)
    pre = int((await env.row())["cas_version"])
    results = await asyncio.gather(
        env.mgr.finish_adventure(USER),
        env.mgr.finish_adventure(USER),
        return_exceptions=True,
    )
    assert not any(isinstance(r, Exception) for r in results), results
    row = await env.row()
    assert row["state"] == STATE_RESOLVED_WIN
    # 恰好两级：adventuring →(锁敌人 CAS)→ ready_combat →(结算 CAS)→ 终态
    assert int(row["cas_version"]) - pre == 2, (
        f"低风险完成路径 CAS 跳了 {int(row['cas_version']) - pre} 级（应为 2）"
    )
    assert (await env.player()).experience == WIN_EXP  # 只有一份收益


@pytest.mark.asyncio
async def test_crash_after_state_advance_resumes_locked_combat(env):
    """崩溃点「推进到 ready_combat 后」重启：迎战续算同一份 snapshot，不重掷."""
    await start_run(env.mgr, HIGH_ROUTE)
    await env.mgr.finish_adventure(USER)
    row = await env.row()
    assert await env.claims() == []
    await env.repo.cas_update_settlement(
        row["settlement_id"],
        expected_cas_version=int(row["cas_version"]),
        expected_state=STATE_PENDING_CHOICE,
        state=STATE_READY_COMBAT,
    )
    assert (await env.row())["state"] == STATE_READY_COMBAT

    revived = build_env(env.db)
    ok, msg, reward_data = await revived.mgr.resolve_adventure_choice(USER, flee=False)
    assert ok, msg
    assert reward_data is not None
    assert (await env.row())["state"] == STATE_RESOLVED_WIN
    assert revived.enemy_mgr.spawned == 0


@pytest.mark.asyncio
async def test_crash_after_commit_before_claim_backfills_once(env):
    """崩溃点「终态已提交、效果未 claim」：重放只补一次，绝不翻倍."""
    await start_run(env.mgr, LOW_ROUTE)
    await env.mgr.finish_adventure(USER)
    assert (await env.player()).experience == WIN_EXP

    sid = await env.settlement_id()
    await env.db.conn.execute(
        "DELETE FROM adventure_effects WHERE settlement_id = ?", (sid,)
    )
    await env.db.conn.commit()
    await env.set_hp(1000)
    await env.db.conn.execute(
        "UPDATE players SET experience = 0, gold = 0 WHERE user_id = ?", (USER,)
    )
    await env.db.conn.commit()

    ok, msg, reward_data = await env.mgr.finish_adventure(USER)
    assert ok and reward_data is None  # 重放不推进悬赏/师承
    assert "此前已结算" in msg
    assert (await env.player()).experience == WIN_EXP  # 补发一次
    assert len(await env.claims()) == 3

    await env.mgr.finish_adventure(USER)
    assert (await env.player()).experience == WIN_EXP  # 不再翻倍
    assert len(await env.claims()) == 3


@pytest.mark.asyncio
async def test_replay_is_deterministic_from_snapshot(env):
    """同一 snapshot 重放两次得到同一份数字；换种子则战报不同（确定性来自锁定）."""
    await start_run(env.mgr, HIGH_ROUTE)
    await env.mgr.finish_adventure(USER)
    snapshot = await env.snapshot()
    player = await env.player()

    first = await env.mgr._compute_locked(player, snapshot)
    second = await env.mgr._compute_locked(player, snapshot)
    assert first == second
    assert env.engine.probes[0] == env.engine.probes[1]

    other = dict(snapshot, rng_seed=int(snapshot["rng_seed"]) ^ 0x5A5A)
    third = await env.mgr._compute_locked(player, other)
    assert third["combat_msg"] != first["combat_msg"]


@pytest.mark.asyncio
async def test_transaction_rolls_back_all_domains(db, monkeypatch):
    """事务内注入异常：状态/气血/休整/忙碌/claim 一起回滚，且可安全重试（AC7）."""

    async def boom(self, *args, **kwargs):
        raise RuntimeError("fatigue write failed")

    mgr = build_env(db).mgr
    monkeypatch.setattr(type(mgr.settlements), "set_fatigue", boom)
    await start_run(mgr, HIGH_ROUTE)
    await mgr.finish_adventure(USER)

    with pytest.raises(RuntimeError):
        await mgr.resolve_adventure_choice(USER, flee=False)

    env = Env(db, mgr, mgr.pve_combat_mgr.combat_engine, None, None, None)
    row = await env.row()
    # 推进到 ready_combat 是提交在结算事务之前的（崩溃点语义），终态没落地
    assert row["state"] == STATE_READY_COMBAT
    assert int(row["hp_after"]) == 0
    player = await env.player()
    assert player.current_hp == 1000 and player.experience == 0
    assert await env.fatigue_until() == 0
    assert await env.claims() == []
    assert await env.user_cd_type() == int(UserStatus.ADVENTURING)

    # 故障恢复后重试：同一张单子照常成立
    monkeypatch.undo()
    ok, msg, reward_data = await mgr.resolve_adventure_choice(USER, flee=False)
    assert ok, msg
    assert reward_data is not None
    assert (await env.row())["state"] == STATE_RESOLVED_WIN
    assert (await env.player()).experience == WIN_EXP


@pytest.mark.asyncio
async def test_effect_failure_is_visible_and_not_retried(db, monkeypatch):
    """效果执行失败：终态不回滚、玩家可见提示、claim 已消耗不再重试."""

    async def boom(player, route, event, rewards):
        raise RuntimeError("drop grant failed")

    harness = build_env(db)
    monkeypatch.setattr(AdventureManager, "_grant_route_drops", boom)
    await start_run(harness.mgr, LOW_ROUTE)
    ok, msg, reward_data = await harness.mgr.finish_adventure(USER)
    assert ok and reward_data is not None
    assert "部分奖励发放失败" in msg
    assert (await harness.row())["state"] == STATE_RESOLVED_WIN
    assert len(await harness.claims()) == 3  # 失败的那项同样已被 claim

    # claim 已消耗：再点「完成历练」不补发也不重试失败项（普通拒绝，不再出现告警）
    ok2, msg2, _ = await harness.mgr.finish_adventure(USER)
    assert not ok2 and "不在历练中" in msg2
    assert "部分奖励发放失败" not in msg2
    assert (await harness.player()).experience == WIN_EXP
    assert len(await harness.claims()) == 3


@pytest.mark.asyncio
async def test_legacy_effect_fires_exactly_once_per_settlement(env):
    """传承机缘每单只博一次：重放不会再来第二次（判定由 rng_seed 派生）."""
    store = MagicMock()
    store.pend = MagicMock(return_value=True)
    env.mgr.encounter_store = store
    env.mgr.legacy_chance = 1.0
    await start_run(env.mgr, LOW_ROUTE)
    ok, msg, _ = await env.mgr.finish_adventure(USER)
    assert ok and "传承" in msg
    assert store.pend.call_count == 1

    await env.mgr.finish_adventure(USER)
    assert store.pend.call_count == 1
    assert len(await env.claims()) == 3


# ---------------------------------------------------------------------------
# GM 时间快进登记（AGENTS §2：等待类冷却域必须注册）
# ---------------------------------------------------------------------------


def test_time_skip_entry_covers_fatigue_window():
    """休整窗口登记了 GM 时间快进字段（label 与 SQL 同步钉住）."""
    labels = [label for label, _ in TIME_SKIP_ENTRIES]
    assert "历练休整到期时间" in labels
    sql = dict(TIME_SKIP_ENTRIES)["历练休整到期时间"]
    assert "adventure_fatigue" in sql and "fatigue_until" in sql


@pytest.mark.asyncio
async def test_time_skip_clears_fatigue_gate(env):
    """快进到期时间后玩家可以重新历练（冷却能被 GM 跨过）."""
    await start_run(env.mgr, LOW_ROUTE)
    await env.mgr.finish_adventure(USER)
    assert not (await env.mgr.start_adventure(USER, LOW_ROUTE))[0]

    sql = dict(TIME_SKIP_ENTRIES)["历练休整到期时间"]
    await env.db.conn.execute(sql, (10_000_000,))
    await env.db.conn.commit()
    ok, msg = await env.mgr.start_adventure(USER, LOW_ROUTE)
    assert ok, msg


# --------------------------------------------------------------------------
# 单据归属：孤儿 pending 行（忙碌被清掉但不等于结算）不得被后来的忙碌消费。
# GM「清除CD / 清除全部冷却」只复位 user_cd、不终结结算单，所以这条路径在
# 测试脚本里是常规动作，不是理论构造。
# --------------------------------------------------------------------------


class _StubHandler:
    """Minimal ``@player_required`` carrier: the interceptor only needs ``self.db``."""

    def __init__(self, db):
        self.db = db

    @_utils_mod.player_required
    async def handle_probe(self, player, event):
        """Body never runs while busy; it only proves the gate's rendered copy."""
        yield event.plain_result("✅ 正常执行")


async def _interceptor_copy(env, command: str) -> str:
    """Run one message through the real busy interceptor and return its reply."""
    event = MagicMock()
    event.get_sender_id.return_value = USER
    event.get_message_str.return_value = command
    event.plain_result.side_effect = lambda msg: msg
    out = []
    async for chunk in _StubHandler(env.db).handle_probe(event):
        out.append(chunk)
    return "\n".join(out)


@pytest.mark.asyncio
async def test_orphan_pending_choice_is_not_consumable(env):
    """清冷却留下的孤儿 pending 单：迎战/逃跑一律拒绝，不发奖也不抹掉当前忙碌."""
    await start_run(env.mgr, HIGH_ROUTE)
    assert (await env.mgr.finish_adventure(USER))[0]
    assert (await env.row())["state"] == STATE_PENDING_CHOICE

    player = await env.player()
    await env.mgr.busy_state.clear(player)
    ok, err = await env.mgr.busy_state.set_busy(
        player, UserStatus.CULTIVATING, int(time.time()) + 600
    )
    assert ok and err is None
    before = await env.player()

    for flee in (False, True):
        success, msg, rewards = await env.mgr.resolve_adventure_choice(USER, flee=flee)
        assert not success and rewards is None
        assert "没有待抉择的历练遭遇" in msg

    after = await env.player()
    assert after.experience == before.experience
    assert after.current_hp == before.current_hp
    assert await env.user_cd_type() == UserStatus.CULTIVATING
    assert (await env.row())["state"] == STATE_PENDING_CHOICE


@pytest.mark.asyncio
async def test_choice_gate_rejects_mismatched_run_id(env):
    """归属闸门的 run-id 比对必须承重（AC13 的核心防线，P2 回归钉子）.

    上一条用例靠 `user_cd.type != ADVENTURING` 就能拒绝，run-id 那一半从未被走到——
    实测把 `_owned_open_run` 里的 run-id 比对整行删掉，41 条用例**全绿**。这条补上
    那一半：`get_open_settlement` 按 `settled_at DESC, rowid DESC` 取最新未终结单，
    把孤儿单的 `settled_at` 顶到未来即可让它排到新单前面，此时玩家正持有**另一场**
    历练的忙碌。缺 run-id 闸门就会消费掉那张不属于本次历练的旧单：真打一场、按旧单
    发奖，并由结算边界的 `busy_state.clear` 抹掉当前忙碌（AC13 明令禁止）。
    """
    # 第 1 场：走成孤儿 pending 单（模拟 GM 清冷却只复位忙碌、不终结单据）
    await start_run(env.mgr, HIGH_ROUTE)
    assert (await env.mgr.finish_adventure(USER))[0]
    orphan = await env.row()
    assert orphan["state"] == STATE_PENDING_CHOICE

    # 第 2 场：玩家开始并完成一场**新的**历练，持有新忙碌
    player = await env.player()
    await env.mgr.busy_state.clear(player)
    await start_run(env.mgr, HIGH_ROUTE)
    assert (await env.mgr.finish_adventure(USER))[0]
    current = await env.row()
    assert current["adventure_run_id"] != orphan["adventure_run_id"]

    # 把孤儿行的 settled_at 顶到未来 → 它成为 get_open_settlement 的返回项
    await env.db.conn.execute(
        "UPDATE adventure_settlements SET settled_at = ? WHERE settlement_id = ?",
        (int(time.time()) + 10_000, orphan["settlement_id"]),
    )
    await env.db.conn.commit()
    fetched = await env.repo.get_open_settlement(USER)
    assert fetched["settlement_id"] == orphan["settlement_id"], (
        "前置条件：孤儿单必须排在最前，否则本用例没验到 run-id 闸门"
    )

    busy_before = await env.user_cd_type()
    exp_before = (await env.player()).experience
    for flee in (False, True):
        success, msg, rewards = await env.mgr.resolve_adventure_choice(USER, flee=flee)
        assert not success, "run-id 闸门失效：孤儿单被当成本次历练消费了"
        assert rewards is None
        assert "没有待抉择的历练遭遇" in msg

    # 当前忙碌与本场单据都必须原样保留
    assert (await env.user_cd_type()) == busy_before == UserStatus.ADVENTURING
    assert (await env.player()).experience == exp_before
    assert (await env.row())["settlement_id"] == current["settlement_id"]
    assert (await env.row())["state"] == STATE_PENDING_CHOICE


@pytest.mark.asyncio
async def test_interceptor_hint_only_for_adventuring_busy(env, monkeypatch):
    """拦截器与 assert_idle 同口径：非历练忙碌零查库、文案逐字不变（AC11）."""
    await start_run(env.mgr, HIGH_ROUTE)
    assert (await env.mgr.finish_adventure(USER))[0]

    hinted = await _interceptor_copy(env, "修炼")
    assert _busy_mod.PENDING_CHOICE_HINT in hinted

    player = await env.player()
    await env.mgr.busy_state.clear(player)
    await env.mgr.busy_state.set_busy(
        player, UserStatus.CULTIVATING, int(time.time()) + 600
    )

    calls: list[str] = []
    real_hint = _utils_mod.pending_choice_hint

    async def _spy(db, user_id: str) -> str:
        calls.append(user_id)
        return await real_hint(db, user_id)

    monkeypatch.setattr(_utils_mod, "pending_choice_hint", _spy)
    # 孤儿 pending 单仍在账上，但闭关玩家不该看到它、也不该为它多查一次库
    assert (await env.row())["state"] == STATE_PENDING_CHOICE
    plain = await _interceptor_copy(env, "修炼")
    assert calls == []
    assert plain == (
        f"道友当前正在「{UserStatus.get_name(UserStatus.CULTIVATING)}」，"
        "无法分心他顾。\n💡 可使用「我的信息」「签到」「银行」等基础指令。"
    )


@pytest.mark.asyncio
async def test_legacy_in_flight_run_recovers_choice(env):
    """升级那一刻在途的历练（extra 没有 run id）：补建单据后迎战照常可用.

    v39 是新增列，改动前挂着的历练忙碌行 ``extra_data`` 里只有 ``route_key``。
    补建时 mint 的新 run id 必须同事务落回 extra：归属校验比的就是这两处，不落回
    就等于把这位玩家永久锁死——「迎战/逃跑」双双被拒而忙碌解不开（修炼/闭关/秘境
    全程被拦），每次重复点「完成历练」还多补建一张事实并重掷敌人。
    """
    player = await env.player()
    ok, err = await env.mgr.busy_state.set_busy(
        player,
        UserStatus.ADVENTURING,
        int(time.time()) - 1,
        extra_data={"route_key": HIGH_ROUTE},
    )
    assert ok and err is None

    success, msg, _ = await env.mgr.finish_adventure(USER)
    assert success, msg
    row = await env.row()
    assert row["state"] == STATE_PENDING_CHOICE
    cd = await env.db.ext.get_user_cd(USER)
    assert env.mgr._read_extra(cd).get("adventure_run_id") == row["adventure_run_id"], (
        "补建 mint 的 run id 必须落回 user_cd.extra_data"
    )

    # 再点一次「完成历练」：拿回同一张单子，不产生第二条事实、不重掷敌人
    success2, _msg2, _ = await env.mgr.finish_adventure(USER)
    assert success2
    row2 = await env.row()
    assert row2["settlement_id"] == row["settlement_id"] and row2["state"] == (
        STATE_PENDING_CHOICE
    )

    success3, msg3, reward = await env.mgr.resolve_adventure_choice(USER, flee=False)
    assert success3, msg3
    assert (await env.row())["state"] == STATE_RESOLVED_WIN
    assert reward is not None and await env.player() is not None
    assert await env.user_cd_type() == UserStatus.IDLE


async def _all_settlement_ids(env) -> list[str]:
    """Every settlement id this player owns, oldest first (counts the facts)."""
    async with env.db.conn.execute(
        "SELECT settlement_id FROM adventure_settlements WHERE user_id = ? "
        "ORDER BY rowid",
        (USER,),
    ) as cursor:
        return [row[0] for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_legacy_in_flight_concurrent_finish_creates_single_fact(env):
    """升级窗口旧忙碌行被并发「完成历练」：确定性 run id 只收敛出一条事实.

    补建分支的 run id 若不唯一（uuid），四路并发各自 mint 一张单、各自发一份
    掉落与传承；确定性 id 靠 adventure_run_id 的 UNIQUE + 冲突回读收敛成一条，
    落败方读到终态后按重放走（reward_data=None，不推悬赏/师承）。
    """
    player = await env.player()
    ok, err = await env.mgr.busy_state.set_busy(
        player,
        UserStatus.ADVENTURING,
        int(time.time()) - 1,
        extra_data={"route_key": LOW_ROUTE},
    )
    assert ok and err is None
    # 与 start_run 同法回拨时钟（时长够一档，收益口径才与其它用例一致）。
    now = int(time.time())
    await env.db.conn.execute(
        "UPDATE user_cd SET create_time = ?, scheduled_time = ? WHERE user_id = ?",
        (now - 601, now - 1, USER),
    )
    await env.db.conn.commit()

    results = await asyncio.gather(
        *(env.mgr.finish_adventure(USER) for _ in range(4))
    )
    assert all(success for success, _, _ in results)

    ids = await _all_settlement_ids(env)
    assert len(ids) == 1, f"并发补建只该有一条事实，实际 {ids}"
    assert len(await env.claims()) == 3
    assert (await env.player()).experience == WIN_EXP  # 不是两倍
    assert (await env.row())["state"] == STATE_RESOLVED_WIN
    # 忙碌必须收尾。落败方若也拿旧快照 stamp 一次，这次写入会排在赢家 `_finalize`
    # 的 clear 之后，把忙碌**复活成历练中**；修复前重放分支不收尾（当时全文件唯一
    # 清忙碌点在 `_finalize`）、迎战/逃跑又被归属闸门拒绝 → 玩家永久卡死、重启不自
    # 愈，只能管理员「清除CD」弃单。突变验证：把 `if minted and created:` 还原成
    # `if minted:` 跑本用例 20 轮 = 20/20 红（真并发 gather 才复现，人类慢点击在
    # 头部检查就被「不在历练中」挡掉）。
    assert await env.user_cd_type() == int(UserStatus.IDLE)


@pytest.mark.asyncio
async def test_revived_busy_self_heals_on_replay(env):
    """被陈旧整行快照复活的忙碌，必须在再点「完成历练」时收尾（第六轮 P2）。

    复刻 core/gm_manager.py:1059-1064 的既有写法：拿**事务前**读到的 user_cd 整行
    回写（``update_user_cd`` 是全列 UPDATE，含 ``type``），会把已经收尾的忙碌复活成
    「历练中」。修复前这是永久锁死：单据已终态 → 迎战/逃跑被归属闸门正确拒绝，重放
    不碰忙碌，而 assert_idle / @player_required 都不看 ``scheduled_time``。
    """
    await start_run(env.mgr, LOW_ROUTE)
    stale = await env.db.ext.get_user_cd(USER)  # GM 事务前持有的那份快照
    ok, msg, reward_data = await env.mgr.finish_adventure(USER)
    assert ok, msg
    assert reward_data is not None
    assert await env.user_cd_type() == int(UserStatus.IDLE)

    await env.db.ext.update_user_cd(stale)  # 陈旧整行回写 → 忙碌被复活
    assert await env.user_cd_type() == int(UserStatus.ADVENTURING)

    ok2, msg2, reward_data2 = await env.mgr.finish_adventure(USER)
    assert ok2, msg2
    assert "本次历练此前已结算" in msg2
    assert reward_data2 is None  # 重放不推进悬赏/师承
    assert await env.user_cd_type() == int(UserStatus.IDLE)  # 一次点击即自愈
    assert len(await env.claims()) == 3  # 也不重复发奖
