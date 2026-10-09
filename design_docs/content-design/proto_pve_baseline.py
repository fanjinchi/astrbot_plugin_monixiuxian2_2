"""PROTOTYPE（一次性脚本，非生产代码）：Step 1 PvE 基准表推导。

回答问题：v6 筑基段落位系数能否平移到其余境界段？若不能，每段每档的
怪物绝对面板（HP/伤害/身法/迅捷/护甲）应取多少，才能同时命中封板目标：
胜率 普通≥95% / 精英~70% / Boss 40-50%，TTK 3-6 / 6-12 / 12-20 回合。

方法：解析反推给初值（命中回合数目标 → HP；败北回合数目标 → 伤害），
真实引擎模拟收口。标模为 T2 口径（2026-10-03 用户拍板）：门槛级期望面板 ×
心法被动（长春功 HP×1.1）+ 门槛可穿的同品级标杆武器/防具 + 通用功法 2 本 +
路线主修 1 本；绝招不进标模（天花板档验收项）。
第一季范围：练气 L1 / 筑基 L10 / 金丹 L20 / 元婴 L30。

运行：uv run python design_docs/content-design/proto_pve_baseline.py [场次]
"""

from __future__ import annotations

import csv
import random
import statistics
import sys
import zlib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent / "attribute-growth"))

from sim_route_matchup import expected_route_attrs  # noqa: E402
from sim_xiuxian_turns import ENGINE, make_fighter, pick_best_weapon  # noqa: E402

BATTLES = int(sys.argv[1]) if len(sys.argv) > 1 else 800

# 第一季四段：段位名 + 门槛级（标模锚点）
SEGMENTS = [("练气", 1), ("筑基", 10), ("金丹", 20), ("元婴", 30)]

# 标模功法（T2 口径，2026-10-03 用户拍板）：通用 2 本（基础吐纳/铁布衫）+
# 路线主修 1 本（灵修·青云剑诀 / 体修·铁山靠），外加心法被动（长春功 HP×1.1，
# 属面板不进 trigger_skills）。敏感性扫掠（附录 E）证明缺这些胜率漂 +17~49pp。
# 绝招不进标模——绝招属天花板档验收项（≤70% 防碾压线）。
PLAYER_SKILLS_COMMON = [
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
PLAYER_SKILLS_ROUTE = {
    "灵修": {
        "name": "青云一剑",
        "trigger_timing": "on_attack",
        "trigger_rate": 0.18,
        "effect_type": "damage_bonus",
        "effect_value": 0.3,
    },
    # 体修第三本按等期望通用增伤建模（0.18×0.3 与灵修青云剑诀同 EV）：
    # T2 首轮曾用铁山靠（counter×1.0），实测体修胜率比灵修高 +20pp——反击
    # 穿甲 raw 在长盘反复触发远超增伤功法，具体门派技的路线偏斜不应进标模。
    "体修": {
        "name": "崩山掌",
        "trigger_timing": "on_attack",
        "trigger_rate": 0.18,
        "effect_type": "damage_bonus",
        "effect_value": 0.3,
    },
}
# 长春功 passive_bonus.hp_percent（config/heart_methods.json heart_001）
HEART_METHOD_HP_MULT = 1.1

# 档位推导目标：ttk_win = 标模杀怪回合数；ttk_lose = 怪杀标模回合数（决定胜率）。
# agi/spd 比与护甲减伤率 r 沿用 v6 的档位性格（怪更灵巧、Boss 甲厚）。
# 落位记录（5 轮迭代，详表见 pve-enemy-design.md 附录 C）：解析初值系统性偏弱，
# 胜率对 ttk_lose 呈陡崖敏感（15.0→84%、14.3→66%、≈13.9→45%）；精英/Boss 的胜率差
# 主要靠 ttk_win（HP 厚度）制造。普通 ttk_win 解析低估约 15%，落位取 4.4。
TIERS = {
    "普通": {
        "ttk_win": 4.4,
        "ttk_lose": 26.0,
        "agi_k": 1.10,
        "spd_k": 1.00,
        "r_armor": 0.00,
    },
    "精英": {
        "ttk_win": 12.0,
        "ttk_lose": 13.2,
        "agi_k": 1.15,
        "spd_k": 1.08,
        "r_armor": 0.03,
    },
    "BOSS": {
        "ttk_win": 15.0,
        "ttk_lose": 12.3,
        "agi_k": 1.12,
        "spd_k": 1.05,
        "r_armor": 0.06,
    },
}

# 胜率验收带（轴一封板）：普通 ≥95%、精英 60-80%、Boss 40-50%（±5pp 容忍）
WIN_BAND = {"普通": (0.95, 1.01), "精英": (0.60, 0.80), "BOSS": (0.40, 0.50)}
TTK_BAND = {"普通": (3, 6), "精英": (6, 12), "BOSS": (12, 20)}

_ARMOR_RANK_ORDER = [
    "凡品",
    "灵品",
    "地品",
    "天品",
    "皇品",
    "帝品",
    "道品",
    "仙品",
    "混元先天",
]


def load_benchmark_armors() -> dict[int, dict[str, dict]]:
    """Per anchor level, best wearable benchmark armor piece per family."""
    pieces: list[dict] = []
    with (SCRIPT_DIR / "armors.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pieces.append(row)
    out: dict[int, dict[str, dict]] = {}
    for _, level in SEGMENTS:
        per_family: dict[str, dict] = {}
        for family in ("重甲", "法袍"):
            candidates = [
                p
                for p in pieces
                if p["armor_family"] == family
                and int(p["required_level_index"]) <= level
            ]
            best = max(
                candidates,
                key=lambda p: (
                    _ARMOR_RANK_ORDER.index(p["rank"]),
                    int(p["armor_value"]),
                ),
            )
            per_family[family] = best
        out[level] = per_family
    return out


BENCH_ARMORS = load_benchmark_armors()


def build_player(route: str, level: int, with_skills: bool = True):
    """区段标模（T2 口径）：门槛期望面板×心法 + 标杆武器/防具 + 通用功法 + 路线主修。"""
    attrs = expected_route_attrs(route, level)
    weapon = pick_best_weapon(level)
    piece = BENCH_ARMORS[level]["重甲" if route == "体修" else "法袍"]
    natural_armor = int(attrs["armor_value"])
    piece_armor = int(piece["armor_value"])
    fighter = make_fighter(
        hp=int((int(attrs["hp"]) + int(piece["bonus_hp"])) * HEART_METHOD_HP_MULT),
        damage=int(attrs["damage"]) + weapon.damage,
        agility=int(attrs["agility"]),
        speed=int(attrs["speed"]),
        armor_value=natural_armor + weapon.armor_value + piece_armor,
        block_armor_value=natural_armor + weapon.armor_value,
        weapon_k=weapon.weapon_k,
        base_damage=weapon.base_damage,
        level_index=level,
        name=f"{route}·标模",
    )
    if with_skills:
        fighter.trigger_skills = [dict(s) for s in PLAYER_SKILLS_COMMON]
        fighter.trigger_skills.append(dict(PLAYER_SKILLS_ROUTE[route]))
    return fighter


def ref_panel(level: int) -> dict[str, float]:
    """两路线标模的战斗相关均值面板（含武器/防具），怪物推导的基数。"""
    panel = {
        "hp": 0.0,
        "damage": 0.0,
        "agility": 0.0,
        "speed": 0.0,
        "armor": 0.0,
        "block_armor": 0.0,
        "raw": 0.0,
    }
    for route in ("体修", "灵修"):
        p = build_player(route, level, with_skills=False)
        raw = p.base_damage + p.damage * p.weapon_k  # 标模每次出手的名义伤害
        panel["hp"] += p.hp / 2
        panel["damage"] += p.damage / 2
        panel["agility"] += p.agility / 2
        panel["speed"] += p.speed / 2
        panel["armor"] += p.armor_value / 2
        panel["block_armor"] += p.block_armor_value / 2
        panel["raw"] += raw / 2
    return panel


def derive_monster(ref: dict[str, float], tier: str, level: int) -> dict[str, float]:
    """解析反推怪物面板初值：命中/败北回合数目标 → HP/伤害，模拟负责收口。"""
    t = TIERS[tier]
    k_shrink = 100 + 10 * level  # 引擎百分比减伤常数 K
    m_armor = t["r_armor"] / (1 - t["r_armor"]) * k_shrink if t["r_armor"] else 0.0
    m_agi = ref["agility"] * t["agi_k"]
    m_spd = ref["speed"] * t["spd_k"]

    # 标模 → 怪：每次出手期望（暴击 1.075、对方闪避/格挡减半、百分比减伤）
    dodge_m = min(max(0.05 + (m_agi - ref["agility"]) * 0.005, 0.0), 0.5)
    block_m = min(0.05 + m_armor * 0.001, 0.30)
    r_m = m_armor / (k_shrink + m_armor)
    p_eff = ref["raw"] * 1.075 * (1 - dodge_m) * (1 - block_m * 0.5) * (1 - r_m)
    p_apr = 2 * ref["speed"] / (ref["speed"] + m_spd)  # 标模每回合出手次数
    m_hp = p_eff * p_apr * t["ttk_win"]

    # 怪 → 标模：怪物空手（base 5 + 0.5×dmg），反解 dmg 使 ttk_lose 成立
    dodge_p = min(max(0.05 + (ref["agility"] - m_agi) * 0.005, 0.0), 0.5)
    block_p = min(0.05 + ref["block_armor"] * 0.001, 0.30)
    r_p = ref["armor"] / (k_shrink + ref["armor"])
    m_apr = 2 * m_spd / (ref["speed"] + m_spd)
    need_per_hit = ref["hp"] / t["ttk_lose"] / m_apr
    m_raw = need_per_hit / (1.075 * (1 - dodge_p) * (1 - block_p * 0.5) * (1 - r_p))
    m_dmg = max(1.0, (m_raw - 5) / 0.5)

    return {
        "hp": m_hp,
        "damage": m_dmg,
        "agility": m_agi,
        "speed": m_spd,
        "armor": m_armor,
    }


def build_monster(stats: dict[str, float], tier: str, level: int, seg: str):
    return make_fighter(
        hp=int(stats["hp"]),
        damage=max(1, int(stats["damage"])),
        agility=int(stats["agility"]),
        speed=int(stats["speed"]),
        armor_value=int(stats["armor"]),
        block_armor_value=int(stats["armor"]),  # 怪物护甲视为天生：全额计格挡
        weapon_k=0.5,  # 空手保底（与 v6 同口径）
        base_damage=5,
        level_index=level,
        name=f"{seg}{tier}怪",
    )


def run_cell(
    route: str, level: int, stats: dict[str, float], tier: str, seg: str, battles: int
) -> dict:
    """Run one (segment, tier, route) cell with per-battle seeding."""
    cell_seed = zlib.crc32(f"{seg}|{tier}|{route}".encode()) % 10**6
    rng = random.Random(cell_seed)
    wins = draws = 0
    rounds_list: list[int] = []
    hp_left_win: list[float] = []
    loss_rounds: list[int] = []
    for _ in range(battles):
        random.seed(rng.randint(0, 2**31 - 1))
        player = build_player(route, level, with_skills=True)
        monster = build_monster(stats, tier, level, seg)
        r = ENGINE.resolve_combat(player, monster, combat_type="spar", merge_count=10)
        rounds_list.append(r.rounds)
        if r.winner_side == "draw":
            draws += 1
        elif r.winner_side == "fighter1":
            wins += 1
            hp_left_win.append(r.fighter1_final_hp / player.max_hp)
        else:
            loss_rounds.append(r.rounds)
    return {
        "win": wins / battles,
        "draw": draws / battles,
        "rounds_avg": statistics.mean(rounds_list),
        "hp_left": statistics.mean(hp_left_win) if hp_left_win else 0.0,
        "loss_rounds_min": min(loss_rounds) if loss_rounds else None,
    }


def main() -> None:
    print(
        f"=== Step 1 基准表扫掠：4 段 × 3 档 × 2 路线，{BATTLES} 场/格（带功法标模）==="
    )
    for seg, level in SEGMENTS:
        ref = ref_panel(level)
        weapon = pick_best_weapon(level)
        armors = BENCH_ARMORS[level]
        print(f"\n--- {seg}段 L{level} 门槛标模 ---")
        print(
            f"标模均值面板：HP {ref['hp']:.0f} / 伤害 {ref['damage']:.0f} / 身法 {ref['agility']:.0f} "
            f"/ 迅捷 {ref['speed']:.0f} / 护甲 {ref['armor']:.0f} / 名义出手 {ref['raw']:.0f}"
        )
        print(
            f"标杆装备：{weapon.name}（{weapon.rank}）＋ 重甲[{armors['重甲']['name']}] / 法袍[{armors['法袍']['name']}]"
        )
        for tier in TIERS:
            stats = derive_monster(ref, tier, level)
            coeff = (
                f"系数: HP×{stats['hp'] / ref['hp']:.2f} 伤害×{stats['damage'] / ref['damage']:.2f} "
                f"身法×{TIERS[tier]['agi_k']:.2f} 迅捷×{TIERS[tier]['spd_k']:.2f} 甲{stats['armor']:.0f}"
            )
            print(
                f"\n[{seg}·{tier}] 面板 HP {stats['hp']:.0f} / 伤害 {stats['damage']:.0f} "
                f"/ 身法 {stats['agility']:.0f} / 迅捷 {stats['speed']:.0f} / 护甲 {stats['armor']:.0f}"
            )
            print(f"  {coeff}")
            for route in ("体修", "灵修"):
                s = run_cell(route, level, stats, tier, seg, BATTLES)
                wlo, whi = WIN_BAND[tier]
                tlo, thi = TTK_BAND[tier]
                wflag = "✓" if wlo <= s["win"] <= whi else "✗"
                tflag = "✓" if tlo <= s["rounds_avg"] <= thi else "✗"
                loss_min = s["loss_rounds_min"] if s["loss_rounds_min"] else "-"
                print(
                    f"  {route}: 胜率 {s['win']:6.1%}{wflag} 平局 {s['draw']:5.1%} "
                    f"回合 {s['rounds_avg']:5.1f}{tflag} 胜场余血 {s['hp_left']:5.0%} "
                    f"败局最短 {loss_min}"
                )


if __name__ == "__main__":
    main()
