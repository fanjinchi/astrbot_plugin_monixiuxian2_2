"""Regression tests for handler-side rendering of service-layer (success, msg) tuples.

Locks the unpack contract that v3.17.8 cleanup accidentally broke: three handlers
rendered the raw tuple (e.g. ``(True, '✅ …')``) straight to players after the
``success, message = ...`` unpack was "cleaned up" as a dead variable.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_package_module

_pill_mod = load_package_module(
    "handlers/pill_handler.py",
    "astrbot_plugin_monixiuxian2_2.handlers.pill_handler",
)
_ring_mod = load_package_module(
    "handlers/storage_ring_handler.py",
    "astrbot_plugin_monixiuxian2_2.handlers.storage_ring_handler",
)
PillHandler = _pill_mod.PillHandler
StorageRingHandler = _ring_mod.StorageRingHandler


class FakePlayer:
    """Minimal player stub; player_required only reads user_id/state here."""

    def __init__(self):
        self.user_id = "u1"
        self.state = "空闲"


@pytest.fixture
def db():
    db = MagicMock()
    db.get_player_by_id = AsyncMock(return_value=FakePlayer())
    db.ext.get_active_loan = AsyncMock(return_value=None)
    db.ext.get_user_cd = AsyncMock(return_value=None)
    return db


def make_event(command_text: str):
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.get_message_str.return_value = command_text
    event.plain_result = MagicMock(side_effect=lambda msg: msg)
    return event


class TestUsePillRendering:
    @pytest.mark.asyncio
    async def test_renders_message_part_of_tuple(self, db):
        """Handler must yield exactly the msg string, never the (success, msg) tuple."""
        pill_manager = MagicMock()
        pill_manager.update_temporary_effects = AsyncMock()
        pill_manager.use_pill = AsyncMock(
            return_value=(True, "✨ 服用【筑基丹】成功！修为大涨！")
        )
        handler = PillHandler(db, MagicMock(), pill_manager=pill_manager)

        event = make_event("服用丹药 筑基丹")
        async for _ in handler.handle_use_pill(event, "筑基丹"):
            pass

        rendered = event.plain_result.call_args[0][0]
        assert rendered == "✨ 服用【筑基丹】成功！修为大涨！"
        assert not rendered.startswith("(")


class TestStorageRingRendering:
    @pytest.fixture
    def handler(self, db):
        ring_manager = MagicMock()
        ring_manager.retrieve_item = AsyncMock(
            return_value=(True, "✅ 已从储物戒取出【精铁】x1")
        )
        ring_manager.discard_item = AsyncMock(
            return_value=(True, "🗑️ 已丢弃【杂草】x1")
        )
        return StorageRingHandler(
            db, MagicMock(), storage_ring_manager=ring_manager
        )

    @pytest.mark.asyncio
    async def test_retrieve_renders_message_part_of_tuple(self, handler):
        """Regression: retrieve once rendered ``(True, '✅ …')`` after unpack removal."""
        event = make_event("取出物品 精铁")
        async for _ in handler.handle_retrieve_item(event, "精铁"):
            pass

        rendered = event.plain_result.call_args[0][0]
        assert rendered == "✅ 已从储物戒取出【精铁】x1"
        assert not rendered.startswith("(")

    @pytest.mark.asyncio
    async def test_discard_renders_message_part_of_tuple(self, handler):
        """Regression: discard once rendered ``(True, '🗑️ …')`` after unpack removal."""
        event = make_event("丢弃物品 杂草")
        async for _ in handler.handle_discard_item(event, "杂草"):
            pass

        rendered = event.plain_result.call_args[0][0]
        assert rendered == "🗑️ 已丢弃【杂草】x1"
        assert not rendered.startswith("(")
