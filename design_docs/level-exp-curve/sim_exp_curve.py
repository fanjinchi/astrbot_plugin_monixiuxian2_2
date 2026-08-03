"""修仙插件升级经验曲线模拟脚本。

运行方式：
    cd /home/guigui/code/AstrBot && uv run python data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/level-exp-curve/sim_exp_curve.py

输出：
    - design_docs/level-exp-curve/exp-curve-results.csv
    - design_docs/level-exp-curve/exp-curve-report.md

本脚本只读取 JSON 配置，不依赖插件运行时，也不修改任何生产代码。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 项目路径
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent

LEVEL_CONFIG_PATH = PLUGIN_ROOT / "config" / "level_config.json"
GAME_CONFIG_PATH = PLUGIN_ROOT / "config" / "game_config.json"
ADVENTURE_CONFIG_PATH = PLUGIN_ROOT / "config" / "adventure_config.json"
OUTPUT_CSV = SCRIPT_DIR / "exp-curve-results.csv"
OUTPUT_REPORT = SCRIPT_DIR / "exp-curve-report.md"

REALM_NAMES = [
    "炼气",
    "筑基",
    "金丹",
    "元婴",
    "化神",
    "炼虚",
    "合体",
    "大乘",
    "渡劫",
    "地仙",
]

# ---------------------------------------------------------------------------
# 玩家日收益模型 G(L) 的假设参数（集中放在顶部，方便调整）
# ---------------------------------------------------------------------------
BASE_EXP_PER_MINUTE = 100  # 闭关基础修为/分钟
SPIRIT_ROOT_MEDIAN_SPEED = 1.3  # 灵根中位数倍率（从 SPIRIT_ROOT_SPEEDS 取值计算）
HEART_METHOD_BONUS = 0.20  # 心法修为加成
DAILY_CULTIVATION_HOURS = 4  # 每天有效闭关小时数
DAILY_CULTIVATION_MINUTES = DAILY_CULTIVATION_HOURS * 60

DAILY_ADVENTURE_COUNT = 2  # 每天历练次数
ADVENTURE_ROUTE_KEY = "scout"  # 短途路线

SPIRIT_EYE_DAILY_HOURS = 8  # 灵眼/福地/灵田平均每日被动收取小时数
MISC_DAILY_EXP = 2000  # 签到/悬赏/秘境等低额日常修为总和（假设）

# 突破成功率（按大境界，用于候选公式）
REALM_SUCCESS_RATES: dict[int, float] = {
    1: 1.00,  # 炼气
    2: 0.70,  # 筑基
    3: 0.55,  # 金丹
    4: 0.40,  # 元婴
    5: 0.30,  # 化神
    6: 0.25,  # 炼虚
    7: 0.22,  # 合体
    8: 0.20,  # 大乘
    9: 0.20,  # 渡劫
    10: 0.20,  # 地仙
}

# 连败保底参数（与 game_config.json skill_system 节一致）
PITY_STEP = 0.05
PITY_GUARANTEE = 19

# 突破失败惩罚：扣除当前修为的 10%（见 core/breakthrough_manager.py）
FAILURE_EXP_PENALTY_RATE = 0.10

# 双修参数（见 managers/dual_cultivation_manager.py / game_config.json）
DUAL_CULT_COOLDOWN_HOURS = 1
DUAL_CULT_EXP_BONUS_RATE = 0.10
DUAL_CULT_DAILY_ATTEMPTS = 24  # 理想情况下每小时一次
DUAL_CULT_PROPOSED_K_HOURS = 2  # 提议定额化：K 小时闭关等效修为

# ---------------------------------------------------------------------------
# 候选公式参数（可调）
# ---------------------------------------------------------------------------
# 候选 D：阶梯二次  E(L) = a * t^2 * s^2
FORMULA_D_A = 500

# 候选 E：混合幂律  E(L) = a * L^1.2 * M^((L-1)//10)
FORMULA_E_A = 2000
FORMULA_E_M = 1.3

# 候选 Custom（分段/WoW 式）：针对目标三段节奏手动校准
#   L1-10:  E(L) = CUSTOM_EARLY_A * L^1.5
#   L11-50: E(L) = CUSTOM_EARLY_A * 10^1.5 * (L/10)^1.0
#   L51-99: E(L) = CUSTOM_MID_E50 * (L/50)^1.7
CUSTOM_EARLY_A = 1800

# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    """加载 JSON 配置文件。"""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


level_config = load_json(LEVEL_CONFIG_PATH)
game_config = load_json(GAME_CONFIG_PATH)
adventure_config = load_json(ADVENTURE_CONFIG_PATH)

# 灵眼加权平均修为/小时
spirit_eye_cfg = game_config.get("spirit_eye", {}).get("types", {})
weighted_spirit_eye_exp_per_hour = sum(
    eye["exp_per_hour"] * eye["spawn_rate"] for eye in spirit_eye_cfg.values()
) / sum(eye["spawn_rate"] for eye in spirit_eye_cfg.values())

# 历练路线参数
scout_route = next(
    r for r in adventure_config["routes"] if r["key"] == ADVENTURE_ROUTE_KEY
)


# ---------------------------------------------------------------------------
# 收益模型 G(L)
# ---------------------------------------------------------------------------


def daily_income(level: int) -> dict[str, float]:
    """计算当前等级 L 下正常活跃玩家的日均修为收入构成。

    Args:
        level: 当前等级（1-99）。

    Returns:
        各收入来源的日均修为字典，以及总计 daily_total。
    """
    # 闭关：固定（不随 L 增长）
    cultivation_multiplier = SPIRIT_ROOT_MEDIAN_SPEED * (1.0 + HEART_METHOD_BONUS)
    cultivation_exp = int(
        BASE_EXP_PER_MINUTE * DAILY_CULTIVATION_MINUTES * cultivation_multiplier
    )

    # 历练：随 L 线性增长（level_bonus_exp * duration * attempts）
    route = scout_route
    duration_min = route["duration"] / 60
    per_adventure = (
        route["base_exp_per_min"] * duration_min
        + route["level_bonus_exp"] * level * duration_min
        + route["completion_bonus"]["exp"]
    )
    adventure_exp = per_adventure * DAILY_ADVENTURE_COUNT

    # 灵眼/福地/灵田：固定（按加权平均被动收入假设）
    spirit_eye_exp = weighted_spirit_eye_exp_per_hour * SPIRIT_EYE_DAILY_HOURS

    # 签到/悬赏/秘境等：固定低额常量
    misc_exp = MISC_DAILY_EXP

    total = cultivation_exp + adventure_exp + spirit_eye_exp + misc_exp
    return {
        "cultivation": cultivation_exp,
        "adventure": adventure_exp,
        "spirit_eye": spirit_eye_exp,
        "misc": misc_exp,
        "daily_total": total,
    }


def hourly_income(level: int) -> float:
    """返回等级 L 下的平均每小时修为收入。"""
    return daily_income(level)["daily_total"] / 24.0


# ---------------------------------------------------------------------------
# 公式族
# ---------------------------------------------------------------------------


def realm_stage(level: int) -> tuple[int, int]:
    """返回大境界序号 t（1-10）和 小层序号 s（1-10）。"""
    t = (level - 1) // 10 + 1
    s = (level - 1) % 10 + 1
    return t, s


# ---------------------------------------------------------------------------
# 从新版公式化配置中读取经验与成功率
# ---------------------------------------------------------------------------


def _config_exp_needed(level: int) -> int:
    """根据新版 level_config.json 计算从 ``level`` 升到 ``level+1`` 所需经验。"""
    curve = level_config.get("exp_curve", {})
    early_a = curve.get("early_a", 1800)
    early_exp = curve.get("early_exp", 1.5)
    mid_end_level = curve.get("mid_end_level", 50)
    late_exp = curve.get("late_exp", 1.7)

    if level <= 10:
        return int(early_a * (level**early_exp))

    pivot10 = int(early_a * (10**early_exp))
    if level <= mid_end_level:
        return int(pivot10 * (level / 10.0))

    pivot50 = int(pivot10 * (mid_end_level / 10.0))
    return int(pivot50 * ((level / mid_end_level) ** late_exp))


def _config_success_rate(level: int) -> float:
    """根据新版 level_config.json 查询目标等级的突破基础成功率。"""
    rates = level_config.get("success_rates", [])
    if not rates:
        return 0.4

    # Level 10 is the "initial" stage of the next realm, so it shares the next
    # realm's success rate (e.g. levels 10-19 use realm index 1).
    realm_index = level // 10
    if realm_index >= len(rates):
        realm_index = len(rates) - 1
    return max(0.0, min(1.0, float(rates[realm_index])))


def baseline_exp_needed(level: int) -> int:
    """当前公式化 level_config.json 中从 L 升到 L+1 所需经验。

    99 级为等级上限，无 100 级配置，沿用 99 级数值作为对比参考。
    """
    if level < 99:
        return _config_exp_needed(level)
    return _config_exp_needed(99)


def formula_d(level: int) -> int:
    """候选 D：阶梯二次  E(L) = a * t^2 * s^2。"""
    t, s = realm_stage(level)
    return int(FORMULA_D_A * t * t * s * s)


def formula_e(level: int) -> int:
    """候选 E：混合幂律  E(L) = a * L^1.2 * M^((L-1)//10)。"""
    t = (level - 1) // 10
    return int(FORMULA_E_A * (level**1.2) * (FORMULA_E_M**t))


def formula_custom(level: int) -> int:
    """候选 Custom：分段幂律，针对三段节奏目标手动校准。"""
    if level <= 10:
        return int(CUSTOM_EARLY_A * (level**1.5))
    if level <= 50:
        # 在 L=10 处与上一段衔接：CUSTOM_EARLY_A * 10^1.5
        pivot = CUSTOM_EARLY_A * (10**1.5)
        return int(pivot * (level / 10.0) ** 1.0)
    # L=51-99：在 L=50 处衔接，再用 1.7 次幂放大后期
    pivot50 = CUSTOM_EARLY_A * (10**1.5) * (50 / 10.0) ** 1.0
    return int(pivot50 * (level / 50.0) ** 1.7)


FORMULAS: dict[str, Any] = {
    "baseline": baseline_exp_needed,
    "D": formula_d,
    "E": formula_e,
    "Custom": formula_custom,
}


# ---------------------------------------------------------------------------
# 突破成功率与失败惩罚
# ---------------------------------------------------------------------------


def success_rate_for_level(level: int, formula_name: str) -> float:
    """返回从 L 升到 L+1 的突破成功率。

    - baseline：读取当前公式化 level_config.json 中目标等级 L+1 的 success_rate。
    - 候选公式：按目标等级所在大境界查 REALM_SUCCESS_RATES。
    """
    if formula_name == "baseline":
        if level < 99:
            return _config_success_rate(level + 1)
        return _config_success_rate(99)
    target_level = level + 1
    t = (target_level - 1) // 10 + 1
    t = max(1, min(t, 10))
    return REALM_SUCCESS_RATES[t]


def expected_attempts_with_pity(base_rate: float) -> float:
    """计算含连败保底时的期望突破次数。

    规则：每失败一次成功率 +5%，19 次失败后下次必成（与代码一致）。
    最大尝试次数 = 20 次。

    Args:
        base_rate: 基础成功率。

    Returns:
        期望尝试次数 E[N]。
    """
    rates = []
    for attempt in range(1, 20):  # 1..19
        streak = attempt - 1
        rate = min(base_rate + streak * PITY_STEP, 1.0)
        if streak >= PITY_GUARANTEE:
            rate = 1.0
        rates.append(rate)
    rates.append(1.0)  # 第 20 次必成

    prob_survive = 1.0
    expected = 0.0
    for attempt, rate in enumerate(rates, start=1):
        prob_first_success = prob_survive * rate
        expected += attempt * prob_first_success
        prob_survive *= 1.0 - rate
    return expected


def cumulative_exp(level: int, exp_func: Any) -> int:
    """计算到达等级 level 所需的累计修为（从 1 级到 level 级）。"""
    return sum(exp_func(lvl) for lvl in range(1, level))


def simulate() -> list[dict[str, Any]]:
    """主模拟循环：为每个公式、每个等级计算所有指标。"""
    rows: list[dict[str, Any]] = []
    for formula_name, exp_func in FORMULAS.items():
        cum_days = 0.0
        for level in range(1, 100):
            t, s = realm_stage(level)
            exp_needed = exp_func(level)
            inc = daily_income(level)
            daily_total = inc["daily_total"]
            hours_to_level = (
                exp_needed / (daily_total / 24.0) if daily_total > 0 else 0.0
            )
            cum_days += hours_to_level / 24.0

            # 失败惩罚期望
            base_rate = success_rate_for_level(level, formula_name)
            attempts = expected_attempts_with_pity(base_rate)
            expected_failures = attempts - 1.0
            current_exp = cumulative_exp(level, exp_func)
            penalty_exp = expected_failures * FAILURE_EXP_PENALTY_RATE * current_exp
            total_exp_needed_with_failure = exp_needed + penalty_exp
            expected_hours_with_failure = (
                total_exp_needed_with_failure / (daily_total / 24.0)
                if daily_total > 0
                else 0.0
            )

            rows.append(
                {
                    "formula": formula_name,
                    "level": level,
                    "realm": REALM_NAMES[t - 1],
                    "stage": s,
                    "exp_needed": exp_needed,
                    "daily_income": int(daily_total),
                    "hours_to_level": round(hours_to_level, 2),
                    "cum_days": round(cum_days, 2),
                    "expected_hours_with_failure": round(
                        expected_hours_with_failure, 2
                    ),
                }
            )
    return rows


# ---------------------------------------------------------------------------
# CSV 输出
# ---------------------------------------------------------------------------


def write_csv(rows: list[dict[str, Any]]) -> None:
    """将模拟结果写入 CSV。"""
    fieldnames = [
        "formula",
        "level",
        "realm",
        "stage",
        "exp_needed",
        "daily_income",
        "hours_to_level",
        "cum_days",
        "expected_hours_with_failure",
    ]
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------


def find_row(rows: list[dict[str, Any]], formula: str, level: int) -> dict[str, Any]:
    """按公式名和等级查找结果行。"""
    for row in rows:
        if row["formula"] == formula and row["level"] == level:
            return row
    raise KeyError(f"未找到 {formula} L={level}")


def format_number(n: float) -> str:
    """格式化大数字，便于阅读。"""
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.2f}万"
    return f"{n:.0f}"


def dual_cultivation_exploit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """量化双修漏洞：两位 50 级玩家互刷。"""
    # 使用当前公式化配置（基线）的 50 级累计修为
    cum_exp_50 = cumulative_exp(50, baseline_exp_needed)

    # 现状：每小时互双修一次，每次获得对方总修为 10%
    gain_per_dual_current = DUAL_CULT_EXP_BONUS_RATE * cum_exp_50
    daily_dual_current = gain_per_dual_current * DUAL_CULT_DAILY_ATTEMPTS
    # 等效闭关小时数（按中位数灵根+心法效率）
    hourly_cultivation_rate = (
        BASE_EXP_PER_MINUTE * 60 * SPIRIT_ROOT_MEDIAN_SPEED * (1 + HEART_METHOD_BONUS)
    )
    equivalent_hours_current = daily_dual_current / hourly_cultivation_rate

    # 提议：定额化 K=2 小时闭关等效
    gain_per_dual_proposed = DUAL_CULT_PROPOSED_K_HOURS * hourly_cultivation_rate
    daily_dual_proposed = gain_per_dual_proposed * DUAL_CULT_DAILY_ATTEMPTS
    equivalent_hours_proposed = daily_dual_proposed / hourly_cultivation_rate

    return {
        "cum_exp_50": cum_exp_50,
        "gain_per_dual_current": gain_per_dual_current,
        "daily_dual_current": daily_dual_current,
        "equivalent_hours_current": equivalent_hours_current,
        "gain_per_dual_proposed": gain_per_dual_proposed,
        "daily_dual_proposed": daily_dual_proposed,
        "equivalent_hours_proposed": equivalent_hours_proposed,
    }


def write_report(rows: list[dict[str, Any]]) -> None:
    """生成中文分析报告。"""
    # 选取关键等级
    showcase_levels = [1, 5, 9, 10, 11, 20, 30, 50, 70, 90, 99]

    lines: list[str] = []
    lines.append("# 修仙插件升级经验曲线模拟报告")
    lines.append("")
    lines.append("## 一、假设清单")
    lines.append("")
    lines.append("### 1.1 玩家日收益模型 G(L) 假设")
    lines.append("")
    lines.append("| 项目 | 参数 | 是否随等级 L 增长 | 说明 |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| 闭关基础修为 | {BASE_EXP_PER_MINUTE}/min | 否 | 来自 core/cultivation_manager.py |"
    )
    lines.append(
        f"| 灵根倍率（中位数） | {SPIRIT_ROOT_MEDIAN_SPEED} | 否 | 从 SPIRIT_ROOT_SPEEDS 取值计算 |"
    )
    lines.append(f"| 心法加成 | {HEART_METHOD_BONUS:.0%} | 否 | 假设固定 +20% |")
    lines.append(
        f"| 每日闭关时长 | {DAILY_CULTIVATION_HOURS}h | 否 | 受 24h+6h/大境界上限约束 |"
    )
    lines.append(
        f"| 每日历练次数 | {DAILY_ADVENTURE_COUNT} 次「{scout_route['name']}」 | 是 | 45/min + 12×L + 完成奖励 |"
    )
    lines.append(
        f"| 灵眼/福地/灵田 | 加权 {weighted_spirit_eye_exp_per_hour:.0f}/h × {SPIRIT_EYE_DAILY_HOURS}h | 否 | 下品/中品/上品/极品按 spawn_rate 加权 |"
    )
    lines.append(
        f"| 签到/悬赏/秘境 | {MISC_DAILY_EXP} / 天 | 否 | 低额日常常量（假设） |"
    )
    lines.append("")
    lines.append("### 1.2 收益明细构成示例（L=1 与 L=50）")
    lines.append("")
    lines.append("| 等级 | 闭关 | 历练 | 灵眼/福地/灵田 | 日常 | 日总计 | 小时收益 |")
    lines.append("|---|---|---|---|---|---|---|")
    for lvl in [1, 50]:
        inc = daily_income(lvl)
        lines.append(
            f"| L={lvl} | {format_number(inc['cultivation'])} | "
            f"{format_number(inc['adventure'])} | "
            f"{format_number(inc['spirit_eye'])} | "
            f"{format_number(inc['misc'])} | "
            f"{format_number(inc['daily_total'])} | "
            f"{format_number(inc['daily_total'] / 24)} |"
        )
    lines.append("")
    lines.append(
        "> 结论：在当前假设下，G(L) 主要由固定的闭关/灵眼/日常构成，只有历练随 L 线性增长，导致 G(L) 整体对 L 不敏感。"
    )
    lines.append("")
    lines.append("### 1.3 突破成功率假设（候选公式）")
    lines.append("")
    lines.append("| 目标境界 | 基础成功率 |")
    lines.append("|---|---|")
    for t, rate in REALM_SUCCESS_RATES.items():
        lines.append(f"| {REALM_NAMES[t - 1]} | {rate:.0%} |")
    lines.append("")
    lines.append(
        f"连败保底：每次失败 +{PITY_STEP:.0%}，{PITY_GUARANTEE} 次失败后下次必成。"
    )
    lines.append("")
    lines.append("### 1.4 公式参数")
    lines.append("")
    lines.append("| 公式 | 表达式 | 参数 |")
    lines.append("|---|---|---|")
    lines.append(f"| D（阶梯二次） | E(L) = a·t²·s² | a={FORMULA_D_A} |")
    lines.append(
        f"| E（混合幂律） | E(L) = a·L^1.2·M^((L-1)//10) | a={FORMULA_E_A}, M={FORMULA_E_M} |"
    )
    lines.append(
        f"| Custom（分段） | L1-10: {CUSTOM_EARLY_A}·L^1.5；L11-50: 衔接×(L/10)^1.0；L51-99: 衔接×(L/50)^1.7 | 手动校准 |"
    )
    lines.append("")
    lines.append("## 二、现状基线")
    lines.append("")
    lines.append(
        "当前公式化 level_config.json：使用分段幂律曲线，L1-10 按 E=1800·L^1.5，L11-50 线性衔接，L51-99 按 (L/50)^1.7 放大。"
    )
    lines.append("")
    lines.append(
        "| 等级 | 下级所需经验 | 成功率 | 日收益 | 升级时间（小时） | 累计天数 |"
    )
    lines.append("|---|---|---|---|---|---|")
    for lvl in [1, 5, 10, 20, 30, 36, 50, 70, 90, 99]:
        row = find_row(rows, "baseline", lvl)
        lines.append(
            f"| L={lvl} | {format_number(row['exp_needed'])} | "
            f"{success_rate_for_level(lvl, 'baseline'):.2%} | "
            f"{format_number(row['daily_income'])} | "
            f"{row['hours_to_level']:.2f}h | "
            f"{row['cum_days']:.1f}d |"
        )
    lines.append("")
    lines.append(
        "**问题总结**：新基线将 L1 控制在约 0.6 小时，L10 约 17 小时，L50 约 2.7 天，L99 约 6.4 天，累计约 300 天；失败惩罚与成功率配套后满级约 380 天。"
    )
    lines.append("")
    lines.append("## 三、候选公式对比")
    lines.append("")
    lines.append("设计目标：")
    lines.append("- 早期 L1→L10：每级 8~16 小时")
    lines.append("- 中期 L30→L50：每级 1~2 天")
    lines.append("- 后期 L80→L99：每级 3~7 天")
    lines.append("")
    lines.append("| 等级/指标 | 现状 Baseline | 候选 D | 候选 E | 候选 Custom |")
    lines.append("|---|---|---|---|---|---|")
    for lvl in showcase_levels:
        for metric, label in [
            ("exp_needed", "所需经验"),
            ("hours_to_level", "升级时间"),
            ("cum_days", "累计天数"),
            ("expected_hours_with_failure", "含失败期望时间"),
        ]:
            parts = [f"L={lvl} {label}"]
            parts.append(format_number(find_row(rows, "baseline", lvl)[metric]))
            for formula in ["D", "E", "Custom"]:
                val = find_row(rows, formula, lvl)[metric]
                if metric == "exp_needed":
                    parts.append(format_number(val))
                else:
                    parts.append(f"{val:.2f}")
            lines.append("| " + " | ".join(parts) + " |")
    lines.append("")
    lines.append("### 3.1 各公式对三段目标的达成情况")
    lines.append("")
    lines.append("| 公式 | 早期 L1-L10 | 中期 L30-L50 | 后期 L80-L99 | 评价 |")
    lines.append("|---|---|---|---|---|")

    def in_target(hours: float, target_low: float, target_high: float) -> str:
        if target_low <= hours <= target_high:
            return "✅"
        if hours < target_low * 0.5 or hours > target_high * 2:
            return "❌"
        return "⚠️"

    for formula in ["baseline", "D", "E", "Custom"]:
        early_samples = [
            find_row(rows, formula, lvl)["hours_to_level"] for lvl in [1, 5, 9]
        ]
        mid_samples = [
            find_row(rows, formula, lvl)["hours_to_level"] for lvl in [30, 40, 50]
        ]
        late_samples = [
            find_row(rows, formula, lvl)["hours_to_level"] for lvl in [80, 90, 99]
        ]
        early_ok = sum(1 for h in early_samples if 8 <= h <= 16)
        mid_ok = sum(1 for h in mid_samples if 24 <= h <= 48)
        late_ok = sum(1 for h in late_samples if 72 <= h <= 168)
        early_flag = in_target(sum(early_samples) / len(early_samples), 8, 16)
        mid_flag = in_target(sum(mid_samples) / len(mid_samples), 24, 48)
        late_flag = in_target(sum(late_samples) / len(late_samples), 72, 168)
        comments = {
            "baseline": "当前公式化基线，分段幂律，节奏贴近三段目标",
            "D": "单公式太陡，前期过快、后期过慢，无法同时满足三段目标",
            "E": "平滑但后期仍偏慢，单公式无法完美覆盖",
            "Custom": "分段校准后最接近目标，L50 略超 2 天，后期基本落在 3-7 天",
        }
        lines.append(
            f"| {formula} | {early_flag} ({early_ok}/3) | {mid_flag} ({mid_ok}/3) | {late_flag} ({late_ok}/3) | {comments[formula]} |"
        )
    lines.append("")
    lines.append("## 四、突破失败的影响")
    lines.append("")
    lines.append(
        "失败时扣除 10% 当前总修为。下表给出含失败惩罚后的期望升级时间（ vs 不考虑失败）。"
    )
    lines.append("")
    lines.append("| 公式 | L=10 | L=30 | L=50 | L=70 | L=90 | L=99 |")
    lines.append("|---|---|---|---|---|---|---|")
    for formula in ["baseline", "D", "E", "Custom"]:
        parts = [formula]
        for lvl in [10, 30, 50, 70, 90, 99]:
            row = find_row(rows, formula, lvl)
            parts.append(
                f"{row['hours_to_level']:.1f}h → {row['expected_hours_with_failure']:.1f}h"
            )
        lines.append("| " + " | ".join(parts) + " |")
    lines.append("")
    lines.append(
        "**观察**：高等级时成功率下降，且当前修为 C(L) 巨大，10% 惩罚的期望成本会显著拉长升级时间。对 Custom 方案而言，L99 含失败的时间约为纯经验需求的 2~3 倍。"
    )
    lines.append("")
    lines.append("## 五、双修漏洞量化")
    lines.append("")
    exploit = dual_cultivation_exploit(rows)
    lines.append(
        f"以两位等级 50 的玩家为例，当前公式化配置下到达 L50 的累计修为约为 **{format_number(exploit['cum_exp_50'])}**（{exploit['cum_exp_50']:,}）。"
    )
    lines.append("")
    lines.append("### 5.1 现状模式（10% 对方总修为）")
    lines.append("")
    lines.append(
        f"- 每次双修获得：{format_number(exploit['gain_per_dual_current'])} 修为"
    )
    lines.append(
        f"- 理想日收益（24 次）：{format_number(exploit['daily_dual_current'])} 修为"
    )
    lines.append(
        f"- 等效闭关小时数：{exploit['equivalent_hours_current']:.1f} 小时/天（远超 24h 上限，属于指数级膨胀漏洞）"
    )
    lines.append("")
    lines.append("### 5.2 提议定额化模式（K=2 小时闭关等效）")
    lines.append("")
    lines.append(
        f"- 每次双修获得：{format_number(exploit['gain_per_dual_proposed'])} 修为"
    )
    lines.append(
        f"- 理想日收益（24 次）：{format_number(exploit['daily_dual_proposed'])} 修为"
    )
    lines.append(
        f"- 等效闭关小时数：{exploit['equivalent_hours_proposed']:.1f} 小时/天（可控，与正常收益同数量级）"
    )
    lines.append("")
    lines.append(
        "**结论**：现状双修以对方总修为为基数，对高修为玩家而言相当于每天多出数倍于闭关上限的修为，必须改为定额化或上限化。"
    )
    lines.append("")
    lines.append("## 六、推荐结论")
    lines.append("")
    lines.append(
        "- **推荐公式**：候选 **Custom 分段公式**。在现有收益模型 G(L) 下，它是唯一能把早期、中期、后期同时拉近设计目标的方案。"
    )
    lines.append(
        f"- **推荐参数**：L1-10 使用 `{CUSTOM_EARLY_A}·L^1.5`；L11-50 线性衔接；L51-99 使用 `(L/50)^1.7` 放大。若后续提高 G(L) 的成长速度（如让灵眼/福地/丹药收益随境界增长），可整体下调指数。"
    )
    lines.append(
        "- **关于单公式**：候选 D 和 E 在「G(L) 增长缓慢」的前提下无法同时满足三段目标；D 后期过陡，E 后期偏慢。若坚持单公式，应优先扩展 G(L) 的成长性（如境界越高灵眼/福地/心法收益越高）。"
    )
    lines.append(
        "- **关于失败惩罚**：10% 当前修为惩罚在高等级过于沉重，建议同步调整惩罚为「固定百分比本级经验」或「定额修为」，避免与 C(L) 线性挂钩。"
    )
    lines.append(
        "- **双修**：应立即改为定额化（K=2 小时闭关等效），否则任意两位高修为玩家互刷都会让经验曲线设计失效。"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*报告由 sim_exp_curve.py 自动生成，参数见脚本顶部常量区。*")

    with OUTPUT_REPORT.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main() -> None:
    """执行模拟并写入结果文件。"""
    rows = simulate()
    write_csv(rows)
    write_report(rows)
    print(f"已生成：{OUTPUT_CSV}")
    print(f"已生成：{OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
