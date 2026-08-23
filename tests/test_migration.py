"""Tests for database migrations (v25 player_skills, v26 impart rework, v32 legacy instances)."""

import aiosqlite
import pytest

from tests.helpers import load_module, load_package_module

_migration_mod = load_module("migration_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager
_create_all_tables_v21 = _migration_mod._create_all_tables_v21
_create_all_tables_v22 = _migration_mod._create_all_tables_v22
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


@pytest.mark.asyncio
async def test_fresh_install_reaches_latest_version():
    """A brand-new database is created with the latest schema and version."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            row = await cursor.fetchone()
        assert row[0] == LATEST_DB_VERSION

        async with db_conn.execute("PRAGMA table_info(players)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}

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

    # player_skills table must exist
    async with aiosqlite.connect(":memory:") as db_conn2:
        await MigrationManager(db_conn2, DummyConfigManager()).migrate()
        async with db_conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player_skills'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "player_skills table not found"

        # v32: fresh installs build the three legacy-instance tables; old impart_info is gone
        for table in (
            "legacy_instances",
            "impart_pk_cooldown",
            "impart_snatch_protection",
        ):
            async with db_conn2.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ) as cursor:
                assert await cursor.fetchone() is not None, f"{table} table not found"

        async with db_conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='impart_info'"
        ) as cursor:
            assert await cursor.fetchone() is None, (
                "impart_info should be dropped at v32"
            )

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

        # v28: fresh installs already carry the system-sect / skill attribution columns
        async with db_conn2.execute("PRAGMA table_info(sects)") as cursor:
            sect_cols = {row[1] for row in await cursor.fetchall()}
        assert {"is_system", "faction_id", "status", "destruction_tier"} <= sect_cols

        async with db_conn2.execute("PRAGMA table_info(player_skills)") as cursor:
            skill_cols = {row[1] for row in await cursor.fetchall()}
        assert {"origin_sect_id", "sect_bound"} <= skill_cols

        # v30: fresh installs carry the master task chain progress column
        async with db_conn2.execute("PRAGMA table_info(players)") as cursor:
            player_cols = {row[1] for row in await cursor.fetchall()}
        assert "sect_master_progress" in player_cols


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
async def test_v21_to_latest_migration_rebuilds_players():
    """Migrating from the old v21 schema drops old players and rebuilds it."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await _create_all_tables_v21(db_conn)
        await db_conn.execute(
            """
            INSERT INTO players (
                user_id, user_name, experience, atk, mp, atkpractice,
                magic_damage, physical_damage, magic_defense, physical_defense, mental_power
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("u1", "Tester", 1000, 10, 50, 3, 5, 5, 2, 2, 100),
        )
        await db_conn.execute("INSERT INTO db_info (version) VALUES (?)", (21,))
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            version = (await cursor.fetchone())[0]
        assert version == LATEST_DB_VERSION

        async with db_conn.execute("PRAGMA table_info(players)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}

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
        assert not old_fields & columns, (
            f"Old fields still present: {old_fields & columns}"
        )

        assert "learned_skills" not in columns, "learned_skills column still present"

        async with db_conn.execute("SELECT COUNT(*) FROM players") as cursor:
            count = (await cursor.fetchone())[0]
        assert count == 0, "Old players should be discarded during v22 migration"

        async with db_conn.execute("PRAGMA table_info(buff_info)") as cursor:
            buff_cols = {row[1] for row in await cursor.fetchall()}
        assert buff_cols == {"id", "user_id"}

        # player_skills table must exist
        async with db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player_skills'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "player_skills table not found"

        # v26 built impart_info, which v32 later drops and replaces with legacy_instances
        async with db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='impart_info'"
        ) as cursor:
            assert await cursor.fetchone() is None, (
                "impart_info should be dropped at v32"
            )
        async with db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_instances'"
        ) as cursor:
            assert await cursor.fetchone() is not None, (
                "legacy_instances table not found"
            )


@pytest.mark.asyncio
async def test_v23_to_v24_adds_spiritual_root():
    """Databases already migrated to v23 get the spiritual_root column from v24."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await db_conn.execute("CREATE TABLE db_info (version INTEGER NOT NULL)")
        await db_conn.execute("INSERT INTO db_info (version) VALUES (?)", (23,))
        await db_conn.execute(
            """
            CREATE TABLE players (
                user_id TEXT PRIMARY KEY,
                user_name TEXT NOT NULL DEFAULT '',
                level_index INTEGER NOT NULL DEFAULT 0,
                cultivation_type TEXT NOT NULL DEFAULT '灵修'
            )
            """
        )
        # v31 会向 rifts 表播种青云剑冢，最小库需带上该表
        await db_conn.execute(
            """
            CREATE TABLE rifts (
                rift_id INTEGER PRIMARY KEY AUTOINCREMENT,
                rift_name TEXT NOT NULL,
                rift_level INTEGER NOT NULL,
                required_level INTEGER NOT NULL,
                rewards TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            version = (await cursor.fetchone())[0]
        assert version == LATEST_DB_VERSION

        async with db_conn.execute("PRAGMA table_info(players)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        assert "spiritual_root" in columns


@pytest.mark.asyncio
async def test_v25_to_v26_rebuilds_impart_info():
    """A v25 database with legacy impart columns is rebuilt to the new schema."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await db_conn.execute("CREATE TABLE db_info (version INTEGER NOT NULL)")
        await db_conn.execute("INSERT INTO db_info (version) VALUES (?)", (25,))
        await db_conn.execute("""
            CREATE TABLE impart_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                impart_hp_per REAL NOT NULL DEFAULT 0.0,
                impart_mp_per REAL NOT NULL DEFAULT 0.0,
                impart_atk_per REAL NOT NULL DEFAULT 0.0,
                impart_know_per REAL NOT NULL DEFAULT 0.0,
                impart_burst_per REAL NOT NULL DEFAULT 0.0
            )
        """)
        await db_conn.execute(
            "INSERT INTO impart_info (user_id, impart_hp_per, impart_atk_per) VALUES (?, 0.1, 0.5)",
            ("u1",),
        )
        # v31 会向 rifts 表播种青云剑冢，最小库需带上该表
        await db_conn.execute("""
            CREATE TABLE rifts (
                rift_id INTEGER PRIMARY KEY AUTOINCREMENT,
                rift_name TEXT NOT NULL,
                rift_level INTEGER NOT NULL,
                required_level INTEGER NOT NULL,
                rewards TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            version = (await cursor.fetchone())[0]
        assert version == LATEST_DB_VERSION

        # v26 重建的 impart_info 在 v32 被 DROP，旧数据经 v26 清零后无值可迁移
        async with db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='impart_info'"
        ) as cursor:
            assert await cursor.fetchone() is None, (
                "impart_info should be dropped at v32"
            )

        # v32 建三张传承新表，但 impart_info 旧行（v26 已清零）不会拷入
        for table in (
            "legacy_instances",
            "impart_pk_cooldown",
            "impart_snatch_protection",
        ):
            async with db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ) as cursor:
                assert await cursor.fetchone() is not None, f"{table} table not found"
        async with db_conn.execute("SELECT COUNT(*) FROM legacy_instances") as cursor:
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
async def test_v28_adds_system_sect_and_skill_attribution_columns():
    """v27 -> v28 adds system-sect columns and skill attribution with safe defaults."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await db_conn.execute("CREATE TABLE db_info (version INTEGER NOT NULL)")
        await db_conn.execute("INSERT INTO db_info (version) VALUES (?)", (27,))
        await db_conn.execute("""
            CREATE TABLE sects (
                sect_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sect_name TEXT NOT NULL UNIQUE,
                sect_owner TEXT NOT NULL,
                sect_scale INTEGER NOT NULL DEFAULT 0,
                sect_used_stone INTEGER NOT NULL DEFAULT 0,
                sect_fairyland INTEGER NOT NULL DEFAULT 0,
                sect_materials INTEGER NOT NULL DEFAULT 0,
                mainbuff TEXT NOT NULL DEFAULT '0',
                secbuff TEXT NOT NULL DEFAULT '0',
                elixir_room_level INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db_conn.execute(
            "INSERT INTO sects (sect_name, sect_owner) VALUES ('太一宗', 'u1')"
        )
        await db_conn.execute("""
            CREATE TABLE player_skills (
                user_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                star_level INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT '',
                learned_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, skill_id)
            )
        """)
        await db_conn.execute(
            "INSERT INTO player_skills (user_id, skill_id) VALUES ('u1', 'common_001')"
        )
        # v31 会向 rifts 表播种青云剑冢，最小库需带上该表
        await db_conn.execute("""
            CREATE TABLE rifts (
                rift_id INTEGER PRIMARY KEY AUTOINCREMENT,
                rift_name TEXT NOT NULL,
                rift_level INTEGER NOT NULL,
                required_level INTEGER NOT NULL,
                rewards TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            assert (await cursor.fetchone())[0] == LATEST_DB_VERSION

        async with db_conn.execute("PRAGMA table_info(sects)") as cursor:
            sect_cols = {row[1] for row in await cursor.fetchall()}
        assert {"is_system", "faction_id", "status", "destruction_tier"} <= sect_cols

        async with db_conn.execute("PRAGMA table_info(player_skills)") as cursor:
            skill_cols = {row[1] for row in await cursor.fetchall()}
        assert {"origin_sect_id", "sect_bound"} <= skill_cols

        # Existing rows keep zero-behavior defaults
        async with db_conn.execute(
            "SELECT is_system, faction_id, status, destruction_tier FROM sects"
        ) as cursor:
            row = await cursor.fetchone()
        assert row == (0, None, "normal", None)

        async with db_conn.execute(
            "SELECT origin_sect_id, sect_bound FROM player_skills"
        ) as cursor:
            row = await cursor.fetchone()
        assert row == (None, 0)


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
async def test_v31_fresh_install_seeds_sword_tomb_rift():
    """Fresh installs carry rift id 6 青云剑冢 (sect-exclusive) alongside the
    original five seeds; id 4 stays 玄冰地宫 (no collision with rift_config)."""
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


@pytest.mark.asyncio
async def test_v30_to_v31_seeds_sword_tomb_idempotently():
    """Existing databases get rift id 6 from v31 without touching id 4;
    a second migrate run is a no-op."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await db_conn.execute("CREATE TABLE db_info (version INTEGER NOT NULL)")
        await db_conn.execute("INSERT INTO db_info (version) VALUES (30)")
        await db_conn.execute("""
            CREATE TABLE rifts (
                rift_id INTEGER PRIMARY KEY AUTOINCREMENT,
                rift_name TEXT NOT NULL,
                rift_level INTEGER NOT NULL,
                required_level INTEGER NOT NULL,
                rewards TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await db_conn.execute(
            "INSERT INTO rifts (rift_id, rift_name, rift_level, required_level, rewards)"
            " VALUES (4, '玄冰地宫', 4, 10, '{}')"
        )
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            assert (await cursor.fetchone())[0] == LATEST_DB_VERSION
        async with db_conn.execute(
            "SELECT rift_name FROM rifts WHERE rift_id = 6"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None and row[0] == "青云剑冢"
        async with db_conn.execute(
            "SELECT rift_name FROM rifts WHERE rift_id = 4"
        ) as cursor:
            assert (await cursor.fetchone())[0] == "玄冰地宫"

        # 幂等：再次迁移不报错、不重复插入
        await MigrationManager(db_conn, DummyConfigManager()).migrate()
        async with db_conn.execute(
            "SELECT COUNT(*) FROM rifts WHERE rift_id = 6"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_create_all_tables_v2_backfills_sect_columns():
    """_create_all_tables_v2 aligns with v22: players sect JSON columns,
    player_skills attribution columns and the idx_sect_faction index."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await _create_all_tables_v21(db_conn)  # v21 builds on top of v2

        async with db_conn.execute("PRAGMA table_info(players)") as cursor:
            player_cols = {row[1] for row in await cursor.fetchall()}
        assert {"sect_treasure_claims", "sect_master_progress"} <= player_cols

        async with db_conn.execute("PRAGMA table_info(player_skills)") as cursor:
            skill_cols = {row[1] for row in await cursor.fetchall()}
        assert {"origin_sect_id", "sect_bound"} <= skill_cols

        async with db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sect_faction'"
        ) as cursor:
            assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_v31_to_v32_migrates_impart_info_to_legacy_instances():
    """v32 copies legacy impart_info rows into legacy_instances (type=common,
    active, value/claimed preserved), then drops impart_info."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await db_conn.execute("CREATE TABLE db_info (version INTEGER NOT NULL)")
        await db_conn.execute("INSERT INTO db_info (version) VALUES (31)")
        await db_conn.execute("""
            CREATE TABLE impart_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                impart_value INTEGER NOT NULL DEFAULT 0,
                claimed_tiers TEXT NOT NULL DEFAULT '[]'
            )
        """)
        await db_conn.execute(
            "INSERT INTO impart_info (user_id, impart_value, claimed_tiers) VALUES ('u1', 45, '[1, 2]')"
        )
        await db_conn.execute(
            "INSERT INTO impart_info (user_id, impart_value, claimed_tiers) VALUES ('u2', 0, '[]')"
        )
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            assert (await cursor.fetchone())[0] == 32

        # 两张新表存在，旧表已 DROP
        for table in (
            "legacy_instances",
            "impart_pk_cooldown",
            "impart_snatch_protection",
        ):
            async with db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ) as cursor:
                assert await cursor.fetchone() is not None, f"{table} table not found"
        async with db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='impart_info'"
        ) as cursor:
            assert await cursor.fetchone() is None, "impart_info should be dropped"

        # 旧行迁为 common 类型、激活、sect_id 为空，值与 claimed 保全
        async with db_conn.execute(
            "SELECT owner_id, legacy_type, impart_value, claimed_tiers, sect_id, is_active"
            " FROM legacy_instances ORDER BY owner_id"
        ) as cursor:
            rows = await cursor.fetchall()
        assert len(rows) == 2
        assert rows[0] == ("u1", "common", 45, "[1, 2]", None, 1)
        assert rows[1] == ("u2", "common", 0, "[]", None, 1)


@pytest.mark.asyncio
async def test_v32_migration_is_idempotent():
    """A second migrate run must not duplicate legacy_instances rows nor fail
    on the already-dropped impart_info table."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await db_conn.execute("CREATE TABLE db_info (version INTEGER NOT NULL)")
        await db_conn.execute("INSERT INTO db_info (version) VALUES (31)")
        await db_conn.execute("""
            CREATE TABLE impart_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                impart_value INTEGER NOT NULL DEFAULT 0,
                claimed_tiers TEXT NOT NULL DEFAULT '[]'
            )
        """)
        await db_conn.execute(
            "INSERT INTO impart_info (user_id, impart_value) VALUES ('u1', 10)"
        )
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()
        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT COUNT(*) FROM legacy_instances") as cursor:
            assert (await cursor.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_v32_active_owner_partial_unique_index():
    """The partial unique index enforces at most one active legacy per owner."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        await db_conn.execute(
            "INSERT INTO legacy_instances (owner_id, legacy_type, is_active, acquired_at)"
            " VALUES ('u1', 'common', 1, 1)"
        )
        await db_conn.commit()
        with pytest.raises(Exception):
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
