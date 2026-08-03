"""Tests for the boss and PvE feature switches."""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_package_module

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


class FakeEvent:
    """Minimal event stand-in for plugin tests."""

    def __init__(self, text=""):
        self._text = text

    def get_sender_id(self):
        return "u1"

    def get_group_id(self):
        return None

    def get_message_str(self):
        return self._text

    def plain_result(self, text):
        return type("Result", (), {"text": text})()


def _async_iter(values):
    """Wrap synchronous values in an async generator for handler mocks."""

    async def _gen():
        for value in values:
            yield value

    return _gen()


def _noop_command(*args, **kwargs):
    """Decorator replacement that leaves the wrapped function unchanged."""

    def _decorator(func):
        return func

    return _decorator


class _StarBase:
    """Minimal replacement for the AstrBot Star base class."""

    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture(scope="module")
def plugin_class():
    """Load XiuXianPlugin with mocked sub-packages and restore them after tests."""
    # Ensure the real parent package exists (it is created by load_package_module
    # if absent, but we keep it so relative imports can resolve).
    parent_name = "astrbot_plugin_monixiuxian2_2"
    if parent_name not in sys.modules:
        pkg = types.ModuleType(parent_name)
        pkg.__path__ = [str(PLUGIN_ROOT)]
        sys.modules[parent_name] = pkg

    # Replace the heavy sub-packages with lightweight mocks only while loading.
    submodule_keys = [
        "astrbot_plugin_monixiuxian2_2.handlers",
        "astrbot_plugin_monixiuxian2_2.managers",
        "astrbot_plugin_monixiuxian2_2.core",
    ]
    original_submodules = {key: sys.modules.get(key) for key in submodule_keys}
    for key in submodule_keys:
        sys.modules[key] = MagicMock()

    # Mock the command filter decorator so the class can be loaded without the
    # real AstrBot runtime, but keep the actual handler methods intact.
    event_mod = sys.modules.setdefault("astrbot.api.event", MagicMock())
    original_filter_command = getattr(event_mod.filter, "command", None)
    event_mod.filter.command = _noop_command

    star_mod = sys.modules.setdefault("astrbot.api.star", MagicMock())
    original_star = getattr(star_mod, "Star", None)
    star_mod.Star = _StarBase

    command_mod = sys.modules.setdefault("astrbot.core.star.filter.command", MagicMock())
    original_greedy = getattr(command_mod, "GreedyStr", None)
    command_mod.GreedyStr = str

    _main_mod = load_package_module(
        "main.py", "astrbot_plugin_monixiuxian2_2.main_test"
    )
    cls = _main_mod.XiuXianPlugin

    yield cls

    # Restore sys.modules to avoid interfering with other tests that load the
    # real handler/manager/core packages.
    for key, value in original_submodules.items():
        if value is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = value

    if original_filter_command is None:
        del event_mod.filter.command
    else:
        event_mod.filter.command = original_filter_command

    if original_star is None:
        del star_mod.Star
    else:
        star_mod.Star = original_star

    if original_greedy is None:
        del command_mod.GreedyStr
    else:
        command_mod.GreedyStr = original_greedy


@pytest.fixture
def plugin(plugin_class):
    """Fresh plugin instance with mocked config and context."""
    config = MagicMock()
    config.get.return_value = {}
    context = MagicMock()
    return plugin_class(context, config)


class TestFeatureSwitchDecision:
    """The two feature switches read from game_config and default to on."""

    def test_boss_switch_enabled_by_default(self, plugin):
        assert plugin._is_boss_enabled() is True

    def test_pve_switch_enabled_by_default(self, plugin):
        assert plugin._is_pve_enabled() is True

    def test_boss_switch_disabled_via_config(self, plugin):
        plugin.config_manager.game_config["boss"]["enabled"] = False
        assert plugin._is_boss_enabled() is False

    def test_pve_switch_disabled_via_config(self, plugin):
        plugin.config_manager.game_config["pve"]["enabled"] = False
        assert plugin._is_pve_enabled() is False


class TestBossGate:
    """Boss commands are gated when the boss switch is off."""

    @pytest.mark.asyncio
    async def test_boss_info_gated_when_disabled(self, plugin):
        plugin.config_manager.game_config["boss"]["enabled"] = False
        plugin.boss_handlers = MagicMock()
        results = [
            result async for result in plugin.handle_boss_info(FakeEvent("世界Boss"))
        ]
        assert len(results) == 1
        assert "维护" in results[0].text
        plugin.boss_handlers.handle_boss_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_boss_fight_gated_when_disabled(self, plugin):
        plugin.config_manager.game_config["boss"]["enabled"] = False
        plugin.boss_handlers = MagicMock()
        results = [
            result async for result in plugin.handle_boss_fight(FakeEvent("挑战Boss"))
        ]
        assert len(results) == 1
        assert "维护" in results[0].text
        plugin.boss_handlers.handle_boss_fight.assert_not_called()

    @pytest.mark.asyncio
    async def test_boss_spawn_gated_when_disabled(self, plugin):
        plugin.config_manager.game_config["boss"]["enabled"] = False
        plugin.boss_handlers = MagicMock()
        results = [
            result
            async for result in plugin.handle_spawn_boss(FakeEvent("生成Boss"))
        ]
        assert len(results) == 1
        assert "维护" in results[0].text
        plugin.boss_handlers.handle_spawn_boss.assert_not_called()


class TestPvEGate:
    """PvE rift entry is gated when the pve switch is off."""

    @pytest.mark.asyncio
    async def test_rift_explore_gated_when_pve_disabled(self, plugin):
        plugin.config_manager.game_config["pve"]["enabled"] = False
        plugin.rift_handlers = MagicMock()
        results = [
            result
            async for result in plugin.handle_rift_explore(
                FakeEvent("探索秘境 1"), 1
            )
        ]
        assert len(results) == 1
        assert "维护" in results[0].text
        plugin.rift_handlers.handle_rift_explore.assert_not_called()


class TestNonPvEGameplay:
    """PvP and adventure remain available when both switches are off."""

    @pytest.mark.asyncio
    async def test_adventure_starts_when_pve_disabled(self, plugin):
        plugin.config_manager.game_config["pve"]["enabled"] = False
        plugin.adventure_handlers = MagicMock()
        plugin.adventure_handlers.handle_start_adventure.return_value = _async_iter(
            [FakeEvent().plain_result("历练开始")]
        )
        results = [
            result
            async for result in plugin.handle_adventure_start(
                FakeEvent("开始历练 巡山问道"), "巡山问道"
            )
        ]
        assert len(results) == 1
        assert results[0].text == "历练开始"
        plugin.adventure_handlers.handle_start_adventure.assert_called_once()

    @pytest.mark.asyncio
    async def test_spar_still_works_when_boss_and_pve_disabled(self, plugin):
        plugin.config_manager.game_config["boss"]["enabled"] = False
        plugin.config_manager.game_config["pve"]["enabled"] = False
        plugin.combat_handlers = MagicMock()
        plugin.combat_handlers.handle_spar.return_value = _async_iter(
            [FakeEvent().plain_result("切磋开始")]
        )
        results = [
            result
            async for result in plugin.handle_spar(FakeEvent("切磋 @u2"), "@u2")
        ]
        assert len(results) == 1
        assert results[0].text == "切磋开始"
        plugin.combat_handlers.handle_spar.assert_called_once()


class TestScheduledTask:
    """The boss spawn background task is not scheduled when the switch is off."""

    @pytest.mark.asyncio
    async def test_boss_spawn_task_not_started_when_disabled(self, plugin, plugin_class):
        plugin.config_manager.game_config["boss"]["enabled"] = False
        plugin.db.connect = AsyncMock()
        plugin.db.ensure_connection = AsyncMock()
        plugin.db.close = AsyncMock()

        _main_mod = sys.modules["astrbot_plugin_monixiuxian2_2.main_test"]
        original_migration = _main_mod.MigrationManager
        _main_mod.MigrationManager = MagicMock(
            return_value=MagicMock(migrate=AsyncMock())
        )

        import asyncio
        from unittest.mock import patch

        def _consume_coro(coro):
            """Close the coroutine without scheduling it to silence GC warnings."""
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        try:
            with patch.object(asyncio, "create_task", side_effect=_consume_coro):
                await plugin.initialize()
        finally:
            _main_mod.MigrationManager = original_migration

        assert plugin.boss_task is None
