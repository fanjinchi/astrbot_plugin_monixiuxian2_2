"""Regression tests for set_user_busy upsert behavior (bd qv9)."""

import aiosqlite
import pytest
import pytest_asyncio

from tests.helpers import load_package_module

_ext_mod = load_package_module(
    "data/database_extended.py", "astrbot_plugin_monixiuxian2_2.data.database_extended"
)
DatabaseExtended = _ext_mod.DatabaseExtended

USER_CD_DDL = """
CREATE TABLE user_cd (
    user_id TEXT PRIMARY KEY,
    type INTEGER NOT NULL DEFAULT 0,
    create_time INTEGER NOT NULL DEFAULT 0,
    scheduled_time INTEGER NOT NULL DEFAULT 0,
    extra_data TEXT NOT NULL DEFAULT '{}'
)
"""


@pytest_asyncio.fixture
async def ext():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute(USER_CD_DDL)
    await conn.commit()
    yield DatabaseExtended(conn)
    await conn.close()


@pytest.mark.asyncio
async def test_set_user_busy_inserts_when_row_missing(ext):
    """set_user_busy must INSERT when the user has no user_cd row."""
    await ext.set_user_busy("u_new", 1, scheduled_time=123456)

    cd = await ext.get_user_cd("u_new")
    assert cd is not None
    assert cd.type == 1
    assert cd.scheduled_time == 123456


@pytest.mark.asyncio
async def test_set_user_busy_updates_existing_row(ext):
    """set_user_busy must UPDATE fields when a user_cd row already exists."""
    await ext.set_user_busy("u_old", 2, scheduled_time=111)
    await ext.set_user_busy("u_old", 3, scheduled_time=222, extra_data={"rift": "r1"})

    cd = await ext.get_user_cd("u_old")
    assert cd is not None
    assert cd.type == 3
    assert cd.scheduled_time == 222
    assert cd.get_extra_data() == {"rift": "r1"}


@pytest.mark.asyncio
async def test_set_user_free_resets_to_idle(ext):
    """set_user_free must work even when the user has no user_cd row."""
    await ext.set_user_free("u_free")

    cd = await ext.get_user_cd("u_free")
    assert cd is not None
    assert cd.type == 0
