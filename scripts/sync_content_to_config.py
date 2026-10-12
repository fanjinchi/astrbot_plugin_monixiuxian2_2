#!/usr/bin/env python3
"""Sync content-design CSVs into runtime config JSONs (reconcile mode).

Reads ``design_docs/content-design/weapons.csv``, ``heart_methods.csv``,
``skills.csv`` and ``armors.csv``, reconciles rows with status
``draft``/``final`` into ``config/weapons.json``, ``config/heart_methods.json``,
``config/skills.json`` and the 法器/防具 slice of ``config/items.json`` (keyed
by item ``name``), and runs two gates before writing: the budget gate
(``design_docs/content-design/validate_budget.py``) and the narrative lint
gate (``design_docs/content-design/lint_narrative.py``, spec
content-sync-pipeline — 初版仅 ``narrative_status=定稿`` 行 FAIL 阻塞).

Armor notes: items.json is a mixed pool (丹药/材料/功法/法器), so reconcile
deletion applies ONLY to entries with ``type=法器, subtype=防具`` — the armor
CSV owns just that slice. ``bonus_hp`` imports as the new-framework direct key
``hp`` (the engine aggregates ``item.hp``; the legacy ``equip_effects.max_hp``
field is not mapped by the engine and is not used).

Reconcile semantics: imported draft/final rows update same-name entries and
append new names; config entries absent from the CSVs are deleted. Rows with
status ``legacy`` are reference-only and never imported; their config
counterparts are PROTECTED from reconcile deletion (a legacy row is the
registry entry for live content not yet brought under design management, e.g.
sect pools backfilled by ``export_config_to_canon.py``). To remove content
from config, delete its CSV row entirely.

skills.csv sync: trigger skills keep the persisted ``trigger_condition`` key
(the skill_manager normalization layer maps it to the engine contract key
``trigger_timing`` at load); ultimates are mandatory-cast (``trigger_rate``
MUST NOT be declared); effect values follow the 0.x additive contract
(``effect_value = x`` means ``x(1+x)`` on the effect base).

Enemy/world-boss fixed roster (Trellis 10-10-pve-enemy-catalog-runtime) is a
SEPARATE domain with governance gating and is NOT synced by a bare run:

- ``--enemies-preview-out PATH``: render enemies.csv + world_bosses.csv into a
  schema-v2 combat-profile document at PATH (memory/tmp use; e.g. tests). Draft
  rows are allowed here; the render carries ``source.mode="preview"`` and
  ``approval=null`` — preview can never carry or forge formal approval state.
- ``--approval-manifest PATH``: formal write. Requires every non-guardian row
  ``status=final``, narrative decisions approved per dataset, CSV SHA-256 and
  column scope matching the manifest, else the whole run aborts WITHOUT
  touching config/enemies.json (fail closed). Legacy sections
  (enemy_groups/drop_tables/naming) pass through from the existing config.

Usage:
    uv run python scripts/sync_content_to_config.py [--dry-run] \
        [--enemies-preview-out PATH | --approval-manifest PATH]

Returns:
    Exit code 0 on success (or successful dry-run), 1 on contract errors or
    budget-gate failure. Nothing is written unless every check passes.
"""

import argparse
import csv
import importlib.util
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


def _load_rows(
    filename: str, base_dir: Path | None = None
) -> tuple[list[dict], list[dict]]:
    """Load a design CSV, splitting (syncable draft/final rows, skipped legacy rows)."""
    with ((base_dir or DESIGN_DIR) / filename).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    active = [r for r in rows if (r.get("status") or "").strip() in ("draft", "final")]
    skipped = [
        r for r in rows if (r.get("status") or "").strip() not in ("draft", "final")
    ]
    return active, skipped


_ENEMY_SCHEMA_MOD = None


def _load_enemy_schema():
    """Load core/enemy_schema.py by file spec (its parent package pulls astrbot).

    Returns:
        The schema module object (cached across calls).
    """
    global _ENEMY_SCHEMA_MOD
    if _ENEMY_SCHEMA_MOD is None:
        path = PLUGIN_ROOT / "core" / "enemy_schema.py"
        spec = importlib.util.spec_from_file_location("sync_enemy_schema", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _ENEMY_SCHEMA_MOD = mod
    return _ENEMY_SCHEMA_MOD


def render_enemy_document(
    design_dir: Path,
    *,
    manifest: dict | None,
    manifest_path: Path | None,
    existing_config: dict | None,
) -> tuple[dict, list[str]]:
    """Render the fixed-roster enemies/world-boss document from design CSVs.

    Two modes (Child B R1/AC1): ``manifest=None`` is preview rendering — draft
    rows allowed, ``source.approval`` stays None; formal rendering runs the
    fail-closed approval gate and passes the legacy specialist sections
    through from ``existing_config``.

    Args:
        design_dir: directory holding enemies.csv / world_bosses.csv.
        manifest: parsed approval manifest (formal mode only).
        manifest_path: manifest file location for the audit block.
        existing_config: current config/enemies.json (formal passthrough).

    Returns:
        ``(document, errors)``; document is ``{}`` when errors are present.
    """
    schema = _load_enemy_schema()
    errors: list[str] = []
    roster_csv = design_dir / schema.ROSTER_CSV
    boss_csv = design_dir / schema.WORLD_BOSS_CSV
    try:
        csv_hashes = {
            schema.ROSTER_CSV: schema.sha256_file(roster_csv),
            schema.WORLD_BOSS_CSV: schema.sha256_file(boss_csv),
        }
    except OSError as exc:
        return {}, [f"敌人 CSV 源读取失败: {exc}"]

    roster_rows, _ = _load_rows(schema.ROSTER_CSV, base_dir=design_dir)
    boss_rows, _ = _load_rows(schema.WORLD_BOSS_CSV, base_dir=design_dir)

    entries: list[dict] = []
    for row in roster_rows:
        ctx = f"{schema.ROSTER_CSV}[{(row.get('id') or '?').strip()}]"
        entry = schema.build_enemy_profile(row, ctx, errors)
        if entry is not None:
            entries.append(entry)
    bosses: list[dict] = []
    for row in boss_rows:
        ctx = f"{schema.WORLD_BOSS_CSV}[{(row.get('id') or '?').strip()}]"
        entry = schema.build_world_boss_profile(row, ctx, errors)
        if entry is not None:
            bosses.append(entry)

    # Stable ids must be unique across the whole roster (catalog index key).
    for label, items in (("enemies", entries), ("world_bosses", bosses)):
        seen: set[str] = set()
        for item in items:
            if item["id"] in seen:
                errors.append(f"{label}: duplicate id {item['id']!r}")
            seen.add(item["id"])

    if not entries:
        errors.append("enemies: 无名册条目可渲染（空导入会清空正式配置，拒绝）")
    if not bosses:
        errors.append("world_bosses: 无世界 Boss 档案可渲染（空导入拒绝）")

    # 守护者行是专项组配置（动态匹配），不进名册 sections；审批闸门口径
    # 只覆盖实际写入的行，draft 守护行不阻塞 Batch 5 正式同步。
    gate_roster = [r for r in roster_rows if (r.get("tier") or "") != "guardian"]

    doc: dict[str, Any] = {
        "schema_version": schema.SCHEMA_VERSION,
        "profile_version": schema.PROFILE_VERSION,
        "generator": schema.GENERATOR,
        "source": {
            "mode": "preview" if manifest is None else "formal",
            "approval": None
            if manifest is None
            else {
                "manifest_path": str(manifest_path) if manifest_path else "",
                "manifest_sha256": (
                    schema.sha256_file(manifest_path) if manifest_path else None
                ),
                "datasets": manifest.get("datasets", {}),
            },
            schema.ROSTER_CSV: {
                "path": f"design_docs/content-design/{schema.ROSTER_CSV}",
                "sha256": csv_hashes[schema.ROSTER_CSV],
                "rows": len(entries),
            },
            schema.WORLD_BOSS_CSV: {
                "path": f"design_docs/content-design/{schema.WORLD_BOSS_CSV}",
                "sha256": csv_hashes[schema.WORLD_BOSS_CSV],
                "rows": len(bosses),
            },
        },
        "enemies": sorted(entries, key=lambda e: e["id"]),
        "world_bosses": sorted(bosses, key=lambda b: b["id"]),
    }

    if manifest is not None:
        errors.extend(
            schema.check_approval(
                manifest,
                csv_hashes,
                {schema.ROSTER_CSV: gate_roster, schema.WORLD_BOSS_CSV: boss_rows},
                require_final=True,
            )
        )
        if existing_config is None:
            errors.append("正式写入需要现有 config/enemies.json 作为专项组透传源")
        else:
            # 守护者/掉落/命名沿用现有配置段直到 Batch 5 切流（R4：专项组
            # 不退化；drop_tables 有 adventure_manager 消费者）。
            for key in ("enemy_groups", "drop_tables", "naming"):
                if key in existing_config:
                    doc[key] = existing_config[key]

    if errors:
        return {}, errors
    errors.extend(schema.validate_enemy_document(doc))
    if errors:
        return {}, errors
    return doc, []


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
    route_mult_ling = _num(row.get("route_mult_ling", ""))
    route_mult_ti = _num(row.get("route_mult_ti", ""))
    route_multiplier = {
        "灵修": 1.0 if route_mult_ling is None else route_mult_ling,
        "体修": 1.0 if route_mult_ti is None else route_mult_ti,
    }
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
        "route_multiplier": route_multiplier,
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


def _build_armor(row: dict, errors: list[str]) -> dict | None:
    """Map an armors.csv row to a config/items.json armor entry (法器/防具)."""
    name = (row.get("name") or "").strip()
    ctx = f"armors.csv[{name or row.get('id', '?')}]"
    if not name:
        errors.append(f"{ctx}: name is required")
        return None
    entry = {
        "name": name,
        "type": "法器",
        "subtype": "防具",
        "rank": (row.get("rank") or "").strip(),
        "required_level_index": _num(row.get("required_level_index", "")) or 0,
        "description": (row.get("description") or "").strip(),
        "price": _num(row.get("price", "")) or 0,
        "shop_weight": _num(row.get("shop_weight", "")) or 0,
        "armor_value": _num(row.get("armor_value", "")) or 0,
        "route_multiplier": {
            "灵修": _num(row.get("route_mult_ling", "")) or 1.0,
            "体修": _num(row.get("route_mult_ti", "")) or 1.0,
        },
    }
    # bonus_hp 入库为新框架直读键 hp（models.py 属性汇总读 item.hp）；
    # 旧 equip_effects.max_hp 引擎并不映射（月华袍/泰坦之铠的 max_hp 实际无效），
    # 故不沿用。0 值不写入（凡品重甲为纯甲件）。
    bonus = _num(row.get("bonus_hp", ""))
    if bonus:
        entry["hp"] = bonus
    return entry


def _merge_armor(items_cfg: dict, payload: dict) -> tuple[str, list[str]]:
    """Merge an armor payload into the items.json dict-of-dict by name.

    Identity is the item name; an existing entry's numeric dict key is
    preserved (keys are config-internal — player/storage references resolve
    by name). New entries get a fresh key above the current numeric max.
    """
    for key, existing in items_cfg.items():
        if isinstance(existing, dict) and existing.get("name") == payload["name"]:
            diffs = []
            for k, value in payload.items():
                old = existing.get(k, "<absent>")
                if old != value:
                    diffs.append(
                        f"    {k}: {json.dumps(old, ensure_ascii=False)} -> {json.dumps(value, ensure_ascii=False)}"
                    )
                existing[k] = value
            # 清掉 payload 不再携带的键（如 bonus_hp=0 时不写 hp）
            for k in list(existing.keys()):
                if k not in payload and k not in ("id",):
                    diffs.append(f"    {k}: removed (absent from design row)")
                    del existing[k]
            return ("UPDATE", diffs)
    numeric_keys = [int(k) for k in items_cfg if str(k).isdigit()]
    new_key = str(max(numeric_keys, default=3000) + 1)
    items_cfg[new_key] = payload
    return ("ADD", [f"    _key: {new_key}"])


def _reconcile_armors(
    items_cfg: dict,
    imported_names: set[str],
    protected_names: set[str] | None = None,
) -> list[str]:
    """Reconcile only the 法器/防具 slice of items.json; other types untouched.

    items.json is a mixed pool (丹药/材料/功法/法器), so the whole-file
    reconcile semantics of ``_reconcile_list`` cannot apply — the armor
    design table only owns the armor slice.
    """
    keep = imported_names | (protected_names or set())
    deleted = []
    for key in list(items_cfg.keys()):
        e = items_cfg[key]
        if (
            isinstance(e, dict)
            and e.get("type") == "法器"
            and e.get("subtype") == "防具"
            and e.get("name") not in keep
        ):
            deleted.append(e["name"])
            del items_cfg[key]
    return deleted


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


def _reconcile_list(
    entries: list[dict],
    imported_names: set[str],
    protected_names: set[str] | None = None,
) -> list[str]:
    """Drop config entries absent from the imported design rows (reconcile).

    Args:
        entries: The config list to filter in place.
        imported_names: Names imported from the CSVs this run.
        protected_names: Names present in the CSV with a non-imported status
            (``legacy``); their config entries are kept (see module docstring).

    Returns:
        The names of deleted entries.
    """
    keep = imported_names | (protected_names or set())
    deleted = [e["name"] for e in entries if e.get("name") not in keep]
    entries[:] = [e for e in entries if e.get("name") in keep]
    return deleted


def _reconcile_groups(
    groups: dict, imported_names: set[str], protected_names: set[str] | None = None
) -> list[str]:
    """Reconcile the grouped (dict-of-list) config format like _reconcile_list."""
    keep = imported_names | (protected_names or set())
    deleted = []
    for entries in groups.values():
        deleted.extend(e["name"] for e in entries if e.get("name") not in keep)
        entries[:] = [e for e in entries if e.get("name") in keep]
    return deleted


def main() -> int:
    """Run the sync. Returns process exit code."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the merge summary without writing files",
    )
    parser.add_argument(
        "--enemies-preview-out",
        metavar="PATH",
        help="render enemies/world-boss schema-v2 preview document to PATH "
        "(draft rows allowed; never touches config/)",
    )
    parser.add_argument(
        "--approval-manifest",
        metavar="PATH",
        help="approval manifest JSON required for the FORMAL enemy-domain "
        "write; without it the enemy domain is skipped entirely",
    )
    args = parser.parse_args()

    if args.enemies_preview_out:
        if args.approval_manifest:
            print(
                "Contract errors, nothing was written:\n"
                "  ERROR preview 模式不得携带 --approval-manifest"
                "（preview 不得接受或伪造正式批准状态）"
            )
            return 1
        preview_target = Path(args.enemies_preview_out).resolve()
        if preview_target.is_relative_to(CONFIG_DIR.resolve()):
            # 预览文档缺 enemy_groups/drop_tables/naming 透传键，落进
            # config/ 会毁掉守护/秘境定向组数据；正式写只走 manifest 路径。
            print(
                "Contract errors, nothing was written:\n"
                f"  ERROR preview 输出不得位于正式配置目录 {CONFIG_DIR}"
                "（draft 预览禁止触碰正式 config/）"
            )
            return 1
        doc, preview_errors = render_enemy_document(
            DESIGN_DIR,
            manifest=None,
            manifest_path=None,
            existing_config=None,
        )
        if preview_errors:
            print("Contract errors, nothing was written:")
            for e in preview_errors:
                print(f"  ERROR {e}")
            return 1
        out = Path(args.enemies_preview_out)
        if args.dry_run:
            print(f"Dry run: preview would be written to {out} (no files written).")
            return 0
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(out)
        print(
            f"Preview rendered {len(doc['enemies'])} roster + "
            f"{len(doc['world_bosses'])} world-boss profiles -> {out}"
        )
        return 0

    errors: list[str] = []
    weapon_rows, weapon_skipped = _load_rows("weapons.csv")
    heart_rows, heart_skipped = _load_rows("heart_methods.csv")
    skill_rows, skill_skipped = _load_rows("skills.csv")
    armor_rows, armor_skipped = _load_rows("armors.csv")

    weapons = [w for r in weapon_rows if (w := _build_weapon(r, errors)) is not None]
    hearts = [h for r in heart_rows if (h := _build_heart(r, errors)) is not None]
    skills = [s for r in skill_rows if (s := _build_skill(r, errors)) is not None]
    armors = [a for r in armor_rows if (a := _build_armor(r, errors)) is not None]

    # Names must be unique within each CSV (config is keyed by name).
    for label, items in (
        ("weapons", weapons),
        ("heart_methods", hearts),
        ("skills", skills),
        ("armors", armors),
    ):
        seen: set[str] = set()
        for item in items:
            if item["name"] in seen:
                errors.append(f"{label}: duplicate name {item['name']!r} in CSV")
            seen.add(item["name"])

    enemies_doc: dict | None = None
    enemies_cfg_path = CONFIG_DIR / "enemies.json"
    if args.approval_manifest:
        manifest_path = Path(args.approval_manifest)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"approval manifest 读取失败: {exc}")
            manifest = None
        existing: dict | None
        try:
            existing = json.loads(enemies_cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"现有 config/enemies.json 读取失败: {exc}")
            existing = None
        enemies_doc, enemy_errors = render_enemy_document(
            DESIGN_DIR,
            manifest=manifest,
            manifest_path=manifest_path,
            existing_config=existing,
        )
        errors.extend(enemy_errors)

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
            ("armors", armors),
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
    items_cfg_path = CONFIG_DIR / "items.json"
    weapons_cfg = json.loads(weapons_cfg_path.read_text(encoding="utf-8"))
    hearts_cfg = json.loads(hearts_cfg_path.read_text(encoding="utf-8"))
    skills_cfg = json.loads(skills_cfg_path.read_text(encoding="utf-8"))
    items_cfg = json.loads(items_cfg_path.read_text(encoding="utf-8"))
    heart_list = hearts_cfg["心法列表"]

    # Armor names must not collide with non-防具 items (runtime resolves by name
    # across the whole items pool; a collision would shadow the other entry).
    armor_names = {a["name"] for a in armors}
    for key, existing in items_cfg.items():
        if (
            isinstance(existing, dict)
            and existing.get("name") in armor_names
            and not (
                existing.get("type") == "法器" and existing.get("subtype") == "防具"
            )
        ):
            print(
                f"items.json[{key}]: name {existing['name']!r} collides with an "
                "armors.csv row but is not 法器/防具; nothing was written."
            )
            return 1

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
    print(
        f"armors.csv: {len(armor_rows)} draft/final rows ({len(armor_skipped)} legacy skipped)"
    )
    for a in armors:
        action, diffs = _merge_armor(items_cfg, a)
        print(f"  {action} {a['name']} [{a['rank']}]")
        print("\n".join(diffs) if diffs else "    (no field changes)")

    # Reconcile: drop config entries absent from the CSVs entirely. legacy rows
    # are not imported but PROTECT their config counterparts from deletion
    # (module docstring; removal of content = delete the CSV row).
    protected = {
        label: {(r.get("name") or "").strip() for r in skipped}
        for label, skipped in (
            ("weapons.json", weapon_skipped),
            ("heart_methods.json", heart_skipped),
            ("skills.json", skill_skipped),
            ("items.json", armor_skipped),
        )
    }
    for label, entries, imported in (
        ("weapons.json", weapons_cfg, weapons),
        ("heart_methods.json", heart_list, hearts),
    ):
        deleted = _reconcile_list(
            entries, {x["name"] for x in imported}, protected[label]
        )
        for name in deleted:
            print(f"  DELETE {name} ({label}, absent from CSV)")
    deleted = _reconcile_groups(
        skills_cfg, {s["name"] for s in skills}, protected["skills.json"]
    )
    for name in deleted:
        print(f"  DELETE {name} (skills.json, absent from CSV)")
    deleted = _reconcile_armors(
        items_cfg, {a["name"] for a in armors}, protected["items.json"]
    )
    for name in deleted:
        print(f"  DELETE {name} (items.json 防具, absent from CSV)")

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

    # Narrative lint gate: second gate after budget check (spec
    # content-sync-pipeline 叙事文案 lint 闸门). Initial version only FAILs
    # narrative_status=定稿 rows (lint_narrative.py default mode), the rest
    # WARN — giving canon 回填 a window before full enforcement (design.md 风险节).
    print("\nRunning narrative lint gate (lint_narrative.py)...")
    sys.stdout.flush()  # keep report order stable when stdout is piped
    lint_gate = subprocess.run(
        [sys.executable, str(DESIGN_DIR / "lint_narrative.py")],
        check=False,
    )
    if lint_gate.returncode != 0:
        print("Narrative lint gate FAILED, nothing was written.")
        return 1

    if args.dry_run:
        print("\nDry run: no files written.")
        return 0

    # Atomic per-file writes: serialize to a sibling temp file, then replace,
    # so a crash mid-write cannot leave a truncated config (review m5).
    write_pairs = [
        (weapons_cfg_path, weapons_cfg),
        (hearts_cfg_path, hearts_cfg),
        (skills_cfg_path, skills_cfg),
        (items_cfg_path, items_cfg),
    ]
    if enemies_doc is not None:
        write_pairs.append((enemies_cfg_path, enemies_doc))
    else:
        print(
            "enemy/world-boss domain: SKIPPED (无 --approval-manifest；"
            "固定名册正式写入在 Batch 5 内容批准后执行)"
        )
    for path, cfg in write_pairs:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    wrote = [str(p) for p, _ in write_pairs]
    print("\nWrote " + ", ".join(wrote) + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
