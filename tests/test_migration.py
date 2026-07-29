"""Tests for database migrations (v22 four-main-attribute redesign and v24)."""

import aiosqlite
import pytest

from tests.helpers import load_module, load_package_module

_migration_mod = load_module("migration_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager
_create_all_tables_v21 = _migration_mod._create_all_tables_v21
LATEST_DB_VERSION = _migration_mod.LATEST_DB_VERSION

_data_mod = load_package_module("data/data_manager.py", "astrbot_plugin_monixiuxian2_2.data.data_manager")
DataBase = _data_mod.DataBase
Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player


class DummyConfigManager:
    """ConfigManager stub; migrations v22/v23/v24 do not use it."""

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
        "learned_skills",
        "study_target",
        "battle_report_merge_count",
        "spiritual_root",
    }
    assert new_fields <= columns, f"Missing new fields: {new_fields - columns}"


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
            "learned_skills",
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
        assert not old_fields & columns, f"Old fields still present: {old_fields & columns}"

        async with db_conn.execute("SELECT COUNT(*) FROM players") as cursor:
            count = (await cursor.fetchone())[0]
        assert count == 0, "Old players should be discarded during v22 migration"

        async with db_conn.execute("PRAGMA table_info(buff_info)") as cursor:
            buff_cols = {row[1] for row in await cursor.fetchall()}
        assert buff_cols == {"id", "user_id"}


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
        await db_conn.commit()

        await MigrationManager(db_conn, DummyConfigManager()).migrate()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            version = (await cursor.fetchone())[0]
        assert version == LATEST_DB_VERSION

        async with db_conn.execute("PRAGMA table_info(players)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        assert "spiritual_root" in columns
