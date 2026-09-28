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

from tests.helpers import load_module

_mod = load_module("time_skip_registry", "core/time_skip_registry.py")
TimeSkipRegistry = _mod.TimeSkipRegistry
PROVIDER_MODULES = _mod._PROVIDER_MODULES

# 插件根目录，静态扫描基于它定位 core/managers/handlers 源码
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# 注册表条目 label 锚点（11 条，顺序 = provider 列表序块连续聚合）。
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
    "Boss/灵眼下次刷新时间",  # 9 spirit_eye (spirit_eye_manager)
    "传承挑战冷却",  # 10 impart_pk
    "传承被夺保护期",  # 11 impart_snatch
)

# 覆盖域行 = label 去重（Boss/灵眼同 label 合并为一域 → 9 项；
# 明细 10 行 vs 覆盖域 9 项为设计使然，见 design.md D4 隐性耦合注记）
EXPECTED_COVERED = "、".join(dict.fromkeys(EXPECTED_LABELS))

# field → label 映射（field 契约面 → label 实现面搭桥，抄自
# openspec/specs/gm-commands/spec.md 「GM 时间快进」覆盖枚举；
# 域数 = 10，行数 = 11（Boss/灵眼同域拆条共享 label））。
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
    "system_config.spirit_eye_next_spawn_time": EXPECTED_LABELS[8],
    "impart_pk_cooldown.failed_at": EXPECTED_LABELS[9],
    "impart_snatch_protection.snatched_at": EXPECTED_LABELS[10],
}

# data/migration.py 等不参与本域；仅 core/managers/handlers 是容忍的属主位置
# （design D3）。
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
        assert labels == list(EXPECTED_LABELS)

    def test_label_set_is_exact_ten_domains(self):
        # label 集合 = 10 个域标签（Boss/灵眼同 label 去重）
        labels = {label for label, _ in _registry().entries()}
        assert labels == set(EXPECTED_LABELS)
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
        # 映射锚点与装配锚点必须同源：FIELD_TO_LABEL 整体等于 EXPECTED_LABELS，
        # 防 field 键重排/增删时只改一处导致的隐性漂移
        assert mapped_labels == list(EXPECTED_LABELS)
        # 行数一致（11），且逐行 label 一致 —— 漏域/错配即 fail fast
        assert reg_labels == mapped_labels
        # label 集合恰好是映射值集（防止多余 label 悄悄混入）
        assert set(reg_labels) == set(mapped_labels)

    def test_every_declared_constant_is_registered(self):
        """静态扫描：含 TIME_SKIP_ENTRIES 声明的模块必须 ∈ provider 列表。

        抓「声明了但漏登记 provider」——声明后登记是自动被覆盖的前提。
        扫描范围限定 core/managers/handlers：handlers/ 不参与扫描，因为处理器
        只做命令路由、架构上不得声明玩法条目（design D3 属主模块=业务 manager/core）；
        若未来有人在 handlers 里误写声明，未登记即不被覆盖、但也不会漏检——
        反向扫描只对 provider 列表内模块检查声明存在，对 provider 之外的文件
        fail-closed（不产生假阳性），代价是该误写不会被正向抓出，靠 review 兜底。
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
