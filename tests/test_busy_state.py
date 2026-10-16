"""Unit tests for core/busy_state.py (openspec change: busy-state-owner).

Covers task 1.2 acceptance:
- dual-write atomicity: a user_cd write failure inside the transaction rolls
  back the whole operation (no row, mirror untouched);
- race: two concurrent set_busy calls on the same user → exactly one winner,
  the loser gets the default message (no silent overwrite);
- set_cooldown: user_cd only, no mirror, no lock recheck;
- assert_idle: missing row / IDLE row → None, busy row → template message;
- clear: unconditional reset of both layers, idempotent without a row.
"""

import asyncio
import sys

import pytest
import pytest_asyncio

from tests.helpers import load_package_module

# Load-order note: busy_state.py uses package-attribute relative imports
# (``from ..data import DataBase`` etc.). Loading it FIRST lets the synthetic
# root package's __path__ resolve the REAL data/models packages.
_busy_mod = load_package_module(
    "core/busy_state.py", "astrbot_plugin_monixiuxian2_2.core.busy_state"
)
BusyState = _busy_mod.BusyState
DEFAULT = _busy_mod.DEFAULT

_data_pkg = sys.modules["astrbot_plugin_monixiuxian2_2.data"]
DataBase = _data_pkg.DataBase
Player = sys.modules["astrbot_plugin_monixiuxian2_2.models"].Player
UserStatus = sys.modules["astrbot_plugin_monixiuxian2_2.models_extended"].UserStatus

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
async def db():
    database = DataBase(":memory:")
    await database.connect()
    await database.conn.execute(USER_CD_DDL)
    await database.conn.commit()
    yield database
    await database.close()


@pytest.fixture
def player():
    return Player(user_id="u_busy")


# ===== set_busy: mirror + persistence =====


@pytest.mark.asyncio
async def test_set_busy_cultivating_mirrors_state(db, player):
    """CULTIVATING writes user_cd and mirrors player.state to '修炼中'."""
    bs = BusyState(db)
    ok, msg = await bs.set_busy(player, UserStatus.CULTIVATING, scheduled_time=123)
    assert (ok, msg) == (True, None)
    assert player.state == "修炼中"
    cd = await db.ext.get_user_cd(player.user_id)
    assert cd is not None
    assert cd.type == UserStatus.CULTIVATING
    assert cd.scheduled_time == 123


@pytest.mark.asyncio
async def test_set_busy_activity_resets_stale_mirror(db, player):
    """ADVENTURING/EXPLORING reset a stale '修炼中' mirror to '空闲'
    (the pre-owner bug class: mirror survived while user_cd moved on)."""
    bs = BusyState(db)
    for i, status in enumerate((UserStatus.ADVENTURING, UserStatus.EXPLORING)):
        p = Player(user_id=f"u_act_{i}")
        p.state = "修炼中"
        ok, _ = await bs.set_busy(p, status, scheduled_time=222)
        assert ok is True
        assert p.state == "空闲"
        cd = await db.ext.get_user_cd(p.user_id)
        assert cd.type == status


@pytest.mark.asyncio
async def test_set_busy_extra_data_roundtrip(db, player):
    """extra_data payload (adventure route_key / rift id+level) must survive."""
    bs = BusyState(db)
    await bs.set_busy(
        player,
        UserStatus.EXPLORING,
        scheduled_time=333,
        extra_data={"rift_id": 7, "rift_level": 2},
    )
    cd = await db.ext.get_user_cd(player.user_id)
    assert cd.get_extra_data() == {"rift_id": 7, "rift_level": 2}


# ===== set_busy: atomicity & race =====


@pytest.mark.asyncio
async def test_set_busy_rolls_back_failed_write(db, player):
    """A failing user_cd write aborts the transaction: no row, mirror untouched."""
    bs = BusyState(db)
    player.state = "历练中"
    real = db.ext.set_user_busy

    async def failing(user_id, busy_type, scheduled_time=0, extra_data=None):
        await real(user_id, busy_type, scheduled_time, extra_data)
        raise RuntimeError("simulated write failure")

    db.ext.set_user_busy = failing
    with pytest.raises(RuntimeError):
        await bs.set_busy(player, UserStatus.CULTIVATING)

    assert await db.ext.get_user_cd(player.user_id) is None
    assert player.state == "历练中"


@pytest.mark.asyncio
async def test_set_busy_race_exactly_one_winner(db, player):
    """Two concurrent set_busy on the same user: exactly one wins, the loser
    gets the default message describing the winner's CURRENT status."""
    bs = BusyState(db)
    results = await asyncio.gather(
        bs.set_busy(player, UserStatus.CULTIVATING),
        bs.set_busy(player, UserStatus.ADVENTURING),
    )
    winners = [r for r in results if r[0] is True]
    losers = [r for r in results if r[0] is False]
    assert len(winners) == 1
    assert len(losers) == 1
    assert winners[0][1] is None

    # Loser message reflects the winner's committed status and carries the
    # default template text.
    cd = await db.ext.get_user_cd(player.user_id)
    assert cd.type in (UserStatus.CULTIVATING, UserStatus.ADVENTURING)
    msg = losers[0][1]
    assert msg is not None
    assert msg.startswith("❌ ")
    assert UserStatus.get_name(cd.type) in msg


# ===== set_cooldown: user_cd only =====


@pytest.mark.asyncio
async def test_set_cooldown_writes_user_cd_without_mirror(db):
    """SECT_TASK cooldown writes user_cd only (no mirror, no clear entry)."""
    bs = BusyState(db)
    await bs.set_cooldown("u_cool", UserStatus.SECT_TASK, 999)
    cd = await db.ext.get_user_cd("u_cool")
    assert cd.type == UserStatus.SECT_TASK
    assert cd.scheduled_time == 999


@pytest.mark.asyncio
async def test_set_cooldown_overwrites_without_recheck(db):
    """Cooldown path keeps status quo: a busy user_cd does NOT block a new
    cooldown write (R1 lock recheck does not extend to cooldowns)."""
    bs = BusyState(db)
    await bs.set_busy(Player(user_id="u_cool"), UserStatus.CULTIVATING)
    await bs.set_cooldown("u_cool", UserStatus.SECT_TASK, 1000)
    await bs.set_cooldown("u_cool", UserStatus.SECT_TASK, 2000)
    cd = await db.ext.get_user_cd("u_cool")
    assert cd.type == UserStatus.SECT_TASK
    assert cd.scheduled_time == 2000


# ===== assert_idle: read-side guard =====


@pytest.mark.asyncio
async def test_assert_idle_missing_row_is_idle(db):
    """No user_cd row counts as idle (None), matching legacy semantics."""
    bs = BusyState(db)
    assert await bs.assert_idle("u_ghost") is None


@pytest.mark.asyncio
async def test_assert_idle_idle_row_is_idle(db):
    """An IDLE row counts as idle."""
    bs = BusyState(db)
    await db.ext.set_user_free("u_free")
    assert await bs.assert_idle("u_free") is None


@pytest.mark.asyncio
async def test_assert_idle_busy_uses_default_template(db, player):
    """Busy row → DEFAULT template formatted with the current status name."""
    bs = BusyState(db)
    await bs.set_busy(player, UserStatus.CULTIVATING)
    msg = await bs.assert_idle(player.user_id)
    assert msg == DEFAULT.format(status="闭关中")
    assert "闭关中" in msg


@pytest.mark.asyncio
async def test_assert_idle_busy_accepts_custom_template(db, player):
    """Custom per-caller templates (cultivation/double-cultivation style) work."""
    bs = BusyState(db)
    await bs.set_busy(player, UserStatus.EXPLORING)
    msg = await bs.assert_idle(
        player.user_id, template="你当前正在「{status}」，无法弃道重修。"
    )
    assert msg == "你当前正在「探索秘境中」，无法弃道重修。"


@pytest.mark.asyncio
async def test_default_template_text():
    """Snapshot of the chosen dominant sect-family wording (guards rely on it)."""
    assert DEFAULT == "❌ 你当前正{status}，无法进行此操作！"


# ===== clear: unconditional reset =====


@pytest.mark.asyncio
async def test_clear_resets_both_layers(db, player):
    """clear() resets user_cd to IDLE and the mirror to '空闲'."""
    bs = BusyState(db)
    await bs.set_busy(player, UserStatus.CULTIVATING)
    assert player.state == "修炼中"
    await bs.clear(player)
    cd = await db.ext.get_user_cd(player.user_id)
    assert cd is not None
    assert cd.type == UserStatus.IDLE
    assert player.state == "空闲"


@pytest.mark.asyncio
async def test_clear_idempotent_without_row(db, player):
    """clear() with no user_cd row is an idempotent upsert, not an error."""
    bs = BusyState(db)
    player.state = "历练中"
    await bs.clear(player)
    cd = await db.ext.get_user_cd(player.user_id)
    assert cd is not None
    assert cd.type == UserStatus.IDLE
    assert player.state == "空闲"


# ===== 窄写收口（bd -546 P0，2026-10-15）=====


@pytest.mark.asyncio
async def test_update_user_cd_fields_writes_only_named_columns(db, player):
    """窄写入口只动显式列出的列，其余列保持库中现值。"""
    bs = BusyState(db)
    await bs.set_busy(
        player, UserStatus.EXPLORING, scheduled_time=777, extra_data={"rift_id": 3}
    )
    await db.ext.update_user_cd_fields(player.user_id, scheduled_time=888)
    row = await db.ext.get_user_cd(player.user_id)
    assert row.scheduled_time == 888
    assert row.type == UserStatus.EXPLORING
    assert row.get_extra_data() == {"rift_id": 3}


@pytest.mark.asyncio
async def test_update_user_cd_fields_rejects_empty_and_unknown(db, player):
    """空字段与白名单外的列名必须显式报错，不得拼进 SQL。"""
    bs = BusyState(db)
    await bs.set_busy(player, UserStatus.CULTIVATING)
    with pytest.raises(ValueError):
        await db.ext.update_user_cd_fields(player.user_id)
    with pytest.raises(ValueError):
        await db.ext.update_user_cd_fields(player.user_id, user_id="x")
    with pytest.raises(ValueError):
        await db.ext.update_user_cd_fields(player.user_id, nope=1)


@pytest.mark.asyncio
async def test_stamp_extra_cannot_resurrect_cleared_busy(db, player):
    """陈旧快照 stamp 只改 extra_data，不得把已收尾的忙碌复活（真交错回归）。

    复刻 _ensure_run_row 闸门失效那一路：调用方手里是进入结算前的 user_cd
    快照，而赢家已经把该行 clear 成 IDLE。修复前的整行回写会把 type 恢复成
    ADVENTURING——忙碌判定只看 type，玩家从此永久卡死、重启不自愈。
    """
    bs = BusyState(db)
    await bs.set_busy(player, UserStatus.ADVENTURING, scheduled_time=999)
    stale = await db.ext.get_user_cd(player.user_id)  # 结算前持有的快照
    await db.ext.set_user_free(player.user_id)  # 赢家已收尾
    assert (await db.ext.get_user_cd(player.user_id)).type == UserStatus.IDLE

    await bs.stamp_extra(stale, {"route_key": "scout", "adventure_run_id": "r1"})

    row = await db.ext.get_user_cd(player.user_id)
    assert row.type == UserStatus.IDLE  # 未被复活
    assert row.scheduled_time == 0  # 陈旧时间戳没有回写
    assert row.get_extra_data()["adventure_run_id"] == "r1"
