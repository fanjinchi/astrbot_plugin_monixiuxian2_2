"""Tests for the pre-reset backup hook in MigrationManager (10g).

A database below the incremental task chain (v31, older than
TASK_CHAIN_MIN_VERSION=32) takes the rebuild path, which wipes all data —
the backup hook must snapshot it to `<db>.v<version>.pre-reset.bak` first.
"""

import sqlite3
from pathlib import Path

import aiosqlite
import pytest

from tests.helpers import load_module

_migration_mod = load_module("migration_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager
LATEST_DB_VERSION = _migration_mod.LATEST_DB_VERSION


class DummyConfigManager:
    """ConfigManager stub; migrations do not use it."""

    pass


async def _build_v31_old_db(db_path: Path) -> None:
    """Create a minimal legacy database at version 31 with one player row."""
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("CREATE TABLE db_info (version INTEGER)")
        await conn.execute("INSERT INTO db_info (version) VALUES (31)")
        await conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT)")
        await conn.execute(
            "INSERT INTO players (id, name) VALUES (900000001, '备份前玩家')"
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_reset_path_produces_pre_reset_backup(tmp_path):
    """A v31 legacy database is rebuilt and snapshotted to
    `<db>.v31.pre-reset.bak` before the wipe."""
    db_path = tmp_path / "old.db"
    await _build_v31_old_db(db_path)

    async with aiosqlite.connect(db_path) as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate_or_reset()

        # (a) After the rebuild the version reaches LATEST_DB_VERSION.
        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            row = await cursor.fetchone()
        assert row[0] == LATEST_DB_VERSION

    # (b) The backup exists, is a valid sqlite database, and still contains
    # the pre-reset player row.
    backup_path = db_path.with_name(f"{db_path.name}.v31.pre-reset.bak")
    assert backup_path.exists(), f"missing backup file {backup_path}"
    conn = sqlite3.connect(backup_path)
    try:
        version = conn.execute("SELECT version FROM db_info").fetchone()[0]
        names = [r[0] for r in conn.execute("SELECT name FROM players")]
    finally:
        conn.close()
    assert version == 31, "backup must hold the pre-reset version"
    assert names == ["备份前玩家"], "backup must hold the pre-reset player row"


@pytest.mark.asyncio
async def test_fresh_install_produces_no_backup_file(tmp_path):
    """A fresh install (no db_info table) never writes a .pre-reset.bak."""
    db_path = tmp_path / "fresh.db"
    async with aiosqlite.connect(db_path) as db_conn:
        await MigrationManager(db_conn, DummyConfigManager()).migrate_or_reset()
    assert not list(tmp_path.glob("*.pre-reset.bak")), "fresh install wrote a backup"


@pytest.mark.asyncio
async def test_memory_connection_skips_backup_without_stray_file(tmp_path):
    """A :memory: connection on the reset path must not create a stray .bak
    (VACUUM INTO would succeed and a naive path join would write
    `.v31.pre-reset.bak` into the pytest CWD)."""
    async with aiosqlite.connect(":memory:") as db_conn:
        await db_conn.execute("CREATE TABLE db_info (version INTEGER)")
        await db_conn.execute("INSERT INTO db_info (version) VALUES (31)")
        await db_conn.commit()
        await MigrationManager(db_conn, DummyConfigManager()).migrate_or_reset()

        async with db_conn.execute("SELECT version FROM db_info") as cursor:
            row = await cursor.fetchone()
        assert row[0] == LATEST_DB_VERSION

    stray = Path.cwd() / ".v31.pre-reset.bak"
    assert not stray.exists(), f"stray backup written to CWD: {stray}"