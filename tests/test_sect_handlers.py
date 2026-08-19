"""Regression tests for sect/player handlers (OCR review fixes M9, H3+M8).

M9: view branches of 宗门丹房/宗门建设/宗门宝库 are allowed while busy;
only the mutation branches (领取/升级) are blocked.
H3+M8: the sect daily reset at check-in advances the date atomically and
its failure never breaks the check-in flow.
"""

import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tests.helpers import load_module, load_package_module

_migration_mod = load_module("migration_sect_handlers_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager

_data_mod = load_package_module(
    "data/data_manager.py",
    "astrbot_plugin_monixiuxian2_2.data.data_manager",
)
DataBase = _data_mod.DataBase

Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player
UserStatus = load_package_module(
    "models_extended.py", "astrbot_plugin_monixiuxian2_2.models_extended"
).UserStatus

_sect_mod = load_package_module(
    "managers/sect_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.sect_handlers_mgr",
)
SectManager = _sect_mod.SectManager

# sect_manager registers ``DataBase`` on the synthetic data package; the
# handlers import the same modules through the same synthetic tree.
sys.modules["astrbot_plugin_monixiuxian2_2.data"].DataBase = DataBase

_sect_handlers_mod = load_package_module(
    "handlers/sect_handlers.py",
    "astrbot_plugin_monixiuxian2_2.handlers.sect_handlers",
)
SectHandlers = _sect_handlers_mod.SectHandlers

# player_handler does ``from ..core import ...``; load the real core package
# __init__ first so the names resolve under the synthetic package tree.
load_package_module("core/__init__.py", "astrbot_plugin_monixiuxian2_2.core")

_player_handler_mod = load_package_module(
    "handlers/player_handler.py",
    "astrbot_plugin_monixiuxian2_2.handlers.player_handler",
)
PlayerHandler = _player_handler_mod.PlayerHandler


class FakeConfigManager:
    """Minimal ConfigManager stub with the qingyun system sect."""

    def __init__(self):
        self.sect_config = {"positions": {}, "scale_ratio": 10}
        self.sect_factions = {
            "factions": [
                {
                    "id": "qingyun",
                    "name": "青云门",
                    "join_level_range": [0, 5],
                    "elders": [{"name": "玄诚子", "title": "传功长老"}],
                    "heart_methods": ["heart_qy_001"],
                    "treasures": [],
                }
            ]
        }
        self.sect_tasks = {"construction_tasks": [], "master_task_chains": []}
        self.game_config = {}
        self.heart_methods_data = {
            "青云心典": {"id": "heart_qy_001", "name": "青云心典"}
        }

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"


async def _make_db() -> DataBase:
    db = DataBase(":memory:")
    await db.connect()
    await MigrationManager(db.conn, FakeConfigManager()).migrate()
    return db


async def _make_player(db: DataBase, user_id: str, check_in_date: str = "") -> Player:
    player = Player(
        user_id=user_id,
        user_name=f"道友{user_id}",
        spiritual_root="天灵根",
        level_index=1,
        last_check_in_date=check_in_date,
    )
    await db.create_player(player)
    return player


def _make_event(user_id: str, text: str = ""):
    """Build a minimal event mock for handler tests."""
    event = MagicMock()
    event.get_sender_id.return_value = user_id
    event.get_message_str.return_value = text
    event.plain_result = MagicMock(return_value="plain")
    return event


async def _collect(handler_gen) -> list[str]:
    """Drain a handler async generator and return the plain messages."""
    messages = []
    async for _ in handler_gen:
        pass
    return messages


def _last_msg(event) -> str:
    return event.plain_result.call_args[0][0]


# ===== M9 查看分支放行 =====


@pytest.mark.asyncio
async def test_busy_player_can_view_but_not_mutate_sect_panels():
    """Busy players may view elixir/construction/treasury panels; the claim
    and upgrade branches still reject them."""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _make_player(db, "u1")
    success, msg = await mgr.join_sect("u1", "青云门")
    assert success, msg

    handlers = SectHandlers(db, mgr)
    await db.ext.set_user_busy("u1", UserStatus.EXPLORING, 9999999999)

    # 查看分支放行
    event = _make_event("u1", "宗门丹房")
    await _collect(handlers.handle_sect_elixir(event, ""))
    assert "无法进行此操作" not in _last_msg(event)
    assert "宗门丹房" in _last_msg(event)

    event = _make_event("u1", "宗门建设")
    await _collect(handlers.handle_sect_construction(event, ""))
    assert "无法进行此操作" not in _last_msg(event)
    assert "宗门建设" in _last_msg(event)

    event = _make_event("u1", "宗门宝库")
    await _collect(handlers.handle_sect_treasury(event, ""))
    assert "无法进行此操作" not in _last_msg(event)
    assert "宝库" in _last_msg(event)

    # 变更分支仍拦截
    event = _make_event("u1", "宗门丹房 领取")
    await _collect(handlers.handle_sect_elixir(event, "领取"))
    assert "无法进行此操作" in _last_msg(event)

    event = _make_event("u1", "宗门建设 洞天")
    await _collect(handlers.handle_sect_construction(event, "洞天"))
    assert "无法进行此操作" in _last_msg(event)

    event = _make_event("u1", "宗门宝库 青云心典")
    await _collect(handlers.handle_sect_treasury(event, "青云心典"))
    assert "无法进行此操作" in _last_msg(event)

    await db.close()


# ===== H3+M8 签到宗门日重置 =====


@pytest.mark.asyncio
async def test_check_in_daily_reset_runs_once_per_day():
    """The first check-in of a day resets sect flags exactly once; later
    check-ins on the same day do not reset again."""
    db = await _make_db()
    handler = PlayerHandler(db, {"VALUES": {}}, FakeConfigManager())
    today = datetime.now().strftime("%Y-%m-%d")

    await _make_player(db, "u1", check_in_date="2000-01-01")
    await _make_player(db, "u2", check_in_date="2000-01-01")

    # u2 已领取过丹药，等待跨日重置
    player2 = await db.get_player_by_id("u2")
    player2.sect_elixir_get = 1
    await db.update_player(player2)

    # 每日首位签到者触发全局重置
    event = _make_event("u1", "签到")
    await _collect(handler.handle_check_in(event))
    assert "签到成功" in _last_msg(event)

    assert await db.ext.get_system_config("sect_daily_reset_date") == today
    player2 = await db.get_player_by_id("u2")
    assert player2.sect_elixir_get == 0

    # 同一天后续签到不再重置
    player2 = await db.get_player_by_id("u2")
    player2.sect_elixir_get = 1
    await db.update_player(player2)

    event = _make_event("u2", "签到")
    await _collect(handler.handle_check_in(event))
    assert "签到成功" in _last_msg(event)
    player2 = await db.get_player_by_id("u2")
    assert player2.sect_elixir_get == 1  # 未被二次重置

    await db.close()


@pytest.mark.asyncio
async def test_check_in_daily_reset_failure_does_not_break_check_in(monkeypatch):
    """A failing sect daily reset is logged and swallowed; check-in succeeds."""
    db = await _make_db()
    handler = PlayerHandler(db, {"VALUES": {}}, FakeConfigManager())

    await _make_player(db, "u1", check_in_date="2000-01-01")

    async def _boom():
        raise RuntimeError("simulated reset failure")

    monkeypatch.setattr(db.ext, "reset_sect_elixir_get", _boom)

    event = _make_event("u1", "签到")
    await _collect(handler.handle_check_in(event))
    assert "签到成功" in _last_msg(event)

    player = await db.get_player_by_id("u1")
    today = datetime.now().strftime("%Y-%m-%d")
    assert player.last_check_in_date == today
    assert player.gold > 0

    await db.close()
