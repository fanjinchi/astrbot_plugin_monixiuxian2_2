"""PROTOTYPE（一次性脚本，非生产代码）：PVE 难度锚体感模拟。

回答问题：pve-enemy-design.md Step 0 的假设目标（普通 ≥95% / 精英 ~70% /
Boss 40-50%，TTK 3-6 / 6-12 / 12-20 回合）打起来是什么手感？

方法：用真实战斗引擎（CombatEngine）跑 标模玩家 vs 三档怪物，输出胜率 /
回合数分布 / 胜场损血 / 反向下限，并打印样本战报供阅读。

怪物数值为第一轮手拍初值（相对标模面板的系数），靠本脚本迭代收口——
这正是"公式给初值、模拟收口"的演示。

运行：uv run python design_docs/content-design/proto_pve_feel.py [场次]
"""

from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent / "attribute-growth"))

from sim_route_matchup import expected_route_attrs  # noqa: E402
from sim_xiuxian_turns import ENGINE, make_fighter, pick_best_weapon  # noqa: E402

# ---------------------------------------------------------------------------
# 场景：筑基段 L10 标模玩家（门槛级 + 同品级标杆装，凡品）
# ---------------------------------------------------------------------------
BAND_LEVEL = 10
BATTLES = int(sys.argv[1]) if len(sys.argv) > 1 else 1000

# 凡品防具设计值（armors.csv 标杆件）：重甲 armor7/hp+0，法袍 armor3/hp+8
_ARMOR_PIECE = {"体修": {"armor": 7, "hp": 0}, "灵修": {"armor": 3, "hp": 8}}

# 标模定义含"通用功法"（Step 0）——v1-v4 原型漏了这条，v5 补上两本既有通用功法
# （skills.csv：基础吐纳 期望增益 3%；铁布衫 期望减伤 10%），量化玩家侧功法对落位的影响。
# 引擎键为 trigger_timing/trigger_rate（CSV 的 trigger_condition 入库时归一化映射）。
PLAYER_SKILLS = [
    {
        "name": "基础吐纳",
        "trigger_timing": "on_attack",
        "trigger_rate": 0.15,
        "effect_type": "damage_bonus",
        "effect_value": 0.2,
    },
    {
        "name": "铁布衫",
        "trigger_timing": "on_defense",
        "trigger_rate": 0.2,
        "effect_type": "damage_reduction",
        "effect_value": 0.5,
    },
]


def build_reference_player(route: str, with_skills: bool = False) -> object:
    """区段标模：门槛级期望面板 + 同品级标杆武器 + 同族防具（不入格挡）。"""
    attrs = expected_route_attrs(route, BAND_LEVEL)
    weapon = pick_best_weapon(BAND_LEVEL)
    piece = _ARMOR_PIECE[route]
    natural_armor = int(attrs["armor_value"])
    fighter = make_fighter(
        hp=int(attrs["hp"]) + piece["hp"],
        damage=int(attrs["damage"]) + weapon.damage,
        agility=int(attrs["agility"]),
        speed=int(attrs["speed"]),
        armor_value=natural_armor + weapon.armor_value + piece["armor"],
        block_armor_value=natural_armor + weapon.armor_value,  # 防具不计格挡
        weapon_k=weapon.weapon_k,
        base_damage=weapon.base_damage,
        level_index=BAND_LEVEL,
        name=f"{route}·标模",
    )
    if with_skills:
        fighter.trigger_skills = [dict(s) for s in PLAYER_SKILLS]
    return fighter


# ---------------------------------------------------------------------------
# 怪物初值：相对标模面板的系数（手拍第一轮，靠模拟迭代收口）
# 怪物空手（引擎保底 base=5, K=0.5）；护甲视为天生（全额计格挡）。
# ---------------------------------------------------------------------------
def _ref_panel() -> dict[str, float]:
    """两路线标模的战斗相关均值，作为怪物系数的基数。"""
    panel = {"hp": 0.0, "damage": 0.0, "agility": 0.0, "speed": 0.0}
    for route in ("体修", "灵修"):
        attrs = expected_route_attrs(route, BAND_LEVEL)
        weapon = pick_best_weapon(BAND_LEVEL)
        panel["hp"] += (attrs["hp"] + _ARMOR_PIECE[route]["hp"]) / 2
        panel["damage"] += (attrs["damage"] + weapon.damage) / 2
        panel["agility"] += attrs["agility"] / 2
        panel["speed"] += attrs["speed"] / 2
    return panel


_REF = _ref_panel()

# (名称, hp×, dmg×, agi×, spd×, 护甲固定值)
# v4 (0.48/0.42, 1.10/0.78, 1.45/0.78) 无功法标模全部落位；
# v5 补功法后精英 +6-7pp、Boss +9pp 越出目标带——证明标模必须含功法；
# v6 对带功法标模重新落位：精英 hp 1.10→1.20，Boss hp 1.45→1.55。
MONSTERS = {
    "普通·疾风狼": ("疾风狼", 0.48, 0.42, 1.10, 1.00, 0),
    "精英·历战的疾风狼": ("历战的疾风狼", 1.20, 0.80, 1.15, 1.08, 5),
    "BOSS·苍月狼王": ("苍月狼王", 1.55, 0.78, 1.12, 1.05, 10),
}


def build_monster(tier: str) -> object:
    name, hp_m, dmg_m, agi_m, spd_m, armor = MONSTERS[tier]
    return make_fighter(
        hp=int(_REF["hp"] * hp_m),
        damage=max(1, int(_REF["damage"] * dmg_m)),
        agility=int(_REF["agility"] * agi_m),
        speed=int(_REF["speed"] * spd_m),
        armor_value=armor,
        block_armor_value=armor,  # 怪物护甲视为天生：全额计格挡
        weapon_k=0.5,  # 空手保底（引擎 _calc_damage 对无武器者的口径）
        base_damage=5,
        level_index=BAND_LEVEL,
        name=name,
    )


# ---------------------------------------------------------------------------
# 模拟
# ---------------------------------------------------------------------------
def run_cell(route: str, tier: str, battles: int, seed: int, with_skills: bool) -> dict:
    """Run one (route, tier, loadout) cell and collect win/rounds/HP-loss stats."""
    rng = random.Random(seed)
    wins = draws = 0
    rounds_list: list[int] = []
    hp_left_win: list[float] = []
    loss_rounds: list[int] = []
    for _ in range(battles):
        random.seed(rng.randint(0, 2**31 - 1))
        player = build_reference_player(route, with_skills=with_skills)
        monster = build_monster(tier)
        r = ENGINE.resolve_combat(player, monster, combat_type="spar", merge_count=10)
        rounds_list.append(r.rounds)
        if r.winner_side == "draw":
            draws += 1
        elif r.winner_side == "fighter1":
            wins += 1
            hp_left_win.append(r.fighter1_final_hp / player.max_hp)
        else:
            loss_rounds.append(r.rounds)
    n = battles
    return {
        "win": wins / n,
        "draw": draws / n,
        "rounds_avg": statistics.mean(rounds_list),
        "rounds_p90": sorted(rounds_list)[int(n * 0.9)],
        "hp_left": statistics.mean(hp_left_win) if hp_left_win else 0.0,
        "loss_rounds_min": min(loss_rounds) if loss_rounds else None,
    }


def sample_log(route: str, tier: str, seed: int, max_lines: int = 45) -> str:
    """Produce one seeded sample battle log for reading."""
    random.seed(seed)
    player, monster = build_reference_player(route), build_monster(tier)
    r = ENGINE.resolve_combat(player, monster, combat_type="spar", merge_count=10)
    log = r.combat_log
    if len(log) > max_lines:
        log = log[: max_lines // 2] + ["……（中段省略）……"] + log[-max_lines // 2 :]
    outcome = {"fighter1": "玩家胜", "fighter2": "怪物胜", "draw": "平局"}[
        r.winner_side
    ]
    header = f"【{route} vs {MONSTERS[tier][0]}】{outcome}，{r.rounds} 回合，玩家余血 {r.fighter1_final_hp}/{player.max_hp}"
    return header + "\n" + "\n".join(log)


def main() -> None:
    print(f"=== PVE 体感原型：筑基段 L{BAND_LEVEL} 标模，{BATTLES} 场/格 ===")
    print(
        f"标模参考面板（两路线均值）：HP {_REF['hp']:.0f} / 伤害 {_REF['damage']:.0f} "
        f"/ 身法 {_REF['agility']:.0f} / 迅捷 {_REF['speed']:.0f}"
    )
    for tier in MONSTERS:
        m = build_monster(tier)
        print(
            f"{tier}: HP {m.hp} / 伤害 {m.damage} / 身法 {m.agility} / 迅捷 {m.speed} / 护甲 {m.armor_value}"
        )
    print()
    header = f"{'档位':<14}{'路线':<6}{'功法':<6}{'胜率':>7}{'平局':>6}{'回合均':>7}{'P90':>5}{'胜场余血':>9}{'败局最短':>9}"
    print(header)
    print("-" * len(header.encode("gbk", "replace")))
    for tier in MONSTERS:
        for i, route in enumerate(("体修", "灵修")):
            for j, with_skills in enumerate((False, True)):
                s = run_cell(
                    route,
                    tier,
                    BATTLES,
                    seed=hash((tier, route, with_skills)) % 10**6,
                    with_skills=with_skills,
                )
                loss_min = f"{s['loss_rounds_min']}" if s["loss_rounds_min"] else "-"
                label = tier if (i == 0 and j == 0) else ""
                print(
                    f"{label:<14}{route:<6}{'带功法' if with_skills else '无功法':<6}"
                    f"{s['win']:>6.1%}{s['draw']:>6.1%}"
                    f"{s['rounds_avg']:>7.1f}{s['rounds_p90']:>5}{s['hp_left']:>9.0%}{loss_min:>9}"
                )
    print()
    print("=== 样本战报 ===")
    print(sample_log("体修", "普通·疾风狼", seed=42, max_lines=20))
    print()
    print(sample_log("灵修", "精英·历战的疾风狼", seed=7, max_lines=30))
    print()
    print(sample_log("体修", "BOSS·苍月狼王", seed=1, max_lines=45))


if __name__ == "__main__":
    main()
