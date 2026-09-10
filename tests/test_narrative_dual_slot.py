"""Tests for the dual-slot narrative scene shape (flavor-copy-assembly).

Covers the fourth scene shape (bucketed flavor pool + single-source string
``panel``): composed rendering, panel-only degradation, route/bucket selection
inside the flavor pool, malformed-shape rejection at load-time validation, the
``select_narrative_pool`` regression lock for the adventure reuse path, and the
D6 newline ownership between the survive panel and the pity_hint line.
"""

import pytest

from tests.helpers import load_package_module

_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager
DEFAULT_NARRATIVE_CONFIG = _config_mod.DEFAULT_NARRATIVE_CONFIG
NARRATIVE_SCENE_VARS = _config_mod.NARRATIVE_SCENE_VARS

_nt_mod = load_package_module(
    "utils/narrative_text.py", "astrbot_plugin_monixiuxian2_2.utils.narrative_text"
)
render_narrative = _nt_mod.render_narrative
select_narrative_pool = _nt_mod.select_narrative_pool


@pytest.fixture
def config_manager(tmp_path):
    """ConfigManager rooted at an empty dir; narrative config is auto-created."""
    return ConfigManager(tmp_path)


@pytest.fixture
def dual_slot_scene(monkeypatch):
    """Register a demo dual-slot scene in defaults, contract, and config stub."""
    monkeypatch.setitem(
        DEFAULT_NARRATIVE_CONFIG, "_test", {"panel_scene": "默认面板{name}"}
    )
    monkeypatch.setitem(
        NARRATIVE_SCENE_VARS, "_test", {"panel_scene": {"name", "level_name"}}
    )
    value = {
        "panel": "面板：{name} 升至 {level_name}",
        "通用": ["通用引子"],
        "练气": ["练气引子", {"text": "体修练气引子", "route": "体修"}],
        "筑基": ["筑基引子"],
    }
    return value


class _StubManager:
    """Minimal stand-in exposing only a narrative_config attribute."""


def _stub_with(value):
    stub = _StubManager()
    stub.narrative_config = {"_test": {"panel_scene": value}}
    return stub


# --- 5.1 双槽渲染 -------------------------------------------------------------


def test_dual_slot_composes_flavor_and_panel(dual_slot_scene):
    out = render_narrative(
        _stub_with(dual_slot_scene), "_test", "panel_scene", {"name": "张三", "level_name": "筑基"}
    )
    assert out.endswith("\n面板：张三 升至 筑基")
    assert out.split("\n")[0] in ("通用引子", "练气引子")


def test_dual_slot_empty_flavor_pool_renders_panel_only(dual_slot_scene):
    """Empty flavor pool (or route-filtered empty) must NOT fall back to the
    embedded default pool — the panel is the authoritative carrier."""
    value = {"panel": "面板：{name}"}  # 无任何分桶
    out = render_narrative(_stub_with(value), "_test", "panel_scene", {"name": "张三"})
    assert out == "面板：张三"
    # route 过滤清空 flavor 池：同样只出 panel，不冒默认文案
    filtered = {"panel": "面板：{name}", "通用": [{"text": "灵修专属", "route": "灵修"}]}
    out = render_narrative(
        _stub_with(filtered), "_test", "panel_scene", {"name": "张三"}, route="体修"
    )
    assert out == "面板：张三"


def test_dual_slot_bucket_and_route_selection(dual_slot_scene):
    # Lv5 体修：通用 + 练气桶合并，体修标注条目参与
    pool_seen = set()
    for _ in range(50):
        out = render_narrative(
            _stub_with(dual_slot_scene),
            "_test",
            "panel_scene",
            {"name": "张三", "level_name": "练气"},
            route="体修",
            level_index=5,
        )
        pool_seen.add(out.split("\n")[0])
    assert pool_seen <= {"通用引子", "练气引子", "体修练气引子"}
    assert "筑基引子" not in pool_seen
    # Lv5 灵修：体修标注条目被过滤
    pool_seen.clear()
    for _ in range(50):
        out = render_narrative(
            _stub_with(dual_slot_scene),
            "_test",
            "panel_scene",
            {"name": "张三", "level_name": "练气"},
            route="灵修",
            level_index=5,
        )
        pool_seen.add(out.split("\n")[0])
    assert "体修练气引子" not in pool_seen
    # Lv12（筑基段）：练气桶不再参与
    pool_seen.clear()
    for _ in range(50):
        out = render_narrative(
            _stub_with(dual_slot_scene),
            "_test",
            "panel_scene",
            {"name": "张三", "level_name": "筑基"},
            route="体修",
            level_index=12,
        )
        pool_seen.add(out.split("\n")[0])
    assert pool_seen <= {"通用引子", "筑基引子"}


def test_dual_slot_flavor_may_reference_declared_vars():
    value = {"panel": "面板", "通用": ["冲击{level_name}的引子"]}
    out = render_narrative(
        _stub_with(value), "_test", "panel_scene", {"name": "张三", "level_name": "金丹"}
    )
    assert out == "冲击金丹的引子\n面板"


def test_dual_slot_flavor_render_failure_skips_flavor():
    """A flavor entry failing at render time is skipped; panel still renders."""
    value = {"panel": "面板{name}", "通用": ["坏引子{unknown}"]}
    out = render_narrative(
        _stub_with(value), "_test", "panel_scene", {"name": "张三", "level_name": "筑基"}
    )
    assert out == "面板张三"


def test_dual_slot_panel_render_failure_degrades_to_raw():
    value = {"panel": "面板{name}{oops}", "通用": ["引子"]}
    # panel 引用未声明变量无法过加载校验；此处直接测运行时防御路径
    out = render_narrative(
        _stub_with(value), "_test", "panel_scene", {"name": "张三", "level_name": "筑基"}
    )
    assert out == "引子\n面板{name}{oops}"


def test_dict_without_panel_key_stays_bucketed_pool():
    """Bucketed dict lacking ``panel`` keeps plain bucket semantics."""
    value = {"通用": ["通1"], "练气": ["气1"]}
    out = render_narrative(_stub_with(value), "_test", "panel_scene", {"name": "张三"}, level_index=5)
    assert out in ("通1", "气1")


# --- 5.2 加载校验扩展 ---------------------------------------------------------


def test_dual_slot_valid_scene_survives_validation(config_manager, dual_slot_scene):
    config_manager.narrative_config = {"_test": {"panel_scene": dual_slot_scene}}
    config_manager._validate_narrative_config()
    assert config_manager.narrative_config["_test"]["panel_scene"] == dual_slot_scene


def test_dual_slot_panel_violation_falls_back(config_manager, dual_slot_scene):
    """panel 模板引用未声明变量 → 整场景回退默认。"""
    config_manager.narrative_config = {
        "_test": {"panel_scene": {"panel": "面板{bad_var}", "通用": ["引子"]}}
    }
    config_manager._validate_narrative_config()
    assert (
        config_manager.narrative_config["_test"]["panel_scene"] == "默认面板{name}"
    )


def test_dual_slot_flavor_violation_falls_back(config_manager, dual_slot_scene):
    """flavor 条目引用未声明变量 → 整场景回退默认。"""
    config_manager.narrative_config = {
        "_test": {
            "panel_scene": {"panel": "面板{name}", "练气": ["引子{bad_var}"]}
        }
    }
    config_manager._validate_narrative_config()
    assert (
        config_manager.narrative_config["_test"]["panel_scene"] == "默认面板{name}"
    )


def test_dual_slot_non_string_panel_falls_back(config_manager, dual_slot_scene):
    config_manager.narrative_config = {
        "_test": {"panel_scene": {"panel": ["面板{name}"], "通用": ["引子"]}}
    }
    config_manager._validate_narrative_config()
    assert (
        config_manager.narrative_config["_test"]["panel_scene"] == "默认面板{name}"
    )


def test_dual_slot_text_and_panel_dict_falls_back(config_manager, dual_slot_scene):
    """dict 同含 text 与 panel 键 = 半畸形形态，回退默认而非静默丢 panel。"""
    config_manager.narrative_config = {
        "_test": {
            "panel_scene": {
                "text": "单条{name}",
                "route": "灵修",
                "panel": "面板{name}",
            }
        }
    }
    config_manager._validate_narrative_config()
    assert (
        config_manager.narrative_config["_test"]["panel_scene"] == "默认面板{name}"
    )


# --- 5.3 select_narrative_pool 回归（保护 adventure desc_variants 复用路径） ---


def test_select_pool_ignores_panel_key():
    """Dual-slot dicts passed straight to select_narrative_pool keep old
    behavior: unknown keys (including panel) are simply not pool buckets."""
    value = {"panel": "面板{name}", "通用": ["通1"], "练气": ["气1"]}
    assert select_narrative_pool(value, level_index=5) == ["通1", "气1"]
    assert select_narrative_pool(value) == ["通1"]


# --- 5.4 D6 换行归属（survive 面板 × pity_hint） -------------------------------


def _bare_manager():
    """No narrative_config attribute → embedded defaults are used."""

    class Bare:
        pass

    return Bare()


def test_pity_hint_default_has_no_leading_newline():
    out = render_narrative(
        _bare_manager(),
        "breakthrough",
        "pity_hint",
        {"streak": 3, "next_bonus": 0.15, "remaining": 16},
    )
    assert not out.startswith("\n")
    assert "连败 3 次" in out
    assert "+15%" in out  # {next_bonus:.0%} 格式符仍生效


def test_survive_default_owns_pity_newline():
    pity = render_narrative(
        _bare_manager(),
        "breakthrough",
        "pity_hint",
        {"streak": 3, "next_bonus": 0.15, "remaining": 16},
    )
    out = render_narrative(
        _bare_manager(),
        "breakthrough",
        "survive",
        {
            "rate_info": "成功率 50%",
            "next_level_name": "筑基",
            "exp_penalty": 100,
            "experience": 12345,
            "pity_msg": pity,
        },
    )
    # 面板自带恰好一个换行衔接 pity 行
    assert f"当前修为：12345\n{pity}" in out
    assert "当前修为：12345\n\n" not in out


def test_survive_degraded_combo_is_bounded():
    """降级格（新 panel + 旧式带前导换行的 pity_msg）：至多双换行，不粘连。"""
    out = render_narrative(
        _bare_manager(),
        "breakthrough",
        "survive",
        {
            "rate_info": "成功率 50%",
            "next_level_name": "筑基",
            "exp_penalty": 100,
            "experience": 12345,
            "pity_msg": "\n连败 3 次",  # 旧式 pity_hint 形态（前导 \n）
        },
    )
    assert "当前修为：12345\n\n连败 3 次" in out


# --- 5.5 端到端冒烟：真实场景 key + 突破后段位桶 ---------------------------------


def test_breakthrough_success_dual_slot_smoke(config_manager):
    """success 渲染发生在 level_index +1 之后：Lv9→10 破境出筑基段 flavor。"""
    config_manager.narrative_config = {
        "breakthrough": {
            "success": {
                "panel": "突破至【{next_level_name}】，气血+{hp_growth}",
                "练气": [{"text": "练气段庆功", "route": "体修"}],
                "筑基": [{"text": "筑基段庆功", "route": "体修"}],
            }
        }
    }
    config_manager._validate_narrative_config()
    out = render_narrative(
        config_manager,
        "breakthrough",
        "success",
        {"next_level_name": "筑基", "hp_growth": 42},
        route="体修",
        level_index=10,  # 突破后境界
    )
    assert out == "筑基段庆功\n突破至【筑基】，气血+42"


def test_breakthrough_success_dual_slot_post_season_levels(config_manager):
    """Lv40+（season-1 幕表外）：flavor 池恒空，只出 panel。"""
    config_manager.narrative_config = {
        "breakthrough": {
            "success": {
                "panel": "突破至【{next_level_name}】",
                "练气": ["练气段庆功"],
            }
        }
    }
    config_manager._validate_narrative_config()
    out = render_narrative(
        config_manager,
        "breakthrough",
        "success",
        {"next_level_name": "化神"},
        route="体修",
        level_index=40,
    )
    assert out == "突破至【化神】"
