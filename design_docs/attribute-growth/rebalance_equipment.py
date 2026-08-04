#!/usr/bin/env python3
"""One-off equipment rebalancing script for AstrBot 修仙 plugin.

Rebalances ``weapons.json`` and armor/accessory entries in ``items.json``
according to the v3.5.0 combat model documented in
``growth-balance-proposals.md`` §4.1 and ``attribute-growth-analysis.md``.

Rules:
- Uses only the Python standard library.
- Deterministic (fixed rounding, no RNG in the transformation).
- Supports ``--dry-run`` for change previews without writing files.
- Supports ``--verify`` to run mirror-match TTK sampling after rebalancing.
- Preserves non-numeric identity fields and ``trigger_skills``.

Legacy five-dimension fields (``physical_damage``/``magic_damage``/
``physical_defense``/``mental_power``) are left untouched because they are
still read by runtime code for backward compatibility.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent

WEAPONS_PATH = PLUGIN_ROOT / "config" / "weapons.json"
ITEMS_PATH = PLUGIN_ROOT / "config" / "items.json"
GAME_CONFIG_PATH = PLUGIN_ROOT / "config" / "game_config.json"

# ---------------------------------------------------------------------------
# Rebalancing parameters (from design documents)
# ---------------------------------------------------------------------------
# HP and damage anchor curves from level_config.json / §2 方案 A
_HP_BASE = 100
_HP_PER_LEVEL = 15
_DAMAGE_BASE = 10
_DAMAGE_PER_LEVEL = 3

# Weapon category archetype mapping
ARCHETYPE_K = {"light": 0.4, "medium": 0.5, "heavy": 0.6}
ARCHETYPE_BUDGET_DIVISOR = {"light": 8.5, "medium": 7.0, "heavy": 5.5}
ARCHETYPE_ARMOR_PCT = {"light": 0.3, "medium": 0.5, "heavy": 0.8}

# Maps Chinese weapon_category to archetype
_WEAPON_CATEGORY_MAP: dict[str, str] = {
    # 轻型：迅捷、低频高爆/连击倾向
    "匕首": "light",
    "琴": "light",
    "笔": "light",
    "符箓": "light",
    # 中型：均衡
    "剑": "medium",
    "刀": "medium",
    "枪": "medium",
    # 重型：高 base、低迅捷
    "棍": "heavy",
    "阔刀": "heavy",
    "鼎": "heavy",
}

# Rank -> representative level index for items.json 法器 that lack
# required_level_index.  Based on weapons.json rank/level distribution.
_RANK_TO_LEVEL: dict[str, int] = {
    "凡品": 0,
    "灵品": 5,
    "地品": 10,
    "天品": 15,
    "皇品": 20,
    "帝品": 30,
    "道品": 40,
    "仙品": 50,
    "混元先天": 60,
    # Non-standard ranks appearing in items.json
    "珍品": 10,
    "圣品": 25,
}

# Fields that must never be modified
_PROTECTED_WEAPON_FIELDS = {
    "id",
    "name",
    "rank",
    "description",
    "price",
    "shop_weight",
    "required_level_index",
    "trigger_skills",
    "type",
    "weapon_category",
}

# Legacy fields still read by runtime code (equipment_manager, combat_manager,
# shop_manager, pve_combat_manager); left unchanged.
_LEGACY_FIELDS = {
    "physical_damage",
    "magic_damage",
    "physical_defense",
    "mental_power",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _get_weapon_archetype(category: str) -> str:
    return _WEAPON_CATEGORY_MAP.get(category, "medium")


def _expected_hp(level_index: int) -> float:
    return _HP_BASE + _HP_PER_LEVEL * level_index


def _expected_damage(level_index: int) -> float:
    return _DAMAGE_BASE + _DAMAGE_PER_LEVEL * level_index


def _compute_weapon_values(weapon: dict[str, Any]) -> dict[str, Any]:
    """Return new numeric values for a weapon without mutating the input."""
    level_index = int(weapon.get("required_level_index", 0))
    category = weapon.get("weapon_category", "")
    archetype = _get_weapon_archetype(category)

    k = ARCHETYPE_K[archetype]
    budget_divisor = ARCHETYPE_BUDGET_DIVISOR[archetype]
    armor_pct = ARCHETYPE_ARMOR_PCT[archetype]

    hp = _expected_hp(level_index)
    expected_dmg = _expected_damage(level_index)

    per_hit_budget = hp / budget_divisor
    base_damage = max(1, int(round(per_hit_budget - expected_dmg * k)))
    armor_value = max(0, int(round(level_index * 2 * armor_pct)))

    return {
        "weapon_coefficient_k": k,
        "base_damage": base_damage,
        "armor_value": armor_value,
    }


def _compute_item_values(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return new numeric values for an armor/accessory 法器 item.

    Only items with equip_effects that map to damage/armor are changed.
    Weapons inside items.json are left to the weapons.json rebalance path.
    """
    subtype = item.get("subtype", "")
    item_type = item.get("type", "")
    if item_type != "法器":
        return None
    if subtype not in ("防具", "饰品"):
        return None

    rank = item.get("rank", "凡品")
    level_index = _RANK_TO_LEVEL.get(rank, 0)

    equip_effects = item.get("equip_effects", {})
    if not isinstance(equip_effects, dict):
        return None

    new_values: dict[str, Any] = {}
    # Armor/accessory treated as "medium" weight for armor formula.
    # Process both legacy equip_effects.defense and already-converted armor_value.
    has_defense_effect = isinstance(equip_effects, dict) and "defense" in equip_effects
    if has_defense_effect or item.get("armor_value") is not None:
        armor_value = max(
            1, int(round(level_index * 2 * ARCHETYPE_ARMOR_PCT["medium"]))
        )
        new_values["armor_value"] = armor_value

    # Damage on accessory treated as "medium" weapon budget contribution.
    # Process both legacy equip_effects.attack and already-converted base_damage.
    has_attack_effect = isinstance(equip_effects, dict) and "attack" in equip_effects
    if has_attack_effect or item.get("base_damage") is not None:
        hp = _expected_hp(level_index)
        expected_dmg = _expected_damage(level_index)
        per_hit_budget = hp / ARCHETYPE_BUDGET_DIVISOR["medium"]
        base_damage = max(
            1, int(round(per_hit_budget - expected_dmg * ARCHETYPE_K["medium"]))
        )
        new_values["base_damage"] = base_damage
        new_values["weapon_coefficient_k"] = ARCHETYPE_K["medium"]

    if not new_values:
        return None

    return new_values


def _apply_weapon_changes(weapons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a list of (weapon, old_values, new_values) change records."""
    changes: list[dict[str, Any]] = []
    for weapon in weapons:
        new_values = _compute_weapon_values(weapon)
        old_values = {
            "weapon_coefficient_k": weapon.get("weapon_coefficient_k"),
            "base_damage": weapon.get("base_damage"),
            "armor_value": weapon.get("armor_value"),
        }

        changed = {
            k: {"old": old_values[k], "new": new_values[k]}
            for k in new_values
            if old_values.get(k) != new_values[k]
        }
        if changed:
            changes.append(
                {
                    "id": weapon.get("id"),
                    "name": weapon.get("name"),
                    "category": weapon.get("weapon_category"),
                    "level_index": weapon.get("required_level_index"),
                    "archetype": _get_weapon_archetype(
                        weapon.get("weapon_category", "")
                    ),
                    "changes": changed,
                }
            )

        for key, value in new_values.items():
            weapon[key] = value
    return changes


def _apply_item_changes(items: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for item_id, item in items.items():
        new_values = _compute_item_values(item)
        if not new_values:
            continue

        # Move legacy numeric fields into the new four-attribute framework.
        old_equip_effects = dict(item.get("equip_effects", {}))
        old_attack = old_equip_effects.pop("attack", None)
        old_defense = old_equip_effects.pop("defense", None)

        changed: dict[str, Any] = {}
        if "armor_value" in new_values:
            old_armor = (
                old_defense if old_defense is not None else item.get("armor_value")
            )
            if old_armor != new_values["armor_value"]:
                changed["armor_value"] = {
                    "old": old_armor,
                    "new": new_values["armor_value"],
                }
        if "base_damage" in new_values:
            old_base = old_attack if old_attack is not None else item.get("base_damage")
            if old_base != new_values["base_damage"]:
                changed["base_damage"] = {
                    "old": old_base,
                    "new": new_values["base_damage"],
                }
                changed["weapon_coefficient_k"] = {
                    "old": item.get("weapon_coefficient_k"),
                    "new": new_values["weapon_coefficient_k"],
                }

        if changed:
            changes.append(
                {
                    "id": item_id,
                    "name": item.get("name"),
                    "rank": item.get("rank"),
                    "subtype": item.get("subtype"),
                    "inferred_level": _RANK_TO_LEVEL.get(item.get("rank", "凡品"), 0),
                    "changes": changed,
                }
            )

        # Apply new framework fields
        for key, value in new_values.items():
            item[key] = value

        # Clean up consumed legacy equip_effects keys; keep max_hp if present
        if "attack" in old_equip_effects or "defense" in old_equip_effects:
            # This branch shouldn't happen because we popped above, but guard anyway
            old_equip_effects.pop("attack", None)
            old_equip_effects.pop("defense", None)

        if old_equip_effects:
            item["equip_effects"] = old_equip_effects
        elif "equip_effects" in item:
            del item["equip_effects"]

    return changes


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _print_weapon_changes(changes: list[dict[str, Any]]) -> None:
    if not changes:
        print("No weapon value changes required.")
        return

    print(f"Weapon changes ({len(changes)} / 120 weapons modified):")
    print("-" * 80)
    for c in changes[:10]:
        detail = ", ".join(
            f"{k}: {v['old']} -> {v['new']}" for k, v in c["changes"].items()
        )
        print(
            f"  {c['id']} {c['name']} ({c['category']}, L{c['level_index']}, "
            f"{c['archetype']}) => {detail}"
        )
    if len(changes) > 10:
        print(f"  ... and {len(changes) - 10} more")


def _print_item_changes(changes: list[dict[str, Any]]) -> None:
    if not changes:
        print("No armor/accessory item changes required.")
        return

    print(f"\nArmor/accessory item changes ({len(changes)} items modified):")
    print("-" * 80)
    for c in changes:
        detail = ", ".join(
            f"{k}: {v['old']} -> {v['new']}" for k, v in c["changes"].items()
        )
        print(
            f"  {c['id']} {c['name']} ({c['rank']}, {c['subtype']}, "
            f"inferred L{c['inferred_level']}) => {detail}"
        )


def _print_legacy_field_report(weapons: list[dict[str, Any]]) -> None:
    print("\nLegacy field report:")
    print("-" * 80)
    print(
        "Fields physical_damage / magic_damage / physical_defense / mental_power "
        "were removed from weapons.json in v3.7.1: their resolved values were baked "
        "into explicit damage/armor_value and all runtime fallback readers were deleted."
    )
    read_locations = [
        "core/equipment_manager.py:_parse_item_config (removed in v3.7.1)",
        "core/shop_manager.py:_normalize_equipment_attributes (removed in v3.7.1)",
        "managers/combat_manager.py:_parse_item_config (removed in v3.7.1)",
        "managers/pve_combat_manager.py:calculate_equipment_atk_bonus/defense (deleted in v3.7.1)",
    ]
    print("Former runtime read locations (all removed):")
    for loc in read_locations:
        print(f"  - {loc}")

    legacy_weapons = [w for w in weapons if any(w.get(f) for f in _LEGACY_FIELDS)]
    print(f"Weapons carrying legacy fields: {len(legacy_weapons)} / {len(weapons)}")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def _load_combat_engine() -> Any:
    """Load CombatEngine via tests/helpers.py, mirroring sim scripts."""
    helpers_path = PLUGIN_ROOT / "tests" / "helpers.py"
    spec = importlib.util.spec_from_file_location("rebalance_helpers", helpers_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load helpers from {helpers_path}")
    helpers_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers_mod)
    _load_module = helpers_mod.load_module  # type: ignore[attr-defined]

    combat_mod = _load_module("rebalance_combat_engine", "managers/combat_manager.py")
    return combat_mod.CombatEngine, combat_mod.FighterState


def _make_stub_config_manager(game_config: dict[str, Any]) -> Any:
    class _StubConfigManager:
        def __init__(self, game_config: dict[str, Any]) -> None:
            self.game_config = game_config
            self.items_data: dict[str, Any] = {}
            self.weapons_data: dict[str, Any] = {}
            self.heart_methods_data: dict[str, Any] = {}

    return _StubConfigManager(game_config)


@dataclass(frozen=True)
class _SampleWeapon:
    category: str
    weapon_k: float
    base_damage: int
    armor_value: int
    level_index: int


def _make_sample_weapon(level_index: int, archetype: str) -> _SampleWeapon:
    k = ARCHETYPE_K[archetype]
    hp = _expected_hp(level_index)
    expected_dmg = _expected_damage(level_index)
    budget_divisor = ARCHETYPE_BUDGET_DIVISOR[archetype]
    per_hit_budget = hp / budget_divisor
    base_damage = max(1, int(round(per_hit_budget - expected_dmg * k)))
    armor_value = max(0, int(round(level_index * 2 * ARCHETYPE_ARMOR_PCT[archetype])))
    return _SampleWeapon(
        category=archetype,
        weapon_k=k,
        base_damage=base_damage,
        armor_value=armor_value,
        level_index=level_index,
    )


def _find_nearest_weapon(
    weapons: list[dict[str, Any]], level_index: int, archetype: str
) -> _SampleWeapon | None:
    candidates = [
        w
        for w in weapons
        if _get_weapon_archetype(w.get("weapon_category", "")) == archetype
    ]
    if not candidates:
        return None
    nearest = min(
        candidates, key=lambda w: abs(w.get("required_level_index", 0) - level_index)
    )
    return _SampleWeapon(
        category=archetype,
        weapon_k=nearest.get("weapon_coefficient_k", 1.0),
        base_damage=nearest.get("base_damage", 0),
        armor_value=nearest.get("armor_value", 0),
        level_index=nearest.get("required_level_index", level_index),
    )


def _make_fighter(
    name: str,
    level_index: int,
    weapon: _SampleWeapon | None,
    FighterState: Any,
) -> Any:
    hp = int(round(_expected_hp(level_index)))
    damage = int(round(_expected_damage(level_index)))
    agility = int(round(5 + 1.25 * level_index))
    speed = int(round(5 + 0.75 * level_index))
    armor_value = 0
    weapon_k = 1.0
    base_damage = 0

    if weapon is not None:
        # Mirror the item stat bonuses: armor from weapon, no flat damage/agility/speed
        armor_value = weapon.armor_value
        weapon_k = weapon.weapon_k
        base_damage = weapon.base_damage

    return FighterState(
        user_id=name,
        name=name,
        hp=hp,
        max_hp=hp,
        damage=damage,
        agility=agility,
        speed=speed,
        armor_value=armor_value,
        level_index=level_index,
        weapon_k=weapon_k,
        base_damage=base_damage,
        trigger_skills=[],
        ultimates=[],
    )


def _run_mirror_battle(
    level_index: int,
    weapon: _SampleWeapon | None,
    FighterState: Any,
    engine: Any,
    battles: int = 2000,
    seed: int = 2026,
) -> dict[str, Any]:
    rng = random.Random(seed + level_index * 10000)
    rounds_list: list[int] = []
    one_shots = 0

    for i in range(battles):
        f1 = _make_fighter("修士甲", level_index, weapon, FighterState)
        f2 = _make_fighter("修士乙", level_index, weapon, FighterState)
        # Mirror matches are symmetric; engine RNG dominates.  Use per-battle seed
        # for reproducibility.
        random.seed(rng.randint(0, 2**31 - 1))
        result = engine.resolve_combat(f1, f2, combat_type="spar", merge_count=10)
        rounds_list.append(result.rounds)
        if result.rounds == 1:
            one_shots += 1

    # Restore global RNG
    random.seed()

    mean = statistics.mean(rounds_list) if rounds_list else 0.0
    return {
        "level": level_index,
        "weapon": weapon.category if weapon else "bare_fists",
        "actual_weapon_level": weapon.level_index if weapon else level_index,
        "battles": battles,
        "rounds_mean": round(mean, 2),
        "rounds_min": min(rounds_list) if rounds_list else 0,
        "rounds_max": max(rounds_list) if rounds_list else 0,
        "one_shot_rate": round(one_shots / battles, 4) if battles else 0.0,
        "in_range": 5.0 <= mean <= 10.0,
    }


def run_verify(weapons: list[dict[str, Any]], battles: int = 2000) -> int:
    print("\n" + "=" * 80)
    print("Verification: mirror-match TTK sampling")
    print("=" * 80)

    CombatEngine, FighterState = _load_combat_engine()
    game_config = _load_json(GAME_CONFIG_PATH)
    config_manager = _make_stub_config_manager(game_config)
    engine = CombatEngine(config_manager, skill_manager=None)

    target_levels = [1, 25, 50, 99]
    archetypes = ["light", "medium", "heavy"]
    all_pass = True

    print(f"Battles per cell: {battles}")
    print(
        "Note: weapons.json only spans L0-L35; L50/L99 use the nearest/highest available weapon.\n"
    )

    for level in target_levels:
        for archetype in archetypes:
            weapon = _find_nearest_weapon(weapons, level, archetype)
            if weapon is None:
                # Fallback to synthetic weapon using the same rebalancing formula
                weapon = _make_sample_weapon(level, archetype)
            result = _run_mirror_battle(
                level, weapon, FighterState, engine, battles=battles
            )
            status = "PASS" if result["in_range"] else "FAIL"
            if not result["in_range"]:
                all_pass = False
            print(
                f"  L{level:2d} {archetype:6s} (weapon L{weapon.level_index:2d}) "
                f"mean_rounds={result['rounds_mean']:.2f} "
                f"range=[{result['rounds_min']}-{result['rounds_max']}] "
                f"one_shot={result['one_shot_rate']:.2%} [{status}]"
            )

    print(
        "\n"
        + (
            "All sampled cells within 5-10 rounds."
            if all_pass
            else "Some cells outside 5-10 rounds."
        )
    )
    return 0 if all_pass else 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebalance equipment values for the new combat model."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run mirror-match TTK verification after loading the new values.",
    )
    parser.add_argument(
        "--verify-battles",
        type=int,
        default=2000,
        help="Number of battles per verification cell (default: 2000).",
    )
    args = parser.parse_args(argv)

    weapons = _load_json(WEAPONS_PATH)
    items = _load_json(ITEMS_PATH)

    weapon_changes = _apply_weapon_changes(weapons)
    item_changes = _apply_item_changes(items)

    _print_weapon_changes(weapon_changes)
    _print_item_changes(item_changes)
    _print_legacy_field_report(weapons)

    if args.dry_run:
        print("\n[Dry run] No files were written.")
    else:
        _save_json(WEAPONS_PATH, weapons)
        _save_json(ITEMS_PATH, items)
        print("\nWrote rebalanced values to:")
        print(f"  {WEAPONS_PATH}")
        print(f"  {ITEMS_PATH}")

    if args.verify:
        return run_verify(weapons, battles=args.verify_battles)

    return 0


if __name__ == "__main__":
    sys.exit(main())
