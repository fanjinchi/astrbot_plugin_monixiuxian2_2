#!/usr/bin/env python3
"""Import finalized copy variants (copy_variants.csv) into runtime configs.

Two targets:

- 短句域（breakthrough/combat/cultivation/fortune）→ ``config/narrative_config.json``
  scene pools. Scene values become bucketed variant pools
  (``{"通用": [...], "练气": [...], ...}``; route-tagged rows become
  ``{"text", "route"}`` dict entries) — the shape ``select_narrative_pool``
  already supports (utils/narrative_text.py). Embedded defaults in
  ``data/narrative_defaults/`` remain the fallback when a pool is empty.
- ``adventure_event`` 域 → ``config/adventure_config.json`` event
  ``desc_variants`` (same bucketed shape; ``managers/adventure_manager.py``
  ``_select_event_desc`` consumes it with a verbatim ``desc`` fallback).

Deliberate exclusions (reported, not silently dropped):

- ``state != 通用`` rows（州条，~186 行）：运行时没有州/世界状态选择轴，
  导入会让州专属文案混进通用池——待运行时出现 state 选择器后再入库。
- config 中不存在的事件 key（sect_duel/sect_trial，随 bd n6o 五宗落地）。
- **config 暂缺但已在 ``NARRATIVE_SCENE_VARS`` 声明且有内嵌默认的短句场景键**
  （change combat-report-structure D5）：直接建分桶池——ConfigManager 只在配置
  文件不存在时物化默认，已有文件不会合并新键，否则新场景永远停在 unknown。
  这是导入器的**永久性全局新语义**（不限本变更两档）；已知副作用并接受：
  故意从 config 移除的已声明键会被下一次导入写回，要让场景回到内嵌默认必须先
  把它从 ``SCENE_VARS`` 退役（``battle_vs`` / ``remaining_hp`` 即走此路径）。
  放行后仍走同一变量契约检查（⊇ 默认模板变量集），不通过照旧归 skipped。
- **双槽场景**（``DUAL_SLOT_SCENES``，breakthrough.success/survive/death/
  revive、cultivation.retreat_start/retreat_settlement）：机械面板与 flavor
  引子分离（change flavor-copy-assembly D1/D7）。导入时旧字符串值整体搬入
  ``panel`` 键（survive 按 D6 补 ``\n{pity_msg}`` 换行；二次运行保留已迁移
  panel），CSV 行作为 flavor 写入分桶池，校验为 ⊆ 该场景声明变量集
  （``NARRATIVE_SCENE_VARS``）。
- **变量契约不满足的其余短句场景**：变体未携带默认模板的全部机械变量时
  整体替换会让机械信息从玩家消息里消失，跳过并逐条报告。事件域无此问题
  （desc 本身就是纯叙事槽位，机械信息在结算消息的独立行）。

level_band 映射：单段直达同名桶；``练气-筑基`` / ``金丹-元婴`` 双段各投两桶；
``通用`` 入通用桶。幂等：每次从 CSV 全量重建池（仅 ``narrative_status=定稿``
行），重写前跑 budget + narrative lint 双闸门（与 sync_content_to_config.py
同一套，spec content-sync-pipeline）。

Usage:
    uv run python scripts/sync_copy_variants_to_config.py [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DESIGN_DIR = PLUGIN_ROOT / "design_docs" / "content-design"
CONFIG_DIR = PLUGIN_ROOT / "config"

COPY_VARIANTS_CSV = DESIGN_DIR / "copy_variants.csv"

# narrative_config.json 顶层域键与 copy_variants.domain 一一同名
SHORT_TEXT_DOMAINS = ("breakthrough", "combat", "cultivation", "fortune")

# 双槽场景（flavor 分桶池 + panel 单源面板），与 flavor-copy-assembly 设计的
# A/B 拆分同源。清单刻意硬编码：新增双槽场景必须同步本清单，避免配置侧
# 意外产生双槽形态。
DUAL_SLOT_SCENES = frozenset(
    {
        ("breakthrough", "success"),
        ("breakthrough", "survive"),
        ("breakthrough", "death"),
        ("breakthrough", "revive"),
        ("cultivation", "retreat_settlement"),
        ("cultivation", "retreat_start"),
    }
)

# level_band → 运行时桶（utils/narrative_text.py NARRATIVE_BUCKET_KEYS）；
# 复合段向两桶各投一份（选择时当前段桶与通用桶合并，不存在跨段泄漏）。
LEVEL_BAND_TO_BUCKETS = {
    "通用": ("通用",),
    "练气": ("练气",),
    "筑基": ("筑基",),
    "金丹": ("金丹",),
    "元婴": ("元婴",),
    "练气-筑基": ("练气", "筑基"),
    "金丹-元婴": ("金丹", "元婴"),
}

ROUTE_TAGS = ("灵修", "体修")


def _load_variants() -> list[dict]:
    """Load finalized copy variant rows from the design CSV."""
    with COPY_VARIANTS_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if (r.get("narrative_status") or "").strip() == "定稿"]


def _load_narrative_defaults():
    """Load ``data/narrative_defaults`` by file path (same standalone trick as
    utils/narrative_text.py) so the script does not depend on the plugin
    package import chain."""
    import importlib.util

    init_path = PLUGIN_ROOT / "data" / "narrative_defaults" / "__init__.py"
    spec = importlib.util.spec_from_file_location("narrative_defaults_sync", init_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _default_scene_vars() -> dict[tuple[str, str], set[str]]:
    """Load embedded default templates' variable sets, keyed by (domain, scene)."""
    mod = _load_narrative_defaults()
    result: dict[tuple[str, str], set[str]] = {}
    for domain, scenes in mod.DEFAULT_NARRATIVE_CONFIG.items():
        if not isinstance(scenes, dict):
            continue
        for scene, value in scenes.items():
            if isinstance(value, str):
                result[(domain, scene)] = set(re.findall(r"\{(\w+)", value))
    return result


def _declared_scene_vars() -> dict[tuple[str, str], set[str]]:
    """Load the render-point declared variable sets (``NARRATIVE_SCENE_VARS``),
    keyed by (domain, scene). Authority for dual-slot flavor validation."""
    mod = _load_narrative_defaults()
    return {
        (domain, scene): set(vars_)
        for domain, scenes in mod.NARRATIVE_SCENE_VARS.items()
        for scene, vars_ in scenes.items()
    }


def _template_vars(text: str) -> set[str]:
    """Extract ``{var}`` names from one template (mirror of the lint rule)."""
    return set(re.findall(r"\{(\w+)", text))


def _strip_separator(text: str) -> str:
    """Drop trailing "entry separator" lines swallowed from the 剧情 draft.

    The copy drafts in ``design_docs/narrative-drafts/**`` use ``---`` to split
    multiple variants inside one cell. When such a cell is imported as a single
    variant the separator survives as a trailing ``\n---`` line and reaches
    players as a stray horizontal rule (bd -74n). Only trailing/leading
    separator-only lines are removed; ``---`` used as an in-sentence pause mark
    (破折号连写) stays untouched.

    Args:
        text: Raw cell text from the variants CSV.

    Returns:
        The same text without separator-only border lines.
    """
    lines = text.split("\n")
    while lines and re.fullmatch(r"-+", lines[-1].strip()):
        lines.pop()
    while lines and re.fullmatch(r"-+", lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def _to_entry(row: dict):
    """Convert one CSV row to a pool entry (str, or route-tagged dict).

    Edge whitespace is dropped on import and reported: line breaks belong to the
    code or the panel template, never to the copy (a variant starting with
    ``\\n`` renders a blank line inside the panel -- bd -ju1). Interior newlines
    are kept, so multi-line copy is unaffected.
    """
    raw = row.get("text") or ""
    label = f"{row.get('domain')}.{row.get('scene')}#{row.get('variant_no')}"
    if raw != raw.strip():
        edge = repr(raw[: len(raw) - len(raw.lstrip())]) + repr(
            raw[len(raw.rstrip()) :]
        )
        print(
            f"  WARN 稿子首尾带空白/换行，导入时已剔除（换行归代码或面板模板所有，"
            f"见 utils/narrative_text.py 「Line-break ownership contract」）: "
            f"{label} 边缘={edge}"
        )
    text = _strip_separator(raw.strip())
    route = (row.get("route") or "").strip()
    if route in ROUTE_TAGS:
        return {"text": text, "route": route}
    return text


def _build_pools(rows: list[dict]) -> dict:
    """Group rows into bucketed pools keyed by (domain, scene)."""
    pools: dict[tuple[str, str], dict[str, list]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        band = (row.get("level_band") or "").strip() or "通用"
        buckets = LEVEL_BAND_TO_BUCKETS.get(band)
        if buckets is None:
            print(f"  WARN 未知 level_band {band!r}，按通用桶处理: {row.get('scene')}")
            buckets = ("通用",)
        key = (row["domain"].strip(), row["scene"].strip())
        for bucket in buckets:
            pools[key][bucket].append(_to_entry(row))
    return pools


def _migrate_dual_slot(
    old_value, label: str, buckets: dict, declared: set[str] | None
) -> dict | None:
    """Build the dual-slot scene value from the current config value + CSV pools.

    The old single-string value moves wholesale into ``panel`` (per design D7;
    survive gets the D6 ``\\n{pity_msg}`` newline fix on migration). A second
    run finds the dual-slot dict and keeps its ``panel`` verbatim (idempotent).
    Flavor validation is ⊆ the declared variable set — flavor never carries
    mechanical variables. Returns None (scene left untouched) when the current
    value is malformed or any variant violates the contract.
    """
    if isinstance(old_value, str):
        panel = old_value
        if (
            label == "breakthrough.survive"
            and "{pity_msg}" in panel
            and "\n{pity_msg}" not in panel
        ):
            # D6: newline duty moves from the pity_hint copy into the panel
            panel = panel.replace("{pity_msg}", "\n{pity_msg}", 1)
    elif (
        isinstance(old_value, dict)
        and isinstance(old_value.get("panel"), str)
        and "text" not in old_value
    ):
        panel = old_value["panel"]
    else:
        print(f"  WARN {label} 现有值既不是字符串也不是双槽 dict，整场景跳过")
        return None
    if declared is not None:
        bad = [
            e
            for entries in buckets.values()
            for e in entries
            if not _template_vars(e if isinstance(e, str) else e.get("text", ""))
            <= declared
        ]
        if bad:
            print(
                f"  WARN {label} 有 {len(bad)} 条 flavor 变量越出声明集 "
                f"{sorted(declared)}，整场景跳过"
            )
            return None
    return {"panel": panel, **dict(sorted(buckets.items()))}


def _apply_short_text(
    ncfg: dict,
    pools: dict,
    default_vars: dict[tuple[str, str], set[str]],
    declared_vars: dict[tuple[str, str], set[str]],
) -> tuple[int, list[str], list[str]]:
    """Write contract-safe short-text pools into narrative_config.

    Dual-slot scenes (``DUAL_SLOT_SCENES``) migrate to the panel + flavor-pool
    shape via :func:`_migrate_dual_slot`. Other scenes import only when EVERY
    variant carries the default template's full variable set (random.choice
    picks any entry, so partial coverage would intermittently drop mechanical
    info like the breakthrough exp penalty).

    A scene key missing from config is admitted (pool created from the CSV)
    when the render point declares it (``NARRATIVE_SCENE_VARS``) AND it has an
    embedded default — the two conditions that make a CSV pool a legal
    replacement for that default. Everything else stays ``unknown``. See the
    module docstring for the permanent global semantics and its accepted side
    effect.

    Returns (scenes written, unknown scene keys, contract-skipped scenes).
    """
    written = 0
    unknown = []
    skipped = []
    for (domain, scene), buckets in sorted(pools.items()):
        if domain not in SHORT_TEXT_DOMAINS:
            continue
        section = ncfg.setdefault(domain, {})
        if scene not in section:
            # 放行规则（change combat-report-structure D5）：config 暂缺的场景键，
            # 只要渲染点已声明（SCENE_VARS）且有内嵌默认，就从 CSV 直接建池；
            # unknown 仅保留给完全未声明的键。双槽场景排除在外：其 config 值是
            # panel 载体，没有可从 CSV 新建的形态（仍需先手工补 panel）。
            admitted = (
                (domain, scene) in declared_vars
                and (domain, scene) in default_vars
                and (domain, scene) not in DUAL_SLOT_SCENES
            )
            if not admitted:
                unknown.append(f"{domain}.{scene}")
                continue
        if (domain, scene) in DUAL_SLOT_SCENES:
            new_value = _migrate_dual_slot(
                section[scene],
                f"{domain}.{scene}",
                buckets,
                declared_vars.get((domain, scene)),
            )
            if new_value is None:
                skipped.append(f"{domain}.{scene}")
                continue
            section[scene] = new_value
            written += 1
            continue
        required = default_vars.get((domain, scene), set())
        ok = all(
            _template_vars(e if isinstance(e, str) else e.get("text", "")) >= required
            for entries in buckets.values()
            for e in entries
        )
        if not ok:
            skipped.append(f"{domain}.{scene}")
            continue
        section[scene] = dict(sorted(buckets.items()))
        written += 1
    return written, unknown, skipped


def _apply_events(acfg: dict, pools: dict) -> tuple[int, int, list[str]]:
    """Write 通用-state event pools into adventure_config desc_variants.

    Returns (events written, state-skipped rows, unknown event keys).
    """
    event_index = {}
    for group in acfg.get("event_groups", {}).values():
        if isinstance(group, list):
            for event in group:
                if isinstance(event, dict) and event.get("key"):
                    event_index[event["key"]] = event
    written = 0
    unknown = []
    event_pools = {
        scene: buckets
        for (domain, scene), buckets in pools.items()
        if domain == "adventure_event"
    }
    for scene, buckets in sorted(event_pools.items()):
        event = event_index.get(scene)
        if event is None:
            unknown.append(scene)
            continue
        event["desc_variants"] = dict(sorted(buckets.items()))
        written += 1
    return written, unknown, event_index


def _run_gate(script: str) -> bool:
    """Run one content gate script; returns True when it passes."""
    gate = subprocess.run(
        [sys.executable, str(DESIGN_DIR / script)],
        check=False,
    )
    return gate.returncode == 0


def main() -> int:
    """Run the copy-variant import. Returns process exit code."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the import summary without writing files",
    )
    args = parser.parse_args()

    rows = _load_variants()
    # 州条（state != 通用）不入库：运行时无 state 选择轴，混入会破坏州域专属设计
    landable = [r for r in rows if (r.get("state") or "通用").strip() == "通用"]
    state_skipped = len(rows) - len(landable)
    pools = _build_pools(landable)

    ncfg_path = CONFIG_DIR / "narrative_config.json"
    acfg_path = CONFIG_DIR / "adventure_config.json"
    ncfg = json.loads(ncfg_path.read_text(encoding="utf-8"))
    acfg = json.loads(acfg_path.read_text(encoding="utf-8"))

    n_written, n_unknown, n_skipped = _apply_short_text(
        ncfg, pools, _default_scene_vars(), _declared_scene_vars()
    )
    e_written, e_unknown, _ = _apply_events(acfg, pools)

    print(f"copy_variants.csv: {len(rows)} 定稿行（州条排除 {state_skipped} 行）")
    print(f"narrative_config.json: {n_written} 场景写入变体池")
    if n_unknown:
        print(f"  未知场景键（未写入）: {', '.join(n_unknown)}")
    if n_skipped:
        print(
            f"  变量契约不满足（A 场景缺机械变量 / 双槽 flavor 越出声明集，跳过）: "
            f"{', '.join(n_skipped)}"
        )
    print(f"adventure_config.json: {e_written} 事件写入 desc_variants")
    if e_unknown:
        print(f"  config 未落地事件（跳过，bd n6o）: {', '.join(e_unknown)}")

    # 双闸门（spec content-sync-pipeline）：预算 + 叙事 lint 全绿才允许写
    print("\nRunning budget gate (validate_budget.py)...")
    sys.stdout.flush()
    if not _run_gate("validate_budget.py"):
        print("Budget gate FAILED, nothing was written.")
        return 1
    print("\nRunning narrative lint gate (lint_narrative.py)...")
    sys.stdout.flush()
    if not _run_gate("lint_narrative.py"):
        print("Narrative lint gate FAILED, nothing was written.")
        return 1

    if args.dry_run:
        print("\nDry run: no files written.")
        return 0

    for path, cfg in ((ncfg_path, ncfg), (acfg_path, acfg)):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    print(f"\nWrote {ncfg_path} and {acfg_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
