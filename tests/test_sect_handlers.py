"""Regression tests for sect/player handlers (OCR review fixes M9, H3+M8).

M9: view branches of 宗门丹房/宗门建设/宗门宝库 are allowed while busy;
only the mutation branches (领取/升级) are blocked.
H3+M8: the sect daily reset at check-in advances the date atomically and
its failure never breaks the check-in flow.
"""

import sys
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

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
        self.sect_config = {
            "positions": {
                "0": {"name": "宗主", "permission": 10},
                "1": {"name": "长老", "permission": 8},
                "2": {"name": "亲传弟子", "permission": 5},
                "3": {"name": "内门弟子", "permission": 2},
                "4": {"name": "外门弟子", "permission": 0},
            },
            "scale_ratio": 10,
        }
        self.sect_factions = {
            "factions": [
                {
                    "id": "qingyun",
                    "name": "青云门",
                    "join_level_range": [0, 5],
                    "elders": [{"name": "玄诚子", "title": "传功长老"}],
                    "heart_methods": ["heart_qy_001"],
                    "treasures": [],
                    "shop": [
                        {"id": "sword_006", "price": 1500, "min_position": 3},
                        {"id": "heart_qy_001", "price": 500},
                    ],
                }
            ]
        }
        self.sect_tasks = {"construction_tasks": [], "master_task_chains": []}
        self.game_config = {}
        self.heart_methods_data = {
            "青云心典": {"id": "heart_qy_001", "name": "青云心典"}
        }
        self.weapons_data = {
            "青云天剑": {"id": "sword_006", "name": "青云天剑", "rank": "天阶"}
        }
        self.items_data = {}

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


class _FrozenDateTime(datetime):
    """Fixed clock for check-in tests so date assertions never race midnight."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 8, 19, 12, 0, 0)


FROZEN_TODAY = "2026-08-19"


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
async def test_check_in_daily_reset_runs_once_per_day(monkeypatch):
    """The first check-in of a day resets sect flags exactly once; later
    check-ins on the same day do not reset again."""
    monkeypatch.setattr(_player_handler_mod, "datetime", _FrozenDateTime)
    db = await _make_db()
    handler = PlayerHandler(db, {"VALUES": {}}, FakeConfigManager())
    today = FROZEN_TODAY

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
    monkeypatch.setattr(_player_handler_mod, "datetime", _FrozenDateTime)
    db = await _make_db()
    handler = PlayerHandler(db, {"VALUES": {}}, FakeConfigManager())

    await _make_player(db, "u1", check_in_date="2000-01-01")

    async def _boom(commit=True):
        raise RuntimeError("simulated reset failure")

    monkeypatch.setattr(db.ext, "reset_sect_elixir_get", _boom)

    event = _make_event("u1", "签到")
    await _collect(handler.handle_check_in(event))
    assert "签到成功" in _last_msg(event)

    player = await db.get_player_by_id("u1")
    assert player.last_check_in_date == FROZEN_TODAY
    assert player.gold > 0

    # 重置失败时日期不推进，下次签到可重试
    assert await db.ext.get_system_config("sect_daily_reset_date") != FROZEN_TODAY

    await db.close()


# ===== /宗门 统一入口分发器 =====


@pytest.mark.asyncio
async def test_sect_entry_navigation_and_unknown_subcommand():
    """无参数与未知子命令均输出导航帮助；带唤醒前缀也能正确解析。"""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    handlers = SectHandlers(db, mgr, bounty_mgr=MagicMock())
    await _make_player(db, "n1")

    event = _make_event("n1", "宗门")
    await _collect(handlers.handle_sect_entry(event))
    assert "指令导航" in _last_msg(event)
    assert "悬赏" in _last_msg(event) and "商店" in _last_msg(event)

    event = _make_event("n1", "/宗门")
    await _collect(handlers.handle_sect_entry(event))
    assert "指令导航" in _last_msg(event)

    event = _make_event("n1", "宗门 不存在的东西")
    await _collect(handlers.handle_sect_entry(event))
    assert "未识别的宗门子命令" in _last_msg(event)
    assert "指令导航" in _last_msg(event)

    await db.close()


@pytest.mark.asyncio
async def test_sect_entry_missing_arg_usage_hints():
    """缺参子命令输出各自用法示例。"""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    handlers = SectHandlers(db, mgr, bounty_mgr=MagicMock())
    await _make_player(db, "n2")

    event = _make_event("n2", "宗门 捐献")
    await _collect(handlers.handle_sect_entry(event))
    assert "/宗门 捐献 1000" in _last_msg(event)

    event = _make_event("n2", "宗门 创建")
    await _collect(handlers.handle_sect_entry(event))
    assert "/宗门 创建 逍遥门" in _last_msg(event)

    event = _make_event("n2", "宗门 捐献 abc")
    await _collect(handlers.handle_sect_entry(event))
    assert "/宗门 捐献 1000" in _last_msg(event)

    await db.close()


@pytest.mark.asyncio
async def test_sect_entry_membership_gates():
    """悬赏/商店/信息子命令对无宗门玩家的拒绝提示。"""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    handlers = SectHandlers(db, mgr, bounty_mgr=MagicMock())
    await _make_player(db, "n3")

    event = _make_event("n3", "宗门 悬赏")
    await _collect(handlers.handle_sect_entry(event))
    assert "你还未加入宗门" in _last_msg(event)

    event = _make_event("n3", "宗门 商店")
    await _collect(handlers.handle_sect_entry(event))
    assert "你还未加入宗门" in _last_msg(event)

    event = _make_event("n3", "宗门 信息")
    await _collect(handlers.handle_sect_entry(event))
    assert "还未加入宗门" in _last_msg(event) or "未加入宗门" in _last_msg(event)

    await db.close()


@pytest.mark.asyncio
async def test_sect_entry_busy_player_blocked():
    """「宗门」不在忙碌白名单：忙碌时所有子命令（含查看类）被拒，与旧独立指令行为一致。"""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    handlers = SectHandlers(db, mgr, bounty_mgr=MagicMock())
    await _make_player(db, "n4")
    success, msg = await mgr.join_sect("n4", "青云门")
    assert success, msg

    await db.ext.set_user_busy("n4", UserStatus.EXPLORING, 9999999999)
    event = _make_event("n4", "宗门 信息")
    await _collect(handlers.handle_sect_entry(event))
    assert "无法分心他顾" in _last_msg(event)

    await db.close()


# ===== 宗门商店 =====


@pytest.mark.asyncio
async def test_sect_shop_list_and_position_gate():
    """商店列表展示贡献价与职阶锁定标注。"""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _make_player(db, "s1")
    success, msg = await mgr.join_sect("s1", "青云门")
    assert success, msg

    success, msg = await mgr.get_sect_shop_info("s1")
    assert success, msg
    assert "宗门商店" in msg
    assert "青云天剑" in msg and "1500 贡献" in msg
    assert "🔒需内门弟子及以上" in msg  # 外门弟子(4) > min_position(3)
    assert "青云心典" in msg and "500 贡献" in msg
    assert "🔒" not in msg.split("青云心典")[1]

    await db.close()


@pytest.mark.asyncio
async def test_sect_shop_buy_flow():
    """购买成功扣贡献并发货；贡献不足与职阶不足分别拒绝。"""
    db = await _make_db()
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _make_player(db, "s2")
    success, msg = await mgr.join_sect("s2", "青云门")
    assert success, msg

    player = await db.get_player_by_id("s2")
    player.sect_contribution = 1000
    await db.update_player(player)

    # 职阶门槛：外门弟子买 min_position=3 的青云天剑被拒
    success, msg = await mgr.buy_sect_shop_item("s2", "青云天剑")
    assert not success and "职阶不足" in msg

    # 贡献不足：买 1500 的剑（先晋升到内门弟子）
    player = await db.get_player_by_id("s2")
    player.sect_position = 3
    await db.update_player(player)
    success, msg = await mgr.buy_sect_shop_item("s2", "青云天剑")
    assert not success and "贡献点不足" in msg and "1500" in msg

    # 正常购买：青云心典 500 贡献
    success, msg = await mgr.buy_sect_shop_item("s2", "青云心典")
    assert success, msg
    assert "购买成功" in msg and "剩余 500" in msg
    player = await db.get_player_by_id("s2")
    assert player.sect_contribution == 500
    assert player.get_storage_ring_items().get("青云心典") == 1

    # 未知商品
    success, msg = await mgr.buy_sect_shop_item("s2", "不存在的东西")
    assert not success and "没有" in msg

    await db.close()


@pytest.mark.asyncio
async def test_end_cultivation_hints_when_legacy_unactivated(monkeypatch):
    """出关时持有传承但未激活：提示需先激活（spec：未激活传承不累积）。

    激活实例存在时正常累积累提示；无实例时不提示。
    """
    db = await _make_db()
    handler = PlayerHandler(db, {"VALUES": {}}, FakeConfigManager())

    await _make_player(db, "u1")

    async def _enter_cultivation(user_id: str):
        player = await db.get_player_by_id(user_id)
        player.state = "修炼中"
        player.cultivation_start_time = int(time.time()) - 30 * 60
        await db.update_player(player)

    # 场景1：持有传承但未激活 → 出关提示需先激活
    fake_impart = MagicMock()
    fake_impart.add_active_impart_value = AsyncMock(return_value=None)
    handler.impart_mgr = fake_impart
    monkeypatch.setattr(
        db.ext, "list_legacy_instances_by_owner", AsyncMock(return_value=[object()])
    )
    await _enter_cultivation("u1")
    event = _make_event("u1", "出关")
    await _collect(handler.handle_end_cultivation(event))
    msg = _last_msg(event)
    assert "未激活" in msg and "激活传承" in msg

    # 场景2：激活累积有输出 → 正常提示，不再提示未激活
    fake_impart.add_active_impart_value = AsyncMock(
        return_value="🌟 【通用传承】传承值 +2（当前 2）"
    )
    monkeypatch.setattr(
        db.ext, "list_legacy_instances_by_owner", AsyncMock(return_value=[])
    )
    await _enter_cultivation("u1")
    event = _make_event("u1", "出关")
    await _collect(handler.handle_end_cultivation(event))
    msg = _last_msg(event)
    assert "未激活" not in msg and "传承值 +2" in msg

    await db.close()
