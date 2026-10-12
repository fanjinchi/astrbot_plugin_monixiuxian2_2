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
- 3.3 cmd_help contains the time-skip usage line and the generated coverage
  domain line, pinned to the same EXPECTED_LABELS anchor as 3.1/3.2.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.helpers import load_module, load_package_module

_mod = load_module("time_skip_registry", "core/time_skip_registry.py")
TimeSkipRegistry = _mod.TimeSkipRegistry
PROVIDER_MODULES = _mod._PROVIDER_MODULES

# 插件根目录，静态扫描基于它定位 core/managers/handlers 源码
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# 注册表条目 label 锚点（14 条，顺序 = provider 列表序块连续聚合）。
# 3.1 行序 / 3.2 FIELD_TO_LABEL / 3.3 覆盖域行三处共用，避免未来加域时三处漂移。
EXPECTED_LABELS: tuple[str, ...] = (
    "历练/秘境/宗门任务计划完成时间",  # 1 user_cd (busy_state)
    "闭关开始时间",  # 2 players (cultivation_manager)
    "决斗/切磋冷却",  # 3 combat_cooldowns
    "双修冷却",  # 4 dual_cultivation
    "进行中悬赏过期时间",  # 5 bounty_tasks (bounty_manager)
    "悬赏放弃冷却",  # 6 bounty_abandon (bounty_manager)
    "贷款到期时间",  # 7 bank_loans (bank_manager)
    "Boss/灵眼下次刷新时间",  # 8 boss (boss_manager)
    "世界Boss实例到期时间",  # 9 world_boss_instances (boss_manager)
    "世界Boss下次再生时间",  # 10 world_boss_instances (boss_manager)
    "Boss/灵眼下次刷新时间",  # 11 spirit_eye (spirit_eye_manager)
    "传承挑战冷却",  # 12 impart_pk
    "传承被夺保护期",  # 13 impart_snatch
    "历练路线疲劳到期时间",  # 14 adventure_fatigue (adventure_manager)
)

# 覆盖域行 = label 去重（14 条目仅 Boss/灵眼同 label 合并 → 13 项；
# 明细 13 行 = 覆盖域 13 项，见 design.md D4 隐性耦合注记）
EXPECTED_COVERED = "、".join(dict.fromkeys(EXPECTED_LABELS))

# field → label 映射（field 契约面 → label 实现面搭桥，抄自
# openspec/specs/gm-commands/spec.md 「GM 时间快进」覆盖枚举 +
# Trellis child P design §5 新增两个 PVE 冷却域；
# 域数 = 13，行数 = 14（Boss/灵眼同域拆条共享 label））。
# 行序与 EXPECTED_LABELS 一致，由 test_registry_labels_match_spec_field_mapping
# 钉住（field 键的先后即注册表行序，防映射锚点与装配锚点漂移）。
FIELD_TO_LABEL: dict[str, str] = {
    "user_cd.scheduled_time": EXPECTED_LABELS[0],
    "players.cultivation_start_time": EXPECTED_LABELS[1],
    "combat_cooldowns.last_duel_time/last_spar_time": EXPECTED_LABELS[2],
    "dual_cultivation.last_dual_time": EXPECTED_LABELS[3],
    "bounty_tasks.expire_time": EXPECTED_LABELS[4],
    "system_config.bounty_abandon_cd_<user_id>": EXPECTED_LABELS[5],
    "bank_loans.due_at": EXPECTED_LABELS[6],
    "system_config.boss_next_spawn_time": EXPECTED_LABELS[7],
    "world_boss_instances.expires_at": EXPECTED_LABELS[8],
    "world_boss_instances.next_spawn_at": EXPECTED_LABELS[9],
    "system_config.spirit_eye_next_spawn_time": EXPECTED_LABELS[10],
    "impart_pk_cooldown.failed_at": EXPECTED_LABELS[11],
    "impart_snatch_protection.snatched_at": EXPECTED_LABELS[12],
    "adventure_fatigue.fatigue_until": EXPECTED_LABELS[13],
}

# 扫描目录 = 全部可能落声明的位置（core/managers/handlers）；合法属主 =
# 仅 core/managers（tasks 1.2 禁止 handlers 作属主），handlers 命中即分层违例被抓。
_SCAN_DIRS = ("core", "managers", "handlers")


def _registry() -> "TimeSkipRegistry":
    """Aggregate the real registry (same path GMManager.__init__ uses)."""
    return TimeSkipRegistry.from_providers()


class TestRegistryAssembly:
    """3.1 装配：provider 汇总顺序与结构锚点（不内联 SQL 文本）。"""

    def test_entry_count_and_structure(self):
        reg = _registry()
        entries = reg.entries()
        # 拆条后 14 条（Boss/灵眼双键拆为两条单键；child P 新增世界Boss 2 条
        # 与历练疲劳 1 条）
        assert len(entries) == 14
        # 全部是 (label, SQL) 二元组且 SQL 非空
        for label, sql in entries:
            assert isinstance(label, str) and label
            assert isinstance(sql, str) and sql.startswith("UPDATE ")

    def test_order_is_provider_block_aggregation(self):
        # 域序 = provider 列表序的块连续聚合（design Risks 决策）：
        # 悬赏两条相邻且先于 bank（6↔7 与现状互换），Boss/灵眼同 label 相邻、boss 在前
        labels = [label for label, _ in _registry().entries()]
        assert labels == list(EXPECTED_LABELS)

    def test_label_set_is_exact_thirteen_domains(self):
        # label 集合 = 13 个域标签（Boss/灵眼同 label 去重）
        labels = {label for label, _ in _registry().entries()}
        assert labels == set(EXPECTED_LABELS)
        assert len(labels) == 13

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
            "managers.adventure_manager",
        )


class TestCoverageContract:
    """3.2 契约钉住：spec 枚举与注册表、注册与声明的一致性。"""

    def test_registry_labels_match_spec_field_mapping(self):
        # 每条注册条目按序对应映射中的 label（field 契约面 → label 实现面搭桥）
        reg_labels = [label for label, _ in _registry().entries()]
        mapped_labels = list(FIELD_TO_LABEL.values())
        # 映射锚点与装配锚点必须同源：FIELD_TO_LABEL 整体等于 EXPECTED_LABELS，
        # 防 field 键重排/增删时只改一处导致的隐性漂移
        assert mapped_labels == list(EXPECTED_LABELS)
        # 行数一致（11），且逐行 label 一致 —— 漏域/错配即 fail fast
        assert reg_labels == mapped_labels
        # label 集合恰好是映射值集（防止多余 label 悄悄混入）
        assert set(reg_labels) == set(mapped_labels)

    def test_every_declared_constant_is_registered(self):
        """静态扫描：含 TIME_SKIP_ENTRIES 声明的模块必须 ∈ provider 列表。

        抓「声明了但漏登记 provider」——登记是声明自动被覆盖的前提。扫描
        core/managers/handlers 三个目录：handlers/ 在扫描范围内正是为了抓
        「常量误落 handlers/」的分层违例（tasks 1.2 禁止 handlers 作属主，
        handler 只做命令路由）；任何目录声明了 TIME_SKIP_ENTRIES 的模块
        若未登记 provider，本测试即 fail（fail-closed，无假阳性方向）。
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
    """3.3 cmd_help：时间快进用法行 + 生成段覆盖域行（label 去重序）。"""

    @pytest.mark.asyncio
    async def test_help_usage_and_covered_line(self):
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
        # 生成段（gm_manager.py:388 附近）「覆盖域：」行 == 注册表 label 去重序。
        # 钉住整行绝对值，兜住未来实现把子域（如 Boss/灵眼拆条）并入覆盖域段的回归
        covered_line = next(
            line for line in msg.splitlines() if line.lstrip().startswith("覆盖域：")
        )
        assert covered_line.strip() == f"覆盖域：{EXPECTED_COVERED}"


class TestPluginPackageDerivation:
    """a971965 回归：`_plugin_package()` 必须按加载布局推导包前缀。

    根因：AstrBot 以 ``data.plugins.<dir>`` 命名空间包加载插件
    （astrbot star_manager），而 tests/helpers.py 把插件目录注入 sys.path
    后按裸包名导入——归档时的测试验证的是运行时根本不存在的布局，硬编码
    裸包名的 provider 导入因此漏网约一天。本用例以合成包名复现 AstrBot
    运行时布局，钉死推导逻辑，防未来再硬编码。
    """

    def test_runtime_namespace_layout_derives_prefix(self):
        # 以 AstrBot 运行时的 data.plugins.<dir> 布局加载（合成包名，
        # 模块无相对导入、加载无副作用）
        mod = load_package_module(
            "core/time_skip_registry.py",
            "data.plugins.astrbot_plugin_monixiuxian2_2.core.time_skip_registry",
        )
        assert mod.__package__ == "data.plugins.astrbot_plugin_monixiuxian2_2.core"
        assert mod._plugin_package() == "data.plugins.astrbot_plugin_monixiuxian2_2"

    def test_bare_layout_falls_back_to_constant(self):
        # 本文件顶部 load_module 加载的模块 __package__ 为空 → 常量兜底，
        # 行为与修复前一致（standalone 脚本/显式路径加载场景）
        assert _mod.__package__ == ""
        assert _mod._plugin_package() == _mod._PLUGIN_PACKAGE
        assert _mod._PLUGIN_PACKAGE == "astrbot_plugin_monixiuxian2_2"
