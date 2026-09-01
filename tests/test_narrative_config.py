"""Tests for the narrative text config carrier (externalize-narrative-texts).

Covers pool normalization (single template / flat pool / realm-segment bucketed
pool), route-tag filtering, the shared bucket-merge helper, template variable
contract validation, and the fake-config-safe render fallback.
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
extract_template_vars = _nt_mod.extract_template_vars
level_to_narrative_bucket = _nt_mod.level_to_narrative_bucket
render_narrative = _nt_mod.render_narrative
select_narrative_pool = _nt_mod.select_narrative_pool

_cult_mod = load_package_module(
    "core/cultivation_manager.py",
    "astrbot_plugin_monixiuxian2_2.core.cultivation_manager",
)
CultivationManager = _cult_mod.CultivationManager

PLUGIN_ROOT = _config_mod.Path(__file__).resolve().parent.parent


@pytest.fixture
def config_manager(tmp_path):
    """ConfigManager rooted at an empty dir; narrative config is auto-created."""
    return ConfigManager(tmp_path)


# --- 场景形态归一（select_narrative_pool） -----------------------------------


def test_select_pool_single_template():
    assert select_narrative_pool("你好{name}") == ["你好{name}"]


def test_select_pool_flat_list():
    assert select_narrative_pool(["甲", "乙"]) == ["甲", "乙"]


def test_select_pool_bucket_merges_current_segment_and_common():
    value = {"通用": ["通1"], "练气": ["气1", "气2"], "筑基": ["筑1"]}
    # Lv5 (练气段): 通用 + 练气 merged, 筑基 excluded
    assert select_narrative_pool(value, level_index=5) == ["通1", "气1", "气2"]
    # Lv12 (筑基段)
    assert select_narrative_pool(value, level_index=12) == ["通1", "筑1"]
    # Lv45 (超出 season-1 段): 通用 only
    assert select_narrative_pool(value, level_index=45) == ["通1"]
    # 未知等级同样只用通用桶
    assert select_narrative_pool(value, level_index=None) == ["通1"]


def test_select_pool_ignores_unknown_bucket_keys():
    value = {"通用": ["通1"], "化神": ["化1"]}
    assert select_narrative_pool(value, level_index=40) == ["通1"]


def test_select_pool_route_filtering():
    value = [
        "通用句",
        {"text": "灵修专属", "route": "灵修"},
        {"text": "体修专属", "route": "体修"},
    ]
    assert select_narrative_pool(value, route="灵修") == ["通用句", "灵修专属"]
    assert select_narrative_pool(value, route="体修") == ["通用句", "体修专属"]
    # 调用方不知路线时保守排除标注条目
    assert select_narrative_pool(value) == ["通用句"]


def test_level_to_narrative_bucket():
    assert level_to_narrative_bucket(1) == "练气"
    assert level_to_narrative_bucket(9) == "练气"
    assert level_to_narrative_bucket(10) == "筑基"
    assert level_to_narrative_bucket(19) == "筑基"
    assert level_to_narrative_bucket(20) == "金丹"
    assert level_to_narrative_bucket(29) == "金丹"
    assert level_to_narrative_bucket(30) == "元婴"
    assert level_to_narrative_bucket(39) == "元婴"
    assert level_to_narrative_bucket(40) is None
    assert level_to_narrative_bucket(None) is None


# --- 渲染与回退（render_narrative） ------------------------------------------


@pytest.fixture
def demo_defaults(monkeypatch):
    """Inject a demo scene into the embedded defaults and declared vars."""
    monkeypatch.setitem(
        DEFAULT_NARRATIVE_CONFIG, "_test", {"greet": "你好，{name}道友"}
    )
    monkeypatch.setitem(NARRATIVE_SCENE_VARS, "_test", {"greet": {"name"}})


class _StubManager:
    """Minimal stand-in exposing only a narrative_config attribute."""


def test_render_uses_config_scene(demo_defaults):
    stub = _StubManager()
    stub.narrative_config = {"_test": {"greet": "幸会，{name}前辈"}}
    assert (
        render_narrative(stub, "_test", "greet", {"name": "张三"}) == "幸会，张三前辈"
    )


def test_render_falls_back_to_default_when_scene_missing(demo_defaults):
    stub = _StubManager()
    stub.narrative_config = {"_test": {}}
    assert (
        render_narrative(stub, "_test", "greet", {"name": "张三"}) == "你好，张三道友"
    )


def test_render_tolerates_manager_without_narrative_config(demo_defaults):
    """Fake config managers in tests lack the attribute entirely."""

    class BareFake:
        pass

    assert (
        render_narrative(BareFake(), "_test", "greet", {"name": "张三"})
        == "你好，张三道友"
    )


def test_render_unknown_scene_returns_empty_string():
    assert render_narrative(object(), "_nope", "missing", {}) == ""


def test_render_broken_template_degrades_to_raw(demo_defaults, monkeypatch):
    """A template passing validation but failing at runtime must not crash."""
    monkeypatch.setitem(
        DEFAULT_NARRATIVE_CONFIG, "_test", {"greet": "你好，{name}{oops}"}
    )
    out = render_narrative(object(), "_test", "greet", {"name": "张三"})
    assert out == "你好，{name}{oops}"


# --- 契约校验（_validate_narrative_config） -----------------------------------


def test_extract_template_vars():
    assert extract_template_vars("{a}打{b.name}出{c[0]}") == {"a", "b", "c"}
    assert extract_template_vars("无占位") == set()
    with pytest.raises(ValueError):
        extract_template_vars("未闭合{brace")


def test_contract_violation_falls_back_to_default(config_manager, monkeypatch):
    monkeypatch.setitem(DEFAULT_NARRATIVE_CONFIG, "_test", {"greet": "你好，{name}"})
    monkeypatch.setitem(NARRATIVE_SCENE_VARS, "_test", {"greet": {"name"}})
    config_manager.narrative_config = {"_test": {"greet": "你好，{name}，{damage}"}}

    config_manager._validate_narrative_config()

    assert config_manager.narrative_config["_test"]["greet"] == "你好，{name}"


def test_contract_violation_does_not_affect_other_scenes(config_manager, monkeypatch):
    monkeypatch.setitem(
        DEFAULT_NARRATIVE_CONFIG,
        "_test",
        {"good": "好的{name}", "bad": "好的{name}"},
    )
    monkeypatch.setitem(
        NARRATIVE_SCENE_VARS, "_test", {"good": {"name"}, "bad": {"name"}}
    )
    config_manager.narrative_config = {
        "_test": {"good": "妙哉{name}", "bad": "坏{unknown_var}"}
    }

    config_manager._validate_narrative_config()

    assert config_manager.narrative_config["_test"]["good"] == "妙哉{name}"
    assert config_manager.narrative_config["_test"]["bad"] == "好的{name}"


def test_contract_validates_bucketed_and_route_entries(config_manager, monkeypatch):
    """Violations inside bucketed pools and {text, route} entries are caught."""
    monkeypatch.setitem(
        DEFAULT_NARRATIVE_CONFIG, "_test", {"greet": {"通用": ["你好{name}"]}}
    )
    monkeypatch.setitem(NARRATIVE_SCENE_VARS, "_test", {"greet": {"name"}})
    config_manager.narrative_config = {
        "_test": {"greet": {"练气": [{"text": "你好{wrong}", "route": "灵修"}]}}
    }

    config_manager._validate_narrative_config()

    assert config_manager.narrative_config["_test"]["greet"] == {"通用": ["你好{name}"]}


def test_declared_scenes_all_have_defaults_and_satisfy_contract():
    """Every declared scene must have an embedded default that passes its own contract."""
    for section, scenes in NARRATIVE_SCENE_VARS.items():
        for scene, declared in scenes.items():
            value = DEFAULT_NARRATIVE_CONFIG.get(section, {}).get(scene)
            assert value is not None, f"{section}.{scene} 缺内嵌默认文案"
            entries = list(_config_mod._iter_scene_entries(value))
            assert entries, f"{section}.{scene} 内嵌默认文案为空"
            for location, entry in entries:
                template = entry if isinstance(entry, str) else entry.get("text", "")
                used = extract_template_vars(template)
                assert used <= declared, (
                    f"{section}.{scene}{location} 默认文案引用未声明变量 "
                    f"{sorted(used - declared)}"
                )


# --- 灵根评价大表（spirit_root_descriptions.json） -----------------------------


def test_spirit_root_descriptions_loaded_from_config(tmp_path):
    import json

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    with open(config_dir / "spirit_root_descriptions.json", "w", encoding="utf-8") as f:
        json.dump([{"name": "金", "description": "【上品】金之精华，锋锐无双"}], f)

    cm = ConfigManager(tmp_path)
    assert (
        cm.spirit_root_descriptions["金"]["description"] == "【上品】金之精华，锋锐无双"
    )


def test_root_description_reads_config_table():
    class _CM:
        spirit_root_descriptions = {"金": {"description": "【上品】金之精华，锋锐无双"}}

    mgr = CultivationManager.__new__(CultivationManager)
    mgr.config_manager = _CM()
    assert mgr._get_root_description("金") == "【上品】金之精华，锋锐无双"
    assert mgr._get_root_description("不存在") == "【未知】神秘的灵根"


def test_root_description_tolerates_fake_config_manager():
    class _Bare:
        pass

    mgr = CultivationManager.__new__(CultivationManager)
    mgr.config_manager = _Bare()
    assert mgr._get_root_description("金") == "【未知】神秘的灵根"


def test_repo_spirit_root_config_matches_original_table():
    """The committed config must carry the full original description table."""
    import json

    with open(
        PLUGIN_ROOT / "config" / "spirit_root_descriptions.json", encoding="utf-8"
    ) as f:
        entries = {e["name"]: e for e in json.load(f)}
    # 47 entries copied verbatim from the original hard-coded table
    assert len(entries) == 47
    assert entries["先天道体"]["description"] == "【禁忌】天生道体，与天地同寿"
    assert entries["伪"]["description"] == "【废柴】资质低劣，修炼如龟速"


# --- 遗留句式外移核对（narrative-text-migration-leftovers） --------------------

# Expected verbatim templates and variable contracts for the 8 leftover scenes
# (design D2): fortune.storage_full_drop plus the 7 combat scenes.
_LEFTOVER_SCENES = {
    ("fortune", "storage_full_drop"): (
        "🎁 机缘天降，获得【{name}】，但储物戒已满无法存入。",
        {"name"},
    ),
    ("combat", "round_header"): ("-- 第 {rounds} 回合 --", {"rounds"}),
    ("combat", "effect_counter"): (
        "{actor_name} 触发【{skill_name}】反击，对 {target_name} 造成 {counter_dmg} 点伤害！",
        {"actor_name", "skill_name", "target_name", "counter_dmg"},
    ),
    ("combat", "effect_heal"): (
        "{actor_name} 触发【{skill_name}】，恢复 {heal} 气血！",
        {"actor_name", "skill_name", "heal"},
    ),
    ("combat", "effect_dot_attach"): (
        "{actor_name} 使【{skill_name}】附着于 {target_name}",
        {"actor_name", "skill_name", "target_name"},
    ),
    ("combat", "effect_stack_cap_rejected"): (
        "{actor_name} 的【{effect_name}】未生效：同类效果已达叠加上限（{stack_cap}）",
        {"actor_name", "effect_name", "stack_cap"},
    ),
    ("combat", "effect_survive_grant"): (
        "{actor_name} 获得【{skill_name}】庇护！",
        {"actor_name", "skill_name"},
    ),
    ("combat", "effect_dot_tick"): (
        "{name} 受【{effect_name}】侵蚀，损失 {dot_dmg} 气血！",
        {"name", "effect_name", "dot_dmg"},
    ),
}


def test_leftover_fragment_defaults_are_verbatim():
    """The 8 leftover scenes' embedded defaults match the original strings."""
    for (section, scene), (template, _declared) in _LEFTOVER_SCENES.items():
        assert DEFAULT_NARRATIVE_CONFIG[section][scene] == template, (
            f"{section}.{scene} 默认文案与原文不一致"
        )


def test_leftover_scene_vars_match_design_contract():
    """SCENE_VARS registrations match the design D2 contract table."""
    for (section, scene), (_template, declared) in _LEFTOVER_SCENES.items():
        assert NARRATIVE_SCENE_VARS[section][scene] == declared, (
            f"{section}.{scene} 变量契约不符"
        )


def test_leftover_scenes_render_like_original_fstring():
    """Rendered output (embedded defaults) equals the original f-string output.

    Sentinel values stand in for the original expressions (actor.name,
    skill.get('name', '反击'), ...); a byte-level mismatch in any literal
    segment (emoji, full/half-width punctuation, spacing) fails the check.
    """

    class _BareFake:
        pass

    cases = [
        (
            ("fortune", "storage_full_drop"),
            {"name": "木剑"},
            "🎁 机缘天降，获得【木剑】，但储物戒已满无法存入。",
        ),
        (("combat", "round_header"), {"rounds": 7}, "-- 第 7 回合 --"),
        (
            ("combat", "effect_counter"),
            {
                "actor_name": "甲",
                "skill_name": "荆棘术",
                "target_name": "乙",
                "counter_dmg": 42,
            },
            "甲 触发【荆棘术】反击，对 乙 造成 42 点伤害！",
        ),
        (
            ("combat", "effect_heal"),
            {"actor_name": "甲", "skill_name": "回春术", "heal": 99},
            "甲 触发【回春术】，恢复 99 气血！",
        ),
        (
            ("combat", "effect_dot_attach"),
            {"actor_name": "甲", "skill_name": "蛊毒", "target_name": "乙"},
            "甲 使【蛊毒】附着于 乙",
        ),
        (
            ("combat", "effect_stack_cap_rejected"),
            {"actor_name": "甲", "effect_name": "嗜血", "stack_cap": 3},
            "甲 的【嗜血】未生效：同类效果已达叠加上限（3）",
        ),
        (
            ("combat", "effect_survive_grant"),
            {"actor_name": "甲", "skill_name": "金钟罩"},
            "甲 获得【金钟罩】庇护！",
        ),
        (
            ("combat", "effect_dot_tick"),
            {"name": "丙", "effect_name": "蛊毒", "dot_dmg": 17},
            "丙 受【蛊毒】侵蚀，损失 17 气血！",
        ),
    ]
    for (section, scene), variables, expected in cases:
        assert render_narrative(_BareFake(), section, scene, variables) == expected


def test_repo_narrative_config_carries_leftover_scenes():
    """The committed narrative_config.json ships the 8 new scenes verbatim."""
    import json

    with open(PLUGIN_ROOT / "config" / "narrative_config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    for (section, scene), (template, _declared) in _LEFTOVER_SCENES.items():
        assert cfg[section][scene] == template, (
            f"config/narrative_config.json {section}.{scene} 与内嵌默认不一致"
        )
