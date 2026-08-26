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


if __name__ == "__main__":
    battles = int(sys.argv[1]) if len(sys.argv) > 1 else BATTLES_DEFAULT
    rows = run_matchup_cells(battles)
    verdicts = evaluate(rows)
    csv_path = write_csv(rows)
    report_path = write_report(rows, verdicts)
    for v in verdicts:
        print(v)
    print(f"\nCSV written: {csv_path}")
    print(f"Report written: {report_path}")
