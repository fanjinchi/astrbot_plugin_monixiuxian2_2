"""Tests for 探索秘境 subcommand wiring (add-rift-encounters task group 3).

Covers:
- rift_handlers.handle_rift_explore dispatch: numeric enter / 破阵 with and
  without answer / 传承 / unknown keyword / empty action;
- main.py handle_rift_explore 迎战 branch: direct accept_beast_challenge call
  and pve_won consumption into the sect master progress chain (design D5),
  including the failure-tolerant try/except and the pve maintenance gate;
- delegation of all non-迎战 subcommands to rift_handlers.
"""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_package_module

_rift_handlers_mod = load_package_module(
    "handlers/rift_handlers.py",
    "astrbot_plugin_monixiuxian2_2.handlers.rift_handlers",
)
RiftHandlers = _rift_handlers_mod.RiftHandlers

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


class _Result(str):
    """str subclass exposing .text: dispatch assertions compare plain strings
    (``outputs == [...]``) while main.py-layer assertions read ``.text``."""

    @property
    def text(self):
        return self


class FakeEvent:
    """Minimal event stand-in for plugin tests (test_feature_switches pattern)."""

    def __init__(self, text="", sender_id="u1"):
        self._text = text
        self._sender_id = sender_id

    def get_sender_id(self):
        return self._sender_id

    def get_group_id(self):
        return None

    def get_message_str(self):
        return self._text

    def plain_result(self, text):
        return _Result(text)


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


# ===== rift_handlers 子命令分发 =====


def _make_handler():
    """RiftHandlers with a mocked manager; db is unused by the dispatch."""
    handler = RiftHandlers.__new__(RiftHandlers)
    handler.db = MagicMock()
    handler.rift_mgr = MagicMock()
    return handler


@pytest.mark.asyncio
async def test_dispatch_numeric_enters_rift():
    """纯数字 action → 走进秘境逻辑（向后兼容旧行为）。"""
    handler = _make_handler()
    handler.rift_mgr.enter_rift = AsyncMock(return_value=(True, "已进入秘境"))

    event = FakeEvent("探索秘境 3")
    outputs = [item async for item in handler.handle_rift_explore(event, "3", "")]

    handler.rift_mgr.enter_rift.assert_awaited_once_with("u1", 3)
    assert outputs == ["已进入秘境"]


@pytest.mark.asyncio
async def test_dispatch_puzzle_with_answer_calls_answer_puzzle():
    handler = _make_handler()
    handler.rift_mgr.answer_puzzle = AsyncMock(return_value=(True, "破阵成功"))

    event = FakeEvent("探索秘境 破阵 土")
    outputs = [item async for item in handler.handle_rift_explore(event, "破阵", "土")]

    handler.rift_mgr.answer_puzzle.assert_awaited_once_with("u1", "土")
    assert outputs == ["破阵成功"]


@pytest.mark.asyncio
async def test_dispatch_puzzle_without_answer_shows_usage_no_attempt_spent():
    """破阵未携带答案 → 用法提示，不调 answer_puzzle、不耗尝试次数（spec）。"""
    handler = _make_handler()
    handler.rift_mgr.answer_puzzle = AsyncMock()

    event = FakeEvent("探索秘境 破阵")
    outputs = [item async for item in handler.handle_rift_explore(event, "破阵", "")]

    handler.rift_mgr.answer_puzzle.assert_not_called()
    assert len(outputs) == 1
    assert "用法" in outputs[0] and "破阵 <答案>" in outputs[0]


@pytest.mark.asyncio
async def test_dispatch_legacy_calls_accept_legacy_challenge():
    handler = _make_handler()
    handler.rift_mgr.accept_legacy_challenge = AsyncMock(
        return_value=(True, "传承战报")
    )

    event = FakeEvent("探索秘境 传承")
    outputs = [item async for item in handler.handle_rift_explore(event, "传承", "")]

    handler.rift_mgr.accept_legacy_challenge.assert_awaited_once_with("u1")
    assert outputs == ["传承战报"]


@pytest.mark.asyncio
async def test_dispatch_unknown_keyword_shows_usage():
    handler = _make_handler()

    event = FakeEvent("探索秘境 闲逛")
    outputs = [item async for item in handler.handle_rift_explore(event, "闲逛", "")]

    handler.rift_mgr.enter_rift.assert_not_called()
    handler.rift_mgr.answer_puzzle.assert_not_called()
    handler.rift_mgr.accept_legacy_challenge.assert_not_called()
    assert len(outputs) == 1
    assert "用法" in outputs[0]


@pytest.mark.asyncio
async def test_dispatch_empty_action_shows_usage():
    handler = _make_handler()

    event = FakeEvent("探索秘境")
    outputs = [item async for item in handler.handle_rift_explore(event, "", "")]

    handler.rift_mgr.enter_rift.assert_not_called()
    assert len(outputs) == 1
    assert "用法" in outputs[0]


@pytest.mark.asyncio
async def test_dispatch_yingzhan_not_handled_here():
    """迎战不经 rift_handlers 分发（main.py 拦截直调 manager，design D5）；
    若意外到达此处，只回用法提示，不触发任何 manager 调用。"""
    handler = _make_handler()

    event = FakeEvent("探索秘境 迎战")
    outputs = [item async for item in handler.handle_rift_explore(event, "迎战", "")]

    handler.rift_mgr.accept_beast_challenge.assert_not_called()
    assert len(outputs) == 1
    assert "用法" in outputs[0] and "迎战" in outputs[0]


# ===== main.py 迎战分支与 pve_won 消费 =====


@pytest.fixture(scope="module")
def plugin_class():
    """Load XiuXianPlugin with mocked sub-packages and restore them after tests.

    Mirrors tests/test_feature_switches.py: the command filter decorator is
    replaced by a no-op so the real handler methods stay intact.
    """
    parent_name = "astrbot_plugin_monixiuxian2_2"
    if parent_name not in sys.modules:
        pkg = types.ModuleType(parent_name)
        pkg.__path__ = [str(PLUGIN_ROOT)]
        sys.modules[parent_name] = pkg

    submodule_keys = [
        "astrbot_plugin_monixiuxian2_2.handlers",
        "astrbot_plugin_monixiuxian2_2.managers",
        "astrbot_plugin_monixiuxian2_2.core",
    ]
    original_submodules = {key: sys.modules.get(key) for key in submodule_keys}
    for key in submodule_keys:
        sys.modules[key] = MagicMock()

    event_mod = sys.modules.setdefault("astrbot.api.event", MagicMock())
    original_filter_command = getattr(event_mod.filter, "command", None)
    event_mod.filter.command = _noop_command

    star_mod = sys.modules.setdefault("astrbot.api.star", MagicMock())
    original_star = getattr(star_mod, "Star", None)
    star_mod.Star = _StarBase

    command_mod = sys.modules.setdefault(
        "astrbot.core.star.filter.command", MagicMock()
    )
    original_greedy = getattr(command_mod, "GreedyStr", None)
    command_mod.GreedyStr = str

    _main_mod = load_package_module(
        "main.py", "astrbot_plugin_monixiuxian2_2.main_rift_cmd_test"
    )
    cls = _main_mod.XiuXianPlugin

    yield cls

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


class TestRiftExploreBeastBranch:
    """迎战子命令在 main.py 层直调 manager 并消费 pve_won（design D5）。"""

    @pytest.mark.asyncio
    async def test_win_advances_master_progress(self, plugin):
        plugin.rift_mgr.accept_beast_challenge = AsyncMock(
            return_value=(True, "战报：胜利", {"pve_won": True})
        )
        plugin.sect_mgr.advance_master_progress = AsyncMock(
            return_value="\n🏅 师承任务进度+1"
        )

        event = FakeEvent("探索秘境 迎战")
        results = [
            r async for r in plugin.handle_rift_explore(event, "迎战", "")
        ]

        assert len(results) == 1
        assert "战报：胜利" in results[0].text
        assert "师承任务进度+1" in results[0].text
        plugin.rift_mgr.accept_beast_challenge.assert_awaited_once_with("u1")
        plugin.sect_mgr.advance_master_progress.assert_awaited_once_with(
            "u1", "win_pve"
        )
        # 迎战不经过 rift_handlers 的 yield 字符串分发
        plugin.rift_handlers.handle_rift_explore.assert_not_called()

    @pytest.mark.asyncio
    async def test_loss_does_not_advance_master_progress(self, plugin):
        plugin.rift_mgr.accept_beast_challenge = AsyncMock(
            return_value=(True, "战报：战败", {"pve_won": False})
        )
        plugin.sect_mgr.advance_master_progress = AsyncMock()

        event = FakeEvent("探索秘境 迎战")
        results = [
            r async for r in plugin.handle_rift_explore(event, "迎战", "")
        ]

        assert len(results) == 1
        assert "战报：战败" in results[0].text
        plugin.sect_mgr.advance_master_progress.assert_not_called()

    @pytest.mark.asyncio
    async def test_master_progress_failure_does_not_break_reply(self, plugin):
        """师承推进异常被吞掉，迎战主反馈照常输出（handle_rift_complete 模式）。"""
        plugin.rift_mgr.accept_beast_challenge = AsyncMock(
            return_value=(True, "战报：胜利", {"pve_won": True})
        )
        plugin.sect_mgr.advance_master_progress = AsyncMock(
            side_effect=RuntimeError("宗门系统异常")
        )

        event = FakeEvent("探索秘境 迎战")
        results = [
            r async for r in plugin.handle_rift_explore(event, "迎战", "")
        ]

        assert len(results) == 1
        assert results[0].text == "战报：胜利"

    @pytest.mark.asyncio
    async def test_no_pending_hint_passes_through(self, plugin):
        """无 pending 遭遇时的提示原样输出，且不推进师承计数。"""
        plugin.rift_mgr.accept_beast_challenge = AsyncMock(
            return_value=(False, "机缘已消散", {"pve_won": False})
        )
        plugin.sect_mgr.advance_master_progress = AsyncMock()

        event = FakeEvent("探索秘境 迎战")
        results = [
            r async for r in plugin.handle_rift_explore(event, "迎战", "")
        ]

        assert len(results) == 1
        assert "机缘已消散" in results[0].text
        plugin.sect_mgr.advance_master_progress.assert_not_called()

    @pytest.mark.asyncio
    async def test_yingzhan_gated_when_pve_disabled(self, plugin):
        plugin.config_manager.game_config["pve"]["enabled"] = False
        plugin.rift_mgr.accept_beast_challenge = AsyncMock()

        event = FakeEvent("探索秘境 迎战")
        results = [
            r async for r in plugin.handle_rift_explore(event, "迎战", "")
        ]

        assert len(results) == 1
        assert "维护" in results[0].text
        plugin.rift_mgr.accept_beast_challenge.assert_not_called()


class TestRiftExploreDelegation:
    """非迎战子命令委托 rift_handlers.handle_rift_explore(event, action, value)。"""

    @pytest.mark.asyncio
    async def test_numeric_delegates_with_action_and_value(self, plugin):
        plugin.rift_handlers.handle_rift_explore = MagicMock(
            return_value=_async_iter([FakeEvent().plain_result("已进入秘境")])
        )

        event = FakeEvent("探索秘境 3")
        results = [
            r async for r in plugin.handle_rift_explore(event, "3", "")
        ]

        assert len(results) == 1
        assert results[0].text == "已进入秘境"
        plugin.rift_handlers.handle_rift_explore.assert_called_once()
        call_args = plugin.rift_handlers.handle_rift_explore.call_args.args
        assert call_args[0] is event
        assert call_args[1] == "3"
        assert call_args[2] == ""
        plugin.rift_mgr.accept_beast_challenge.assert_not_called()

    @pytest.mark.asyncio
    async def test_puzzle_delegates_with_answer(self, plugin):
        plugin.rift_handlers.handle_rift_explore = MagicMock(
            return_value=_async_iter([FakeEvent().plain_result("破阵结果")])
        )

        event = FakeEvent("探索秘境 破阵 土")
        results = [
            r async for r in plugin.handle_rift_explore(event, "破阵", "土")
        ]

        assert len(results) == 1
        call_args = plugin.rift_handlers.handle_rift_explore.call_args.args
        assert call_args[1] == "破阵"
        assert call_args[2] == "土"

    @pytest.mark.asyncio
    async def test_empty_action_delegates_to_handler(self, plugin):
        """空参数委托 handler 出用法提示；main.py 层不拦截。"""
        plugin.rift_handlers.handle_rift_explore = MagicMock(
            return_value=_async_iter([FakeEvent().plain_result("用法提示")])
        )

        event = FakeEvent("探索秘境")
        results = [r async for r in plugin.handle_rift_explore(event, "", "")]

        assert len(results) == 1
        assert results[0].text == "用法提示"
        plugin.rift_handlers.handle_rift_explore.assert_called_once()
