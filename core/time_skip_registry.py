"""Time-skip registry: field-owner declared coverage of the GM time-skip command.

OpenSpec change: gm-time-skip-registry (design D1-D6).

The GM "时间快进" command (``GMManager.cmd_time_skip``) shifts all
expiry/cooldown timestamps forward by N seconds inside one transaction. The
coverage list used to live inside ``core/gm_manager.py`` as a hand-maintained
tuple of (label, SQL) pairs whose maintenance duty was duplicated in
AGENTS.md §2. This module inverts the ownership: every module owning
expiry-relevant timestamp fields declares a module-level ``TIME_SKIP_ENTRIES``
constant, and the registry aggregates those declarations at assembly time
("declare-and-be-covered"). A new cooling domain is covered by adding an entry
in its owner module AND registering the module name in ``_PROVIDER_MODULES``.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types

# 新增等待类冷却域 = 在字段属主模块声明 `TIME_SKIP_ENTRIES` 常量 + 把模块点号名登记进
# 本列表（AGENTS.md §2 人工义务的登记点）。列表顺序 = 时间快进回复的域明细顺序：
# 按 provider 块连续聚合（忙碌 → 闭关 → 决斗/切磋 → 双修 → 悬赏任务 → 悬赏放弃 →
# 贷款 → Boss → 灵眼 → 传承挑战 → 传承保护）。悬赏两条与 bank 跨模块交错，块连续
# 聚合后为 5,7,6（原 5,6,7 的 6↔7 单次相邻互换，设计取舍见 design Risks；
# 回复明细行序非契约，spec 无顺序保证）。Boss/灵眼按 design D2a 拆为
# 两条单键 UPDATE、共享同一域标签，展开后相邻（boss 在前）。
_PROVIDER_MODULES: tuple[str, ...] = (
    "core.busy_state",
    "core.cultivation_manager",
    "managers.combat_manager",
    "managers.dual_cultivation_manager",
    "managers.bounty_manager",
    "managers.bank_manager",
    "managers.boss_manager",
    "managers.spirit_eye_manager",
    "managers.impart_manager",
)

_PLUGIN_PACKAGE = "astrbot_plugin_monixiuxian2_2"


def _import_provider(module_name: str) -> types.ModuleType:
    """Import a provider module by its dotted name within the plugin package.

    The plugin is loaded by AstrBot under its directory name; tests may also
    register modules under that package (tests/helpers.load_package_module).
    Falling back to a file-path load keeps the registry usable when the
    package is not importable (standalone test scripts).

    Args:
        module_name: Dotted module path relative to the plugin root, e.g.
            ``"managers.combat_manager"``.

    Returns:
        The loaded module object.
    """
    dotted = f"{_PLUGIN_PACKAGE}.{module_name}"
    try:
        return importlib.import_module(dotted)
    except Exception:
        pass
    path = (
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            *module_name.split("."),
        )
        + ".py"
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


class TimeSkipRegistry:
    """Immutable (label, UPDATE SQL) coverage list aggregated from providers.

    Each provider module declares ``TIME_SKIP_ENTRIES`` as a tuple of
    (domain label, parameterized UPDATE SQL) pairs. Every ``?`` in a SQL
    statement is filled with the shift seconds in the same position order
    (see ``GMManager.cmd_time_skip``). Entries only touch timestamps that
    participate in expiry/cooldown decisions; historical records are never
    included (principle inherited from the former hand-maintained list, kept
    per entry comment).
    """

    def __init__(self, entries: tuple[tuple[str, str], ...]):
        self._entries = entries

    @classmethod
    def from_providers(
        cls, provider_modules: tuple[str, ...] = _PROVIDER_MODULES
    ) -> TimeSkipRegistry:
        """Aggregate entries from provider modules in the given order.

        Args:
            provider_modules: Dotted module names of field-owner modules.
                Defaults to ``_PROVIDER_MODULES`` (the registration list).

        Returns:
            A registry whose entry order follows the provider list order and
            each module's declaration order.
        """
        entries: list[tuple[str, str]] = []
        for module_name in provider_modules:
            entries.extend(_import_provider(module_name).TIME_SKIP_ENTRIES)
        return cls(tuple(entries))

    def entries(self) -> tuple[tuple[str, str], ...]:
        """Return all (label, SQL) entries in aggregation order."""
        return self._entries
