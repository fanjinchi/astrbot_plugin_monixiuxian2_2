#!/usr/bin/env python3
"""Sync content-design CSVs into runtime config JSONs (merge mode).

Reads ``design_docs/content-design/weapons.csv`` and ``heart_methods.csv``,
merges rows with status ``draft``/``final`` into ``config/weapons.json`` and
``config/heart_methods.json`` (keyed by item ``name``), and runs the budget
gate (``design_docs/content-design/validate_budget.py``) before writing.

Merge semantics: existing config entries with the same name are updated
field-by-field (unmapped fields are preserved); new names are appended;
config entries absent from the CSVs are never touched. Rows with status
``legacy`` are reference-only and always skipped.

skills.csv sync is intentionally deferred: skill values are frozen until the
skill-pool redesign (openspec change skill-engine-fit-and-content-sync, D8
scope adjustment; bd issue dhh).

Usage:
    uv run python scripts/sync_content_to_config.py [--dry-run]

Returns:
    Exit code 0 on success (or successful dry-run), 1 on contract errors or
    budget-gate failure. Nothing is written unless every check passes.
"""

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DESIGN_DIR = PLUGIN_ROOT / "design_docs" / "content-design"
CONFIG_DIR = PLUGIN_ROOT / "config"

# Engine contract for trigger skills (weapons mount these verbatim; the
# combat engine dispatches EFFECT_HANDLERS by effect_type).
TRIGGER_REQUIRED_KEYS = {
    "trigger_timing",
    "effect_type",
    "trigger_rate",
    "effect_value",
}
TRIGGER_TIMINGS = {"on_attack", "on_defense", "on_crit", "round_start"}

# Passive bonus vocabulary consumed by models.get_total_attributes for
# main_technique items. Unknown keys would be silently ignored, so reject.
PASSIVE_BONUS_KEYS = {
    "hp_percent",
    "damage_percent",
    "agility_percent",
    "speed_percent",
    "armor_value",
}


def _num(text: str):
    """Parse a CSV cell as int when integral, else float. Returns None for empty."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return float(text)


def _load_rows(filename: str) -> tuple[list[dict], list[dict]]:
    """Load a design CSV, splitting (syncable draft/final rows, skipped legacy rows)."""
    with (DESIGN_DIR / filename).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    active = [r for r in rows if (r.get("status") or "").strip() in ("draft", "final")]
    skipped = [
        r for r in rows if (r.get("status") or "").strip() not in ("draft", "final")
    ]
    return active, skipped


def _validate_trigger_skills(raw_json: str, ctx: str, errors: list[str]) -> list[dict]:
    """Parse and contract-check a trigger_skills_json cell."""
    raw_json = (raw_json or "").strip()
    if not raw_json:
        return []
    try:
        skills = json.loads(raw_json)
    except json.JSONDecodeError as e:
        errors.append(f"{ctx}: trigger_skills_json is not valid JSON: {e}")
        return []
    if not isinstance(skills, list):
        errors.append(f"{ctx}: trigger_skills_json must be a JSON list")
        return []
    for i, skill in enumerate(skills):
        where = f"{ctx} trigger_skills[{i}]"
        if not isinstance(skill, dict):
            errors.append(f"{where}: must be an object")
            continue
        item = cast(dict[str, Any], skill)
        missing = TRIGGER_REQUIRED_KEYS - item.keys()
        if missing:
            errors.append(f"{where}: missing engine keys {sorted(missing)}")
            continue
        if item["trigger_timing"] not in TRIGGER_TIMINGS:
            errors.append(f"{where}: unknown trigger_timing {item['trigger_timing']!r}")
        rate = item["trigger_rate"]
        if not isinstance(rate, (int, float)) or not 0 < rate <= 1:
            errors.append(f"{where}: trigger_rate must be in (0, 1], got {rate!r}")
        if not isinstance(item["effect_value"], (int, float)):
            errors.append(
                f"{where}: effect_value must be numeric, got {item['effect_value']!r}"
            )
    return skills


def _build_weapon(row: dict, errors: list[str]) -> dict | None:
    """Map a weapons.csv row to a config/weapons.json entry."""
    name = (row.get("name") or "").strip()
    ctx = f"weapons.csv[{name or row.get('id', '?')}]"
    entry = {
        "id": (row.get("id") or "").strip(),
        "name": name,
        "type": "weapon",
        "weapon_category": (row.get("weapon_category") or "").strip(),
        "rank": (row.get("rank") or "").strip(),
        "required_level_index": _num(row.get("required_level_index", "")) or 0,
        "description": (row.get("description") or "").strip(),
        "price": _num(row.get("price", "")) or 0,
        "shop_weight": _num(row.get("shop_weight", "")) or 0,
        "weapon_coefficient_k": _num(row.get("weapon_coefficient_k", "")),
        "base_damage": _num(row.get("base_damage", "")) or 0,
        "armor_value": _num(row.get("armor_value", "")) or 0,
        "trigger_skills": _validate_trigger_skills(
            row.get("trigger_skills_json", ""), ctx, errors
        ),
        "route_multiplier": {
            "灵修": _num(row.get("route_mult_ling", "")) or 1.0,
            "体修": _num(row.get("route_mult_ti", "")) or 1.0,
        },
    }
    if entry["weapon_coefficient_k"] is None:
        errors.append(f"{ctx}: weapon_coefficient_k is required")
        return None
    if not name:
        errors.append(f"{ctx}: name is required")
        return None
    # bonus_damage maps to the config attribute key ``damage``. Only written
    # when the cell is non-empty so legacy attribute entries stay untouched
    # unless the design row explicitly sets a value (e.g. 0 for benchmarks).
    bonus = _num(row.get("bonus_damage", ""))
    if bonus is not None:
        entry["damage"] = bonus
    return entry


def _build_heart(row: dict, errors: list[str]) -> dict | None:
    """Map a heart_methods.csv row to a config/heart_methods.json entry."""
    name = (row.get("name") or "").strip()
    ctx = f"heart_methods.csv[{name or row.get('id', '?')}]"
    try:
        passive = json.loads((row.get("passive_bonus_json") or "").strip() or "{}")
    except json.JSONDecodeError as e:
        errors.append(f"{ctx}: passive_bonus_json is not valid JSON: {e}")
        return None
    unknown = set(passive) - PASSIVE_BONUS_KEYS
    if unknown:
        errors.append(
            f"{ctx}: unknown passive_bonus keys {sorted(unknown)} (allowed: {sorted(PASSIVE_BONUS_KEYS)})"
        )
        return None
    try:
        pool = json.loads((row.get("skill_pool_json") or "").strip() or "[]")
    except json.JSONDecodeError as e:
        errors.append(f"{ctx}: skill_pool_json is not valid JSON: {e}")
        return None
    if not isinstance(pool, list):
        errors.append(f"{ctx}: skill_pool_json must be a JSON list")
        return None
    if not name:
        errors.append(f"{ctx}: name is required")
        return None
    return {
        "id": (row.get("id") or "").strip(),
        "name": name,
        "description": (row.get("description") or "").strip(),
        "rank": (row.get("rank") or "").strip(),
        "required_level_index": _num(row.get("required_level_index", "")) or 0,
        "passive_bonus": passive,
        "exp_multiplier": _num(row.get("exp_multiplier", "")) or 1.0,
        "skill_pool": pool,
        "route": (row.get("route") or "").strip() or "通用",
        "shop_weight": _num(row.get("shop_weight", "")) or 0,
    }


def _merge(entries: list[dict], payload: dict) -> tuple[str, list[str]]:
    """Merge payload into a config list by name. Returns (action, field diff lines)."""
    for existing in entries:
        if existing.get("name") == payload["name"]:
            diffs = []
            for key, value in payload.items():
                old = existing.get(key, "<absent>")
                if old != value:
                    diffs.append(
                        f"    {key}: {json.dumps(old, ensure_ascii=False)} -> {json.dumps(value, ensure_ascii=False)}"
                    )
                existing[key] = value
            return ("UPDATE", diffs)
    entries.append(payload)
    return ("ADD", [])


def main() -> int:
    """Run the sync. Returns process exit code."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the merge summary without writing files",
    )
    args = parser.parse_args()

    errors: list[str] = []
    weapon_rows, weapon_skipped = _load_rows("weapons.csv")
    heart_rows, heart_skipped = _load_rows("heart_methods.csv")

    weapons = [w for r in weapon_rows if (w := _build_weapon(r, errors)) is not None]
    hearts = [h for r in heart_rows if (h := _build_heart(r, errors)) is not None]

    # Names must be unique within each CSV (config is keyed by name).
    for label, items in (("weapons", weapons), ("heart_methods", hearts)):
        seen: set[str] = set()
        for item in items:
            if item["name"] in seen:
                errors.append(f"{label}: duplicate name {item['name']!r} in CSV")
            seen.add(item["name"])

    if errors:
        print("Contract errors, nothing was written:")
        for e in errors:
            print(f"  ERROR {e}")
        return 1

    weapons_cfg_path = CONFIG_DIR / "weapons.json"
    hearts_cfg_path = CONFIG_DIR / "heart_methods.json"
    weapons_cfg = json.loads(weapons_cfg_path.read_text(encoding="utf-8"))
    hearts_cfg = json.loads(hearts_cfg_path.read_text(encoding="utf-8"))
    heart_list = hearts_cfg["心法列表"]

    print(
        f"weapons.csv: {len(weapon_rows)} draft/final rows ({len(weapon_skipped)} legacy skipped)"
    )
    for w in weapons:
        action, diffs = _merge(weapons_cfg, w)
        print(f"  {action} {w['name']} [{w['rank']}]")
        print("\n".join(diffs) if diffs else "    (no field changes)")
    print(
        f"heart_methods.csv: {len(heart_rows)} draft/final rows ({len(heart_skipped)} legacy skipped)"
    )
    for h in hearts:
        action, diffs = _merge(heart_list, h)
        print(f"  {action} {h['name']} [{h['rank']}]")
        print("\n".join(diffs) if diffs else "    (no field changes)")

    # Budget gate: every draft/final design row must pass before any write.
    print("\nRunning budget gate (validate_budget.py)...")
    sys.stdout.flush()  # keep report order stable when stdout is piped
    gate = subprocess.run(
        [sys.executable, str(DESIGN_DIR / "validate_budget.py")],
        check=False,
    )
    if gate.returncode != 0:
        print("Budget gate FAILED, nothing was written.")
        return 1

    if args.dry_run:
        print("\nDry run: no files written.")
        return 0

    # Atomic per-file writes: serialize to a sibling temp file, then replace,
    # so a crash mid-write cannot leave a truncated config (review m5).
    for path, cfg in ((weapons_cfg_path, weapons_cfg), (hearts_cfg_path, hearts_cfg)):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    print(f"\nWrote {weapons_cfg_path} and {hearts_cfg_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
