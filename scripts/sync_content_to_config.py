#!/usr/bin/env python3
"""Sync content-design CSVs into runtime config JSONs (reconcile mode).

Reads ``design_docs/content-design/weapons.csv``, ``heart_methods.csv`` and
``skills.csv``, reconciles rows with status ``draft``/``final`` into
``config/weapons.json``, ``config/heart_methods.json`` and
``config/skills.json`` (keyed by item ``name``), and runs the budget gate
(``design_docs/content-design/validate_budget.py``) before writing.

Reconcile semantics: imported draft/final rows update same-name entries and
append new names; config entries absent from the CSVs are deleted. Rows with
status ``legacy`` are reference-only and always skipped (their config
counterparts are therefore deleted by reconcile).

skills.csv sync: trigger skills keep the persisted ``trigger_condition`` key
(the skill_manager normalization layer maps it to the engine contract key
``trigger_timing`` at load); ultimates are mandatory-cast (``trigger_rate``
MUST NOT be declared); effect values follow the 0.x additive contract
(``effect_value = x`` means ``x(1+x)`` on the effect base).

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

# skills.csv trigger_condition values (persisted key; the skill_manager
# normalization layer injects the engine contract key trigger_timing at load).
SKILL_TIMING_MAP = {
    "attack": "on_attack",
    "defend": "on_defense",
    "crit": "on_crit",
    "round_start": "round_start",
}

# Effect vocabulary consumed by the combat engine (EFFECT_HANDLERS registry).
# Keep in sync with managers/combat_manager.py EFFECT_HANDLERS (asserted by
# tests/test_sync_effect_vocabulary.py).
SKILL_EFFECT_TYPES = {
    "damage_bonus",
    "combo",
    "stun",
    "counter",
    "damage_reduction",
    "heal",
    "dot",
    "buff",
    "debuff",
    "pierce",
    "unavoidable",
    "reflect",
    "survive",
    "fatigue",
}

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
    exp_mult = _num(row.get("exp_multiplier", ""))
    if exp_mult is None:
        # Default matches equipment_manager.Item.exp_multiplier (0.0): an
        # absent cell means no cultivation bonus, never 1.0. Preserve 0.0.
        exp_mult = 0.0
    return {
        "id": (row.get("id") or "").strip(),
        "name": name,
        "description": (row.get("description") or "").strip(),
        "rank": (row.get("rank") or "").strip(),
        "required_level_index": _num(row.get("required_level_index", "")) or 0,
        "passive_bonus": passive,
        "exp_multiplier": exp_mult,
        "skill_pool": pool,
        "route": (row.get("route") or "").strip() or "通用",
        "shop_weight": _num(row.get("shop_weight", "")) or 0,
    }


def _validate_optional_keys(item: dict, ctx: str, errors: list[str]) -> None:
    """Contract-check the optional effect keys (spec: skill-system delta).

    Args:
        item: The trigger skill or ultimate dict.
        ctx: Context label for error messages.
        errors: Error list to append to.
    """
    if "duration" in item:
        d = item["duration"]
        if not isinstance(d, int) or d < 1:
            errors.append(f"{ctx}: duration must be an int >= 1, got {d!r}")
    for key, lo, hi in (
        ("tick_rate", 0.0, 1.0),
        ("heal_percent", 0.0, 1.0),
        ("pierce_rate", 0.0, 1.0),
        ("reflect_rate", 0.0, 1.0),
    ):
        if key in item:
            v = item[key]
            if not isinstance(v, (int, float)) or not lo <= v <= hi:
                errors.append(
                    f"{ctx}: {key} must be numeric in [{lo}, {hi}], got {v!r}"
                )
    if "survive_count" in item:
        c = item["survive_count"]
        if not isinstance(c, int) or c < 1:
            errors.append(f"{ctx}: survive_count must be an int >= 1, got {c!r}")


def _validate_ultimate(raw_json: str, ctx: str, errors: list[str]) -> dict | None:
    """Parse and contract-check an ultimate_json cell (mandatory-cast ultimates).

    Args:
        raw_json: The CSV cell text ("null" or empty means no ultimate).
        ctx: Context label for error messages.
        errors: Error list to append to.

    Returns:
        The parsed ultimate dict, or None when absent or invalid.
    """
    raw_json = (raw_json or "").strip()
    if not raw_json or raw_json == "null":
        return None
    try:
        ult = json.loads(raw_json)
    except json.JSONDecodeError as e:
        errors.append(f"{ctx}: ultimate_json is not valid JSON: {e}")
        return None
    if not isinstance(ult, dict):
        errors.append(f"{ctx}: ultimate_json must be a JSON object")
        return None
    if "trigger_rate" in ult:
        errors.append(
            f"{ctx}: ultimate MUST NOT declare trigger_rate (mandatory-cast, engine defaults to 1.0)"
        )
        return None
    for key in ("effect_type", "effect_value"):
        if key not in ult:
            errors.append(f"{ctx}: ultimate missing key {key!r}")
            return None
    if not isinstance(ult["effect_value"], (int, float)):
        errors.append(f"{ctx}: ultimate effect_value must be numeric")
        return None
    for key in (
        "min_action_index",
        "trigger_self_hp_below",
        "trigger_opponent_hp_below",
    ):
        if key in ult and not isinstance(ult[key], (int, float)):
            errors.append(f"{ctx}: ultimate {key} must be numeric")
            return None
    _validate_optional_keys(ult, ctx, errors)
    return ult


def _build_skill(row: dict, errors: list[str]) -> dict | None:
    """Map a skills.csv row to a config/skills.json entry (grouped format).

    Trigger skills keep the persisted ``trigger_condition`` key; the combat
    engine consumes the normalized ``trigger_timing`` key injected by the
    skill_manager normalization layer at load time. ``_pool`` is a merge-only
    marker (group key) and is never persisted.
    """
    name = (row.get("name") or "").strip()
    ctx = f"skills.csv[{name or row.get('id', '?')}]"
    if not name:
        errors.append(f"{ctx}: name is required")
        return None
    entry: dict[str, Any] = {
        "id": (row.get("id") or "").strip(),
        "name": name,
        "description": (row.get("description") or "").strip(),
        "_pool": (row.get("pool") or "").strip() or "通用功法池",
    }
    condition = (row.get("trigger_condition") or "").strip()
    trigger_name = (row.get("trigger_name") or "").strip()
    trigger_skill: dict | None = None
    if trigger_name or condition:
        if condition not in SKILL_TIMING_MAP:
            errors.append(
                f"{ctx}: unknown trigger_condition {condition!r} (allowed: {sorted(SKILL_TIMING_MAP)})"
            )
            return None
        rate = _num(row.get("trigger_rate", ""))
        if rate is None or not 0 < rate <= 1:
            errors.append(f"{ctx}: trigger_rate must be in (0, 1], got {rate!r}")
            return None
        effect_type = (row.get("effect_type") or "").strip()
        if effect_type not in SKILL_EFFECT_TYPES:
            errors.append(
                f"{ctx}: unknown effect_type {effect_type!r} (allowed: {sorted(SKILL_EFFECT_TYPES)})"
            )
            return None
        value = _num(row.get("effect_value", ""))
        if value is None:
            errors.append(f"{ctx}: effect_value is required for trigger skills")
            return None
        trigger_skill = {
            "name": trigger_name,
            "trigger_condition": condition,
            "trigger_rate": rate,
            "effect_type": effect_type,
            "effect_value": value,
        }
        for key in (
            "duration",
            "tick_rate",
            "heal_percent",
            "pierce_rate",
            "reflect_rate",
            "survive_count",
        ):
            cell = row.get(key, "")
            if (cell or "").strip():
                # A malformed cell must not crash the whole sync; collect it
                # into the per-row error gate instead (review fix).
                try:
                    trigger_skill[key] = _num(cell)
                except ValueError:
                    errors.append(f"{ctx}: {key} must be numeric, got {cell!r}")
        # stat is a string key selecting which stat buff/debuff modifies
        # (damage | armor | speed); engine defaults to damage when absent.
        if (row.get("stat") or "").strip():
            trigger_skill["stat"] = row["stat"].strip()
        vampire = (row.get("vampire") or "").strip().lower()
        if vampire in ("1", "true", "yes"):
            trigger_skill["vampire"] = True
        elif vampire and vampire not in ("0", "false", "no"):
            errors.append(
                f"{ctx}: vampire must be 1/true/yes or 0/false/no, got {vampire!r}"
            )
        _validate_optional_keys(trigger_skill, f"{ctx} trigger_skill", errors)
    # Persist None when the row omits the keys so the merge overwrites any
    # stale trigger/ultimate left in config by an earlier sync (review fix).
    entry["trigger_skill"] = trigger_skill
    ult = _validate_ultimate(row.get("ultimate_json", ""), ctx, errors)
    entry["ultimate"] = ult  # null when absent, so merge clears stale ultimate
    ling = _num(row.get("route_mult_ling", ""))
    ti = _num(row.get("route_mult_ti", ""))
    entry["route_multiplier"] = {
        "灵修": ling if ling is not None else 1.0,
        "体修": ti if ti is not None else 1.0,
    }
    return entry


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


def _merge_skill(groups: dict, payload: dict) -> tuple[str, list[str]]:
    """Merge a skills.csv row into the grouped skills config (dict-of-list).

    Same-name entries are updated field-by-field with their ``id`` preserved
    (player_skills references skill ids); new names are appended to the group
    named by the ``_pool`` marker.

    Args:
        groups: The loaded config/skills.json dict (group name -> list).
        payload: The built skill entry (may carry the ``_pool`` marker).

    Returns:
        (action, field diff lines) with action in {"UPDATE", "ADD"}.
    """
    name = payload["name"]
    pool = payload.pop("_pool")
    for group_key, entries in groups.items():
        for existing in entries:
            if existing.get("name") == name:
                diffs = []
                for key, value in payload.items():
                    if key == "id":
                        continue
                    old = existing.get(key, "<absent>")
                    if old != value:
                        diffs.append(
                            f"    {key}: {json.dumps(old, ensure_ascii=False)} -> {json.dumps(value, ensure_ascii=False)}"
                        )
                    existing[key] = value
                if group_key != pool:
                    entries.remove(existing)
                    groups.setdefault(pool, []).append(existing)
                    diffs.append(f"    _pool: {group_key!r} -> {pool!r}")
                return ("UPDATE", diffs)
    group = groups.setdefault(pool, [])
    group.append(payload)
    return ("ADD", [])


def _reconcile_list(entries: list[dict], imported_names: set[str]) -> list[str]:
    """Drop config entries absent from the imported design rows (reconcile).

    Args:
        entries: The config list to filter in place.
        imported_names: Names imported from the CSVs this run.

    Returns:
        The names of deleted entries.
    """
    deleted = [e["name"] for e in entries if e.get("name") not in imported_names]
    entries[:] = [e for e in entries if e.get("name") in imported_names]
    return deleted


def _reconcile_groups(groups: dict, imported_names: set[str]) -> list[str]:
    """Reconcile the grouped (dict-of-list) config format like _reconcile_list."""
    deleted = []
    for entries in groups.values():
        deleted.extend(
            e["name"] for e in entries if e.get("name") not in imported_names
        )
        entries[:] = [e for e in entries if e.get("name") in imported_names]
    return deleted


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
    skill_rows, skill_skipped = _load_rows("skills.csv")

    weapons = [w for r in weapon_rows if (w := _build_weapon(r, errors)) is not None]
    hearts = [h for r in heart_rows if (h := _build_heart(r, errors)) is not None]
    skills = [s for r in skill_rows if (s := _build_skill(r, errors)) is not None]

    # Names must be unique within each CSV (config is keyed by name).
    for label, items in (
        ("weapons", weapons),
        ("heart_methods", hearts),
        ("skills", skills),
    ):
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

    # Empty-import guard: an import set that is empty would make reconcile
    # delete every entry of that table. Refuse to write (dry-run may still
    # inspect the would-be DELETE list); transient mid-edit CSVs are the
    # usual cause (review fix).
    if not args.dry_run:
        for label, items in (
            ("weapons", weapons),
            ("heart_methods", hearts),
            ("skills", skills),
        ):
            if not items:
                print(
                    f"{label}: zero draft/final rows imported; refusing to write "
                    "(an empty import would reconcile-delete all entries). "
                    "Run with --dry-run to inspect the would-be deletions."
                )
                return 1

    weapons_cfg_path = CONFIG_DIR / "weapons.json"
    hearts_cfg_path = CONFIG_DIR / "heart_methods.json"
    skills_cfg_path = CONFIG_DIR / "skills.json"
    weapons_cfg = json.loads(weapons_cfg_path.read_text(encoding="utf-8"))
    hearts_cfg = json.loads(hearts_cfg_path.read_text(encoding="utf-8"))
    skills_cfg = json.loads(skills_cfg_path.read_text(encoding="utf-8"))
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
    print(
        f"skills.csv: {len(skill_rows)} draft/final rows ({len(skill_skipped)} legacy skipped)"
    )
    for s in skills:
        action, diffs = _merge_skill(skills_cfg, s)
        print(f"  {action} {s['name']}")
        print("\n".join(diffs) if diffs else "    (no field changes)")

    # Reconcile: drop config entries absent from the imported design rows.
    for label, entries, imported in (
        ("weapons.json", weapons_cfg, weapons),
        ("heart_methods.json", heart_list, hearts),
    ):
        deleted = _reconcile_list(entries, {x["name"] for x in imported})
        for name in deleted:
            print(f"  DELETE {name} ({label}, absent from CSV)")
    deleted = _reconcile_groups(skills_cfg, {s["name"] for s in skills})
    for name in deleted:
        print(f"  DELETE {name} (skills.json, absent from CSV)")

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
    for path, cfg in (
        (weapons_cfg_path, weapons_cfg),
        (hearts_cfg_path, hearts_cfg),
        (skills_cfg_path, skills_cfg),
    ):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    print(f"\nWrote {weapons_cfg_path}, {hearts_cfg_path} and {skills_cfg_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
