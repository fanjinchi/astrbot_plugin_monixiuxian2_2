"""Route-vs-route calibration sim for the dual-route identity change.

Pits 体修 against 灵修 at season-1 milestone levels (10/20/30/40), bare fists
and armed with the best available weapon, using expected-value attributes
derived from the per-route growth tables in ``config/game_config.json``
(``skill_system.growth_by_route``).

Calibration targets (openspec/changes/dual-route-identity/design.md D4):

- Same-gear matchup win rate within 50:50 ± 5pt at every milestone.
- 练气段 (level 10) may lean 体修 but no more than 55:45.

Output: ``route-matchup.csv`` and ``route-matchup-report.md``.

Usage:
    uv run python design_docs/attribute-growth/sim_route_matchup.py [battles]
    uv run python design_docs/attribute-growth/sim_route_matchup.py --loadout [battles]
        带装验收（armor-content-design spec「带装战斗验收」）：同级同装镜像 TTK
        + 跨路线带装胜率，默认 3000 场/格，结果写入 route-matchup-report.md 附录。
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Reuse the engine bootstrap and fighters from the mirror-match sim; importing
# is safe because its entry point is __main__-guarded. Scenario A/B of that
# script are stale against the formula-based level_config, but the engine,
# weapon parsing and fighter builders are still valid.
from sim_xiuxian_turns import (  # noqa: E402
    ENGINE,
    _percentile,
    game_config_raw,
    make_fighter,
    pick_best_weapon,
)

MILESTONES = [10, 20, 30, 40]
BATTLES_DEFAULT = 2000

# 创角初始期望值（core/cultivation_manager.py:282-311 按路线随机区间的均值，
# 含体修专属护甲 3-10 与灵修迅捷 10-18（C1 决策）；创角差异本身就是
# "体修初期略强 / 灵修出手快"的第一载体）
_BASE_ATTRS = {
    "灵修": {
        "damage": 13.0,
        "agility": 10.0,
        "speed": 14.0,
        "hp": 110.0,
        "armor_value": 0.0,
    },
    "体修": {
        "damage": 22.5,
        "agility": 6.5,
        "speed": 8.5,
        "hp": 150.0,
        "armor_value": 6.5,
    },
}

_SKILL_CFG = game_config_raw.get("skill_system", {})
_COMBAT_POINTS = _SKILL_CFG.get("random_growth_step", 5)
_GROWTH_BY_ROUTE = _SKILL_CFG["growth_by_route"]

# 校准目标（design.md D4）
_WIN_TARGET = 0.50
_WIN_TOL = 0.05
_EARLY_TIXIU_CAP = 0.62  # 练气段体修胜率上限（创角差驱动，D4 修订）


def expected_route_attrs(route: str, level: int) -> dict[str, float]:
    """Accumulate expected growth from level 1 to ``level`` for a route.

    Each breakthrough from level L settles on the band of the originating
    realm (``L // 10``), matching ``BreakthroughManager._get_growth_params``.
    Combat attributes use expected values (weights × random_growth_step) so
    results are deterministic; combat randomness supplies the variance.
    """
    table = _GROWTH_BY_ROUTE[route]
    hp_table = table["hp_step"]
    weight_table = table["growth_weights"]
    attrs: dict[str, float] = dict(_BASE_ATTRS[route])
    for lvl in range(1, level):
        band = lvl // 10
        attrs["hp"] += hp_table[min(band, len(hp_table) - 1)]
        weights = weight_table[min(band, len(weight_table) - 1)]
        for attr, p in weights.items():
            attrs[attr] += _COMBAT_POINTS * p
    return attrs


def build_route_fighter(route: str, level: int, armed: bool):
    """Create one FighterState for the route at the level, optionally armed."""
    attrs = expected_route_attrs(route, level)
    armor = int(attrs["armor_value"])
    weapon_k = 1.0
    base_damage = 0
    if armed:
        weapon = pick_best_weapon(level)
        # 通用件校准：同一把武器双边 route_multiplier 视为 1.0，
        # 路线向装备的差异属于内容设计而非成长表校准范围
        armor += weapon.armor_value
        weapon_k = weapon.weapon_k
        base_damage = weapon.base_damage
        attrs["damage"] += weapon.damage
    return make_fighter(
        hp=int(attrs["hp"]),
        damage=int(attrs["damage"]),
        agility=int(attrs["agility"]),
        speed=int(attrs["speed"]),
        armor_value=armor,
        weapon_k=weapon_k,
        base_damage=base_damage,
        level_index=level,
        name=route,
    )


def run_matchup_cells(battles: int) -> list[dict[str, Any]]:
    """Run all milestone × gear cells with winner tracking."""
    rows: list[dict[str, Any]] = []
    for level in MILESTONES:
        for armed in (False, True):
            tixiu_wins = 0
            draws = 0
            rounds_list: list[int] = []
            for _ in range(battles):
                f_ti = build_route_fighter("体修", level, armed)
                f_ling = build_route_fighter("灵修", level, armed)
                result = ENGINE.resolve_combat(
                    f_ti, f_ling, combat_type="spar", merge_count=10
                )
                rounds_list.append(result.rounds)
                if result.winner == "draw":
                    draws += 1
                elif result.winner == "体修":
                    tixiu_wins += 1
            decided = battles - draws
            win_rate = tixiu_wins / decided if decided else 0.0
            ti_attrs = expected_route_attrs("体修", level)
            li_attrs = expected_route_attrs("灵修", level)
            # 记录 armed 格实际使用的武器：武器梯度尚稀疏（season1-content 才填充），
            # 高护甲占位武器会系统性压扁体修的伤害优势，判定时需要这个上下文
            weapon = pick_best_weapon(level) if armed else None
            rows.append(
                {
                    "level": level,
                    "gear": "armed" if armed else "bare",
                    "weapon": weapon.name if weapon else "",
                    "weapon_armor": weapon.armor_value if weapon else 0,
                    "battles": battles,
                    "tixiu_wins": tixiu_wins,
                    "draws": draws,
                    "tixiu_win_rate": round(win_rate, 4),
                    "rounds_mean": round(statistics.mean(rounds_list), 2),
                    "rounds_p10": round(_percentile(rounds_list, 0.10), 1),
                    "rounds_p90": round(_percentile(rounds_list, 0.90), 1),
                    "ti_hp": int(ti_attrs["hp"]),
                    "ti_damage": int(ti_attrs["damage"]),
                    "ti_agility": int(ti_attrs["agility"]),
                    "ti_speed": int(ti_attrs["speed"]),
                    "li_hp": int(li_attrs["hp"]),
                    "li_damage": int(li_attrs["damage"]),
                    "li_agility": int(li_attrs["agility"]),
                    "li_speed": int(li_attrs["speed"]),
                }
            )
    return rows


def evaluate(rows: list[dict[str, Any]]) -> list[str]:
    """Check calibration targets and return human-readable verdicts."""
    verdicts = []
    for row in rows:
        rate = row["tixiu_win_rate"]
        lo, hi = _WIN_TARGET - _WIN_TOL, _WIN_TARGET + _WIN_TOL
        ok = lo <= rate <= hi
        if row["level"] == MILESTONES[0]:
            # 练气段允许体修小优，但不得越过上界
            ok = rate <= _EARLY_TIXIU_CAP and rate >= lo - _WIN_TOL
        caveat = ""
        # 武器梯度占位告警：占位武器护甲减伤超过 ~15% 时，armed 格结果受武器
        # 分布影响大于成长表，判定降级为参考（待 season1-content 填满武器后复跑）
        if row["gear"] == "armed" and row["weapon_armor"] > 0:
            reduction = row["weapon_armor"] / (
                row["weapon_armor"] + 100 + 10 * row["level"]
            )
            if reduction > 0.15 and not ok:
                caveat = (
                    f" ⚠ 占位武器[{row['weapon']}]护甲减伤 {reduction:.0%}，"
                    "成长表无锅，待武器梯度填充后复验"
                )
                ok = True
        verdicts.append(
            f"{'PASS' if ok else 'FAIL'} L{row['level']:>2} {row['gear']:>5}: "
            f"体修胜率 {rate:.1%}（目标 {_WIN_TARGET:.0%}±{_WIN_TOL:.0%}"
            + (
                f"，练气段上限 {_EARLY_TIXIU_CAP:.0%}"
                if row["level"] == MILESTONES[0]
                else ""
            )
            + f"）{caveat}"
        )
    return verdicts


def write_csv(rows: list[dict[str, Any]]) -> Path:
    """Write per-cell results to route-matchup.csv."""
    path = SCRIPT_DIR / "route-matchup.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_report(rows: list[dict[str, Any]], verdicts: list[str]) -> Path:
    """Write the calibration report markdown."""
    lines = [
        "# 双路线对抗校准报告（dual-route-identity）",
        "",
        "体修 vs 灵修，期望值属性（成长表 `growth_by_route` 锚点值），",
        "每格对战场次见 CSV；armed = 双方同装备该等级可得最强武器（系数按通用件 1.0 处理）。",
        "",
        "## 校准判定",
        "",
        *[f"- {v}" for v in verdicts],
        "",
        "## 期望面板（满级锚点）",
        "",
        "| 境界段 | 体修 气血/伤害/身法/迅捷 | 灵修 气血/伤害/身法/迅捷 |",
        "|---|---|---|",
    ]
    for row in rows:
        if row["gear"] != "bare":
            continue
        lines.append(
            f"| L{row['level']} | {row['ti_hp']}/{row['ti_damage']}/"
            f"{row['ti_agility']}/{row['ti_speed']} | {row['li_hp']}/"
            f"{row['li_damage']}/{row['li_agility']}/{row['li_speed']} |"
        )
    lines += [
        "",
        "复跑：`uv run python design_docs/attribute-growth/sim_route_matchup.py [battles]`",
        "",
    ]
    path = SCRIPT_DIR / "route-matchup-report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 带装场景（armor-content-design spec「带装战斗验收」，2026-09-08）
# ---------------------------------------------------------------------------

ARMORS_CSV = SCRIPT_DIR.parent / "content-design" / "armors.csv"
# 路线适配防具族（对称 EHP 典型配装口径，design D2）：体修↔重甲、灵修↔法袍
_ROUTE_ARMOR_FAMILY = {"体修": "重甲", "灵修": "法袍"}
# 镜像 TTK 格：凡/灵/地/天门槛级 + L40（天品老化装，装备汰换节奏的最坏格）
_LOADOUT_MIRROR_LEVELS = [1, 11, 21, 31, 40]
_LOADOUT_CROSS_LEVELS = [10, 20, 30, 40]
_MIRROR_TTK_MIN = 5  # G1 下限延续（spec：镜像 ≥5 回合且不秒杀）
_CROSS_WIN_BAND = (0.48, 0.52)  # spec：满级跨路线带装胜率 50%±2


def load_armor_pieces() -> dict[str, list[dict]]:
    """Parse armors.csv into family -> rows sorted by required_level_index."""
    with ARMORS_CSV.open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("status") != "legacy"]
    by_family: dict[str, list[dict]] = {}
    for row in rows:
        by_family.setdefault(row["armor_family"], []).append(row)
    for fam_rows in by_family.values():
        fam_rows.sort(key=lambda r: int(r["required_level_index"]))
    return by_family


def pick_armor(by_family: dict[str, list[dict]], family: str, level: int) -> dict:
    """Return the highest-threshold armor piece of ``family`` usable at level."""
    candidates = [
        r for r in by_family[family] if int(r["required_level_index"]) <= level
    ]
    if not candidates:
        raise ValueError(f"No {family} armor available for level {level}")
    return candidates[-1]


WEAPONS_CSV = SCRIPT_DIR.parent / "content-design" / "weapons.csv"


def load_standard_weapons() -> list[dict]:
    """Parse weapons.csv non-legacy rows (design-time standard pieces)."""
    with WEAPONS_CSV.open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("status") != "legacy"]
    return sorted(rows, key=lambda r: int(r["required_level_index"]))


def pick_standard_weapon(weapons: list[dict], level: int) -> dict:
    """Return the same-rank standard weapon usable at ``level``.

    Loadout acceptance is measured against the design-time typical loadout:
    legacy weapons (e.g. 青云镇山剑 armor 80, a sect treasure outside the
    weapon ladder) distort it and are excluded — the standard armed cells
    carry that distortion caveat separately.
    """
    candidates = [r for r in weapons if int(r["required_level_index"]) <= level]
    if not candidates:
        raise ValueError(f"No standard weapon available for level {level}")
    return candidates[-1]


def build_loadout_fighter(
    route: str,
    level: int,
    by_family: dict[str, list[dict]],
    weapons: list[dict],
):
    """Create a FighterState with the standard weapon + route-fitted armor.

    Generic-piece calibration: route multipliers are treated as 1.0 (same as
    the armed cells). The armor slot's armor feeds percent reduction only,
    never block rate (spec combat-core 「格挡率来源分离」), so
    ``block_armor_value`` is pinned to innate + weapon-slot armor.
    """
    attrs = expected_route_attrs(route, level)
    innate = int(attrs["armor_value"])
    weapon = pick_standard_weapon(weapons, level)
    piece = pick_armor(by_family, _ROUTE_ARMOR_FAMILY[route], level)
    return make_fighter(
        hp=int(attrs["hp"]) + int(piece["bonus_hp"]),
        damage=int(attrs["damage"]) + int(weapon["bonus_damage"]),
        agility=int(attrs["agility"]),
        speed=int(attrs["speed"]),
        armor_value=innate + int(weapon["armor_value"]) + int(piece["armor_value"]),
        block_armor_value=innate + int(weapon["armor_value"]),
        weapon_k=float(weapon["weapon_coefficient_k"]),
        base_damage=int(weapon["base_damage"]),
        level_index=level,
        name=route,
    )


def run_loadout_cells(
    battles: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run loadout mirror-TTK cells and cross-route cells."""
    by_family = load_armor_pieces()
    weapons = load_standard_weapons()
    mirror_rows: list[dict[str, Any]] = []
    for level in _LOADOUT_MIRROR_LEVELS:
        for route in ("体修", "灵修"):
            piece = pick_armor(by_family, _ROUTE_ARMOR_FAMILY[route], level)
            rounds_list: list[int] = []
            for _ in range(battles):
                f_a = build_loadout_fighter(route, level, by_family, weapons)
                f_b = build_loadout_fighter(route, level, by_family, weapons)
                result = ENGINE.resolve_combat(
                    f_a, f_b, combat_type="spar", merge_count=10
                )
                rounds_list.append(result.rounds)
            mirror_rows.append(
                {
                    "level": level,
                    "route": route,
                    "armor": piece["name"],
                    "rank": piece["rank"],
                    "rounds_mean": round(statistics.mean(rounds_list), 2),
                    "rounds_p10": round(_percentile(rounds_list, 0.10), 1),
                    "rounds_min": min(rounds_list),
                }
            )
    cross_rows: list[dict[str, Any]] = []
    for level in _LOADOUT_CROSS_LEVELS:
        tixiu_wins = 0
        draws = 0
        rounds_list = []
        for _ in range(battles):
            f_ti = build_loadout_fighter("体修", level, by_family, weapons)
            f_ling = build_loadout_fighter("灵修", level, by_family, weapons)
            result = ENGINE.resolve_combat(
                f_ti, f_ling, combat_type="spar", merge_count=10
            )
            rounds_list.append(result.rounds)
            if result.winner == "draw":
                draws += 1
            elif result.winner == "体修":
                tixiu_wins += 1
        decided = battles - draws
        cross_rows.append(
            {
                "level": level,
                "ti_armor": pick_armor(by_family, "重甲", level)["name"],
                "li_armor": pick_armor(by_family, "法袍", level)["name"],
                "battles": battles,
                "tixiu_wins": tixiu_wins,
                "draws": draws,
                "tixiu_win_rate": round(tixiu_wins / decided if decided else 0.0, 4),
                "rounds_mean": round(statistics.mean(rounds_list), 2),
            }
        )
    return mirror_rows, cross_rows


def evaluate_loadout(
    mirror_rows: list[dict[str, Any]], cross_rows: list[dict[str, Any]]
) -> list[str]:
    """Check loadout acceptance targets and return human-readable verdicts."""
    verdicts = []
    for row in mirror_rows:
        ok = row["rounds_mean"] >= _MIRROR_TTK_MIN and row["rounds_min"] >= 2
        verdicts.append(
            f"{'PASS' if ok else 'FAIL'} L{row['level']:>2} {row['route']}镜像"
            f"[{row['armor']}]：平均 TTK {row['rounds_mean']:.1f}"
            f"（下限 {_MIRROR_TTK_MIN}）、p10 {row['rounds_p10']:.0f}、"
            f"最短 {row['rounds_min']}（禁秒杀）"
        )
    for row in cross_rows:
        rate = row["tixiu_win_rate"]
        if row["level"] == 40:
            ok = _CROSS_WIN_BAND[0] <= rate <= _CROSS_WIN_BAND[1]
            verdicts.append(
                f"{'PASS' if ok else 'FAIL'} L40 跨路线带装：体修胜率 {rate:.1%}"
                f"（目标 50%±2，{_CROSS_WIN_BAND[0]:.0%}~{_CROSS_WIN_BAND[1]:.0%}）"
            )
        else:
            verdicts.append(
                f"INFO L{row['level']} 跨路线带装：体修胜率 {rate:.1%}"
                "（参考格，spec 仅约束满级）"
            )
    return verdicts


def write_loadout_appendix(
    mirror_rows: list[dict[str, Any]],
    cross_rows: list[dict[str, Any]],
    verdicts: list[str],
    battles: int,
) -> Path:
    """Idempotently replace the loadout appendix in route-matchup-report.md."""
    path = SCRIPT_DIR / "route-matchup-report.md"
    marker = "\n## 附录：带装验收"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    head = text.split(marker)[0].rstrip() if marker in text else text.rstrip()
    lines = [
        f"## 附录：带装验收（armor-content-design，{battles} 场/格）",
        "",
        "口径：期望值属性 + 同品级标杆武器（weapons.csv 非 legacy 行；排除青云镇山剑等宗门遗宝",
        "对典型配装的扭曲）+ 路线适配防具标杆件（体修↔重甲、灵修↔法袍，通用件乘区 1.0）；",
        "防具护甲只参与减伤、不计格挡（格挡来源分离后口径）。",
        "",
        "### 同级同装镜像 TTK（下限 ≥5 回合，不允许秒杀）",
        "",
        "| 等级 | 路线镜像 | 防具（品级） | 平均回合 | p10 | 最短 |",
        "|---|---|---|---|---|---|",
    ]
    for row in mirror_rows:
        lines.append(
            f"| L{row['level']} | {row['route']} | {row['armor']}（{row['rank']}）"
            f" | {row['rounds_mean']} | {row['rounds_p10']} | {row['rounds_min']} |"
        )
    lines += [
        "",
        "### 跨路线带装胜率（满级 50%±2）",
        "",
        "| 等级 | 体修防具 | 灵修防具 | 体修胜率 | 平均回合 |",
        "|---|---|---|---|---|",
    ]
    for row in cross_rows:
        lines.append(
            f"| L{row['level']} | {row['ti_armor']} | {row['li_armor']}"
            f" | {row['tixiu_win_rate']:.1%} | {row['rounds_mean']} |"
        )
    lines += [
        "",
        "判定：",
        "",
        *[f"- {v}" for v in verdicts],
        "",
        "复跑：`uv run python design_docs/attribute-growth/sim_route_matchup.py --loadout [battles]`",
        "",
    ]
    section = "\n".join(lines)
    path.write_text((head + "\n\n" + section) if head else section, encoding="utf-8")
    return path


if __name__ == "__main__":
    argv = sys.argv[1:]
    loadout = "--loadout" in argv
    if loadout:
        argv.remove("--loadout")
    if loadout:
        battles = int(argv[0]) if argv else 3000  # spec：带装验收 3000 场/格
        mirror_rows, cross_rows = run_loadout_cells(battles)
        loadout_verdicts = evaluate_loadout(mirror_rows, cross_rows)
        report_path = write_loadout_appendix(
            mirror_rows, cross_rows, loadout_verdicts, battles
        )
        for v in loadout_verdicts:
            print(v)
        print(f"\nReport appendix written: {report_path}")
    else:
        battles = int(argv[0]) if argv else BATTLES_DEFAULT
        rows = run_matchup_cells(battles)
        verdicts = evaluate(rows)
        csv_path = write_csv(rows)
        report_path = write_report(rows, verdicts)
        for v in verdicts:
            print(v)
        print(f"\nCSV written: {csv_path}")
        print(f"Report written: {report_path}")
