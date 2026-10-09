#!/usr/bin/env python3
"""PvE acceptance gate: enemies.csv × T2 标模 × 真实引擎验收（pve-enemy-design.md Step 5）。

前身是 Step 2 的一次性原型 proto_pve_roster.py（2026-10-03 落位用）；
2026-10-08 转正为常驻验收门——与 proto 期的关键差异：

- 怪物数据源从脚本内硬编码 ROSTER 换成 **读 enemies.csv**（Step 4 的表就是
  验收对象：五维绝对值直接进 FighterState，脚本不再按公式推导）；
- 机制 key（affix/boss_skill）映射到 Q3c 定案的触发技参数挂载；
- 加自动断言（对照 Step 0 锚点带判 PASS/FAIL，非零退出码），并新增
  **天花板档（T2+绝招）对 Boss ≤70%** 验收格（附录 E 遗留项；若出带，
  调节手柄是 Boss 侧 trim 而非回改标模）。

与 sim_route_matchup.py 的分工：它管 PvP 路线平衡（体修 vs 灵修 50:50±5），
本脚本管 PvE 难度锚（普通 ≥95% / 精英 60-80% / Boss 40-50%，TTK 3-7 / 6-13 / 12-20）。
静态结构校验（矩阵/词缀轮转/落位容差）在 validate_budget.py check_enemies。

Usage:
    uv run python design_docs/content-design/sim_pve_acceptance.py [场次]

Returns:
    Exit code 0 when every cell lands in its band, 1 otherwise.
"""

from __future__ import annotations

import csv
import random
import statistics
import sys
import zlib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent / "attribute-growth"))

from proto_pve_baseline import ENGINE, build_player  # noqa: E402
from sim_xiuxian_turns import make_fighter  # noqa: E402

BATTLES = int(sys.argv[1]) if len(sys.argv) > 1 else 3000

SEGMENT_ORDER = ["练气", "筑基", "金丹", "元婴"]

# 锚点带（Step 0 矩阵；边界比文档 3-6/6-12 宽 1 回合，吸收练气段整数粒度，
# 附录 C.2 发现 4——与 proto 期终验口径一致）
WIN_BAND = {"normal": (0.95, 1.01), "elite": (0.60, 0.80), "boss": (0.40, 0.50)}
TTK_BAND = {"normal": (3, 7), "elite": (6, 13), "boss": (12, 20)}
CEILING_BOSS_WIN_CAP = 0.70  # 天花板档对 Boss 胜率上限（Step 0：不许碾压）

# 机制参数（Q3c 定案；权威文本 pve-enemy-design.md §5 Q3）
# 狂暴/坚甲是纯面板修饰（已含在 CSV 绝对值内），只有嗜血是触发机制。
AFFIX_SKILLS = {
    "嗜血": [
        {
            "name": "嗜血",
            "trigger_timing": "on_attack",
            "trigger_rate": 0.20,
            "effect_type": "heal",
            "effect_value": 0.20,
            "vampire": True,
        }
    ],
}
BOSS_MECHANICS = {
    "拱土疗伤": {
        "skills": [
            {
                "name": "拱土疗伤",
                "trigger_timing": "on_defense",
                "trigger_rate": 0.12,
                "effect_type": "heal",
                "heal_percent": 0.07,
            }
        ],
        "ultimates": [],
    },
    "狼王连咬": {
        "skills": [
            {
                "name": "狼王连咬",
                "trigger_timing": "on_attack",
                "trigger_rate": 0.15,
                "effect_type": "combo",
                "effect_value": 0.5,
            }
        ],
        "ultimates": [],
    },
    "鳞甲反震": {
        "skills": [
            {
                "name": "鳞甲反震",
                "trigger_timing": "on_defense",
                "trigger_rate": 0.20,
                "effect_type": "counter",
                "effect_value": 0.3,
            }
        ],
        "ultimates": [],
    },
    "九尾现形": {
        "skills": [],
        "ultimates": [
            {
                "id": "boss_rage",
                "name": "九尾现形",
                "trigger_self_hp_below": 0.30,
                "trigger_rate": 1.0,
                "effect_type": "buff",
                "stat": "damage",
                "effect_value": 0.10,
                "duration": 3,
            }
        ],
    },
}

# 天花板档绝招（附录 E 扫掠口径：真龙一击，min_action 5、对手 HP<30% 触发、
# +200% 伤害——引擎对未知 ultimate 效果回退 damage_bonus，等价语义）
CEILING_ULTIMATE = {
    "id": "zhenlong",
    "name": "真龙一击",
    "min_action_index": 5,
    "trigger_opponent_hp_below": 0.3,
    "trigger_rate": 1.0,
    "effect_type": "damage_bonus",
    "effect_value": 2.0,
}


def load_roster() -> list[dict]:
    """Read enemies.csv; skip guardian rows (动态匹配机制，胜率锚不在本门范围)。"""
    with (SCRIPT_DIR / "enemies.csv").open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["tier"] != "guardian"]
    rows.sort(key=lambda r: SEGMENT_ORDER.index(r["segment"]))
    return rows


def build_monster(row: dict):
    """Build a monster FighterState directly from one enemies.csv row."""
    fighter = make_fighter(
        hp=int(row["hp"]),
        damage=int(row["damage"]),
        agility=int(row["agility"]),
        speed=int(row["speed"]),
        armor_value=int(row["armor_value"]),
        block_armor_value=int(row["armor_value"]),
        weapon_k=0.5,
        base_damage=5,  # 怪物空手（base 5 + 0.5×伤害，附录 C.4 口径）
        level_index=int(row["level"]),
        name=row["name"],
    )
    if row["tier"] == "elite" and row["affix"] in AFFIX_SKILLS:
        fighter.trigger_skills = [dict(s) for s in AFFIX_SKILLS[row["affix"]]]
    elif row["tier"] == "boss":
        mech = BOSS_MECHANICS[row["boss_skill"]]
        fighter.trigger_skills = [dict(s) for s in mech["skills"]]
        fighter.ultimates = [dict(u) for u in mech["ultimates"]]
    return fighter


def run_cell(row: dict, route: str, battles: int, ceiling: bool = False) -> dict:
    """Run one (monster, route) cell with deterministic per-battle seeding."""
    level = int(row["level"])
    tag = "t3" if ceiling else "t2"
    cell_seed = zlib.crc32(f"{row['id']}|{route}|{tag}".encode()) % 10**6
    rng = random.Random(cell_seed)
    wins = draws = 0
    rounds_list: list[int] = []
    hp_left_win: list[float] = []
    for _ in range(battles):
        random.seed(rng.randint(0, 2**31 - 1))
        player = build_player(route, level, with_skills=True)
        if ceiling:
            player.ultimates = [dict(CEILING_ULTIMATE)]
        monster = build_monster(row)
        r = ENGINE.resolve_combat(player, monster, combat_type="spar", merge_count=10)
        rounds_list.append(r.rounds)
        if r.winner_side == "draw":
            draws += 1
        elif r.winner_side == "fighter1":
            wins += 1
            hp_left_win.append(r.fighter1_final_hp / player.max_hp)
    return {
        "win": wins / battles,
        "draw": draws / battles,
        "rounds": statistics.mean(rounds_list),
        "tax": 1 - (statistics.mean(hp_left_win) if hp_left_win else 1.0),
    }


def main() -> int:
    roster = load_roster()
    failures: list[str] = []
    print(f"=== PvE 验收：enemies.csv {len(roster)} 只 × 2 路线，{BATTLES} 场/格 ===")

    for seg in SEGMENT_ORDER:
        print(f"\n--- {seg}段 ---")
        print(
            f"{'怪':<16}{'档':<8}{'胜率·体':>8}{'胜率·灵':>8}{'回合':>6}{'损税':>6}  判定"
        )
        for row in [r for r in roster if r["segment"] == seg]:
            cells = [run_cell(row, route, BATTLES) for route in ("体修", "灵修")]
            tier = row["tier"]
            wlo, whi = WIN_BAND[tier]
            tlo, thi = TTK_BAND[tier]
            wmin = min(c["win"] for c in cells)
            wmax = max(c["win"] for c in cells)
            rounds = statistics.mean(c["rounds"] for c in cells)
            tax = statistics.mean(c["tax"] for c in cells)
            wok = wlo <= wmin and wmax <= whi
            tok = tlo <= rounds <= thi
            if not wok:
                failures.append(
                    f"{row['id']} 胜率出带：[{wmin:.1%},{wmax:.1%}] ∉ [{wlo:.0%},{whi:.0%}]"
                )
            if not tok:
                failures.append(f"{row['id']} TTK 出带：{rounds:.1f} ∉ [{tlo},{thi}]")
            print(
                f"{row['name']:<16}{tier:<8}"
                f"{cells[0]['win']:>7.1%}{cells[1]['win']:>8.1%}"
                f"{rounds:>6.1f}{tax:>6.0%}  {'✓' if wok else '✗'}{'✓' if tok else '✗'}"
            )

    # 天花板档（T2+绝招）对 Boss：≤70% 不许碾压（附录 E 遗留项）
    print(f"\n--- 天花板档（T2+绝招）对 Boss，{BATTLES} 场/格 ---")
    print(f"{'怪':<16}{'胜率·体':>8}{'胜率·灵':>8}{'回合':>6}  判定")
    for row in [r for r in roster if r["tier"] == "boss"]:
        cells = [
            run_cell(row, route, BATTLES, ceiling=True) for route in ("体修", "灵修")
        ]
        wmax = max(c["win"] for c in cells)
        rounds = statistics.mean(c["rounds"] for c in cells)
        ok = wmax <= CEILING_BOSS_WIN_CAP
        if not ok:
            failures.append(
                f"{row['id']} 天花板胜率 {wmax:.1%} 突破 ≤{CEILING_BOSS_WIN_CAP:.0%} 上限"
            )
        print(
            f"{row['name']:<16}{cells[0]['win']:>7.1%}{cells[1]['win']:>8.1%}"
            f"{rounds:>6.1f}  {'✓' if ok else '✗'}"
        )

    total = len(roster) * 2 + 8
    if failures:
        print(f"\nFAIL {len(failures)}/{total} 项出带：")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print(f"\nPASS：{total} 项全在带内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
