"""`sync_copy_variants_to_config.py` 新键放行规则的回归测试。

覆盖 change combat-report-structure 4.1/D5 引入的导入器语义：config 暂缺的
场景键，只要渲染点已声明（``SCENE_VARS``）且有内嵌默认，就从 CSV 直接建池；
其余情况照旧归 unknown / skipped。放行规则的已知副作用是「故意从 config 移除
的已声明键会被写回」，退役场景（``battle_vs`` / ``remaining_hp``）因此必须从
``SCENE_VARS`` 与内嵌默认两处同时退场——本文件用合成池钉死这条退役链路，
防止 4.1 的放行规则把退役键悄悄写回 config。
"""

import pytest

from tests.helpers import load_module

_sync = load_module(
    "sync_copy_variants_to_config", "scripts/sync_copy_variants_to_config.py"
)

_default_vars = _sync._default_scene_vars()
_declared_vars = _sync._declared_scene_vars()

NEW_SCENE = ("combat", "remaining_hp_mid")
NEW_SCENE_VARS = "{defender_name} 气血还剩 {remaining_hp} 点，架势未散。"
RETIRED_SCENES = [("combat", "remaining_hp"), ("combat", "battle_vs")]


def _run(pools: dict, config: dict | None = None, drop_default: tuple | None = None):
    """Drive the real `_apply_short_text` with the real declared/default sets.

    Args:
        pools: (domain, scene) → bucket pool, as built by `_build_pools`.
        config: starting narrative_config; defaults to an empty dict.
        drop_default: (domain, scene) to strip from the embedded-default set,
            faking a scene that is declared but has no embedded default.

    Returns:
        (written, unknown, skipped, mutated config).
    """
    defaults = {
        k: v
        for k, v in _default_vars.items()
        if drop_default is None or k != drop_default
    }
    ncfg = {"combat": {}} if config is None else config
    written, unknown, skipped = _sync._apply_short_text(
        ncfg, pools, defaults, _declared_vars
    )
    return written, unknown, skipped, ncfg


def test_missing_scene_with_declared_and_default_builds_pool() -> None:
    """已声明 + 有内嵌默认 + config 暂缺 → 直接建分桶池（written，非 unknown）。"""
    written, unknown, skipped, ncfg = _run({NEW_SCENE: {"通用": [NEW_SCENE_VARS]}})
    assert (written, unknown, skipped) == (1, [], [])
    assert ncfg["combat"]["remaining_hp_mid"] == {"通用": [NEW_SCENE_VARS]}


def test_missing_scene_with_contract_violation_is_skipped_without_key() -> None:
    """放行后仍走变量契约：不满足归 skipped，且不得预建空键占位。"""
    written, unknown, skipped, ncfg = _run(
        {NEW_SCENE: {"通用": ["{defender_name} 气血还剩一点。"]}}  # 缺 {remaining_hp}
    )
    assert (written, unknown, skipped) == (0, [], ["combat.remaining_hp_mid"])
    assert "remaining_hp_mid" not in ncfg["combat"]


def test_declared_scene_without_embedded_default_is_unknown() -> None:
    """已声明但无内嵌默认 → 无回退句可替换，仍归 unknown。"""
    written, unknown, skipped, ncfg = _run(
        {NEW_SCENE: {"通用": [NEW_SCENE_VARS]}}, drop_default=NEW_SCENE
    )
    assert (written, unknown, skipped) == (0, ["combat.remaining_hp_mid"], [])
    assert "remaining_hp_mid" not in ncfg["combat"]


def test_undeclared_scene_is_unknown() -> None:
    """完全未声明（不在 SCENE_VARS）→ unknown。"""
    written, unknown, skipped, ncfg = _run(
        {("combat", "never_declared_scene"): {"通用": ["随便一句。"]}}
    )
    assert (written, unknown, skipped) == (0, ["combat.never_declared_scene"], [])
    assert "never_declared_scene" not in ncfg["combat"]


def test_dual_slot_scene_missing_from_config_stays_unknown() -> None:
    """双槽场景 config 暂缺 → 排除在放行之外（config 值是 panel 载体，无 CSV 形态）。"""
    written, unknown, skipped, ncfg = _run(
        {("breakthrough", "success"): {"通用": ["{rate_info} {hp}"]}},
        config={"breakthrough": {}},
    )
    assert (written, unknown, skipped) == (0, ["breakthrough.success"], [])
    assert "success" not in ncfg["breakthrough"]


def test_existing_scene_keeps_original_overwrite_path() -> None:
    """已存在于 config 的场景照旧走原逻辑：契约满足即整体覆写为池。"""
    written, unknown, skipped, ncfg = _run(
        {NEW_SCENE: {"通用": [NEW_SCENE_VARS]}},
        config={"combat": {"remaining_hp_mid": "旧句 {defender_name} {remaining_hp}"}},
    )
    assert (written, unknown, skipped) == (1, [], [])
    assert ncfg["combat"]["remaining_hp_mid"] == {"通用": [NEW_SCENE_VARS]}


def test_existing_scene_with_contract_violation_keeps_old_value() -> None:
    """已存在场景契约不过 → skipped，旧值原样保留（不删不改）。"""
    old = "旧句 {defender_name} {remaining_hp}"
    written, unknown, skipped, ncfg = _run(
        {NEW_SCENE: {"通用": ["{defender_name} 缺变量。"]}},
        config={"combat": {"remaining_hp_mid": old}},
    )
    assert (written, unknown, skipped) == (0, [], ["combat.remaining_hp_mid"])
    assert ncfg["combat"]["remaining_hp_mid"] == old


@pytest.mark.parametrize("scene", RETIRED_SCENES)
def test_retired_scene_keys_are_never_resurrected(scene: tuple[str, str]) -> None:
    """退役键即便被硬塞回 CSV，也只归 unknown，绝不写回 config（4.1 放行规则边界）。"""
    written, unknown, skipped, ncfg = _run({scene: {"通用": ["{name1} {name2}"]}})
    assert (written, skipped) == (0, [])
    assert unknown == [f"{scene[0]}.{scene[1]}"]
    assert scene[1] not in ncfg["combat"]


def test_real_copy_variants_csv_carries_no_retired_scene() -> None:
    """真实 CSV 池：退役键 0 残留，两档剩余气血键在场（退役链路闭合的输入侧证据）。"""
    rows = _sync._load_variants()
    landable = [r for r in rows if (r.get("state") or "通用").strip() == "通用"]
    pools = _sync._build_pools(landable)
    scenes = {scene for _, scene in pools}
    assert "battle_vs" not in scenes
    assert "remaining_hp" not in scenes
    assert {"remaining_hp_low", "remaining_hp_mid"} <= scenes
