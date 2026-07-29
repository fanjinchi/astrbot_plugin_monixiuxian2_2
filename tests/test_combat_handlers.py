"""Regression tests for combat handler command wiring."""

import inspect

from tests.helpers import load_package_module

_combat_mod = load_package_module(
    "handlers/combat_handlers.py", "astrbot_plugin_monixiuxian2_2.handlers.combat_handlers"
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
