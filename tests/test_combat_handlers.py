"""Regression tests for combat handler command wiring."""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_package_module

_combat_mod = load_package_module(
    "handlers/combat_handlers.py",
    "astrbot_plugin_monixiuxian2_2.handlers.combat_handlers",
)
CombatHandlers = _combat_mod.CombatHandlers


def test_handle_duel_method_exists():
    """CombatHandlers must expose handle_duel with the expected signature."""
    assert hasattr(CombatHandlers, "handle_duel")
    sig = inspect.signature(CombatHandlers.handle_duel)
    params = list(sig.parameters)
    assert params == ["self", "event", "target"]


def test_handle_spar_method_exists():
    """CombatHandlers must still expose handle_spar."""
    assert hasattr(CombatHandlers, "handle_spar")


@pytest.mark.asyncio
async def test_handle_spar_assigns_engine_result():
    """Regression (bd tbp): handle_spar must call the combat engine before using result."""
    handler = CombatHandlers.__new__(CombatHandlers)

    p1 = MagicMock(hp=100)
    p2 = MagicMock(hp=100)

    handler.db = MagicMock()
    handler.db.ext = MagicMock()
    handler.db.ext.get_user_cd = AsyncMock(return_value=None)
    handler.db.update_player = AsyncMock()
    handler.combat_mgr = MagicMock()
    handler.combat_mgr.player_vs_player = AsyncMock(
        return_value={
            "winner": "u1",
            "combat_log": ["第一回合", "切磋结束"],
            "player1_final_hp": 100,
            "player2_final_hp": 100,
        }
    )
    handler._get_target_id = AsyncMock(return_value="u2")
    handler._get_combat_cooldown = AsyncMock(return_value={})
    handler._fetch_player = AsyncMock(side_effect=[p1, p2])
    handler._update_combat_cooldown = AsyncMock()

    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.plain_result.side_effect = lambda text: text

    outputs = [item async for item in handler.handle_spar(event, "@u2")]

    handler.combat_mgr.player_vs_player.assert_awaited_once_with(p1, p2, combat_type=1)
    assert any("切磋结束" in str(o) for o in outputs)
