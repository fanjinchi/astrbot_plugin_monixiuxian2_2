"""Tests for database migrations (v3.11.0 不再向前兼容：旧库统一重建到最新 schema)。"""

import aiosqlite
import pytest
import sqlite3

from tests.helpers import load_module, load_package_module

_migration_mod = load_module("migration_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager
_create_all_tables = _migration_mod._create_all_tables
LATEST_DB_VERSION = _migration_mod.LATEST_DB_VERSION

_data_mod = load_package_module(
    "data/data_manager.py",
    "astrbot_plugin_monixiuxian2_2.data.data_manager",
)
DataBase = _data_mod.DataBase
Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player


class DummyConfigManager:
    """ConfigManager stub; migrations do not use it."""

    pass


async def _all_tables(db_conn) -> set[str]:
    """Return the set of user table names in the database."""
    async with db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ) as cursor:
        return {row[0] for row in await cursor.fetchall()}


async def _player_columns(db_conn) -> set[str]:
    async with db_conn.execute("PRAGMA table_info(players)") as cursor:
        return {row[1] for row in await cursor.fetchall()}


@pytest.mark.asyncio
async def test_fresh_install_reaches_latest_version():
    """A brand-new database is created with the latest schema and version."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            row = await cursor.fetchone()
        assert row[0] == LATEST_DB_VERSION

        columns = await _player_columns(db_conn)

    new_fields = {
        "damage",
        "agility",
        "speed",
        "hp",
        "armor_value",
        "study_target",
        "battle_report_merge_count",
        "spiritual_root",
    }
    assert new_fields <= columns, f"Missing new fields: {new_fields - columns}"

    # learned_skills column must NOT exist
    assert "learned_skills" not in columns, "learned_skills column still present"

    # 全部 24 张业务表齐备
    async with aiosqlite.connect(":memory:") as db_conn2:
        await MigrationManager(db_conn2, DummyConfigManager()).migrate()
        tables = await _all_tables(db_conn2)
        expected_tables = {
            "db_info",
            "players",
            "shop",
            "sects",
            "buff_info",
            "boss",
            "rifts",
            "legacy_instances",
            "impart_pk_cooldown",
            "impart_snatch_protection",
            "user_cd",
            "pending_gifts",
            "bank_accounts",
            "bank_loans",
            "bank_transactions",
            "bounty_tasks",
            "blessed_lands",
            "spirit_farms",
            "dual_cultivation",
            "spirit_eyes",
            "dual_cultivation_requests",
            "combat_cooldowns",
            "player_skills",
            "system_config",
        }
        assert expected_tables <= tables, f"Missing tables: {expected_tables - tables}"

        # 旧的 impart_info 表已彻底移除
        assert "impart_info" not in tables

        async with db_conn2.execute("PRAGMA table_info(legacy_instances)") as cursor:
            legacy_cols = {row[1] for row in await cursor.fetchall()}
        assert legacy_cols == {
            "id",
            "owner_id",
            "legacy_type",
            "impart_value",
            "claimed_tiers",
            "sect_id",
            "is_active",
            "acquired_at",
        }, f"Unexpected legacy_instances columns: {legacy_cols}"

        # 每人最多一条激活的部分唯一索引
        async with db_conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_legacy_active_owner'"
        ) as cursor:
            assert await cursor.fetchone() is not None, (
                "idx_legacy_active_owner index not found"
            )

        # sect_id 类型统一为 INTEGER（不再有 v22 TEXT 与 v32 INTEGER 两路径漂移）
        async with db_conn2.execute("PRAGMA table_info(legacy_instances)") as cursor:
            sect_id_type = {row[1]: row[2] for row in await cursor.fetchall()}[
                "sect_id"
            ]
        assert sect_id_type == "INTEGER"

        # 系统宗门列 / 技能归属列 / 师承进度列
        async with db_conn2.execute("PRAGMA table_info(sects)") as cursor:
            sect_cols = {row[1] for row in await cursor.fetchall()}
        assert {"is_system", "faction_id", "status", "destruction_tier"} <= sect_cols

        async with db_conn2.execute("PRAGMA table_info(player_skills)") as cursor:
            skill_cols = {row[1] for row in await cursor.fetchall()}
        assert {"origin_sect_id", "sect_bound"} <= skill_cols

        async with db_conn2.execute("PRAGMA table_info(players)") as cursor:
            player_cols = {row[1] for row in await cursor.fetchall()}
        assert "sect_master_progress" in player_cols


@pytest.mark.asyncio
async def test_fresh_install_seeds_rifts_and_eyes():
    """Fresh installs seed 6 rifts (incl. 青云剑冢) and 3 spirit eyes.

    v34 起不再播种试炼古境（add-rift-encounters 脚手架验证完毕拆除）。
    """
    import json

    async with aiosqlite.connect(":memory:") as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute(
            "SELECT rift_id, rift_name, rift_level, required_level, rewards FROM rifts"
        ) as cursor:
            rows = await cursor.fetchall()
        by_id = {row[0]: row for row in rows}
        assert set(by_id) == {1, 2, 3, 4, 5, 6}
        assert by_id[4][1] == "玄冰地宫"
        tomb = by_id[6]
        assert tomb[1] == "青云剑冢"
        assert tomb[2] == 3  # rift_level
        assert tomb[3] == 3  # required_level
        assert json.loads(tomb[4]) == {"exp": [300, 900], "gold": [100, 400]}

        async with db_conn.execute("SELECT COUNT(*) FROM spirit_eyes") as cursor:
            assert (await cursor.fetchone())[0] == 3


@pytest.mark.asyncio
async def test_fresh_install_player_crud_works():
    """DataManager create_player/update_player must work against the migrated schema."""
    db = DataBase(":memory:")
    await db.connect()
    await MigrationManager(db.conn, DummyConfigManager()).migrate()

    player = Player(user_id="u1", user_name="Tester", spiritual_root="天灵根")
    await db.create_player(player)

    player.gold = 100
    await db.update_player(player)

    fetched = await db.get_player_by_id("u1")
    assert fetched is not None
    assert fetched.user_id == "u1"
    assert fetched.spiritual_root == "天灵根"
    assert fetched.gold == 100

    await db.close()


@pytest.mark.asyncio
async def test_migrate_is_idempotent_on_fresh():
    """Running migrate() twice on a fresh database is a no-op."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        # 写入用户数据后二次 migrate：数据必须保留（区分真 no-op 与破坏性重建）
        await db_conn.execute(
            "INSERT INTO players (user_id, user_name, spiritual_root) VALUES ('u1', 'T', '天灵根')"
        )
        await db_conn.commit()
        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            assert (await cursor.fetchone())[0] == LATEST_DB_VERSION
        async with db_conn.execute(
            "SELECT COUNT(*) FROM players WHERE user_id = 'u1'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 1
        async with db_conn.execute("SELECT COUNT(*) FROM legacy_instances") as cursor:
            assert (await cursor.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_newer_db_version_raises_without_touching_data():
    """Version above LATEST must raise (no silent downgrade) and leave the DB intact."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate()
        # 预置一条玩家数据，断言 raise 后数据库未被改动
        await db_conn.execute(
            "INSERT INTO players (user_id, user_name, spiritual_root) VALUES ('u1', 'T', '天灵根')"
        )
        await db_conn.execute(
            "UPDATE db_info SET version = ?", (LATEST_DB_VERSION + 1,)
        )
        await db_conn.commit()

        with pytest.raises(RuntimeError, match="不允许降级运行"):
            await MigrationManager(db_conn, DummyConfigManager()).migrate()

        # 版本号与数据均未被改动
        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            assert (await cursor.fetchone())[0] == LATEST_DB_VERSION + 1
        async with db_conn.execute(
            "SELECT COUNT(*) FROM players WHERE user_id = 'u1'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_legacy_db_rebuilt_to_latest_schema():
    """v3.11.0 不再向前兼容：旧版库（version < LATEST 且无迁移任务）整体重建——
    schema 达最新，旧数据清空。低于 v32 完整 schema 基线的库即使存在已注册的
    增量任务（v33+）也不得进任务链，仍走本重建路径。"""
    async with aiosqlite.connect(":memory:") as db_conn:
        # 模拟遗留 v21 库：旧 players 列
        await db_conn.execute("CREATE TABLE db_info (version INTEGER NOT NULL)")
        await db_conn.execute("INSERT INTO db_info (version) VALUES (21)")
        await db_conn.execute(
            """
            CREATE TABLE players (
                user_id TEXT PRIMARY KEY,
                user_name TEXT NOT NULL DEFAULT '',
                experience INTEGER NOT NULL DEFAULT 0,
                atk INTEGER NOT NULL DEFAULT 0,
                mp INTEGER NOT NULL DEFAULT 0,
                atkpractice INTEGER NOT NULL DEFAULT 0,
                magic_damage INTEGER NOT NULL DEFAULT 0,
                physical_damage INTEGER NOT NULL DEFAULT 0,
                magic_defense INTEGER NOT NULL DEFAULT 0,
                physical_defense INTEGER NOT NULL DEFAULT 0,
                mental_power INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db_conn.execute(
            """
            INSERT INTO players (user_id, user_name, experience)
            VALUES ('u1', 'Tester', 1000)
            """
        )
        # 遗留旧表（不应再存在的名字）也要能容忍：重建路径 DROP 全表
        await db_conn.execute(
            "CREATE TABLE impart_info (user_id TEXT PRIMARY KEY, impart_value INTEGER)"
        )
        await db_conn.execute("INSERT INTO impart_info VALUES ('u1', 50)")
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            assert (await cursor.fetchone())[0] == LATEST_DB_VERSION

        columns = await _player_columns(db_conn)
        new_fields = {
            "damage",
            "agility",
            "speed",
            "hp",
            "armor_value",
            "study_target",
            "battle_report_merge_count",
            "spiritual_root",
        }
        assert new_fields <= columns
        old_fields = {
            "attack",
            "defense",
            "mp",
            "atkpractice",
            "magic_damage",
            "physical_damage",
            "magic_defense",
            "physical_defense",
            "mental_power",
        }
        assert not old_fields & columns

        # 旧数据被清空（重建非保真）
        async with db_conn.execute("SELECT COUNT(*) FROM players") as cursor:
            assert (await cursor.fetchone())[0] == 0

        # 旧表被 DROP，最新 schema 的传承三表重建
        tables = await _all_tables(db_conn)
        assert "impart_info" not in tables
        assert {
            "legacy_instances",
            "impart_pk_cooldown",
            "impart_snatch_protection",
        } <= tables

        # 重建后种子数据可用（v34 起 6 个秘境：试炼古境脚手架已拆除）
        async with db_conn.execute("SELECT COUNT(*) FROM rifts") as cursor:
            assert (await cursor.fetchone())[0] == 6


@pytest.mark.asyncio
async def test_registered_migration_task_chain(monkeypatch):
    """MIGRATION_TASKS 注册机制保留：后续版本（v33+）任务按升序执行，
    版本号逐级推进，且执行后可幂等。"""
    ran = []

    async def _v33_task(conn, config_manager):
        """Demo next-version task: create a marker table."""
        await conn.execute("CREATE TABLE demo_v33_table (k TEXT PRIMARY KEY)")
        ran.append(True)

    # 临时注册演示任务并抬高 LATEST 验证任务链；monkeypatch 结束后恢复
    # （v33 的真实任务已随脚手架拆除移除，此处 key 33 为纯演示占用）
    monkeypatch.setitem(_migration_mod.MIGRATION_TASKS, 33, _v33_task)
    monkeypatch.setattr(_migration_mod, "LATEST_DB_VERSION", 33)

    async with aiosqlite.connect(":memory:") as db_conn:
        # 先建 v32 库，再升级到 v33
        await _create_all_tables(db_conn)
        await db_conn.execute("INSERT INTO db_info (version) VALUES (32)")
        await db_conn.commit()

        assert _migration_mod.MIGRATION_TASKS[33] is _v33_task

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            assert (await cursor.fetchone())[0] == 33
        assert ran == [True]
        async with db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='demo_v33_table'"
        ) as cursor:
            assert await cursor.fetchone() is not None

        # 幂等：再跑一次不触发
        await MigrationManager(db_conn, DummyConfigManager()).migrate()
        assert ran == [True]

    # 体验证失败回滚路径：任务抛错时版本不前进、表不保留
    async def _v34_bad_task(conn, config_manager):
        await conn.execute("CREATE TABLE demo_v34_table (k TEXT PRIMARY KEY)")
        raise RuntimeError("boom")

    monkeypatch.setitem(_migration_mod.MIGRATION_TASKS, 34, _v34_bad_task)
    monkeypatch.setattr(_migration_mod, "LATEST_DB_VERSION", 34)

    async with aiosqlite.connect(":memory:") as db_conn:
        await _create_all_tables(db_conn)
        await db_conn.execute("INSERT INTO db_info (version) VALUES (33)")
        await db_conn.commit()

        with pytest.raises(RuntimeError):
            await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            assert (await cursor.fetchone())[0] == 33
        async with db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='demo_v34_table'"
        ) as cursor:
            assert await cursor.fetchone() is None


@pytest.mark.asyncio
async def test_v34_task_removes_trial_rift_on_existing_db():
    """真实的 v34 注册任务：删除 v33 时代播种的试炼古境（id 7），重复执行幂等。

    add-rift-encounters 脚手架验证完毕拆除：模拟已含 id 7 行的存量 v33 库，
    升级到 v34 后该行应被删除；从 v32 直接升级时 v33 任务已不存在，
    v34 的 DELETE 对无该行库为 no-op。
    """
    import json

    async with aiosqlite.connect(":memory:") as db_conn:
        # 模拟经 v33 播种的存量库（_create_all_tables 已不再播种 id 7，手动补回）
        await _create_all_tables(db_conn)
        await db_conn.execute(
            "INSERT INTO rifts (rift_id, rift_name, rift_level, required_level, rewards) VALUES (?, ?, ?, ?, ?)",
            (7, "试炼古境", 1, 0, json.dumps({"exp": [100, 200], "gold": [50, 100]})),
        )
        await db_conn.execute("INSERT INTO db_info (version) VALUES (33)")
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            assert (await cursor.fetchone())[0] == 34
        async with db_conn.execute(
            "SELECT COUNT(*) FROM rifts WHERE rift_id = 7"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 0

        # 幂等：再次 migrate 仍为 0（DELETE no-op）
        await MigrationManager(db_conn, DummyConfigManager()).migrate()
        async with db_conn.execute(
            "SELECT COUNT(*) FROM rifts WHERE rift_id = 7"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_player_skills_crud():
    """player_skills CRUD: learn, check, star level, get all."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate()
        db = DataBase(":memory:")
        db.conn = db_conn
        db.ext = _data_mod.DatabaseExtended(db_conn)

        # Fresh: no learned skills
        skills = await db.ext.get_learned_skills("u1")
        assert skills == []

        # Learn a new skill
        is_new, star = await db.ext.learn_or_star_up("u1", "common_001", "test")
        assert is_new
        assert star == 1

        # Now learned
        assert await db.ext.is_skill_learned("u1", "common_001")
        assert not await db.ext.is_skill_learned("u1", "nonexist")

        # Get star level
        assert await db.ext.get_star_level("u1", "common_001") == 1

        # Duplicate learn: star up
        is_new2, star2 = await db.ext.learn_or_star_up("u1", "common_001", "retest")
        assert not is_new2
        assert star2 == 2

        # Get learned skills list
        skills = await db.ext.get_learned_skills("u1")
        assert len(skills) == 1
        assert skills[0]["skill_id"] == "common_001"
        assert skills[0]["star_level"] == 2
        assert skills[0]["source"] == "retest"


@pytest.mark.asyncio
async def test_player_skills_sect_attribution_pass_through():
    """learn_or_star_up stores origin_sect_id/sect_bound on first learn only."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate()
        db = DataBase(":memory:")
        db.conn = db_conn
        db.ext = _data_mod.DatabaseExtended(db_conn)

        is_new, star = await db.ext.learn_or_star_up(
            "u1", "qy_001", "test", origin_sect_id="qingyun", sect_bound=True
        )
        assert is_new and star == 1

        skills = await db.ext.get_learned_skills("u1")
        assert skills[0]["origin_sect_id"] == "qingyun"
        assert skills[0]["sect_bound"] is True

        # Star-up does not overwrite the original attribution
        is_new2, star2 = await db.ext.learn_or_star_up("u1", "qy_001", "retest")
        assert not is_new2 and star2 == 2
        skills = await db.ext.get_learned_skills("u1")
        assert skills[0]["origin_sect_id"] == "qingyun"
        assert skills[0]["sect_bound"] is True

        # Plain skills default to unattributed/unbound
        await db.ext.learn_or_star_up("u1", "common_001", "test")
        skills = {s["skill_id"]: s for s in await db.ext.get_learned_skills("u1")}
        assert skills["common_001"]["origin_sect_id"] is None
        assert skills["common_001"]["sect_bound"] is False


@pytest.mark.asyncio
async def test_active_owner_partial_unique_index():
    """The partial unique index enforces at most one active legacy per owner."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        await db_conn.execute(
            "INSERT INTO legacy_instances (owner_id, legacy_type, is_active, acquired_at)"
            " VALUES ('u1', 'common', 1, 1)"
        )
        await db_conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            await db_conn.execute(
                "INSERT INTO legacy_instances (owner_id, legacy_type, is_active, acquired_at)"
                " VALUES ('u1', 'adventure', 1, 2)"
            )
            await db_conn.commit()

        # 多条非激活实例不受限
        await db_conn.execute(
            "INSERT INTO legacy_instances (owner_id, legacy_type, is_active, acquired_at)"
            " VALUES ('u1', 'adventure', 0, 2)"
        )
        await db_conn.commit()
        async with db_conn.execute(
            "SELECT COUNT(*) FROM legacy_instances WHERE owner_id = 'u1'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 2
