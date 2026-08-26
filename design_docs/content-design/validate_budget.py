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

# 三族系数规范（route-identity.md §3，2026-08-27 修订：奖小于罚体现路线专属）
GENERIC_RANGE = (0.95, 1.05)  # 通用件双边
FAVORED_RANGE = (1.2, 1.4)  # 路线向件优势方
PENALIZED_RANGE = (0.5, 0.7)  # 路线向件劣势方


def _in_range(v: float, r: tuple[float, float]) -> bool:
    """Inclusive range check with a small float epsilon."""
    return r[0] - 1e-9 <= v <= r[1] + 1e-9


def check_route_multipliers(rows: list[dict]) -> list[str]:
    """Check route_mult_ling/route_mult_ti pairs against the three-family rule.

    Generic items keep both sides in GENERIC_RANGE; route-leaning items must
    pair one FAVORED_RANGE side with one PENALIZED_RANGE side (the penalty is
    deliberately harsher than the bonus to make items feel route-exclusive).
    """
    results = []
    for r in rows:
        ling = float(r["route_mult_ling"])
        ti = float(r["route_mult_ti"])
        generic = _in_range(ling, GENERIC_RANGE) and _in_range(ti, GENERIC_RANGE)
        leaning = (
            _in_range(ling, FAVORED_RANGE)
            and _in_range(ti, PENALIZED_RANGE)
            or _in_range(ti, FAVORED_RANGE)
            and _in_range(ling, PENALIZED_RANGE)
        )
        if generic or leaning:
            continue
        verdict = "WARN" if r["status"] == "legacy" else "FAIL"
        results.append(
            f"{verdict} {r['id']:<14} 路线系数越出三族规范："
            f"灵修={ling} 体修={ti}（通用 {GENERIC_RANGE} / 路线向 "
            f"{FAVORED_RANGE}×{PENALIZED_RANGE}） {r['name']}"
        )
    return results


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

# 机制预算表（route-identity.md §4）：机制复杂度按境界段解锁
# 练气段仅允许直接增伤/减伤；筑基段解锁数值变种但禁状态效果；
# 金丹（L20+）起解锁状态效果，元婴（L30+）起解锁必杀/复合机制。
# skills.csv 无等级列，功法侧段位纪律经心法 required_level_index 门禁人工落实，
# 此处只对 weapons.csv 的挂载触发技做机器校验。
DIRECT_ONLY_EFFECTS = {"damage_bonus", "damage_reduction"}
STATUS_EFFECTS = {"stun", "dot", "buff", "debuff"}


def check_weapon_mechanics_band(rows: list[dict]) -> list[str]:
    """Check mounted trigger skills against the per-realm mechanics budget.

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
        except json.JSONDecodeError:
            continue  # 语法错误由 check_weapon_mounts 报告
        level = int(r["required_level_index"])
        for i, s in enumerate(skills):
            if not isinstance(s, dict) or "effect_type" not in s:
                continue  # 结构错误由 check_weapon_mounts 报告
            where = f"{r['id']} trigger_skills[{i}]"
            effect = s["effect_type"]
            violation = None
            if level < 10 and effect not in DIRECT_ONLY_EFFECTS:
                violation = f"练气段仅允许直接增伤/减伤类，得 {effect}"
            elif level < 20 and effect in STATUS_EFFECTS:
                violation = f"筑基及以下禁状态效果，得 {effect}"
            if violation is None:
                continue
            verdict = "WARN" if r["status"] == "legacy" else "FAIL"
            results.append(
                f"{verdict} {where:<16} 机制预算违规：{violation} {r['name']}"
            )
    return results


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

    Per-effect expected-gain formulas (skills-ultimates.md §4.1, additive
    semantics: effect_value 0.4 = that hit x1.4, schema-and-engine-fit §3):
    - damage_bonus / combo / damage_reduction / counter: rate x effect_value
    - stun: 2 x rate / mirror_TTK (self action window + enemy stall), TTK ~= 7
    - heal: rate x value x TTK (restores value x max_hp, TTK ~= 7)
    - dot: rate x value x duration x tick_rate
    - pierce: rate x value x 1.5 (armor ~50% of mitigation, spec D11)
    - fatigue: excluded (self-nerf trade-off, spec D11)
    - buff/debuff/reflect/survive/unavoidable: value-based utility, WARN only
    Rows without a trigger skill (pure-ultimate skills) are PASS. Effect types
    outside the engine vocabulary (EFFECT_HANDLERS) are hard FAIL, since the
    registry is the single source of truth (sync SKILL_EFFECT_TYPES asserts
    equality). The 40% total reduction cap (§3.2) is enforced at combat
    resolution, not here.
    """
    results = []
    for r in rows:
        effect = r["effect_type"]
        if not effect:
            results.append(f"PASS {r['id']:<14} 纯大招功法（无触发技） {r['name']}")
            continue
        rate = float(r["trigger_rate"])
        value = float(r["effect_value"])
        if effect in ("damage_bonus", "combo", "damage_reduction", "counter"):
            expected = rate * value
        elif effect == "stun":
            expected = 2 * rate / 7  # mirror TTK ~= 7 rounds
        elif effect == "heal":
            expected = rate * value * 7  # restores value x max_hp, TTK ~= 7
        elif effect == "dot":
            # Guard malformed cells: a bad duration/tick_rate must surface as
            # FAIL, not crash the whole validation run (review fix).
            try:
                duration = (
                    int(r["duration"]) if (r.get("duration") or "").strip() else 1
                )
                tick = (
                    float(r["tick_rate"]) if (r.get("tick_rate") or "").strip() else 1.0
                )
            except ValueError:
                results.append(
                    f"FAIL {r['id']:<14} dot 的 duration/tick_rate 必须为数字 {r['name']}"
                )
                continue
            if duration < 1 or not (0 <= tick <= 1):
                results.append(
                    f"FAIL {r['id']:<14} dot 的 duration 须 >=1、tick_rate 须在 [0,1]（sync 契约） {r['name']}"
                )
                continue
            expected = rate * value * duration * tick
        elif effect == "pierce":
            expected = rate * value * 1.5  # bypasses ~half of mitigation
        elif effect == "fatigue":
            expected = 0.0  # self-nerf: excluded from budget (spec D11)
        elif effect in ("buff", "debuff", "reflect", "survive", "unavoidable"):
            expected = None  # value-based utility: numeric check skipped
        else:
            results.append(
                f"FAIL {r['id']:<14} 未注册 effect_type={effect}（引擎词表外） {r['name']}"
            )
            continue
        if expected is None:
            verdict, detail = "WARN", f"utility effect={effect}，跳过数值校验"
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
        ("weapons.csv", check_weapon_mechanics_band),
        ("weapons.csv", check_route_multipliers),
        ("skills.csv", check_skills),
        ("skills.csv", check_route_multipliers),
        ("heart_methods.csv", check_heart_methods),
        ("heart_methods.csv", check_route_multipliers),
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
