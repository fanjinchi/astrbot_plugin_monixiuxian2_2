"""Tests for the GM time-skip coverage registry (openspec change:
gm-time-skip-registry).

Covers:
- 3.1 registry assembly: provider order, entry count, label set (no second
  copy of SQL text — migration correctness is guarded by
  tests/test_gm_manager.py::TestTimeSkip behavior tests).
- 3.2 contract pins: a field→label mapping transcribed from the spec's
  enumeration (field = spec contract surface, label = registry display text),
  plus a static scan making sure every module declaring TIME_SKIP_ENTRIES is
  registered in the provider list.
- 3.3 cmd_help contains the time-skip usage line and every domain label.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.helpers import load_module

_mod = load_module("time_skip_registry", "core/time_skip_registry.py")
TimeSkipRegistry = _mod.TimeSkipRegistry
PROVIDER_MODULES = _mod._PROVIDER_MODULES

# 插件根目录，静态扫描基于它定位 core/managers/handlers 源码
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# field → label 映射（10 域 11 行，抄自 openspec/specs/gm-commands/spec.md
# 「GM 时间快进」覆盖枚举；Boss/灵眼同域拆条共享 label）。
# 域数 = 10（label 集合），行数 = 11（拆条后的注册表条目数）。
FIELD_TO_LABEL: dict[str, str] = {
    "user_cd.scheduled_time": "历练/秘境/宗门任务计划完成时间",
    "players.cultivation_start_time": "闭关开始时间",
    "combat_cooldowns.last_duel_time/last_spar_time": "决斗/切磋冷却",
    "dual_cultivation.last_dual_time": "双修冷却",
    "bounty_tasks.expire_time": "进行中悬赏过期时间",
    "system_config.bounty_abandon_cd_<user_id>": "悬赏放弃冷却",
    "bank_loans.due_at": "贷款到期时间",
    "system_config.boss_next_spawn_time": "Boss/灵眼下次刷新时间",
    "system_config.spirit_eye_next_spawn_time": "Boss/灵眼下次刷新时间",
    "impart_pk_cooldown.failed_at": "传承挑战冷却",
    "impart_snatch_protection.snatched_at": "传承被夺保护期",
}

# data/migration.py 中 _initialize_plugins 等不参与本域；仅 core/managers/handlers
# 是容忍的属主位置（design D3）。
_SCAN_DIRS = ("core", "managers", "handlers")


def _registry() -> "TimeSkipRegistry":
    """Aggregate the real registry (same path GMManager.__init__ uses)."""
    return TimeSkipRegistry.from_providers()


class TestRegistryAssembly:
    """3.1 装配：provider 汇总顺序与结构锚点（不内联 SQL 文本）。"""

    def test_entry_count_and_structure(self):
        reg = _registry()
        entries = reg.entries()
        # 拆条后 11 条（Boss/灵眼双键拆为两条单键）
        assert len(entries) == 11
        # 全部是 (label, SQL) 二元组且 SQL 非空
        for label, sql in entries:
            assert isinstance(label, str) and label
            assert isinstance(sql, str) and sql.startswith("UPDATE ")

    def test_order_is_provider_block_aggregation(self):
        # 域序 = provider 列表序的块连续聚合（design Risks 决策）：
        # 悬赏两条相邻且先于 bank（6↔7 与现状互换），Boss/灵眼同 label 相邻、boss 在前
        labels = [label for label, _ in _registry().entries()]
        assert labels == [
            "历练/秘境/宗门任务计划完成时间",  # 1 user_cd (busy_state)
            "闭关开始时间",  # 2 players (cultivation_manager)
            "决斗/切磋冷却",  # 3 combat_cooldowns
            "双修冷却",  # 4 dual_cultivation
            "进行中悬赏过期时间",  # 5 bounty_tasks (bounty_manager)
            "悬赏放弃冷却",  # 6 bounty_abandon (bounty_manager)
            "贷款到期时间",  # 7 bank_loans (bank_manager)
            "Boss/灵眼下次刷新时间",  # 8 boss (boss_manager)
            "Boss/灵眼下次刷新时间",  # 9 spirit_eye (spirit_eye_manager)
            "传承挑战冷却",  # 10 impart_pk
            "传承被夺保护期",  # 11 impart_snatch
        ]

    def test_label_set_is_exact_ten_domains(self):
        # label 集合 = 10 个域标签（Boss/灵眼同 label 去重）
        labels = {label for label, _ in _registry().entries()}
        assert len(labels) == 10

    def test_provider_registration_is_immutable_list(self):
        # provider 列表是登记点，顺序即块序；必须为元组防误改
        assert isinstance(PROVIDER_MODULES, tuple)
        assert PROVIDER_MODULES == (
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


class TestCoverageContract:
    """3.2 契约钉住：spec 枚举与注册表、注册与声明的一致性。"""

    def test_registry_labels_match_spec_field_mapping(self):
        # 每条注册条目按序对应映射中的 label（field 契约面 → label 实现面搭桥）
        reg_labels = [label for label, _ in _registry().entries()]
        mapped_labels = list(FIELD_TO_LABEL.values())
        # 行数一致（11），且逐行 label 一致 —— 漏域/错配即 fail fast
        assert reg_labels == mapped_labels
        # label 集合恰好是映射值集（防止多余 label 悄悄混入）
        assert set(reg_labels) == set(mapped_labels)

    def test_every_declared_constant_is_registered(self):
        """静态扫描：含 TIME_SKIP_ENTRIES 声明的模块必须 ∈ provider 列表。

        抓「声明了但漏登记 provider」——声明后登记是自动被覆盖的前提。
        """
        declared = []
        for dirname in _SCAN_DIRS:
            for path in sorted((_PLUGIN_ROOT / dirname).glob("*.py")):
                text = path.read_text(encoding="utf-8")
                if re.search(r"^\s*TIME_SKIP_ENTRIES\s*:\s*tuple", text, re.M):
                    declared.append(f"{dirname}/{path.stem}")

        registered = {m.replace(".", "/") for m in PROVIDER_MODULES}
        unregistered = [d for d in declared if d not in registered]
        assert unregistered == [], (
            f"声明了 TIME_SKIP_ENTRIES 但未登记进 _PROVIDER_MODULES: {unregistered}"
        )
        # 反向：provider 列表里的模块应确实存在声明（防登记了但常量被误删）
        for dotted in PROVIDER_MODULES:
            rel = dotted.replace(".", "/") + ".py"
            assert (_PLUGIN_ROOT / rel).exists() and re.search(
                r"^\s*TIME_SKIP_ENTRIES\s*:\s*tuple",
                (_PLUGIN_ROOT / rel).read_text(encoding="utf-8"),
                re.M,
            ), f"provider {dotted} 缺少 TIME_SKIP_ENTRIES 声明"


class TestCmdHelpCoverage:
    """3.3 cmd_help：时间快进用法行 + 全部域标签（生成段来自注册表）。"""

    @pytest.mark.asyncio
    async def test_help_lists_usage_and_all_domain_labels(self):
        # 与 tests/test_gm_manager.py 相同：绕过 __init__.py 链裸名加载
        _gm_mod = load_module("gm_manager", "core/gm_manager.py")
        GMManager = _gm_mod.GMManager

        gm = GMManager(
            db=MagicMock(),
            config_manager=MagicMock(),
            storage_ring_manager=MagicMock(),
            equipment_manager=MagicMock(),
            adventure_manager=None,
            rift_manager=None,
            boss_manager=None,
            bounty_manager=None,
            plugin_data_path=MagicMock(),
            busy_state=MagicMock(),
        )
        event = MagicMock()
        event.sender_id = "gm_001"
        success, msg = await gm.cmd_help(event, "")
        assert success is True
        assert "时间快进 <秒> 确认" in msg
        for label in FIELD_TO_LABEL.values():
            assert label in msg, f"帮助缺失覆盖域标签: {label}"