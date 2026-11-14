"""Child A (10-10-pve-player-health-foundation) acceptance tests.

Covers the PRD/acceptance criteria of the health-foundation split:

- AC1  schema/model: players carries base_hp / current_hp / health_recovered_at,
  no bare hp column for players and no Player.hp usage left in product code.
- AC2  v34 -> v35 migration: RENAME hp -> base_hp + backfill current_hp to the
  migration-moment dynamic max (equipment aggregation), idempotent rerun and
  failure rollback that keeps the database at v34.
- AC3  three-layer ownership: breakthrough-style base growth never heals
  current; combat-style current changes never move base; clamp on ceiling drop.
- AC4  lazy recovery: 1% of the dynamic max per elapsed minute, purely
  time-based — the busy gate was removed on 2026-10-12 (用户拍板), so
  闭关/修炼/历练 pending windows heal exactly like idle ones; settle+anchor
  still rides inside the caller
  transaction, and GM 时间快进 (TIME_SKIP_ENTRIES) never touches
  health_recovered_at.
- AC5  the HealthService snapshot API has no reward/platform side effects.

Elapsed time is driven through the injectable business clock (design D3):
no sleeps, no per-player timers.
"""

import re
import sys
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from tests.helpers import load_package_module

# Load order matters: core.health first pulls in the real data/models
# packages through the plugin package (same idiom as test_busy_state.py).
_health_mod = load_package_module(
    "core/health.py", "astrbot_plugin_monixiuxian2_2.core.health"
)
HealthService = _health_mod.HealthService
DEFEAT_HP_FLOOR_RATIO = _health_mod.DEFEAT_HP_FLOOR_RATIO
RECOVERY_RATE_PER_MINUTE = _health_mod.RECOVERY_RATE_PER_MINUTE

_busy_mod = load_package_module(
    "core/busy_state.py", "astrbot_plugin_monixiuxian2_2.core.busy_state"
)
BusyState = _busy_mod.BusyState
TIME_SKIP_ENTRIES = _busy_mod.TIME_SKIP_ENTRIES

_migration_mod = load_package_module(
    "data/migration.py", "astrbot_plugin_monixiuxian2_2.data.migration"
)
MigrationManager = _migration_mod.MigrationManager
LATEST_DB_VERSION = _migration_mod.LATEST_DB_VERSION
_players_health_layers_v35 = _migration_mod._players_health_layers_v35

_data_pkg = sys.modules["astrbot_plugin_monixiuxian2_2.data"]
DataBase = _data_pkg.DataBase
Player = sys.modules["astrbot_plugin_monixiuxian2_2.models"].Player
UserStatus = sys.modules["astrbot_plugin_monixiuxian2_2.models_extended"].UserStatus

_EQUIP_MOD = load_package_module(
    "core/equipment_manager.py", "astrbot_plugin_monixiuxian2_2.core.equipment_manager"
)
EquipmentManager = _EQUIP_MOD.EquipmentManager

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
T0 = 1_700_000_000  # fixed fake unix clock base

WEAPON_SWORD = "灵锋剑"
SWORD_HP = 200


class StubConfigManager:
    """Minimal ConfigManager: only the three item tables health aggregates."""

    def __init__(self):
        self.items_data = {WEAPON_SWORD: {"hp": SWORD_HP}}
        self.weapons_data = {}
        self.heart_methods_data = {}


def make_service(db, clock_value=None):
    return HealthService(
        db,
        StubConfigManager(),
        equipment_manager=EquipmentManager(db=None),
        clock=clock_value if clock_value is not None else (lambda: T0),
    )


@pytest_asyncio.fixture
async def db():
    """Real DataBase on the fresh (latest) schema."""
    database = DataBase(":memory:")
    await database.connect()
    await MigrationManager(database.conn, StubConfigManager()).migrate_or_reset()
    yield database
    await database.close()


async def columns_of(conn, table):
    async with conn.execute("PRAGMA table_info(" + table + ")") as cursor:
        return {row[1] for row in await cursor.fetchall()}


async def health_row(conn, user_id):
    async with conn.execute(
        "SELECT base_hp, current_hp, health_recovered_at FROM players "
        "WHERE user_id = ?",
        (user_id,),
    ) as cursor:
        return await cursor.fetchone()


async def put_player(database, user_id, base, current, anchor=0, weapon=""):
    player = Player(
        user_id=user_id,
        base_hp=base,
        current_hp=current,
        health_recovered_at=anchor,
        weapon=weapon,
        cultivation_type="灵修",
    )
    await database.create_player(player)
    if anchor or weapon:
        await database.conn.execute(
            "UPDATE players SET health_recovered_at = ?, weapon = ? WHERE user_id = ?",
            (anchor, weapon, user_id),
        )
        await database.conn.commit()
    return player


# ----------------------------------------------------------------------
# AC1 — schema and model shape
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_schema_has_three_layer_health_columns():
    db_conn = await aiosqlite.connect(":memory:")
    try:
        await MigrationManager(db_conn, StubConfigManager()).migrate_or_reset()
        cols = await columns_of(db_conn, "players")
        assert {"base_hp", "current_hp", "health_recovered_at"} <= cols
        assert "hp" not in cols, "bare hp column survived on fresh schema"
        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            row = await cursor.fetchone()
        # 钉住链条末端版本；新增迁移版本时同步更新（见 child P design §1）
        assert row[0] == LATEST_DB_VERSION == 39
    finally:
        await db_conn.close()


def test_player_model_has_no_hp_attribute():
    assert not hasattr(Player(user_id="x"), "hp")
    p = Player(user_id="x", base_hp=101, current_hp=57)
    assert (p.base_hp, p.current_hp) == (101, 57)


def test_no_player_hp_usage_left_in_product_code():
    """Static checklist: product code never touches a hp attribute of players."""
    pattern = re.compile(r"\b(player|player1|player2|p1|p2)\.hp\b")
    offenders = []
    for path in PLUGIN_ROOT.rglob("*.py"):
        # .scratch 是临时脚本目录（评审/验证用），不算产品代码
        if {"tests", "design_docs", "__pycache__", ".scratch"} & set(path.parts):
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(PLUGIN_ROOT)))
    assert not offenders, f"Player.hp consumers left: {offenders}"


# ----------------------------------------------------------------------
# AC2 — v34 -> v35 migration
# ----------------------------------------------------------------------


V34_PLAYERS_DDL = """
CREATE TABLE players (
    user_id TEXT PRIMARY KEY,
    user_name TEXT DEFAULT '',
    level_index INTEGER DEFAULT 1,
    spiritual_root TEXT DEFAULT '',
    cultivation_type TEXT DEFAULT '灵修',
    lifespan INTEGER DEFAULT 100,
    experience INTEGER DEFAULT 0,
    gold INTEGER DEFAULT 0,
    damage INTEGER DEFAULT 10,
    agility INTEGER DEFAULT 10,
    speed INTEGER DEFAULT 10,
    hp INTEGER DEFAULT 100,
    armor_value INTEGER DEFAULT 0,
    weapon TEXT DEFAULT '',
    armor TEXT DEFAULT '',
    main_technique TEXT DEFAULT '',
    techniques TEXT DEFAULT '[]',
    state TEXT DEFAULT '空闲'
)
"""


async def build_v34_db(path):
    conn = await aiosqlite.connect(path)
    try:
        await conn.execute(
            "CREATE TABLE db_info (id INTEGER PRIMARY KEY, version INTEGER)"
        )
        await conn.execute("INSERT INTO db_info (id, version) VALUES (1, 34)")
        await conn.execute(V34_PLAYERS_DDL)
        await conn.execute(
            "INSERT INTO players (user_id, hp, weapon) VALUES ('u_sword', 500, ?)",
            (WEAPON_SWORD,),
        )
        await conn.execute("INSERT INTO players (user_id, hp) VALUES ('u_bare', 120)")
        await conn.commit()
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_v34_upgrade_backfills_dynamic_max(tmp_path):
    path = str(tmp_path / "v34.db")
    await build_v34_db(path)
    conn = await aiosqlite.connect(path)
    try:
        await MigrationManager(conn, StubConfigManager()).migrate_or_reset()
        cols = await columns_of(conn, "players")
        assert {"base_hp", "current_hp", "health_recovered_at"} <= cols
        assert "hp" not in cols
        async with conn.execute(
            "SELECT user_id, base_hp, current_hp, health_recovered_at, gold "
            "FROM players ORDER BY user_id"
        ) as cursor:
            rows = {r[0]: r for r in await cursor.fetchall()}
        # 永久血量原样保留（RENAME COLUMN），gold 未受影响
        assert rows["u_bare"][1] == 120
        assert rows["u_sword"][1] == 500
        # 回填是迁移时刻的动态 max（装备聚合，非裸 base_hp）
        assert rows["u_bare"][2] == 120
        assert rows["u_sword"][2] == 500 + SWORD_HP
        assert rows["u_sword"][3] > 0 and rows["u_bare"][3] > 0
        async with conn.execute("SELECT version FROM db_info") as cursor:
            row = await cursor.fetchone()
        assert row[0] == LATEST_DB_VERSION
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_v35_rerun_is_idempotent(tmp_path):
    path = str(tmp_path / "v34b.db")
    await build_v34_db(path)
    conn = await aiosqlite.connect(path)
    try:
        await _players_health_layers_v35(conn, StubConfigManager())
        await conn.commit()
        first = await health_row(conn, "u_sword")
        # 框架已提交后再次直接执行：PRAGMA 守卫应为空操作
        await _players_health_layers_v35(conn, StubConfigManager())
        await conn.commit()
        second = await health_row(conn, "u_sword")
        assert first == second
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_v35_failure_rolls_back_and_stays_v34(tmp_path):
    """Unrecognizable players schema -> task raises, chain keeps version 34."""
    path = str(tmp_path / "broken.db")
    conn = await aiosqlite.connect(path)
    try:
        await conn.execute(
            "CREATE TABLE db_info (id INTEGER PRIMARY KEY, version INTEGER)"
        )
        await conn.execute("INSERT INTO db_info (id, version) VALUES (1, 34)")
        await conn.execute("CREATE TABLE players (user_id TEXT PRIMARY KEY, note TEXT)")
        await conn.commit()
        with pytest.raises(RuntimeError):
            await MigrationManager(conn, StubConfigManager()).migrate_or_reset()
        async with conn.execute("SELECT version FROM db_info") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 34, "failed v35 must not advance the version"
        cols = await columns_of(conn, "players")
        assert "base_hp" not in cols, "partial ALTER must have rolled back"
    finally:
        await conn.close()


# ----------------------------------------------------------------------
# AC3 — three-layer ownership
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_growth_never_heals_current(db):
    health = make_service(db)
    player = await put_player(db, "u_base", base=1000, current=400, anchor=T0)
    # 突破式显式底数增长：只动 base，不回血
    new_base = await health.add_base_hp(player, 100)
    assert new_base == 1100 and player.current_hp == 400
    # 动态上限随之上涨（装备槽空，max == base）
    assert health.compute_max_hp(player) == 1100
    # 底数通道的持久化归调用方（突破/商店/GM 都各自 update_player）
    await db.update_player(player)
    row = await health_row(db.conn, "u_base")
    assert (row[0], row[1]) == (1100, 400)


@pytest.mark.asyncio
async def test_add_base_hp_floors_at_one(db):
    """base_hp 下限与商店兜底/回生丹减半一致：max(1, ...)，永不归零。"""
    health = make_service(db)
    player = await put_player(db, "u_floor", base=100, current=50, anchor=T0)
    assert await health.add_base_hp(player, -99999) == 1
    assert player.base_hp == 1 and player.current_hp == 50


@pytest.mark.asyncio
async def test_current_change_never_moves_base_and_clamps(db):
    health = make_service(db)
    player = await put_player(db, "u_cur", base=1000, current=990, anchor=T0)
    # 治疗封顶动态 max，不越界
    after = await health.apply_current_hp_change(player, +99999)
    assert after == 1000 and player.base_hp == 1000
    # 伤害可以打到 0（败局语义），且不会低于 minimum
    after = await health.apply_current_hp_change(player, -500, minimum=1)
    assert after == 500
    after = await health.apply_current_hp_change(player, -99999, minimum=1)
    assert after == 1


@pytest.mark.asyncio
async def test_clamp_when_ceiling_drops(db):
    health = make_service(db)
    player = await put_player(
        db, "u_clamp", base=1000, current=1000, anchor=T0, weapon=WEAPON_SWORD
    )
    snap = await health.get_health_snapshot(player)
    assert snap == {"base_hp": 1000, "current_hp": 1000, "max_hp": 1200}
    # 卸下装备（上限下降）后钳制 current 到新上限
    await db.conn.execute("UPDATE players SET weapon = '' WHERE user_id = 'u_clamp'")
    await db.conn.commit()
    player.weapon = ""
    clamped = await health.clamp_current_hp(player)
    assert clamped == 1000 == player.current_hp
    # 底数被 GM 压低后，快照把 current 收敛进新上限（AC: 0<=current<=max）
    player.base_hp = 300
    await db.update_player(player)
    snap = await health.get_health_snapshot(player)
    assert snap["max_hp"] == 300 and snap["current_hp"] == 300
    row = await health_row(db.conn, "u_clamp")
    assert row[1] == 300


@pytest.mark.asyncio
async def test_defeat_hp_floor_uses_dynamic_max_and_rounds_up(db):
    """The shared defeat floor is ceil(1% of dynamic max), with a minimum of 1."""
    health = make_service(db)
    player = await put_player(
        db, "u_defeat_floor", base=950, current=0, anchor=T0, weapon=WEAPON_SWORD
    )
    assert health.compute_max_hp(player) == 1150
    assert DEFEAT_HP_FLOOR_RATIO == 0.01
    assert health.defeat_hp_floor(player) == 12

    player.weapon = ""
    player.base_hp = 1
    assert health.defeat_hp_floor(player) == 1


@pytest.mark.asyncio
async def test_pve_defeat_floor_persists_across_restart(tmp_path):
    """A rift loss writes the dynamic floor to SQLite and survives reconnect."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    pve_mod = load_package_module(
        "managers/pve_combat_manager.py",
        "astrbot_plugin_monixiuxian2_2.managers.pve_combat_manager",
    )
    db_path = tmp_path / "defeat-floor.db"
    database = DataBase(str(db_path))
    await database.connect()
    await MigrationManager(database.conn, StubConfigManager()).migrate_or_reset()
    try:
        player = await put_player(
            database,
            "u_defeat_restart",
            base=950,
            current=500,
            anchor=T0,
            weapon=WEAPON_SWORD,
        )
        health = make_service(database)
        engine = MagicMock()
        engine.build_fighter_from_player = AsyncMock(
            return_value=SimpleNamespace(user_id=player.user_id)
        )
        engine.resolve_combat.return_value = SimpleNamespace(
            winner_side="fighter2",
            winner_id="enemy_wolf",
            fighter1_final_hp=0,
            combat_log=[],
        )
        enemy_mgr = MagicMock()
        enemy_mgr.spawn_enemy.return_value = pve_mod.Enemy(
            user_id="enemy_wolf",
            name="狼",
            hp=100,
            max_hp=100,
            damage=10,
            agility=5,
            speed=5,
            armor_value=0,
            exp=0,
        )
        pve = pve_mod.PVECombatManager(
            MagicMock(engine=engine), enemy_mgr, health_service=health
        )

        outcome = await pve.challenge_rift_beast(player)

        assert outcome.won is False
        assert outcome.draw is False
        assert player.current_hp == 12
        assert (await database.get_player_by_id(player.user_id)).current_hp == 12
    finally:
        await database.close()

    reopened = DataBase(str(db_path))
    await reopened.connect()
    try:
        restored = await reopened.get_player_by_id("u_defeat_restart")
        assert restored.base_hp == 950
        assert restored.current_hp == 12
        assert await make_service(reopened).get_health_snapshot(restored) == {
            "base_hp": 950,
            "current_hp": 12,
            "max_hp": 1150,
        }
    finally:
        await reopened.close()


# ----------------------------------------------------------------------
# AC4 — lazy recovery (time-based; 忙碌不再参与判定)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_one_percent_per_minute_injected_clock(db):
    health = make_service(db)
    await put_player(db, "u_rec", base=1000, current=100, anchor=T0)
    # +180s -> 3 分钟 * 1% * 1000 = 30
    cur = await health.settle("u_rec", now=T0 + 180)
    assert cur == 130
    row = await health_row(db.conn, "u_rec")
    assert row[1] == 130 and row[2] == T0 + 180
    # 同一分钟内重复读取不再恢复（幂等）
    cur = await health.settle("u_rec", now=T0 + 200)
    assert cur == 130
    row = await health_row(db.conn, "u_rec")
    assert row[2] == T0 + 180, "sub-minute remainder must not advance anchor"
    # 长时间挂机封顶在动态 max，不会过恢复
    cur = await health.settle("u_rec", now=T0 + 100000)
    assert cur == 1000
    assert int(1000 * RECOVERY_RATE_PER_MINUTE) == 10


@pytest.mark.asyncio
async def test_anchor_zero_adopts_clock_without_retro_heal(db):
    health = make_service(db)
    await put_player(db, "u_new", base=500, current=250, anchor=0)
    cur = await health.settle("u_new", now=T0 + 99999)
    assert cur == 250, "anchor==0 must adopt the clock, not retro-heal"
    row = await health_row(db.conn, "u_new")
    assert row[2] == T0 + 99999


@pytest.mark.asyncio
async def test_busy_window_heals_exactly_like_idle(db):
    """2026-10-12 R6：恢复不再看 user_cd。忙碌（未到期）窗口按分钟照常回血，
    锚点推进的是真实经过的整分钟，而不是跳到 now 吞掉窗口。"""
    health = make_service(db)
    await put_player(db, "u_busy", base=1000, current=400, anchor=T0)
    await db.ext.set_user_busy("u_busy", int(UserStatus.CULTIVATING), T0 + 60000)
    cur = await health.settle("u_busy", now=T0 + 300)
    assert cur == 450, "忙碌窗口必须回血：5 min * 10（max 1000 的 1%）"
    row = await health_row(db.conn, "u_busy")
    assert row[1] == 450 and row[2] == T0 + 300, "锚点按整分钟推进，不跳 now"
    # 继续挂在该忙碌状态里：仍然持续恢复，直到动态上限封顶
    cur = await health.settle("u_busy", now=T0 + 6300)
    assert cur == 1000, "长时间忙碌后封顶在动态 max_hp，不会过恢复"
    await db.ext.set_user_free("u_busy")
    cur = await health.settle("u_busy", now=T0 + 6900)
    assert cur == 1000, "解除忙碌后不产生任何额外补偿"


@pytest.mark.asyncio
async def test_indefinite_busy_still_heals(db):
    """闭关式 indefinite busy（scheduled_time == 0）曾经是闸门最硬的分支
    （“blocks healing until explicitly cleared”）；R6 取消后必须同样回血。"""
    health = make_service(db)
    await put_player(db, "u_closed", base=1000, current=500, anchor=T0)
    await db.ext.set_user_busy("u_closed", int(UserStatus.CULTIVATING), 0)
    cur = await health.settle("u_closed", now=T0 + 300)
    assert cur == 550  # 5 min * 10/min of max 1000
    row = await health_row(db.conn, "u_closed")
    assert row[2] == T0 + 300, "锚点仍在推进，忙碌期未被吞掉"


@pytest.mark.asyncio
async def test_set_busy_settles_old_state_in_same_transaction(db):
    """AC4: entering busy settles the elapsed time first, atomically with the
    user_cd write — and a losing set_busy writes nothing at all. 忙碌期间同样
    持续回血（R6 取消闸门），所以 clear 结算出的是整段窗口的血。"""
    now = {"t": T0}
    health = make_service(db, clock_value=lambda: now["t"])
    player = await put_player(db, "u_tx", base=1000, current=300, anchor=T0)
    busy = BusyState(db, health)
    now["t"] = T0 + 180
    ok, _ = await busy.set_busy(player, UserStatus.CULTIVATING, T0 + 60000)
    assert ok
    row = await health_row(db.conn, "u_tx")
    assert row[1] == 330, "3 idle minutes settled before going busy"
    assert row[2] == T0 + 180, "anchor lands exactly at the busy start"
    # 已忙碌时再次 set_busy：竞争失败者不得推进锚点/结算
    ok2, _ = await busy.set_busy(player, UserStatus.ADVENTURING, T0 + 120000)
    assert not ok2
    row2 = await health_row(db.conn, "u_tx")
    assert row2 == row, "loser path must not settle"
    # 忙碌 600s 后 clear：窗口内 10 分钟照样回血（+100），锚点推进到结算时刻
    now["t"] = T0 + 780
    await busy.clear(player)
    row3 = await health_row(db.conn, "u_tx")
    assert row3[1] == 430, "busy window heals too: 330 + 10 min * 10"
    assert row3[2] == T0 + 780, "anchor advances by whole elapsed minutes"
    # 空闲后再读：恢复继续从锚点起算（3 分钟 -> +30）
    cur = await health.settle("u_tx", now=T0 + 960)
    assert cur == 460


@pytest.mark.asyncio
async def test_settle_joins_outer_transaction_rollback(db):
    """Fault-injection analogue: a settle inside an aborted transaction must
    disappear with it (D2 ownership gate via _txn_depth)."""
    health = make_service(db)
    await put_player(db, "u_rb", base=1000, current=200, anchor=T0)
    async with db.transaction() as txn:
        cur = await health.settle("u_rb", now=T0 + 300)
        assert cur == 250  # visible inside the tx
        txn.abort()
    row = await health_row(db.conn, "u_rb")
    assert row[1] == 200 and row[2] == T0, "aborted tx must roll back settle+anchor"


@pytest.mark.asyncio
async def test_update_player_never_reverts_settled_anchor(db):
    """P0 regression: health_recovered_at is domain-owned — a stale in-memory
    Player written back via update_player must not resurrect settled windows."""
    health = make_service(db)
    player = await put_player(db, "u_anchor", base=1000, current=100, anchor=T0)
    # 战斗前置快照：结算 3 分钟，DB 锚点前移到 T0+180、回血到 130
    cur = await health.settle("u_anchor", now=T0 + 180)
    assert cur == 130
    # 调用方内存副本仍是旧值（current=100, anchor=T0）；战后 update_player
    # 不得把锚点刷回 T0（锚点由健康域独占写入，排除出 update_player）
    assert player.health_recovered_at == T0 and player.current_hp == 100
    await db.update_player(player)
    row = await health_row(db.conn, "u_anchor")
    assert row[2] == T0 + 180, "settled anchor must survive update_player"
    # 锚点未回退 → 同一窗口不会被重复回血（从调用方写回的 100 起算 1 分钟）
    cur = await health.settle("u_anchor", now=T0 + 240)
    assert cur == 110
    row = await health_row(db.conn, "u_anchor")
    assert row[2] == T0 + 240


@pytest.mark.asyncio
async def test_set_busy_syncs_current_hp_and_busy_window_heals(db):
    """P0/AC4 regression: set_busy 结算后同步内存 current_hp，随后的
    update_player 既不丢已结算的回血，也不复活窗口（锚点不回退）。忙碌期
    本身照常回血（R6），所以 clear 后 DB 与内存都必须是结算后的值。"""
    now = {"t": T0}
    health = make_service(db, clock_value=lambda: now["t"])
    player = await put_player(db, "u_busysync", base=1000, current=300, anchor=T0)
    busy = BusyState(db, health)
    now["t"] = T0 + 180
    ok, _ = await busy.set_busy(player, UserStatus.ADVENTURING, T0 + 60000)
    assert ok
    assert player.current_hp == 330, "set_busy must sync the settled current_hp"
    # 历练流程随后落库（旧 bug：陈旧内存把回血与锚点一起刷回）
    await db.update_player(player)
    row = await health_row(db.conn, "u_busysync")
    assert (row[1], row[2]) == (330, T0 + 180)
    # 忙碌 10 分钟后回来：窗口内回血入账，锚点绝不回退
    now["t"] = T0 + 780
    await busy.clear(player)
    assert player.current_hp == 430, "clear 必须把结算值同步回内存，防陈旧回写"
    await db.update_player(player)
    row = await health_row(db.conn, "u_busysync")
    assert (row[1], row[2]) == (430, T0 + 780)


@pytest.mark.asyncio
async def test_low_max_hp_still_recovers(db):
    """P1 regression: 灵修创角 roll 90–99 无装备时 max_hp<100，每分钟恢复量
    向下取整必须有 1 点保底，否则败北后永远回不了血（软锁到突破）。"""
    health = make_service(db)
    await put_player(db, "u_low", base=95, current=10, anchor=T0)
    cur = await health.settle("u_low", now=T0 + 3600)  # 空闲 60 分钟
    assert cur == 70, "max_hp<100: 每分钟保底 1 点，60 分钟 +60"
    # 长时间挂机仍封顶动态 max，不会过恢复
    cur = await health.settle("u_low", now=T0 + 100000)
    assert cur == 95


# ----------------------------------------------------------------------
# AC4 boundary — GM 时间快进 must not fast-forward recovery
# ----------------------------------------------------------------------


def test_health_anchor_not_registered_in_time_skip():
    joined = " ".join(sql for _label, sql in TIME_SKIP_ENTRIES).lower()
    assert "health_recovered_at" not in joined
    assert "players" not in joined, "时间快进 entries must only touch user_cd"


@pytest.mark.asyncio
async def test_time_skip_sql_leaves_health_state_untouched(db):
    await put_player(db, "u_skip", base=1000, current=400, anchor=T0)
    await db.ext.set_user_busy("u_skip", int(UserStatus.ADVENTURING), T0 + 3000)
    delta = 7200
    for _label, sql in TIME_SKIP_ENTRIES:
        await db.conn.execute(sql, (delta,))
    await db.conn.commit()
    row = await health_row(db.conn, "u_skip")
    assert tuple(row) == (1000, 400, T0), "时间快进 must not move anchor or heal"
    # 快进只前移 user_cd 到期判定，绝不代偿恢复：锚点仍是权威时间戳


# ----------------------------------------------------------------------
# AC5 — snapshot API purity (usable by PVE/Boss without rewards)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_returns_three_layers_without_side_effects(db):
    health = make_service(db)
    player = await put_player(
        db, "u_snap", base=1000, current=100, anchor=T0, weapon=WEAPON_SWORD
    )
    before = None
    async with db.conn.execute(
        "SELECT gold, experience, lifespan, state FROM players WHERE user_id='u_snap'"
    ) as cursor:
        before = tuple(await cursor.fetchone())
    snap = await health.get_health_snapshot(player, now=T0 + 120)
    # 1%/min 按动态上限计（1200 -> 12/min，非裸 base）
    assert snap == {"base_hp": 1000, "current_hp": 124, "max_hp": 1200}
    assert player.current_hp == 124  # 同步内存对象，调用方可直接持久化
    async with db.conn.execute(
        "SELECT gold, experience, lifespan, state FROM players WHERE user_id='u_snap'"
    ) as cursor:
        after = tuple(await cursor.fetchone())
    assert after == before, "health snapshot must not touch rewards/other fields"
