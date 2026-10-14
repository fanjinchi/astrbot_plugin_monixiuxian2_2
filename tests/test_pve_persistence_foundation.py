"""Child P（10-10-pve-persistence-transaction-foundation）验收测试。

覆盖 PRD AC1–AC6 与 design §1–§6：

- 版本矩阵：v36–v39 注册齐全、表归属正确、fresh install 建齐 10 张新表；
- schema 一致性：fresh install == 逐版本升级链（参数化 N ∈ {36,37,38}）；
- v34 → 最新走任务链升级（数据保留、不触发 reset 备份）；
- 迁移失败回滚停在 N-1，且修复后可续跑；任务重放幂等；
- 仓储契约：幂等插入（insert-or-read）、CAS 冲突、效果 claim、
  Boss 每日次数封顶、贡献累积 sticky-last-hit、Outbox claim/lease/
  retry 水位/uncertain、FK 强制；
- design §3 四条原子调用图：事务内抛错 → 全域零残留；成功 → 原子提交；
- 叶子门控：事务内不提前提交（跨连接观察）、standalone 立即提交；
- 静态审计：data/ 下 0 个未门控裸 ``conn.commit()``；
- 时间模型：``shanghai_date_key`` 北京时间日界；健康锚点/结算记录/
  每日计数不参与 GM「时间快进」。

测试基建复用 tests/test_player_health_foundation.py 的 fixture 与工具。
"""

import ast
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from tests.helpers import load_package_module
from tests.test_player_health_foundation import (
    T0,
    StubConfigManager,
    build_v34_db,
    put_player,
)

_migration_mod = load_package_module(
    "data/migration.py", "astrbot_plugin_monixiuxian2_2.data.migration"
)
MigrationManager = _migration_mod.MigrationManager
LATEST_DB_VERSION = _migration_mod.LATEST_DB_VERSION
MIGRATION_TASKS = _migration_mod.MIGRATION_TASKS
VERSION_SCHEMA_TABLES = _migration_mod.VERSION_SCHEMA_TABLES
TASK_CHAIN_MIN_VERSION = _migration_mod.TASK_CHAIN_MIN_VERSION

_repo_mod = load_package_module(
    "data/pve_repository.py", "astrbot_plugin_monixiuxian2_2.data.pve_repository"
)
BaseRepository = _repo_mod.BaseRepository
AdventureRepository = _repo_mod.AdventureRepository
WorldBossRepository = _repo_mod.WorldBossRepository
OutboxRepository = _repo_mod.OutboxRepository
shanghai_date_key = _repo_mod.shanghai_date_key

_registry_mod = load_package_module(
    "core/time_skip_registry.py",
    "astrbot_plugin_monixiuxian2_2.core.time_skip_registry",
)
TimeSkipRegistry = _registry_mod.TimeSkipRegistry

DataBase = sys.modules["astrbot_plugin_monixiuxian2_2.data"].DataBase

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# design §1 版本矩阵：每个新迁移版本独占的表集合
NEW_TABLES = {
    36: {"adventure_settlements", "adventure_effects", "adventure_fatigue"},
    37: {
        "world_boss_instances",
        "world_boss_challenges",
        "world_boss_daily_attempts",
        "world_boss_ledger",
        "world_boss_contributions",
    },
    38: {"business_events", "event_deliveries"},
    # v39 不拥有新表，只给 v36 的表增列（见 data/migration.py 注释）
    39: set(),
}

# 回退 DROP 必须子表先于父表（FK 引用方向见 data/migration.py DDL）
_DROP_ORDER = (
    "event_deliveries",
    "business_events",
    "world_boss_ledger",
    "world_boss_contributions",
    "world_boss_challenges",
    "world_boss_daily_attempts",
    "world_boss_instances",
    "adventure_effects",
    "adventure_settlements",
    "adventure_fatigue",
)
PVE_DOMAIN_TABLES = set().union(*NEW_TABLES.values())


# ----------------------------------------------------------------------
# fixtures / helpers
# ----------------------------------------------------------------------


@pytest_asyncio.fixture
async def db():
    """已迁移到最新版本、含 u1/u2 两名玩家的内存库。"""
    database = DataBase(":memory:")
    await database.connect()
    await MigrationManager(database.conn, StubConfigManager()).migrate_or_reset()
    await put_player(database, "u1", 500, 500, anchor=T0)
    await put_player(database, "u2", 300, 300, anchor=T0)
    yield database
    await database.close()


async def _scalar(conn, sql, params=()):
    async with conn.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row is not None else None


async def _table_names(conn):
    async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
        return {row[0] for row in await cur.fetchall()}


async def _db_version(conn):
    return int(await _scalar(conn, "SELECT version FROM db_info"))


async def _pragma_rows(conn, sql):
    async with conn.execute(sql) as cursor:
        return [tuple(row) for row in await cursor.fetchall()]


async def _schema_snapshot(conn):
    """归一化 schema 快照：sqlite_master 文本 + 每表 PRAGMA 结果。

    比较 fresh install 与升级链产物是否逐表一致（child P 锁定的关键
    decision）。sqlite_autoindex* 名称依赖建表顺序，排除后由 master 中
    的 UNIQUE 约束文本兜底。
    """
    master = await _pragma_rows(
        conn,
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name IS NOT NULL AND name != 'sqlite_sequence'",
    )
    norm_master = sorted(
        ((t, n, " ".join((sql or "").split())) for (t, n, sql) in master), key=repr
    )
    snap = {"master": norm_master}
    for table_type, name, _sql in master:
        if table_type != "table":
            continue
        table_info = {
            "table_info": sorted(
                await _pragma_rows(conn, f"PRAGMA table_info({name})")
            ),
            "index_list": sorted(
                row
                for row in await _pragma_rows(conn, f"PRAGMA index_list({name})")
                if not str(row[1]).startswith("sqlite_autoindex")
            ),
            "foreign_keys": sorted(
                await _pragma_rows(conn, f"PRAGMA foreign_key_list({name})")
            ),
        }
        for row in table_info["index_list"]:
            idx_name = str(row[1])
            table_info[idx_name] = sorted(
                await _pragma_rows(conn, f"PRAGMA index_info({idx_name})")
            )
        snap[name] = table_info
    return snap


async def _table_rows(conn, table):
    async with conn.execute(f"SELECT * FROM {table}") as cursor:
        rows = [tuple(row) for row in await cursor.fetchall()]
    # 用 repr 排序：首列可能含 NULL，元组直接比较在混合类型下不稳定
    return sorted(rows, key=repr)


async def _snapshot(conn, tables):
    return {table: await _table_rows(conn, table) for table in tables}


async def _build_rewound(path, to_version):
    """全新安装后回退到 to_version：DROP 掉 v > to_version 的域表并改写版本号。

    同时插入哨兵玩家 u_keep：后续升级若走 reset 路径会清库，哨兵消失即失败，
    由此保证测试覆盖的是任务链升级路径。
    """
    conn = await aiosqlite.connect(path)
    try:
        await MigrationManager(conn, StubConfigManager()).migrate_or_reset()
        doomed = set()
        for version, tables in NEW_TABLES.items():
            if version > to_version:
                doomed |= tables
        for table in _DROP_ORDER:
            if table in doomed:
                await conn.execute(f"DROP TABLE {table}")
        await conn.execute("INSERT INTO players (user_id) VALUES ('u_keep')")
        await conn.execute("UPDATE db_info SET version = ?", (to_version,))
        await conn.commit()
    finally:
        await conn.close()


async def _seed_instance(boss, instance_id="ins-1", max_hp=10000):
    """standalone 模式先提交一个 active Boss 实例，供事务内测试引用。"""
    row, created = await boss.insert_instance(
        instance_id=instance_id,
        profile_id="pf_cangyan",
        profile_version=3,
        max_hp=max_hp,
        now=T0,
        expires_at=T0 + 48 * 3600,
        boss_name="苍岩龙主",
        birth_snapshot={"phases": [1, 2, 3], "skills": ["劈岳"]},
    )
    assert created
    return row, created


async def _seed_event_and_delivery(outbox, event_id="ev-1", group_id="100"):
    event, created = await outbox.append_event(
        event_id=event_id,
        business_key=f"boss:{event_id}",
        event_type="boss_defeated",
        aggregate_type="world_boss_instance",
        aggregate_id="ins-1",
        occurred_at=T0,
        payload={"boss": "苍岩龙主"},
    )
    assert created
    delivery, d_created = await outbox.add_delivery(
        event_id=event_id, platform="aiocqhttp", group_id=group_id, now=T0
    )
    assert d_created
    return event, delivery


# ----------------------------------------------------------------------
# AC1 — 版本矩阵与 fresh install（design §1）
# ----------------------------------------------------------------------


def test_version_matrix_chain_registration():
    """v36–v39 均已注册迁移任务，链条末端 == LATEST_DB_VERSION。"""
    versions = set(MIGRATION_TASKS)
    assert LATEST_DB_VERSION == max(versions) == 39
    assert {36, 37, 38, 39} <= versions
    assert TASK_CHAIN_MIN_VERSION <= 36


def test_version_matrix_table_ownership():
    """VERSION_SCHEMA_TABLES 与 PRD 表清单逐版本一致且互不重叠。

    v39 拥有空表集合（child C 只给 v36 的 adventure_settlements 增列），
    登记它是为了版本矩阵逐版可复现；增列路径的 parity 由
    ``test_v39_adds_state_columns_to_published_v36_table`` 负责。
    """
    assert sorted(VERSION_SCHEMA_TABLES) == [36, 37, 38, 39]
    seen = set()
    for version, tables in NEW_TABLES.items():
        assert set(VERSION_SCHEMA_TABLES[version]) == tables
        assert not (seen & tables), f"v{version} 表集合与更早版本重叠"
        seen |= tables


@pytest.mark.asyncio
async def test_fresh_install_creates_all_pve_tables(db):
    """全新库迁移后：版本到最新，10 张 PVE 域表全部存在。"""
    assert await _db_version(db.conn) == LATEST_DB_VERSION
    names = await _table_names(db.conn)
    assert PVE_DOMAIN_TABLES <= names


# ----------------------------------------------------------------------
# AC1 强化 — fresh == upgrade schema 一致性（参数化回退点）
# ----------------------------------------------------------------------


@pytest.mark.parametrize("n", [36, 37, 38, 39])
@pytest.mark.asyncio
async def test_upgraded_schema_equals_fresh_install(tmp_path, n):
    """回退到 v{n}-1 后沿任务链升上来，schema 与全新安装逐表一致。"""
    up_path = str(tmp_path / f"at_v{n - 1}.db")
    await _build_rewound(up_path, n - 1)
    conn = await aiosqlite.connect(up_path)
    try:
        await MigrationManager(conn, StubConfigManager()).migrate_or_reset()
        assert await _db_version(conn) == LATEST_DB_VERSION
        upgraded = await _schema_snapshot(conn)
        # 哨兵存活 => 走的是升级链而非 reset 重建
        assert (
            await _scalar(conn, "SELECT COUNT(*) FROM players WHERE user_id='u_keep'")
            == 1
        )
    finally:
        await conn.close()

    fresh_conn = await aiosqlite.connect(str(tmp_path / "fresh.db"))
    try:
        await MigrationManager(fresh_conn, StubConfigManager()).migrate_or_reset()
        fresh_snap = await _schema_snapshot(fresh_conn)
    finally:
        await fresh_conn.close()

    assert upgraded == fresh_snap
    assert not list(tmp_path.glob("*.pre-reset.bak"))


# ----------------------------------------------------------------------
# v39 增列路径 — 已发布 v36 表结构的老库（ADD COLUMN 唯一真实覆盖）
# ----------------------------------------------------------------------

# 逐字抄自本 child 之前的 _create_adventure_persistence_tables（v36 已发布
# 定义）。上面那组 parity 用例靠 DROP+重建构造「升级前」，重建用的是**新版**
# DDL，永远摸不到 ADD COLUMN；真实用户库里那张表就是下面这个形状，所以
# 老库升级只能由这条用例覆盖。
_LEGACY_V36_SETTLEMENT_DDL = """
CREATE TABLE players (user_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS adventure_settlements (
    settlement_id TEXT PRIMARY KEY,
    adventure_run_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL
        REFERENCES players(user_id) ON DELETE CASCADE,
    encounter_id TEXT NOT NULL DEFAULT '',
    profile_id TEXT NOT NULL DEFAULT '',
    profile_version INTEGER NOT NULL DEFAULT 0,
    risk_level INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL DEFAULT '',
    hp_before INTEGER NOT NULL DEFAULT 0,
    hp_after INTEGER NOT NULL DEFAULT 0,
    fled INTEGER NOT NULL DEFAULT 0 CHECK (fled IN (0, 1)),
    defeated INTEGER NOT NULL DEFAULT 0 CHECK (defeated IN (0, 1)),
    settled_at INTEGER NOT NULL DEFAULT 0,
    cas_version INTEGER NOT NULL DEFAULT 1
);
INSERT INTO players VALUES ('u_old');
INSERT INTO adventure_settlements
    (settlement_id, adventure_run_id, user_id, outcome, hp_before, hp_after,
     defeated, settled_at)
VALUES ('s_old', 'r_old', 'u_old', 'win', 500, 420, 1, 1700000000);
"""

_V39_COLUMNS = ("state", "route_key", "snapshot")


async def _column_defs(conn):
    """PRAGMA table_info 的 (name, type, notnull, dflt_value, pk) 视图。"""
    rows = await _pragma_rows(conn, "PRAGMA table_info(adventure_settlements)")
    # row = (cid, name, type, notnull, dflt_value, pk)
    return {row[1]: (row[2], row[3], row[4], row[5]) for row in rows}


@pytest.mark.asyncio
async def test_v39_adds_state_columns_to_published_v36_table(tmp_path):
    """老库（v36 原表 + 已有事实行）升到 v39：补三列、历史行落合法终态。"""
    conn = await aiosqlite.connect(str(tmp_path / "at_v36_with_data.db"))
    try:
        await conn.executescript(_LEGACY_V36_SETTLEMENT_DDL)
        await conn.commit()
        # 前置：确认构造出的确实是增列前的形状
        assert not set(_V39_COLUMNS) & set(await _column_defs(conn))

        await MIGRATION_TASKS[39](conn, StubConfigManager())
        await conn.commit()

        defs = await _column_defs(conn)
        assert set(_V39_COLUMNS) <= set(defs), "v39 必须补齐状态机三列"
        # 三列追加在 cas_version 之后：与 fresh 路径的列序一致（cid 也一致）
        names = [
            row[1]
            for row in await _pragma_rows(
                conn, "PRAGMA table_info(adventure_settlements)"
            )
        ]
        assert names[-3:] == list(_V39_COLUMNS)

        # 历史行不能被新代码读成「进行中/待选择」：默认值必须是合法终态
        assert (
            await _scalar(
                conn, "SELECT state FROM adventure_settlements WHERE settlement_id='s_old'"
            )
            == "resolved_win"
        )
        assert (
            await _scalar(
                conn,
                "SELECT route_key || '|' || snapshot FROM adventure_settlements "
                "WHERE settlement_id='s_old'",
            )
            == "|{}"
        )

        # CHECK 取值域留在 schema 层（ADD COLUMN 带约束在 SQLite 里真能拦截），
        # 不退化成仓储层校验
        with pytest.raises(sqlite3.IntegrityError):
            await conn.execute(
                "UPDATE adventure_settlements SET state='in_fight' "
                "WHERE settlement_id='s_old'"
            )

        # 状态索引随增列补齐
        idx = {
            row[1]
            for row in await _pragma_rows(conn, "PRAGMA index_list(adventure_settlements)")
        }
        assert "idx_adventure_settlements_user_state" in idx

        # 幂等重放：v35→v39 一路升上来的库，表是新版 DDL 建的，列已存在，
        # 二次执行不得 duplicate column 报错
        await MIGRATION_TASKS[39](conn, StubConfigManager())
        assert (await _column_defs(conn)) == defs
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_v39_legacy_columns_equal_fresh_install(tmp_path, db):
    """增列后的列定义与全新安装逐字段一致（fresh==upgrade 的增列版证明）。"""
    conn = await aiosqlite.connect(str(tmp_path / "legacy_parity.db"))
    try:
        await conn.executescript(_LEGACY_V36_SETTLEMENT_DDL)
        await conn.commit()
        await MIGRATION_TASKS[39](conn, StubConfigManager())
        await conn.commit()
        upgraded = await _column_defs(conn)
        fresh = await _column_defs(db.conn)
        for name in _V39_COLUMNS:
            assert upgraded[name] == fresh[name], f"{name} 列定义漂移"
    finally:
        await conn.close()


# ----------------------------------------------------------------------
# AC2 — v34 → 最新走升级链，不触发 reset
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v34_upgrade_chain_preserves_data(tmp_path):
    """v34 老库升级到最新：玩家数据保留、无 reset 备份、新域表齐备。"""
    path = str(tmp_path / "v34.db")
    await build_v34_db(path)
    conn = await aiosqlite.connect(path)
    try:
        await MigrationManager(conn, StubConfigManager()).migrate_or_reset()
        assert await _db_version(conn) == LATEST_DB_VERSION
        assert (
            await _scalar(conn, "SELECT base_hp FROM players WHERE user_id='u_bare'")
            == 120
        )
        names = await _table_names(conn)
        assert PVE_DOMAIN_TABLES <= names
    finally:
        await conn.close()
    assert not list(tmp_path.glob("*.pre-reset.bak"))


# ----------------------------------------------------------------------
# AC3 — 迁移失败回滚停在 N-1；任务重放幂等
# ----------------------------------------------------------------------


@pytest.mark.parametrize("n", [36, 37, 38])
@pytest.mark.asyncio
async def test_migration_failure_rolls_back_and_resumes(tmp_path, monkeypatch, n):
    """注入 v{n} 任务失败：整体回滚（版本与 DDL 都不落库），修好后可续跑到最新。"""
    path = str(tmp_path / f"boom_v{n}.db")
    await _build_rewound(path, n - 1)
    conn = await aiosqlite.connect(path)
    try:

        async def boom(_conn, _config):
            await _conn.execute(f"CREATE TABLE canary_v{n} (x INTEGER)")
            raise RuntimeError("injected migration failure")

        monkeypatch.setitem(MIGRATION_TASKS, n, boom)
        with pytest.raises(RuntimeError, match="injected migration failure"):
            await MigrationManager(conn, StubConfigManager()).migrate_or_reset()

        assert await _db_version(conn) == n - 1
        names = await _table_names(conn)
        assert f"canary_v{n}" not in names, "失败事务未回滚（SQLite 应支持事务性 DDL）"
        for version, tables in NEW_TABLES.items():
            if version >= n:
                assert not (names & tables), f"v{version} 表泄漏"
            else:
                assert tables <= names, f"v{version} 已提交表被误删"
        assert (
            await _scalar(conn, "SELECT COUNT(*) FROM players WHERE user_id='u_keep'")
            == 1
        )
    finally:
        await conn.close()

    monkeypatch.undo()
    resume = await aiosqlite.connect(path)
    try:
        await MigrationManager(resume, StubConfigManager()).migrate_or_reset()
        assert await _db_version(resume) == LATEST_DB_VERSION
        assert PVE_DOMAIN_TABLES <= await _table_names(resume)
    finally:
        await resume.close()


@pytest.mark.parametrize("n", [36, 37, 38])
@pytest.mark.asyncio
async def test_migration_task_rerun_is_idempotent(db, n):
    """v{n} 任务在最新 schema 上重放：schema 不变（CREATE IF NOT EXISTS 幂等）。"""
    before = await _schema_snapshot(db.conn)
    await MIGRATION_TASKS[n](db.conn, StubConfigManager())
    await db.conn.commit()
    assert await _schema_snapshot(db.conn) == before
    assert await _db_version(db.conn) == LATEST_DB_VERSION


# ----------------------------------------------------------------------
# AC4 — 仓储契约：幂等 / CAS / claim / 封顶
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settlement_insert_is_idempotent_per_run(db):
    """同 adventure_run_id 重放返回首行、不重复插入；不同 run 各自成行。"""
    adv = AdventureRepository(db.conn)
    row1, created1 = await adv.insert_settlement(
        settlement_id="set-1",
        adventure_run_id="run-1",
        user_id="u1",
        now=T0,
        encounter_id="enc-7",
        outcome="win",
        hp_before=500,
        hp_after=420,
    )
    assert created1 and row1["settlement_id"] == "set-1" and row1["cas_version"] == 1
    row2, created2 = await adv.insert_settlement(
        settlement_id="set-dup",
        adventure_run_id="run-1",
        user_id="u1",
        now=T0 + 5,
        outcome="lose",
    )
    assert not created2
    assert row2["settlement_id"] == "set-1", "重放必须返回首次结算行"
    assert row2["outcome"] == "win", "重放不得覆盖原始结算字段"
    again = await adv.get_settlement_by_run("run-1")
    assert again["settlement_id"] == "set-1"
    row3, created3 = await adv.insert_settlement(
        settlement_id="set-2",
        adventure_run_id="run-2",
        user_id="u2",
        now=T0,
    )
    assert created3 and row3["settlement_id"] == "set-2"


@pytest.mark.asyncio
async def test_settlement_cas_conflict_rejects_stale(db):
    """结算行 CAS：前像版本匹配则更新并 bump，过期版本返回 False。"""
    adv = AdventureRepository(db.conn)
    await adv.insert_settlement(
        settlement_id="set-cas",
        adventure_run_id="run-cas",
        user_id="u1",
        now=T0,
        outcome="fighting",
    )
    assert (
        await adv.cas_update_settlement(
            "set-cas", expected_cas_version=1, outcome="fled", fled=True
        )
        is True
    )
    row = await adv.get_settlement("set-cas")
    assert row["outcome"] == "fled" and row["fled"] == 1 and row["cas_version"] == 2
    assert (
        await adv.cas_update_settlement("set-cas", expected_cas_version=1, outcome="x")
        is False
    )
    assert (await adv.get_settlement("set-cas"))["outcome"] == "fled"


@pytest.mark.asyncio
async def test_effect_claim_first_consumer_wins(db):
    """效果消费 claim 键 (consumer, settlement, effect_type)：首个 True，重复 False。"""
    adv = AdventureRepository(db.conn)
    await adv.insert_settlement(
        settlement_id="set-claim",
        adventure_run_id="run-claim",
        user_id="u1",
        now=T0,
    )
    common = {"settlement_id": "set-claim", "now": T0}
    assert await adv.claim_effect(consumer_name="gold", effect_type="reward", **common)
    assert not await adv.claim_effect(
        consumer_name="gold", effect_type="reward", **common
    )
    assert await adv.claim_effect(consumer_name="bag", effect_type="reward", **common)
    assert await adv.claim_effect(consumer_name="gold", effect_type="hp", **common)
    claims = await adv.list_effect_claims("set-claim")
    assert len(claims) == 3
    assert {(c["consumer_name"], c["effect_type"]) for c in claims} == {
        ("gold", "reward"),
        ("bag", "reward"),
        ("gold", "hp"),
    }


@pytest.mark.asyncio
async def test_fatigue_upsert_and_cas_clear(db):
    """疲劳按玩家 upsert，cas_clear 只认当前版本；到期列是 fatigue_until。"""
    adv = AdventureRepository(db.conn)
    assert await adv.get_fatigue("u1") is None
    row = await adv.set_fatigue(
        user_id="u1", route_id="r9", fatigue_until=T0 + 3600, settlement_id="set-f"
    )
    assert row["fatigue_until"] == T0 + 3600 and row["cas_version"] == 1
    row2 = await adv.set_fatigue(user_id="u1", route_id="r10", fatigue_until=T0 + 7200)
    assert row2["route_id"] == "r10" and row2["cas_version"] == 2
    assert await adv.cas_clear_fatigue("u1", expected_cas_version=1) is False
    assert await adv.cas_clear_fatigue("u1", expected_cas_version=2) is True
    cleared = await adv.get_fatigue("u1")
    assert cleared["fatigue_until"] == 0 and cleared["route_id"] == ""


@pytest.mark.asyncio
async def test_player_health_cas_uses_before_image(db):
    """健康 CAS 以 (current_hp, health_recovered_at) 前像对为版本。"""
    base = BaseRepository(db.conn)
    assert (
        await base.cas_update_player_health(
            user_id="u1",
            expected_current_hp=500,
            expected_health_recovered_at=T0,
            new_current_hp=250,
        )
        is True
    )
    row = await base.get_player_health("u1")
    assert row["current_hp"] == 250 and row["health_recovered_at"] == T0
    assert (
        await base.cas_update_player_health(
            user_id="u1",
            expected_current_hp=500,
            expected_health_recovered_at=T0,
            new_current_hp=10,
        )
        is False
    ), "前像不匹配必须拒绝"
    assert (
        await base.cas_update_player_health(
            user_id="u1",
            expected_current_hp=250,
            expected_health_recovered_at=T0,
            new_current_hp=500,
            new_health_recovered_at=T0 + 60,
        )
        is True
    )
    healed = await base.get_player_health("u1")
    assert healed["current_hp"] == 500 and healed["health_recovered_at"] == T0 + 60
    assert (
        await base.cas_update_player_health(
            user_id="ghost",
            expected_current_hp=1,
            expected_health_recovered_at=0,
            new_current_hp=2,
        )
        is False
    )


@pytest.mark.asyncio
async def test_boss_instance_replay_keeps_birth_snapshot(db):
    """实例按 instance_id 幂等：重放冻结出生数值，只回读首行。"""
    boss = WorldBossRepository(db.conn)
    row, created = await _seed_instance(boss)
    assert created and row["state"] == "active" and row["current_hp"] == 10000
    assert row["cas_version"] == 1 and row["spawned_at"] == T0
    replay, created2 = await boss.insert_instance(
        instance_id="ins-1",
        profile_id="pf_other",
        profile_version=99,
        max_hp=1,
        now=T0 + 10,
        expires_at=T0 + 1,
        boss_name="改名龙主",
    )
    assert not created2
    assert replay["max_hp"] == 10000 and replay["profile_version"] == 3
    assert replay["boss_name"] == "苍岩龙主"
    assert json.loads(replay["birth_snapshot"]) == {
        "phases": [1, 2, 3],
        "skills": ["劈岳"],
    }
    assert await boss.list_instances(states=("active",)) == [replay]
    assert await boss.list_instances(states=("defeated",)) == []


@pytest.mark.asyncio
async def test_boss_instance_cas_damage_conflict(db):
    """实例伤害写入按谓词列 + cas_version 做 CAS，过期前像拒绝。"""
    boss = WorldBossRepository(db.conn)
    await _seed_instance(boss)
    assert (
        await boss.cas_update_instance(
            "ins-1",
            expected={"state": "active", "current_hp": 10000, "cas_version": 1},
            current_hp=9000,
        )
        is True
    )
    assert (
        await boss.cas_update_instance(
            "ins-1",
            expected={"state": "active", "current_hp": 10000, "cas_version": 1},
            current_hp=8000,
        )
        is False
    ), "过期前像必须 CAS 冲突"
    row = await boss.get_instance("ins-1")
    assert row["current_hp"] == 9000 and row["cas_version"] == 2
    assert (
        await boss.cas_update_instance(
            "ins-1",
            expected={"state": "active", "current_hp": 9000, "cas_version": 2},
            current_hp=0,
            state="defeated",
        )
        is True
    )
    assert (await boss.get_instance("ins-1"))["state"] == "defeated"


@pytest.mark.asyncio
async def test_cas_update_instance_requires_cas_version(db):
    """expected 缺 cas_version 必须显式报错——静默按 0 会伪装成永远冲突。"""
    boss = WorldBossRepository(db.conn)
    await _seed_instance(boss)
    with pytest.raises(ValueError):
        await boss.cas_update_instance(
            "ins-1",
            expected={"state": "active", "current_hp": 10000},
            current_hp=1,
        )
    row = await boss.get_instance("ins-1")
    assert row["current_hp"] == 10000 and row["cas_version"] == 1, (
        "参数校验必须发生在任何 DB 写入之前"
    )


@pytest.mark.asyncio
async def test_instance_cas_conflict_under_concurrent_tasks(db):
    """AC4 真并发：两任务交错读同一前像，后写者必须 CAS 失败。

    用 Event 钉死交错点：A 读 → B 读（同一 cas_version）→ A 写 → B 写。
    gather 保证两个 racer 是独立 Task，走真实调度而非顺序模拟。
    """
    boss = WorldBossRepository(db.conn)
    await _seed_instance(boss)
    a_read, b_read, a_done = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def _racer_a() -> bool:
        snap = await boss.get_instance("ins-1")
        assert snap["cas_version"] == 1
        a_read.set()
        await b_read.wait()
        ok = await boss.cas_update_instance(
            "ins-1",
            expected={
                "state": snap["state"],
                "current_hp": snap["current_hp"],
                "cas_version": snap["cas_version"],
            },
            current_hp=7000,
        )
        a_done.set()
        return ok

    async def _racer_b() -> bool:
        await a_read.wait()
        snap = await boss.get_instance("ins-1")
        b_read.set()
        await a_done.wait()
        ok = await boss.cas_update_instance(
            "ins-1",
            expected={
                "state": snap["state"],
                "current_hp": snap["current_hp"],
                "cas_version": snap["cas_version"],
            },
            current_hp=6000,
        )
        return ok

    ok_a, ok_b = await asyncio.gather(_racer_a(), _racer_b())
    assert ok_a is True and ok_b is False, "基于同一陈旧前像的后写者必须败给 CAS"
    row = await boss.get_instance("ins-1")
    assert row["current_hp"] == 7000 and row["cas_version"] == 2


@pytest.mark.asyncio
async def test_daily_attempts_gather_concurrency_respects_cap(db):
    """并发自增每日次数：5 任务 gather、limit=3 恰好 3 次成功且不越帽。"""
    boss = WorldBossRepository(db.conn)
    date_key = shanghai_date_key(T0)
    results = await asyncio.gather(
        *[
            boss.increment_daily_attempts(date_key=date_key, user_id="u1", limit=3)
            for _ in range(5)
        ]
    )
    granted = [row for row in results if row is not None]
    assert len(granted) == 3, "封顶语义必须扛住任务交错"
    final = await boss.get_daily_attempts(date_key=date_key, user_id="u1")
    assert final["attempts_used"] == 3


@pytest.mark.asyncio
async def test_daily_attempts_capped_per_beijing_day(db):
    """每日次数按 (date_key, user_id) 封顶：满额返回 None 且不消耗。"""
    boss = WorldBossRepository(db.conn)
    day_a, day_b = shanghai_date_key(T0), "2023-11-16"
    for expected in (1, 2, 3):
        row = await boss.increment_daily_attempts(date_key=day_a, user_id="u1", limit=3)
        assert row is not None and row["attempts_used"] == expected
    assert (
        await boss.increment_daily_attempts(date_key=day_a, user_id="u1", limit=3)
        is None
    )
    stuck = await boss.get_daily_attempts(date_key=day_a, user_id="u1")
    assert stuck["attempts_used"] == 3, "封顶后不得再自增"
    other_day = await boss.increment_daily_attempts(
        date_key=day_b, user_id="u1", limit=3
    )
    assert other_day["attempts_used"] == 1, "跨自然日重新计数"
    other_user = await boss.increment_daily_attempts(
        date_key=day_a, user_id="u2", limit=3
    )
    assert other_user["attempts_used"] == 1, "按玩家维度独立"


@pytest.mark.asyncio
async def test_challenge_replay_and_ledger_idempotent(db):
    """挑战按 challenge_id 幂等；账本对 challenge 唯一，重放不双记。"""
    boss = WorldBossRepository(db.conn)
    await _seed_instance(boss)
    date_key = shanghai_date_key(T0)
    common = {
        "challenge_id": "ch-1",
        "instance_id": "ins-1",
        "user_id": "u1",
        "date_key": date_key,
        "damage_dealt": 1000,
        "hp_before": 10000,
        "hp_after": 9000,
        "player_hp_before": 500,
        "player_hp_after": 450,
        "instance_cas_version": 1,
        "now": T0,
        "outcome": "win",
    }
    row, created = await boss.record_challenge(**common)
    assert created and row["damage_dealt"] == 1000
    replay, created2 = await boss.record_challenge(
        **{**common, "damage_dealt": 5, "hp_after": 9995}
    )
    assert (
        not created2 and replay["damage_dealt"] == 1000 and replay["hp_after"] == 9000
    )
    assert len(await boss.list_challenges("ins-1")) == 1

    ledger, l_created = await boss.record_ledger(
        instance_id="ins-1",
        challenge_id="ch-1",
        user_id="u1",
        profile_version=3,
        damage_dealt=1000,
        now=T0,
    )
    assert l_created and ledger["damage_dealt"] == 1000
    replay_ledger, l_created2 = await boss.record_ledger(
        instance_id="ins-1",
        challenge_id="ch-1",
        user_id="u1",
        profile_version=9,
        damage_dealt=777,
        now=T0 + 1,
    )
    assert not l_created2 and replay_ledger["damage_dealt"] == 1000
    assert (await boss.get_ledger("ch-1"))["profile_version"] == 3


@pytest.mark.asyncio
async def test_contribution_accumulates_with_sticky_last_hit(db):
    """贡献 upsert 单语句累积：total/attempt 累加、first 只认最早、last-hit 粘住。"""
    boss = WorldBossRepository(db.conn)
    await _seed_instance(boss)
    first = await boss.accumulate_contribution(
        instance_id="ins-1", user_id="u1", profile_version=3, damage_dealt=1000, now=T0
    )
    assert (first["total_damage"], first["attempt_count"]) == (1000, 1)
    assert first["first_hit_at"] == T0 and first["is_last_hit"] == 0
    killer = await boss.accumulate_contribution(
        instance_id="ins-1",
        user_id="u1",
        profile_version=3,
        damage_dealt=9000,
        now=T0 + 10,
        is_last_hit=True,
    )
    assert (killer["total_damage"], killer["attempt_count"]) == (10000, 2)
    assert killer["first_hit_at"] == T0 and killer["last_hit_at"] == T0 + 10
    assert killer["is_last_hit"] == 1
    later = await boss.accumulate_contribution(
        instance_id="ins-1",
        user_id="u1",
        profile_version=3,
        damage_dealt=1,
        now=T0 + 20,
    )
    assert later["is_last_hit"] == 1, "非终击不得清除 sticky last-hit"
    assert later["first_hit_at"] == T0
    await boss.accumulate_contribution(
        instance_id="ins-1",
        user_id="u2",
        profile_version=3,
        damage_dealt=500,
        now=T0 + 5,
    )
    board = await boss.list_contributions("ins-1")
    assert [row["user_id"] for row in board] == ["u1", "u2"]
    assert board[0]["total_damage"] == 10001


@pytest.mark.asyncio
async def test_event_business_key_and_delivery_pair_idempotent(db):
    """事件按 business_key、投递按 (event, platform, group) 各自幂等。"""
    outbox = OutboxRepository(db.conn)
    event, created = await outbox.append_event(
        event_id="ev-a",
        business_key="bk-a",
        event_type="boss_spawned",
        aggregate_type="world_boss_instance",
        aggregate_id="ins-1",
        occurred_at=T0,
        payload={"hp": 10000},
    )
    assert created and json.loads(event["payload"]) == {"hp": 10000}
    replay, created2 = await outbox.append_event(
        event_id="ev-b",
        business_key="bk-a",
        event_type="boss_spawned",
        aggregate_type="world_boss_instance",
        aggregate_id="ignored",
        occurred_at=T0 + 99,
        payload="{}",
    )
    assert not created2 and replay["event_id"] == "ev-a", (
        "business_key 重放须返回原事件"
    )
    delivery, d1 = await outbox.add_delivery(
        event_id="ev-a", platform="aiocqhttp", group_id="100", now=T0
    )
    assert d1 and delivery["state"] == "queued"
    dup, d2 = await outbox.add_delivery(
        event_id="ev-a", platform="aiocqhttp", group_id="100", now=T0 + 1
    )
    assert not d2 and dup["delivery_id"] == delivery["delivery_id"]
    other, d3 = await outbox.add_delivery(
        event_id="ev-a", platform="aiocqhttp", group_id="200", now=T0
    )
    assert d3 and other["group_id"] == "200"
    queued = await outbox.list_deliveries(states=("queued",), now=T0)
    assert len(queued) == 2


@pytest.mark.asyncio
async def test_foreign_keys_enforced_on_new_tables(db):
    """新表 FK 生效：未知玩家结算、未知事件投递都报 IntegrityError 且无残留。"""
    adv = AdventureRepository(db.conn)
    with pytest.raises(sqlite3.IntegrityError):
        await adv.insert_settlement(
            settlement_id="set-orphan",
            adventure_run_id="run-orphan",
            user_id="ghost-user",
            now=T0,
        )
    assert await adv.get_settlement("set-orphan") is None
    outbox = OutboxRepository(db.conn)
    with pytest.raises(sqlite3.IntegrityError):
        await outbox.add_delivery(
            event_id="no-such-event", platform="aiocqhttp", group_id="1", now=T0
        )
    assert await _scalar(db.conn, "SELECT COUNT(*) FROM event_deliveries") == 0


@pytest.mark.asyncio
async def test_foreign_key_check_clean_on_seeded_db(db):
    """PRD R1 点名：PVE 十表全部灌入合法关联行后 foreign_key_check 零违例。

    逐表断言非空，防止「空库平凡通过」的假阳性。
    """
    adv = AdventureRepository(db.conn)
    boss = WorldBossRepository(db.conn)
    outbox = OutboxRepository(db.conn)
    date_key = shanghai_date_key(T0)
    await adv.insert_settlement(
        settlement_id="set-fk",
        adventure_run_id="run-fk",
        user_id="u1",
        now=T0,
    )
    assert await adv.claim_effect(
        consumer_name="gold", settlement_id="set-fk", effect_type="reward", now=T0
    )
    await adv.set_fatigue(user_id="u1", route_id="r-fk", fatigue_until=T0 + 3600)
    await _seed_instance(boss)
    assert await boss.increment_daily_attempts(date_key=date_key, user_id="u1", limit=3)
    await boss.record_challenge(
        challenge_id="ch-fk",
        instance_id="ins-1",
        user_id="u1",
        date_key=date_key,
        damage_dealt=1500,
        hp_before=10000,
        hp_after=8500,
        player_hp_before=500,
        player_hp_after=480,
        instance_cas_version=1,
        now=T0,
        outcome="win",
    )
    await boss.record_ledger(
        instance_id="ins-1",
        challenge_id="ch-fk",
        user_id="u1",
        profile_version=3,
        damage_dealt=1500,
        now=T0,
    )
    await boss.accumulate_contribution(
        instance_id="ins-1",
        user_id="u1",
        profile_version=3,
        damage_dealt=1500,
        now=T0,
        is_last_hit=False,
    )
    await _seed_event_and_delivery(outbox)
    assert await _pragma_rows(db.conn, "PRAGMA foreign_key_check") == []
    for table in sorted(PVE_DOMAIN_TABLES):
        assert await _scalar(db.conn, f"SELECT COUNT(*) FROM {table}") > 0, (
            f"{table} 未灌数据，FK 检查结论无效"
        )


@pytest.mark.asyncio
async def test_foreign_key_check_clean_on_v34_upgraded_db(tmp_path):
    """真实 v34→latest 升级链产物库同样须通过 foreign_key_check。"""
    path = str(tmp_path / "v34.db")
    await build_v34_db(path)
    conn = await aiosqlite.connect(path)
    try:
        await MigrationManager(conn, StubConfigManager()).migrate_or_reset()
        assert await _db_version(conn) == LATEST_DB_VERSION
        boss = WorldBossRepository(conn)
        await boss.insert_instance(
            instance_id="ins-fk2",
            profile_id="pf_cangyan",
            profile_version=3,
            max_hp=5000,
            now=T0,
            expires_at=T0 + 3600,
            boss_name="苍岩龙主",
        )
        await boss.accumulate_contribution(
            instance_id="ins-fk2",
            user_id="u_bare",
            profile_version=3,
            damage_dealt=200,
            now=T0,
            is_last_hit=False,
        )
        assert await _pragma_rows(conn, "PRAGMA foreign_key_check") == []
    finally:
        await conn.close()


# ----------------------------------------------------------------------
# AC4 强化 — Outbox dispatcher claim/lease 生命周期（design §3.4）
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_claim_lease_and_complete_lifecycle(db):
    """投递 claim 单赢家；lease 前不可重占；错误 owner/版本拒绝；sent 终结。"""
    outbox = OutboxRepository(db.conn)
    _event, delivery = await _seed_event_and_delivery(outbox)
    did = delivery["delivery_id"]
    claimed = await outbox.claim_delivery(did, owner="w1", lease_until=T0 + 30, now=T0)
    assert claimed and claimed["state"] == "dispatching"
    assert claimed["claim_owner"] == "w1"
    assert claimed["attempt_count"] == delivery["attempt_count"] + 1
    assert (
        await outbox.claim_delivery(did, owner="w2", lease_until=T0 + 30, now=T0 + 1)
        is None
    ), "lease 有效期内第二个 worker 必须抢不到"
    assert await outbox.list_stale_dispatching(now=T0 + 10) == []
    stale = await outbox.list_stale_dispatching(now=T0 + 30)
    assert [row["delivery_id"] for row in stale] == [did]
    v = claimed["cas_version"]
    assert (
        await outbox.complete_delivery(
            did, owner="w2", expected_cas_version=v, state="sent", now=T0 + 5
        )
        is False
    ), "非持有者不得终结"
    assert (
        await outbox.complete_delivery(
            did, owner="w1", expected_cas_version=v - 1, state="sent", now=T0 + 5
        )
        is False
    ), "过期 cas_version 必须拒绝"
    assert (
        await outbox.complete_delivery(
            did, owner="w1", expected_cas_version=v, state="sent", now=T0 + 5
        )
        is True
    )
    done = await outbox.get_delivery(did)
    assert done["state"] == "sent" and done["claim_owner"] == ""
    assert done["next_retry_at"] == 0
    assert (
        await outbox.claim_delivery(
            did, owner="w3", lease_until=T0 + 9999, now=T0 + 999
        )
        is None
    ), "sent 是终态，不可再 claim"


@pytest.mark.asyncio
async def test_retry_watermark_and_uncertain_never_auto_reclaimed(db):
    """queued 重试受 next_retry_at 水位约束；uncertain 永不自动回收。"""
    outbox = OutboxRepository(db.conn)
    _event, delivery = await _seed_event_and_delivery(outbox)
    did = delivery["delivery_id"]
    claimed = await outbox.claim_delivery(did, owner="w1", lease_until=T0 + 30, now=T0)
    assert (
        await outbox.complete_delivery(
            did,
            owner="w1",
            expected_cas_version=claimed["cas_version"],
            state="queued",
            now=T0 + 5,
            error="网络超时",
            retry_at=T0 + 60,
        )
        is True
    )
    waiting = await outbox.get_delivery(did)
    assert waiting["state"] == "queued" and waiting["next_retry_at"] == T0 + 60
    assert waiting["last_error"] == "网络超时"
    assert (
        await outbox.claim_delivery(did, owner="w1", lease_until=T0 + 90, now=T0 + 10)
        is None
    ), "未到重试水位不得重新领取"
    again = await outbox.claim_delivery(
        did, owner="w1", lease_until=T0 + 90, now=T0 + 60
    )
    assert again is not None and again["attempt_count"] == 2
    assert (
        await outbox.complete_delivery(
            did,
            owner="w1",
            expected_cas_version=again["cas_version"],
            state="uncertain",
            now=T0 + 70,
            error="发送结果未知",
        )
        is True
    )
    hung = await outbox.get_delivery(did)
    assert hung["state"] == "uncertain" and hung["claim_owner"] == ""
    assert (
        await outbox.claim_delivery(
            did, owner="w9", lease_until=T0 + 10**9, now=T0 + 10**8
        )
        is None
    ), "uncertain 必须留给人工裁决，永不自动回收"
    assert await outbox.list_stale_dispatching(now=T0 + 10**9) == []
    with pytest.raises(ValueError):
        await outbox.complete_delivery(
            did, owner="w1", expected_cas_version=99, state="dispatching", now=T0
        )


# ----------------------------------------------------------------------
# AC5 — 原子调用图（design §3）：事务内抛错 → 零残留
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_transition_graph_rolls_back_atomically(db):
    """§3.1 健康转换图：players + user_cd 同事务，抛错后两边都不留痕。"""
    tables = ("players", "user_cd")
    base = BaseRepository(db.conn)
    baseline = await _snapshot(db.conn, tables)
    with pytest.raises(RuntimeError):
        async with db.transaction():
            assert await base.cas_update_player_health(
                user_id="u1",
                expected_current_hp=500,
                expected_health_recovered_at=T0,
                new_current_hp=250,
                new_health_recovered_at=T0 + 60,
            )
            await db.ext.set_user_busy("u1", 2, T0 + 600)
            raise RuntimeError("boom after partial writes")
    assert await _snapshot(db.conn, tables) == baseline

    async with db.transaction():
        assert await base.cas_update_player_health(
            user_id="u1",
            expected_current_hp=500,
            expected_health_recovered_at=T0,
            new_current_hp=250,
            new_health_recovered_at=T0 + 60,
        )
        await db.ext.set_user_busy("u1", 2, T0 + 600)
    row = await base.get_player_health("u1")
    assert row["current_hp"] == 250 and row["health_recovered_at"] == T0 + 60
    cd = await db.ext.get_user_cd("u1")
    assert cd is not None and cd.scheduled_time == T0 + 600


@pytest.mark.asyncio
async def test_adventure_terminal_graph_rolls_back_atomically(db):
    """§3.2 历练终结图：结算+效果 claim+疲劳+健康+忙碌五写点，失败零残留。"""
    tables = (
        "players",
        "user_cd",
        "adventure_settlements",
        "adventure_effects",
        "adventure_fatigue",
    )
    adv = AdventureRepository(db.conn)
    base = BaseRepository(db.conn)
    baseline = await _snapshot(db.conn, tables)

    async def _body():
        await adv.insert_settlement(
            settlement_id="set-g2",
            adventure_run_id="run-g2",
            user_id="u1",
            now=T0,
            outcome="win",
            hp_before=500,
            hp_after=380,
        )
        assert await adv.claim_effect(
            consumer_name="gold", settlement_id="set-g2", effect_type="reward", now=T0
        )
        assert await adv.claim_effect(
            consumer_name="bag", settlement_id="set-g2", effect_type="reward", now=T0
        )
        await adv.set_fatigue(
            user_id="u1", route_id="r1", fatigue_until=T0 + 3600, settlement_id="set-g2"
        )
        assert await base.cas_update_player_health(
            user_id="u1",
            expected_current_hp=500,
            expected_health_recovered_at=T0,
            new_current_hp=380,
        )
        await db.ext.set_user_busy("u1", 0, 0)

    with pytest.raises(RuntimeError):
        async with db.transaction():
            await _body()
            raise RuntimeError("boom mid-graph")
    assert await _snapshot(db.conn, tables) == baseline

    async with db.transaction():
        await _body()
    assert await adv.get_settlement_by_run("run-g2") is not None
    assert len(await adv.list_effect_claims("set-g2")) == 2
    assert (await adv.get_fatigue("u1"))["fatigue_until"] == T0 + 3600
    assert (await base.get_player_health("u1"))["current_hp"] == 380


@pytest.mark.asyncio
async def test_boss_challenge_graph_rolls_back_atomically(db):
    """§3.3 Boss 挑战图：次数+实例 CAS+挑战+账本+贡献+事件+投递，失败零残留。"""
    boss = WorldBossRepository(db.conn)
    outbox = OutboxRepository(db.conn)
    await _seed_instance(boss)
    tables = (
        "players",
        "world_boss_daily_attempts",
        "world_boss_instances",
        "world_boss_challenges",
        "world_boss_ledger",
        "world_boss_contributions",
        "business_events",
        "event_deliveries",
    )
    baseline = await _snapshot(db.conn, tables)
    date_key = shanghai_date_key(T0)

    async def _body():
        attempt = await boss.increment_daily_attempts(
            date_key=date_key, user_id="u1", limit=3
        )
        assert attempt is not None
        assert await boss.cas_update_instance(
            "ins-1",
            expected={"state": "active", "current_hp": 10000, "cas_version": 1},
            current_hp=0,
            state="defeated",
        )
        await boss.record_challenge(
            challenge_id="ch-g3",
            instance_id="ins-1",
            user_id="u1",
            date_key=date_key,
            damage_dealt=10000,
            hp_before=10000,
            hp_after=0,
            player_hp_before=500,
            player_hp_after=500,
            instance_cas_version=1,
            now=T0,
            outcome="win",
            is_last_hit=True,
        )
        await boss.record_ledger(
            instance_id="ins-1",
            challenge_id="ch-g3",
            user_id="u1",
            profile_version=3,
            damage_dealt=10000,
            now=T0,
        )
        await boss.accumulate_contribution(
            instance_id="ins-1",
            user_id="u1",
            profile_version=3,
            damage_dealt=10000,
            now=T0,
            is_last_hit=True,
        )
        await outbox.append_event(
            event_id="ev-g3",
            business_key="boss-defeat:ins-1",
            event_type="boss_defeated",
            aggregate_type="world_boss_instance",
            aggregate_id="ins-1",
            occurred_at=T0,
        )
        await outbox.add_delivery(
            event_id="ev-g3", platform="aiocqhttp", group_id="100", now=T0
        )

    with pytest.raises(RuntimeError):
        async with db.transaction():
            await _body()
            raise RuntimeError("boom after boss writes")
    assert await _snapshot(db.conn, tables) == baseline, (
        "实例 cas_version 回到 1 即证明写点全部回滚"
    )

    async with db.transaction():
        await _body()
    inst = await boss.get_instance("ins-1")
    assert inst["state"] == "defeated" and inst["cas_version"] == 2
    assert (await boss.get_daily_attempts(date_key=date_key, user_id="u1"))[
        "attempts_used"
    ] == 1
    assert await outbox.get_event("ev-g3") is not None


@pytest.mark.asyncio
async def test_dispatcher_claim_graph_rolls_back_atomically(db):
    """§3.4 dispatcher claim 图：claim 在事务内抛错 → 投递回到未领取态。"""
    outbox = OutboxRepository(db.conn)
    _event, delivery = await _seed_event_and_delivery(outbox)
    did = delivery["delivery_id"]
    baseline = await _snapshot(db.conn, ("event_deliveries",))
    with pytest.raises(RuntimeError):
        async with db.transaction():
            claimed = await outbox.claim_delivery(
                did, owner="w1", lease_until=T0 + 30, now=T0
            )
            assert claimed is not None
            raise RuntimeError("crash after claim, before send")
    assert await _snapshot(db.conn, ("event_deliveries",)) == baseline
    fresh = await outbox.get_delivery(did)
    assert fresh["state"] == "queued" and fresh["claim_owner"] == ""
    async with db.transaction():
        assert await outbox.claim_delivery(did, owner="w1", lease_until=T0 + 30, now=T0)
    assert (await outbox.get_delivery(did))["state"] == "dispatching"


# ----------------------------------------------------------------------
# AC5 强化 — 叶子门控跨连接语义
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leaf_commit_defers_to_outer_transaction(tmp_path):
    """事务内叶子不提交（旁观连接不可见、回滚无痕）；standalone 叶子立即提交。"""
    path = str(tmp_path / "gate.db")
    database = DataBase(path)
    await database.connect()
    await MigrationManager(database.conn, StubConfigManager()).migrate_or_reset()
    await put_player(database, "u1", 500, 500, anchor=T0)
    observer = await aiosqlite.connect(path)
    try:
        adv = AdventureRepository(database.conn)
        count = "SELECT COUNT(*) FROM adventure_settlements"
        with pytest.raises(RuntimeError):
            async with database.transaction():
                await adv.insert_settlement(
                    settlement_id="s-obs",
                    adventure_run_id="r-obs",
                    user_id="u1",
                    now=T0,
                )
                raise RuntimeError("boom before commit")
        assert await _scalar(observer, count) == 0, "回滚后旁观连接不应看到数据"

        async with database.transaction():
            await adv.insert_settlement(
                settlement_id="s-obs2",
                adventure_run_id="r-obs2",
                user_id="u1",
                now=T0,
            )
        assert await _scalar(observer, count) == 1, "owner 提交后立即可见"

        await adv.insert_settlement(
            settlement_id="s-obs3",
            adventure_run_id="r-obs3",
            user_id="u1",
            now=T0,
        )
        assert await _scalar(observer, count) == 2, "standalone 叶子须自提交"
    finally:
        await observer.close()
        await database.close()


# ----------------------------------------------------------------------
# 时间模型（design §5）
# ----------------------------------------------------------------------


def test_shanghai_date_key_beijing_boundaries():
    """日界按北京时间切分；epoch 秒与 datetime 入参一致，naive 视为 UTC。"""
    assert shanghai_date_key(1577807999) == "2019-12-31"
    assert shanghai_date_key(1577808000) == "2020-01-01"
    assert shanghai_date_key(datetime(2020, 1, 1, 16, 30)) == "2020-01-02"
    assert (
        shanghai_date_key(datetime(2019, 12, 31, 16, 0, tzinfo=timezone.utc))
        == "2020-01-01"
    )
    assert shanghai_date_key(datetime(2019, 12, 31, 15, 59, tzinfo=timezone.utc)) == (
        "2019-12-31"
    )


def test_time_skip_excludes_health_anchor_and_pve_history():
    """GM「时间快进」覆盖边界：负向 = 健康锚点/结算/效果/每日计数/date_key；
    正向 = 疲劳到期与 Boss 实例到期/再生（child P design §5 登记的等待类冷却域）。
    """
    entries = dict(TimeSkipRegistry.from_providers().entries())
    joined = " ".join(entries.values()).lower()
    for forbidden in (
        "health_recovered_at",
        "adventure_settlements",
        "adventure_effects",
        "world_boss_daily_attempts",
        "date_key",
    ):
        assert forbidden not in joined, f"时间快进不得覆盖 {forbidden}"
    # 正向：§5 要求的三个冷却域必须登记，且各为单语句列式 UPDATE
    for label, fragment in (
        ("历练休整到期时间", "adventure_fatigue set fatigue_until"),
        ("世界Boss实例到期时间", "world_boss_instances set expires_at"),
        ("世界Boss下次再生时间", "world_boss_instances set next_spawn_at"),
    ):
        assert label in entries, f"缺少注册域：{label}"
        assert fragment in entries[label].lower(), entries[label]


# ----------------------------------------------------------------------
# AC6 — 静态审计：data/ 下无未门控的裸 conn.commit()
# ----------------------------------------------------------------------

_COMMIT_ALLOWLIST = {
    # owner 层：迁移链逐版本自提交，不在任何 CM 内
    "data/migration.py::MigrationManager.migrate_or_reset",
    # _TransactionCM 本体：COMMIT/ROLLBACK 是 owner 职责本身
    "data/data_manager.py::_TransactionCM.__aexit__",
}


def _ast_parents(tree):
    mapping = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            mapping[child] = node
    return mapping


def _commit_calls(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "commit"
            and not node.args
        ):
            yield node


def _owner_local_names(fn):
    """函数体内由 `... = <含 _txn_depth 的表达式>` 赋出的局部名（门控哨兵）。"""
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and "_txn_depth" in ast.dump(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _enclosing_fn(node, parents):
    cur = node
    while cur is not None and not isinstance(
        cur, (ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        cur = parents.get(cur)
    return cur


def _is_gated(node, parents):
    fn = _enclosing_fn(node, parents)
    if fn is None:
        return False
    names = _owner_local_names(fn)
    cur = parents.get(node)
    while cur is not None and cur is not fn:
        if isinstance(cur, ast.If):
            test_dump = ast.dump(cur.test)
            if "_txn_depth" in test_dump or any(
                f"Name(id='{name}'" in test_dump for name in names
            ):
                return True
        cur = parents.get(cur)
    return False


def _qualname(node, parents):
    parts = []
    cur = node
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parts.append(cur.name)
        cur = parents.get(cur)
    return ".".join(reversed(parts))


def _scan_data_commits():
    gated, raw = [], []
    for path in sorted((PLUGIN_ROOT / "data").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = _ast_parents(tree)
        rel = path.relative_to(PLUGIN_ROOT).as_posix()
        for node in _commit_calls(tree):
            qualname = _qualname(node, parents)
            if f"{rel}::{qualname}" in _COMMIT_ALLOWLIST:
                continue
            entry = (rel, node.lineno, qualname)
            (gated if _is_gated(node, parents) else raw).append(entry)
    return gated, raw


def test_no_ungated_commit_in_data_layer():
    """事务叶子门控约定：data/ 的每个 conn.commit() 都在 _txn_depth 守卫之下。"""
    gated, raw = _scan_data_commits()
    assert raw == [], f"未门控的裸提交点（提前提交隐患）: {raw}"
    assert len(gated) >= 40, f"门控提交点数量异常: {len(gated)}"
