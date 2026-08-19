"""Regression tests for shop buy paths (bd: missing item type crashing purchase)."""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_package_module

_shop_mod = load_package_module(
    "handlers/shop_handler.py",
    "astrbot_plugin_monixiuxian2_2.handlers.shop_handler",
)
ShopHandler = _shop_mod.ShopHandler


def _make_event() -> MagicMock:
    """Build a minimal AstrMessageEvent stand-in for handler tests."""
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.get_message_str.return_value = "购买 筑基丹"
    event.plain_result.side_effect = lambda text: text
    return event


def _make_player() -> MagicMock:
    player = MagicMock()
    player.user_id = "u1"
    player.user_name = "测试道友"
    player.gold = 999999
    return player


def _mock_handler_db(handler: ShopHandler, player: MagicMock) -> None:
    """Satisfy the ``@player_required`` wrapper's pre-handler db lookups."""
    handler.db = MagicMock()
    handler.db.get_player_by_id = AsyncMock(return_value=player)
    handler.db.ext = MagicMock()
    handler.db.ext.get_user_cd = AsyncMock(return_value=None)  # 空闲
    handler.db.ext.get_active_loan = AsyncMock(return_value=None)


@pytest.mark.asyncio
async def test_handle_buy_missing_type_yields_clear_message_no_transaction():
    """A shop item without a ``type`` key must yield a clear message, not a KeyError.

    Regression for the crash seen in the functional test suite when the shop
    seed item lacked ``type`` (previously ``target_item["type"]`` raised KeyError).
    """
    handler = ShopHandler.__new__(ShopHandler)
    handler.shop_manager = MagicMock()
    handler.shop_manager.get_sect_shop_discount.return_value = 1.0
    handler._find_item_in_pavilions = AsyncMock(
        return_value=("pill_pavilion", {"name": "筑基丹", "price": 5000, "stock": 5})
    )
    # 故意不 mock db.conn：断言防御分支不会触碰数据库事务
    event = _make_event()
    player = _make_player()
    _mock_handler_db(handler, player)
    outputs = [item async for item in handler.handle_buy(event, "筑基丹")]

    assert len(outputs) == 1
    msg = str(outputs[0])
    assert "数据异常" in msg and "缺少类型信息" in msg
    handler.db.conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_handle_buy_valid_pill_still_succeeds():
    """A normal pill purchase must still succeed after the type guard change."""
    handler = ShopHandler.__new__(ShopHandler)
    handler.shop_manager = MagicMock()
    handler.shop_manager.get_sect_shop_discount.return_value = 1.0
    handler._find_item_in_pavilions = AsyncMock(
        return_value=(
            "pill_pavilion",
            {"name": "筑基丹", "type": "pill", "price": 5000, "stock": 5},
        )
    )
    event = _make_event()
    player = _make_player()
    _mock_handler_db(handler, player)
    handler.db.conn.execute = AsyncMock()
    handler.db.conn.commit = AsyncMock()
    handler.db.conn.rollback = AsyncMock()
    handler.db.decrement_shop_item_stock = AsyncMock(return_value=(True, 1, 4))
    handler.db.update_player = AsyncMock()
    handler.pill_manager = MagicMock()
    handler.pill_manager.add_pill_to_inventory = AsyncMock()

    event = _make_event()
    player = _make_player()
    outputs = [item async for item in handler.handle_buy(event, "筑基丹")]

    assert len(outputs) == 1
    msg = str(outputs[0])
    assert "成功购买【筑基丹】x1" in msg and "花费灵石: 5000" in msg
    handler.pill_manager.add_pill_to_inventory.assert_awaited_once()
    handler.db.conn.commit.assert_awaited_once()
