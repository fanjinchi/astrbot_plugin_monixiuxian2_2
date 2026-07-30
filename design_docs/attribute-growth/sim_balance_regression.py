"""Balance regression simulation harness for AstrBot 修仙 plugin.

Runs mirror-match battles under the "方案 A" growth model (§2 of
`growth-balance-proposals.md`) with budget-grade weapons (§4.1) to
produce a baseline CSV and built-in acceptance checks (G1/G2).

This script is designed to work with the **current unmodified** CombatEngine
so that it can serve as a regression harness before and after the growth /
armor / caps changes land.

Assumptions (documented in code and output):
- Budget weapons are synthetic: base_damage, weapon_k, and a flat damage bonus
  are derived from the "每击预算" in §4.1.  They do NOT read from the existing
  weapons.json because those values are known to be unbalanced (one-shot at
  all levels per `xiuxian-methodology.md` §4.3).
- The "期望模式" uses the exact anchor curve from level_config.json base_*
  (hp=100+15*(L-1), damage=10+3*(L-1), agility=5+1.25*(L-1), speed=5+0.75*(L-1)).
- The "随机实现模式" uses a fixed-seed RNG to sample per-level growth.

Only writes under design_docs/attribute-growth/.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths and module loading (mirrors sim_xiuxian_turns.py)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent


def _load_helpers() -> Any:
    helpers_path = PLUGIN_ROOT / "tests" / "helpers.py"
    spec = importlib.util.spec_from_file_location("reg_test_helpers", helpers_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load helpers from {helpers_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


helpers_mod = _load_helpers()
_load_module = helpers_mod.load_module

_combat_mod = _load_module("reg_combat_engine", "managers/combat_manager.py")
CombatEngine = _combat_mod.CombatEngine
FighterState = _combat_mod.FighterState

# ---------------------------------------------------------------------------
# Config loading (minimal, only for CombatEngine constructor)
# ---------------------------------------------------------------------------
GAME_CONFIG_PATH = PLUGIN_ROOT / "config" / "game_config.json"

with GAME_CONFIG_PATH.open("r", encoding="utf-8") as f:
    game_config_raw = json.load(f)


class _StubConfigManager:
    """Minimal config container required by CombatEngine."""

    def __init__(self, game_config: dict[str, Any]) -> None:
        self.game_config = game_config
        self.items_data: dict[str, Any] = {}
        self.weapons_data: dict[str, Any] = {}
        self.heart_methods_data: dict[str, Any] = {}


CONFIG_MANAGER = _StubConfigManager(game_config=game_config_raw)
ENGINE = CombatEngine(CONFIG_MANAGER, skill_manager=None)

# ---------------------------------------------------------------------------
# Scenario parameters (from design document §2 / §4)
# ---------------------------------------------------------------------------
# §2 方案 A: 期望曲线 (小数保留在模拟内部，FighterState 取整)
# hp = 100 + 15 * (L - 1)
# damage = 10 + 3 * (L - 1)
# agility = 5 + 1.25 * (L - 1)
# speed = 5 + 0.75 * (L - 1)
#
# §4.1 武器预算 (每击期望预算 = 同级 HP 的固定比例)
# 轻型: HP / 10 ~ HP / 8  (低 base, 高 speed/agility, 连击)
# 中型: HP / 8  ~ HP / 6  (均衡)
# 重型: HP / 6  ~ HP / 4  (高 base, 低 speed, 低频高伤)
#
# 武器面板合成假设 (§4.1 预算表 → CombatEngine 字段，v2 修正):
#   - 预算为【含属性贡献的总每击】：base_damage + 属性伤害 × weapon_k ≈ 每击预算
#   - weapon_k < 1: 轻型 0.4, 中型 0.5, 重型 0.6
#     （属性随等级线性增长（L99 伤害 ~300），k>1 时高等级每击必超预算——v1 假设
#      (k=0.8/1.2/1.5) 实测 TTK 2.5~3.2 回合，违反 G1；武器强度应以固定面板为主）
#   - base_damage = max(1, 每击预算 - 期望属性伤害 × weapon_k)（卡牌化固定面板）
#   - 轻型 +25% 迅捷 +3 身法；重型 -20% 迅捷（§4.1 低频高伤定位）
#   - armor_value = 同级典型护甲的 30%/50%/80%，典型护甲 = level × 2
#
# 注: 以上拆分为 §4.1 的一种合理解释；若后续武器设计采用不同拆分，
# 只需调整 _make_weapon() 并重新跑回归。

LEVELS = [1, 10, 25, 50, 75, 99]
BATTLES_PER_CELL = 5000

_GROWTH_WEIGHTS = {"damage": 0.60, "agility": 0.25, "speed": 0.15}
_HP_PER_LEVEL = 15
_COMBAT_POINTS_PER_LEVEL = 5


# ---------------------------------------------------------------------------
# Fighter / weapon builders
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WeaponProfile:
    """Synthetic weapon derived from §4.1 budget table."""

    name: str
    category: str  # light / medium / heavy
    weapon_k: float
    base_damage: int
    flat_damage_bonus: int  # added to FighterState.damage
    armor_value: int
    speed_bonus: int
    agility_bonus: int


def _expected_attrs(level: int) -> dict[str, float]:
    """§2 方案 A 期望曲线 (浮点，用于 FighterState 前取整)."""
    return {
        "hp": 100.0 + _HP_PER_LEVEL * (level - 1),
        "damage": 10.0 + 3.0 * (level - 1),
        "agility": 5.0 + 1.25 * (level - 1),
        "speed": 5.0 + 0.75 * (level - 1),
    }


def _random_growth_attrs(level: int, rng: random.Random) -> dict[str, float]:
    """§2 方案 A 随机实现: HP 独立通道 + 5 点按 60/25/15 逐点随机."""
    hp = 100.0 + _HP_PER_LEVEL * (level - 1)
    # 随机调味: HP 通道 ±3 (期望不变)
    hp += rng.randint(-3, 3)

    damage = 10.0
    agility = 5.0
    speed = 5.0
    for _ in range(level - 1):
        for _ in range(5):  # random_growth_step：每级 5 个战斗点
            r = rng.random()
            if r < _GROWTH_WEIGHTS["damage"]:
                damage += 1.0
            elif r < _GROWTH_WEIGHTS["damage"] + _GROWTH_WEIGHTS["agility"]:
                agility += 1.0
            else:
                speed += 1.0

    return {"hp": hp, "damage": damage, "agility": agility, "speed": speed}


def _make_weapon(level: int, category: str) -> WeaponProfile:
    """Generate a budget-grade weapon for the given level and category.

    §4.1 预算:
      light : per_hit_budget = hp / 10  (取区间中点)
      medium: per_hit_budget = hp / 7   (1/8~1/6 中点)
      heavy : per_hit_budget = hp / 5   (1/6~1/4 中点)

    合成到 CombatEngine 字段的假设 (见模块顶部注释):
      总每击 = base_damage + 属性伤害 × weapon_k ≈ per_hit_budget（预算为含属性贡献的总量）
      weapon_k = {light:0.4, medium:0.5, heavy:0.6}（<1：属性缩放为次，面板以固定 base_damage 为主）
      base_damage = max(1, per_hit_budget - 期望属性伤害 × weapon_k)
      armor_value = typical_armor * {light:0.3, medium:0.5, heavy:0.8}
      speed_bonus = 期望迅捷 × {light:+25%, medium:0, heavy:-20%} (下限 0)
      agility_bonus = {light:+3, medium:+1, heavy:0}
    """
    hp = 100.0 + _HP_PER_LEVEL * (level - 1)
    expected_damage = 10.0 + 3.0 * (level - 1)
    expected_speed = 5.0 + 0.75 * (level - 1)
    typical_armor = level * 2.0

    if category == "light":
        per_hit = hp / 8.5  # §4.1 区间 1/10~1/8 取中偏高，避免低等级甲薄弱时超 10 回合
        weapon_k = 0.4
        armor_pct = 0.3
        speed_bonus = int(round(expected_speed * 0.25))
        agility_bonus = 3
    elif category == "medium":
        per_hit = hp / 7.0
        weapon_k = 0.5
        armor_pct = 0.5
        speed_bonus = 0
        agility_bonus = 1
    else:  # heavy
        per_hit = hp / 5.5  # §4.1 区间 1/6~1/4 取中偏低，避免低等级时低于 5 回合
        weapon_k = 0.6
        armor_pct = 0.8
        speed_bonus = -int(round(expected_speed * 0.2))
        agility_bonus = 0

    base_dmg = max(1, int(round(per_hit - expected_damage * weapon_k)))
    armor = int(round(typical_armor * armor_pct))

    name = f"{category}_{level}"
    return WeaponProfile(
        name=name,
        category=category,
        weapon_k=weapon_k,
        base_damage=base_dmg,
        flat_damage_bonus=0,
        armor_value=armor,
        speed_bonus=speed_bonus,
        agility_bonus=agility_bonus,
    )


def _make_fighter(
    *,
    hp: int,
    damage: int,
    agility: int,
    speed: int,
    armor_value: int = 0,
    weapon_k: float = 1.0,
    base_damage: int = 0,
    level_index: int = 1,
    name: str = "修士A",
) -> FighterState:
    return FighterState(
        user_id=name,
        name=name,
        hp=hp,
        max_hp=hp,
        damage=damage,
        agility=agility,
        speed=speed,
        armor_value=armor_value,
        weapon_k=weapon_k,
        base_damage=base_damage,
        level_index=level_index,
        trigger_skills=[],
        ultimates=[],
    )


def _make_mirror_pair(
    attrs: dict[str, float], weapon: WeaponProfile | None = None, level_index: int = 1
) -> tuple[FighterState, FighterState]:
    hp = int(round(attrs["hp"]))
    dmg = int(round(attrs["damage"]))
    agi = int(round(attrs["agility"]))
    spd = int(round(attrs["speed"]))
    arm = 0
    wk = 1.0
    bd = 0
    if weapon is not None:
        dmg += weapon.flat_damage_bonus
        arm += weapon.armor_value
        wk = weapon.weapon_k
        bd = weapon.base_damage
        spd += weapon.speed_bonus
        agi += weapon.agility_bonus
        spd = max(1, spd)
        agi = max(1, agi)
    return (
        _make_fighter(
            hp=hp,
            damage=dmg,
            agility=agi,
            speed=spd,
            armor_value=arm,
            weapon_k=wk,
            base_damage=bd,
            level_index=level_index,
            name="修士甲",
        ),
        _make_fighter(
            hp=hp,
            damage=dmg,
            agility=agi,
            speed=spd,
            armor_value=arm,
            weapon_k=wk,
            base_damage=bd,
            level_index=level_index,
            name="修士乙",
        ),
    )


# ---------------------------------------------------------------------------
# Combat simulation
# ---------------------------------------------------------------------------
def _one_battle(f1: FighterState, f2: FighterState) -> tuple[int, int, bool]:
    result = ENGINE.resolve_combat(f1, f2, combat_type="spar", merge_count=10)
    return result.total_actions, result.rounds, result.winner == "draw"


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    data = sorted(values)
    n = len(data)
    if n == 1:
        return float(data[0])
    idx = (n - 1) * pct
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return float(data[lower])
    weight = idx - lower
    return data[lower] * (1 - weight) + data[upper] * weight


def _run_cell(
    *,
    level: int,
    growth_mode: str,  # "expected" | "random"
    weapon_category: str | None,  # None = bare_fists
    battles: int,
    seed_offset: int = 0,
) -> dict[str, Any]:
    """Run N mirror battles for one matrix cell and return aggregate stats."""
    rng = random.Random(2026 + level * 10000 + seed_offset)

    actions_list: list[int] = []
    rounds_list: list[int] = []
    draws = 0
    one_shots = 0  # rounds == 1

    for _ in range(battles):
        if growth_mode == "expected":
            attrs = _expected_attrs(level)
        else:
            attrs = _random_growth_attrs(level, rng)

        weapon = _make_weapon(level, weapon_category) if weapon_category else None
        f1, f2 = _make_mirror_pair(attrs, weapon, level_index=level)
        acts, rnds, is_draw = _one_battle(f1, f2)
        actions_list.append(acts)
        rounds_list.append(rnds)
        if is_draw:
            draws += 1
        if rnds == 1:
            one_shots += 1

    return {
        "level": level,
        "growth_mode": growth_mode,
        "weapon": weapon_category if weapon_category else "bare_fists",
        "battles": battles,
        "actions_mean": round(statistics.mean(actions_list), 2),
        "rounds_mean": round(statistics.mean(rounds_list), 2),
        "rounds_median": int(round(_percentile(rounds_list, 0.5))),
        "rounds_p10": round(_percentile(rounds_list, 0.10), 2),
        "rounds_p90": round(_percentile(rounds_list, 0.90), 2),
        "rounds_min": min(rounds_list),
        "rounds_max": max(rounds_list),
        "draw_rate": round(draws / battles, 4),
        "one_shot_rate": round(one_shots / battles, 4),
    }


# ---------------------------------------------------------------------------
# Acceptance checks (G1 / G2)
# ---------------------------------------------------------------------------
def _check_g1(rows: list[dict[str, Any]]) -> list[str]:
    """G1: 裸拳 8~15 回合; 持械 5~10; 任何格子秒杀率 = 0."""
    failures: list[str] = []
    for r in rows:
        weapon = r["weapon"]
        mean = r["rounds_mean"]
        one_shot = r["one_shot_rate"]
        key = f"L{r['level']} {r['growth_mode']} {weapon}"

        if weapon == "bare_fists":
            if not (8.0 <= mean <= 15.0):
                failures.append(f"G1 FAIL {key}: bare_fists mean={mean} not in [8,15]")
        else:
            if not (5.0 <= mean <= 10.0):
                failures.append(f"G1 FAIL {key}: armed mean={mean} not in [5,10]")

        if one_shot > 0.0:
            failures.append(f"G1 FAIL {key}: one_shot_rate={one_shot:.4f} > 0")

    return failures


def _check_g2(rows: list[dict[str, Any]]) -> list[str]:
    """G2: 相邻等级平均回合波动 ≤ ±30%."""
    failures: list[str] = []
    # Group by (growth_mode, weapon) and sort by level
    from collections import defaultdict

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["growth_mode"], r["weapon"])].append(r)

    for key, group in groups.items():
        group.sort(key=lambda x: x["level"])
        for i in range(1, len(group)):
            prev = group[i - 1]["rounds_mean"]
            curr = group[i]["rounds_mean"]
            if prev == 0:
                continue
            change = abs(curr - prev) / prev
            if change > 0.30:
                label = (
                    f"L{group[i - 1]['level']}→L{group[i]['level']} {key[0]} {key[1]}"
                )
                failures.append(
                    f"G2 FAIL {label}: |{curr:.2f}-{prev:.2f}|/{prev:.2f}={change:.2%} > 30%"
                )
    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
CSV_COLUMNS = [
    "level",
    "growth_mode",
    "weapon",
    "battles",
    "actions_mean",
    "rounds_mean",
    "rounds_median",
    "rounds_p10",
    "rounds_p90",
    "rounds_min",
    "rounds_max",
    "draw_rate",
    "one_shot_rate",
]


def run_simulation() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seed_counter = 0

    for level in LEVELS:
        for growth_mode in ("expected", "random"):
            for weapon_cat in (None, "light", "medium", "heavy"):
                weapon_label = weapon_cat if weapon_cat else "bare_fists"
                print(
                    f"Running L{level:2d} {growth_mode:8s} {weapon_label:12s} ...",
                    flush=True,
                )
                row = _run_cell(
                    level=level,
                    growth_mode=growth_mode,
                    weapon_category=weapon_cat,
                    battles=BATTLES_PER_CELL,
                    seed_offset=seed_counter,
                )
                rows.append(row)
                print(
                    f"  -> rounds_mean={row['rounds_mean']:.2f} "
                    f"one_shot={row['one_shot_rate']:.4f}",
                    flush=True,
                )
                seed_counter += 1

    return rows


def write_csv(rows: list[dict[str, Any]]) -> Path:
    csv_path = SCRIPT_DIR / "balance-regression-baseline.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def main() -> int:
    print("=" * 60)
    print("Balance Regression Simulation Harness")
    print("=" * 60)
    print(f"Levels: {LEVELS}")
    print(f"Battles per cell: {BATTLES_PER_CELL}")
    print(f"Total battles: {len(LEVELS) * 2 * 4 * BATTLES_PER_CELL:,}")
    print()

    rows = run_simulation()
    csv_path = write_csv(rows)
    print(f"\nCSV written: {csv_path}")

    print("\n" + "=" * 60)
    print("ACCEPTANCE CHECKS")
    print("=" * 60)

    g1_fails = _check_g1(rows)
    g2_fails = _check_g2(rows)
    all_fails = g1_fails + g2_fails

    if g1_fails:
        print("\n[G1 failures]")
        for msg in g1_fails:
            print(f"  {msg}")
    else:
        print(
            "\n[G1] PASS — all cells within bare_fists [8,15], armed [5,10], no one-shots"
        )

    if g2_fails:
        print("\n[G2 failures]")
        for msg in g2_fails:
            print(f"  {msg}")
    else:
        print("[G2] PASS — all adjacent-level fluctuations ≤ ±30%")

    print("\n" + "=" * 60)
    if all_fails:
        print(f"RESULT: FAIL ({len(all_fails)} check(s) failed)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
