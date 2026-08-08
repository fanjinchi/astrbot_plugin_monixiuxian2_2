#!/usr/bin/env python3
"""Validate content-design CSVs against the numeric budgets in
design_docs/attribute-growth/growth-balance-proposals.md (§3 caps / §4 budgets).

Rows with status ``legacy`` are existing config values kept for reference:
they are printed as informational WARN lines and do not affect the exit code.
Rows with status ``draft`` or ``final`` must pass every check.

Usage:
    uv run python design_docs/content-design/validate_budget.py

Returns:
    Exit code 0 when all draft/final rows pass, 1 otherwise.
"""

import csv
import json
import sys
from pathlib import Path

DESIGN_DIR = Path(__file__).resolve().parent


# Benchmark growth curve anchors from growth-balance-proposals.md §2:
# HP grows through an independent +15/breakthrough channel; damage gets
# 5 attribute points/level x 60% weight = +3/level expected.
def benchmark_hp(level: int) -> float:
    """Expected HP at a given level_index (L10=235, L99=1570)."""
    return 100 + 15 * (level - 1)


def benchmark_damage(level: int) -> float:
    """Expected damage attribute at a given level_index (L10=37, L99=304)."""
    return 10 + 3 * (level - 1)


# Per-hit budget as a fraction of same-level HP, by size_class (§4.1).
SIZE_BUDGET = {"轻": (1 / 10, 1 / 8), "中": (1 / 8, 1 / 6), "重": (1 / 6, 1 / 4)}
SKILL_EXPECTED_GAIN_CAP = 0.30  # §4.2: trigger_rate x (effect_value - 1) per slot
HEART_PASSIVE_CAP = 0.15  # §4.3: single passive percent bonus
WEAPON_MOUNT_TAX_CAP = 0.08  # weapon-skills.md §2 rule 3: mounted skill expected gain
TRIGGER_TIMINGS = ("on_attack", "on_defense", "on_crit", "round_start")
STUN_RATE_CAP = 0.10  # weapon-skills.md §1: stun rates must stay low


def check_weapon_mounts(rows: list[dict]) -> list[str]:
    """Check mounted trigger skills on weapons (engine-key contract + tax cap).

    Each mounted skill must use the engine key contract (trigger_timing /
    effect_type / trigger_rate / effect_value) and stay within the mounted
    tax budget (weapon-skills.md rule 3): expected gain = rate x value <= 8%,
    and the tax-adjusted per-hit must not exceed the budget band high +5%.

    Args:
        rows: Parsed weapons.csv rows.

    Returns:
        Human-readable result lines, each prefixed PASS/WARN/FAIL.
    """
    results = []
    for r in rows:
        if not r.get("trigger_skills_json") or r["trigger_skills_json"] == "[]":
            continue
        try:
            skills = json.loads(r["trigger_skills_json"])
        except json.JSONDecodeError as e:
            results.append(f"FAIL {r['id']:<12} trigger_skills_json 不是合法 JSON: {e}")
            continue
        level = max(1, int(r["required_level_index"]))
        size = r["size_class"]
        per_hit = float(r["base_damage"]) + (
            benchmark_damage(level) + float(r["bonus_damage"])
        ) * float(r["weapon_coefficient_k"])
        hp = benchmark_hp(level)
        lo, hi = SIZE_BUDGET.get(size, (0, 0))
        for i, s in enumerate(skills):
            where = f"{r['id']} trigger_skills[{i}]"
            if not isinstance(s, dict):
                results.append(f"FAIL {where:<16} 必须是对象")
                continue
            missing = {
                "trigger_timing",
                "effect_type",
                "trigger_rate",
                "effect_value",
            } - s.keys()
            if missing:
                results.append(f"FAIL {where:<16} 缺引擎键 {sorted(missing)}")
                continue
            timing = s["trigger_timing"]
            rate = float(s["trigger_rate"])
            value = float(s["effect_value"])
            if timing not in TRIGGER_TIMINGS:
                results.append(f"FAIL {where:<16} 未知 timing {timing}")
            if not 0 < rate <= 1:
                results.append(f"FAIL {where:<16} trigger_rate 需在 (0,1]，得 {rate}")
            gain = rate * value
            if s["effect_type"] == "stun":
                if rate > STUN_RATE_CAP:
                    results.append(
                        f"FAIL {where:<16} stun 概率 {rate} 超上限 {STUN_RATE_CAP}"
                    )
            elif gain > WEAPON_MOUNT_TAX_CAP:
                results.append(
                    f"FAIL {where:<16} 期望增幅 {gain:.1%} 超税上限 {WEAPON_MOUNT_TAX_CAP:.0%}"
                )
            taxed = per_hit * (1 + gain)
            if taxed > hp * hi * 1.05:
                results.append(
                    f"FAIL {where:<16} 含税每击 {taxed:.1f} 越带上限 {hp * hi * 1.05:.1f}"
                )
            results.append(
                f"PASS {where:<16} {s['name']} {timing} {s['effect_type']} "
                f"rate={rate} value={value} 期望增幅={gain:.1%}"
            )
    return results


MIRROR_TTK_RANGE = (5, 10)  # G1: armed mirror-match TTK target


def check_weapons(rows: list[dict]) -> list[str]:
    """Check each weapon's expected per-hit damage against the size budget.

    Expected per-hit = base_damage + (benchmark_damage(L) + bonus_damage) x K,
    evaluated at L = max(1, required_level_index) (§4.1 worked example).

    Args:
        rows: Parsed weapons.csv rows.

    Returns:
        Human-readable result lines, each prefixed PASS/WARN/FAIL.
    """
    results = []
    for r in rows:
        level = max(1, int(r["required_level_index"]))
        size = r["size_class"]
        per_hit = float(r["base_damage"]) + (
            benchmark_damage(level) + float(r["bonus_damage"])
        ) * float(r["weapon_coefficient_k"])
        hp = benchmark_hp(level)
        lo, hi = SIZE_BUDGET.get(size, (0, 0))
        budget_lo, budget_hi = hp * lo, hp * hi
        ttk = hp / per_hit if per_hit > 0 else float("inf")
        in_budget = budget_lo <= per_hit <= budget_hi
        ttk_ok = MIRROR_TTK_RANGE[0] <= ttk <= MIRROR_TTK_RANGE[1]
        verdict = "PASS" if (in_budget and ttk_ok) else "FAIL"
        if r["status"] == "legacy":
            verdict = "WARN"  # legacy rows are informational only
        results.append(
            f"{verdict} {r['id']:<12} L{level:<3} {size} 每击={per_hit:7.1f} "
            f"预算=[{budget_lo:6.1f},{budget_hi:6.1f}] TTK={ttk:4.1f} {r['name']}"
        )
    return results


def check_skills(rows: list[dict]) -> list[str]:
    """Check trigger-skill expected gain: rate x (effect_value - 1) <= 30% (§4.2).

    For damage_reduction, expected reduction is rate x effect_value and is
    checked against the same cap; the 40% total reduction cap (§3.2) is
    enforced at combat resolution, not here.
    """
    results = []
    for r in rows:
        rate = float(r["trigger_rate"])
        value = float(r["effect_value"])
        effect = r["effect_type"]
        if effect == "damage_bonus":
            expected = rate * (value - 1)
        elif effect == "damage_reduction":
            expected = rate * value
        else:
            expected = None  # unknown effect type: skip numeric check
        if expected is None:
            verdict, detail = "WARN", f"未识别 effect={effect}，跳过数值校验"
        else:
            ok = expected <= SKILL_EXPECTED_GAIN_CAP
            verdict = "PASS" if ok else "FAIL"
            detail = f"期望增益={expected:.1%} cap=30%"
        if r["status"] == "legacy" and verdict == "FAIL":
            verdict = "WARN"
        results.append(f"{verdict} {r['id']:<14} {detail} {r['name']}")
    return results


def check_heart_methods(rows: list[dict]) -> list[str]:
    """Check each passive_bonus entry against the 15% single-passive cap (§4.3)."""
    results = []
    for r in rows:
        bonus = json.loads(r["passive_bonus_json"])
        violations = [
            f"{k}={v:.0%}"
            for k, v in bonus.items()
            if k.endswith("_percent") and v > HEART_PASSIVE_CAP
        ]
        verdict = "PASS" if not violations else "FAIL"
        if r["status"] == "legacy" and verdict == "FAIL":
            verdict = "WARN"
        detail = "被动合规" if not violations else f"超 cap: {', '.join(violations)}"
        results.append(f"{verdict} {r['id']:<12} {detail} {r['name']}")
    return results


def main() -> int:
    """Run all budget checks and print a report. Returns process exit code."""
    all_lines: list[str] = []
    for filename, checker in (
        ("weapons.csv", check_weapons),
        ("weapons.csv", check_weapon_mounts),
        ("skills.csv", check_skills),
        ("heart_methods.csv", check_heart_methods),
    ):
        path = DESIGN_DIR / filename
        with path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        print(f"\n== {filename} ({len(rows)} rows) ==")
        lines = checker(rows)
        all_lines.extend(lines)
        for line in lines:
            print(" ", line)

    fails = sum(line.startswith("FAIL") for line in all_lines)
    warns = sum(line.startswith("WARN") for line in all_lines)
    print(f"\nSummary: {fails} FAIL, {warns} WARN (legacy rows 不计入 FAIL)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
