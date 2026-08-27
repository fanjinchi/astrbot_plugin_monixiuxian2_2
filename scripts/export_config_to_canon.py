#!/usr/bin/env python3
"""Export runtime config entries back into content-design canon CSVs.

Reverse direction of ``sync_content_to_config.py``: finds config entries whose
``id`` is absent from the design CSVs and appends rows with every numeric
column copied verbatim from config (``status=legacy`` — never imported, never
budget-FAILed, and protects the live config entry from reconcile deletion;
``ref_source=现有配置``, narrative columns left at 占位 defaults). This closes
the coverage gap where live content (e.g. sect skill pools, 青云心典) existed
only in config. To bring such an entry under design management, flip the row
to ``draft`` and make its values pass the budget gate.

Also (re)builds the light narrative table ``bounty-canon.csv`` from
``config/bounty_templates.json`` (id/name + canon columns; no numeric columns,
per design D2 light-table convention).

Idempotent: ids already present in a CSV are skipped. Existing rows are never
modified — the CSVs remain the design source of truth.

Usage:
    uv run python scripts/export_config_to_canon.py [--dry-run]

Returns:
    Exit code 0 on success, 1 on unexpected schema mismatch.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DESIGN_DIR = PLUGIN_ROOT / "design_docs" / "content-design"
CONFIG_DIR = PLUGIN_ROOT / "config"

# canon 四列默认值：出处按宗门归属给（可在 bible §3.2 查证），其余占位起步，
# 回填叙事本身是梯队 3 的内容任务（season-1-outline.md）。
_TONE_BY_SECT = {"qingyun": "正经", "huanxi": "玩梗灰"}
_SECT_NAME = {"qingyun": "青云门", "huanxi": "合欢宗"}

EXPORT_NOTE = "config 逆向导出补登记（scripts/export_config_to_canon.py）"


def _load_csv(path: Path) -> tuple[list[dict], list[str]]:
    """Load a design CSV, returning (rows, fieldnames)."""
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """Rewrite a design CSV fully (rows already include any appended ones)."""
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _jdump(obj: object) -> str:
    """Serialize a JSON cell with the same format existing CSV cells use."""
    return json.dumps(obj, ensure_ascii=False)


def _canon_defaults(sect: str | None) -> dict[str, str]:
    """Default canon column values for a backfilled row."""
    return {
        "canon_origin": _SECT_NAME.get(sect or "", ""),
        "tone_tier": _TONE_BY_SECT.get(sect or "", "平淡"),
        "story_hook": "",
        "narrative_status": "占位",
    }


def _weapon_row(entry: dict) -> dict:
    """Map a config/weapons.json entry to a weapons.csv row."""
    row = {
        "id": entry.get("id", ""),
        "name": entry.get("name", ""),
        "weapon_category": entry.get("weapon_category", ""),
        "size_class": "",  # 设计列，config 无此字段，留空待设计补
        "rank": entry.get("rank", ""),
        "required_level_index": entry.get("required_level_index", 0),
        "base_damage": entry.get("base_damage", 0),
        "weapon_coefficient_k": entry.get("weapon_coefficient_k", ""),
        # config 键为 damage（武器 +伤害词条）；缺省即无词条，单元格留空
        "bonus_damage": entry.get("damage", ""),
        "armor_value": entry.get("armor_value", 0),
        "price": entry.get("price", 0),
        "shop_weight": entry.get("shop_weight", 0),
        "route_mult_ling": (entry.get("route_multiplier") or {}).get("灵修", 1.0),
        "route_mult_ti": (entry.get("route_multiplier") or {}).get("体修", 1.0),
        "trigger_skills_json": _jdump(entry.get("trigger_skills") or []),
        "description": entry.get("description", ""),
        "ref_source": "现有配置",
        "design_note": EXPORT_NOTE,
        "status": "legacy",
        **_canon_defaults(None),
    }
    return row


def _heart_row(entry: dict) -> dict:
    """Map a config/heart_methods.json entry to a heart_methods.csv row."""
    return {
        "id": entry.get("id", ""),
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "rank": entry.get("rank", ""),
        "required_level_index": entry.get("required_level_index", 0),
        "passive_bonus_json": _jdump(entry.get("passive_bonus") or {}),
        "exp_multiplier": entry.get("exp_multiplier", 0.0),
        "skill_pool_json": _jdump(entry.get("skill_pool") or []),
        "route": entry.get("route", "通用"),
        "route_mult_ling": (entry.get("route_multiplier") or {}).get("灵修", 1.0),
        "route_mult_ti": (entry.get("route_multiplier") or {}).get("体修", 1.0),
        "shop_weight": entry.get("shop_weight", 0),
        "ref_source": "现有配置",
        "design_note": EXPORT_NOTE,
        "status": "legacy",
        # sect_id/sect_bound 是 config 专有字段（无 CSV 列），sync merge 只写
        # payload 已有的键，不会被覆盖，无需导出
        **_canon_defaults(entry.get("sect_id")),
    }


def _skill_row(pool: str, entry: dict) -> dict:
    """Map a config/skills.json entry (grouped format) to a skills.csv row."""
    trig = entry.get("trigger_skill") or {}
    row = {
        "pool": pool,
        "id": entry.get("id", ""),
        "name": entry.get("name", ""),
        "trigger_name": trig.get("name", ""),
        "trigger_condition": trig.get("trigger_condition", ""),
        "trigger_rate": trig.get("trigger_rate", ""),
        "effect_type": trig.get("effect_type", ""),
        "effect_value": trig.get("effect_value", ""),
        "stat": trig.get("stat", ""),
        "duration": trig.get("duration", ""),
        "tick_rate": trig.get("tick_rate", ""),
        "heal_percent": trig.get("heal_percent", ""),
        "pierce_rate": trig.get("pierce_rate", ""),
        "reflect_rate": trig.get("reflect_rate", ""),
        "survive_count": trig.get("survive_count", ""),
        "vampire": "1" if trig.get("vampire") else "",
        "route_mult_ling": (entry.get("route_multiplier") or {}).get("灵修", 1.0),
        "route_mult_ti": (entry.get("route_multiplier") or {}).get("体修", 1.0),
        "learn_coefficient": entry.get("learn_coefficient", ""),
        "ultimate_json": _jdump(entry["ultimate"]) if entry.get("ultimate") else "null",
        "description": entry.get("description", ""),
        "ref_source": "现有配置",
        "design_note": EXPORT_NOTE,
        "status": "legacy",
        # sect_bound 同 heart 的 sect_id：config 专有，merge 保留，无需导出
        **_canon_defaults(entry.get("sect_id") or _sect_of_pool(pool)),
    }
    return row


def _sect_of_pool(pool: str) -> str | None:
    """Derive the sect id from a skills.json pool key (``sect_qingyun`` → ``qingyun``)."""
    return pool.removeprefix("sect_") if pool.startswith("sect_") else None


def _backfill(
    csv_name: str, config_entries: list[tuple[str, dict]], to_row
) -> list[str]:
    """Append config entries missing from a design CSV. Returns added ids.

    Args:
        csv_name: Design CSV filename under ``design_docs/content-design/``.
        config_entries: ``(pool_or_empty, config_entry)`` pairs to cover.
        to_row: Callable ``(pool, entry) -> csv row dict`` for missing entries.

    Returns:
        Ids of the rows appended (empty when the CSV already covers config).
    """
    path = DESIGN_DIR / csv_name
    rows, fieldnames = _load_csv(path)
    known_ids = {(r.get("id") or "").strip() for r in rows}
    added: list[str] = []
    for pool, entry in config_entries:
        eid = str(entry.get("id", "")).strip()
        if not eid or eid in known_ids:
            continue
        row = to_row(pool, entry)
        unknown_cols = set(row) - set(fieldnames)
        if unknown_cols:
            raise ValueError(
                f"{csv_name}: row for {eid} has unknown columns {sorted(unknown_cols)}"
            )
        rows.append({col: row.get(col, "") for col in fieldnames})
        added.append(eid)
    if added and not _dry_run:
        _write_csv(path, rows, fieldnames)
    return added


def _export_bounty_canon() -> list[str]:
    """(Re)build bounty-canon.csv from config/bounty_templates.json.

    Light narrative table (design D2): no numeric columns, only id/name +
    canon columns + a note carrying category/difficulty for writers. Existing
    rows keep their canon values; only missing ids are appended.
    """
    path = DESIGN_DIR / "bounty-canon.csv"
    fieldnames = [
        "id",
        "name",
        "canon_origin",
        "tone_tier",
        "story_hook",
        "narrative_status",
        "note",
    ]
    rows: list[dict] = []
    if path.exists():
        rows, _ = _load_csv(path)
    known_ids = {(r.get("id") or "").strip() for r in rows}
    bounty = json.loads(
        (CONFIG_DIR / "bounty_templates.json").read_text(encoding="utf-8")
    )
    added: list[str] = []
    for tpl in bounty.get("templates", []):
        tid = str(tpl.get("id", "")).strip()
        if not tid or tid in known_ids:
            continue
        rows.append(
            {
                "id": tid,
                "name": tpl.get("name", ""),
                "canon_origin": "散修日常",
                "tone_tier": "平淡",
                "story_hook": "",
                "narrative_status": "占位",
                "note": f"category={tpl.get('category', '')}；difficulty={tpl.get('difficulty', '')}",
            }
        )
        added.append(tid)
    if added and not _dry_run:
        _write_csv(path, rows, fieldnames)
    return added


_dry_run = False


def main() -> int:
    """Run the export. Returns process exit code."""
    global _dry_run
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be appended without writing files",
    )
    args = parser.parse_args()
    _dry_run = args.dry_run

    weapons_cfg = json.loads((CONFIG_DIR / "weapons.json").read_text(encoding="utf-8"))
    hearts_cfg = json.loads(
        (CONFIG_DIR / "heart_methods.json").read_text(encoding="utf-8")
    )
    skills_cfg = json.loads((CONFIG_DIR / "skills.json").read_text(encoding="utf-8"))

    added_weapons = _backfill(
        "weapons.csv",
        [("", e) for e in weapons_cfg],
        lambda _pool, e: _weapon_row(e),
    )
    added_hearts = _backfill(
        "heart_methods.csv",
        [("", e) for e in hearts_cfg.get("心法列表", [])],
        lambda _pool, e: _heart_row(e),
    )
    skill_entries = [(pool, e) for pool, entries in skills_cfg.items() for e in entries]
    added_skills = _backfill("skills.csv", skill_entries, _skill_row)
    added_bounty = _export_bounty_canon()

    verb = "would add" if _dry_run else "added"
    print(f"weapons.csv: {verb} {len(added_weapons)} rows {added_weapons or ''}")
    print(f"heart_methods.csv: {verb} {len(added_hearts)} rows {added_hearts or ''}")
    print(f"skills.csv: {verb} {len(added_skills)} rows {added_skills or ''}")
    print(f"bounty-canon.csv: {verb} {len(added_bounty)} rows {added_bounty or ''}")
    if added_weapons or added_hearts or added_skills:
        print(
            "\nNext: run `uv run python scripts/sync_content_to_config.py --dry-run` "
            "to confirm both gates (budget + narrative lint) pass with the new rows."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
