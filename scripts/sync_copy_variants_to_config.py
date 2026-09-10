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
- **变量契约不满足的短句场景**：变体是纯 flavor 句、未携带默认模板的机械
  变量（如 breakthrough.survive 的损失修为/连败保底）时，整体替换会让机械
  信息从玩家消息里消失。此类场景跳过并逐条报告，待内容侧决定"flavor 句 +
  机械行"的拼装方式后另行导入。事件域无此问题（desc 本身就是纯叙事槽位，
  机械信息在结算消息的独立行）。

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


def _default_scene_vars() -> dict[tuple[str, str], set[str]]:
    """Load embedded default templates' variable sets, keyed by (domain, scene).

    Loaded by file path (same standalone trick as utils/narrative_text.py) so
    the script does not depend on the plugin package import chain.
    """
    import importlib.util
    import re

    init_path = PLUGIN_ROOT / "data" / "narrative_defaults" / "__init__.py"
    spec = importlib.util.spec_from_file_location("narrative_defaults_sync", init_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    result: dict[tuple[str, str], set[str]] = {}
    for domain, scenes in mod.DEFAULT_NARRATIVE_CONFIG.items():
        if not isinstance(scenes, dict):
            continue
        for scene, value in scenes.items():
            if isinstance(value, str):
                result[(domain, scene)] = set(re.findall(r"\{(\w+)", value))
    return result


def _template_vars(text: str) -> set[str]:
    """Extract ``{var}`` names from one template (mirror of the lint rule)."""
    import re

    return set(re.findall(r"\{(\w+)", text))


def _to_entry(row: dict):
    """Convert one CSV row to a pool entry (str, or route-tagged dict)."""
    text = (row.get("text") or "").strip()
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


def _apply_short_text(
    ncfg: dict, pools: dict, default_vars: dict[tuple[str, str], set[str]]
) -> tuple[int, list[str], list[str]]:
    """Write contract-safe short-text pools into narrative_config.

    A scene is imported only when EVERY variant carries the default template's
    full variable set (random.choice picks any entry, so partial coverage would
    intermittently drop mechanical info like the breakthrough exp penalty).
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
            unknown.append(f"{domain}.{scene}")
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
        ncfg, pools, _default_scene_vars()
    )
    e_written, e_unknown, _ = _apply_events(acfg, pools)

    print(f"copy_variants.csv: {len(rows)} 定稿行（州条排除 {state_skipped} 行）")
    print(f"narrative_config.json: {n_written} 场景写入变体池")
    if n_unknown:
        print(f"  未知场景键（未写入）: {', '.join(n_unknown)}")
    if n_skipped:
        print(
            f"  变量契约不满足（flavor 句缺机械变量，跳过待拼装设计）: "
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
