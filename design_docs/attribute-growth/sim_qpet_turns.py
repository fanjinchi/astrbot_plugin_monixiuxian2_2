"""Q宠大乐斗早期版本镜像战回合数模拟器。

基于本地调研资料（design_docs/qpet-daledou/ 下的 battle-mechanics.md、
research-notes.md、weapons-skills.md）中的战斗公式与机制，对两只**完全相同**
的宠物进行全自动战斗模拟，估算平均回合数（TTK）。

运行方式（必须在 AstrBot 宿主目录下使用其 uv 环境）：
    cd /home/guigui/code/AstrBot
    uv run python /home/guigui/code/AstrBot/data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/sim_qpet_turns.py

输出：同目录下的 qpet-daledou-battle-turns.csv
"""

from __future__ import annotations

import csv
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path

SEED = 2025_06_11
BATTLES = 5000
MAX_ROUNDS = 2000
COUNTER_PROB = 0.15
FAKE_DEATH_PROB = 0.10

SCENARIOS: dict[str, dict[str, object]] = {
    "unarmed": {
        "base_min": 8,
        "base_max": 15,
        "skill_bonus": 0.20,
        "crit_rate": 0.05,
        "combo_rate": 0.20,
        "weapon": "",
        "note": "肉搏好手/武术好手+20%，无影手连击20%",
    },
    "red_spear": {
        "base_min": 15,
        "base_max": 30,
        "skill_bonus": 0.20,
        "crit_rate": 0.10,
        "combo_rate": 0.10,
        "weapon": "red_spear(15-30)",
        "note": "武器好手+20%，红缨枪10%连击",
    },
}

LEVELS = (10, 20, 30, 40, 50)

FIELDNAMES = [
    "scenario",
    "level",
    "power_str",
    "agi",
    "spd",
    "defense",
    "hp",
    "weapon",
    "battles",
    "rounds_mean",
    "rounds_median",
    "rounds_p10",
    "rounds_p90",
    "rounds_min",
    "rounds_max",
    "ttk_analytic",
    "notes",
]


@dataclass
class Pet:
    """镜像战中一方的属性快照。"""

    level: int
    power: float
    agi: float
    spd: float
    defense: float
    max_hp: int
    scenario: dict[str, object]
    hp: int = field(init=False)
    fake_death_used: bool = field(init=False)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.hp = self.max_hp
        self.fake_death_used = False


def dodge_probability(agi: float) -> float:
    """根据敏捷估算基础闪避率（社区经验公式，资料未公开精确式）。"""
    return min(0.35, 0.04 + agi * 0.008)


def build_pet(level: int, scenario_name: str) -> Pet:
    """根据等级和场景构造宠物。

    属性成长曲线为基于“每次升级+1点随机属性/潜心补偿”的近似代表点，
    因为资料中未给出逐级的官方基础属性表。
    """
    power = 5 + level // 3
    agi = 5 + level // 4
    spd = 5 + level // 3
    defense = 2 + level * 0.3
    max_hp = 50 + level * 11
    return Pet(level, power, agi, spd, defense, max_hp, SCENARIOS[scenario_name])


def attack(
    attacker: Pet,
    defender: Pet,
    allow_counter: bool = True,
    rng: random.Random = random,
) -> None:
    """执行一次攻击，含闪避、暴击、减法防御、装死与反击。"""
    if defender.hp <= 0:
        return

    if rng.random() < dodge_probability(defender.agi):
        return

    scenario = attacker.scenario
    base_min = float(scenario["base_min"])
    base_max = float(scenario["base_max"])
    skill_bonus = float(scenario["skill_bonus"])
    crit_rate = float(scenario["crit_rate"])

    base = rng.uniform(base_min, base_max)
    raw = base * (attacker.power / 10.0) * (1.0 + skill_bonus)
    if rng.random() < crit_rate:
        raw *= 1.5

    final = max(1, int(round(raw - defender.defense)))
    defender.hp -= final

    if defender.hp <= 0 and not defender.fake_death_used:
        if rng.random() < FAKE_DEATH_PROB:
            defender.hp = 1
            defender.fake_death_used = True

    if allow_counter and defender.hp > 0 and rng.random() < COUNTER_PROB:
        # 反击不再触发二次反击，避免无限链。
        attack(defender, attacker, allow_counter=False, rng=rng)


def perform_turn(attacker: Pet, defender: Pet, rng: random.Random) -> None:
    """一方的完整回合：基础攻击 + 可能触发的连击。"""
    while True:
        attack(attacker, defender, allow_counter=True, rng=rng)
        combo_rate = float(attacker.scenario["combo_rate"])
        if defender.hp <= 0 or rng.random() >= combo_rate:
            break


def simulate_one(pet0: Pet, pet1: Pet, rng: random.Random) -> int:
    """模拟一场镜像战，返回消耗的回合数。"""
    pet0.reset()
    pet1.reset()
    first: int = rng.choice((0, 1))

    for current_round in range(1, MAX_ROUNDS + 1):
        if first == 0:
            perform_turn(pet0, pet1, rng)
            if pet1.hp <= 0:
                return current_round
            perform_turn(pet1, pet0, rng)
            if pet0.hp <= 0:
                return current_round
        else:
            perform_turn(pet1, pet0, rng)
            if pet0.hp <= 0:
                return current_round
            perform_turn(pet0, pet1, rng)
            if pet1.hp <= 0:
                return current_round

    return MAX_ROUNDS


def analytic_ttk(pet: Pet) -> float:
    """基于简化公式的解析期望回合数（仅用于与模拟结果对照）。

    假设：双方每回合各出手1次（速度相同=1:1），只考虑武器基础伤害期望、
    力量系数、技能加成、暴击和闪避，忽略连击、反击、装死与控制。
    """
    scenario = pet.scenario
    avg_base = (float(scenario["base_min"]) + float(scenario["base_max"])) / 2.0
    crit_rate = float(scenario["crit_rate"])

    raw = avg_base * (pet.power / 10.0) * (1.0 + float(scenario["skill_bonus"]))
    raw *= 1.0 + crit_rate * 0.5  # 暴击期望：1.5倍伤害，加权后 1 + crit*0.5
    final = max(1.0, raw - pet.defense)
    dpr = final * (1.0 - dodge_probability(pet.agi))
    if dpr <= 0:
        return float("inf")
    return pet.max_hp / dpr


def percentile(sorted_data: list[int], p: float) -> int:
    """返回已排序数据的第 p 百分位（线性最近邻）。"""
    n = len(sorted_data)
    idx = int(p * (n - 1))
    return sorted_data[idx]


def run_simulations() -> list[dict[str, object]]:
    """运行全部配置的模拟并返回 CSV 行。"""
    rng = random.Random(SEED)
    rows: list[dict[str, object]] = []

    for level in LEVELS:
        for scenario_name in SCENARIOS:
            pet_a = build_pet(level, scenario_name)
            pet_b = build_pet(level, scenario_name)

            rounds: list[int] = []
            for _ in range(BATTLES):
                rounds.append(simulate_one(pet_a, pet_b, rng))

            rounds.sort()
            mean = statistics.mean(rounds)
            median = statistics.median(rounds)

            rows.append(
                {
                    "scenario": scenario_name,
                    "level": level,
                    "power_str": pet_a.power,
                    "agi": pet_a.agi,
                    "spd": pet_a.spd,
                    "defense": pet_a.defense,
                    "hp": pet_a.max_hp,
                    "weapon": pet_a.scenario["weapon"],
                    "battles": BATTLES,
                    "rounds_mean": round(mean, 2),
                    "rounds_median": median,
                    "rounds_p10": percentile(rounds, 0.10),
                    "rounds_p90": percentile(rounds, 0.90),
                    "rounds_min": min(rounds),
                    "rounds_max": max(rounds),
                    "ttk_analytic": round(analytic_ttk(pet_a), 2),
                    "notes": (
                        "镜像战；速度相同=>1:1基础出手；"
                        "模拟含闪避/暴击/连击/反击/装死。"
                    ),
                }
            )

    return rows


def write_csv(rows: list[dict[str, object]]) -> Path:
    """将结果写入 CSV。"""
    out_path = Path(__file__).parent / "qpet-daledou-battle-turns.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def main() -> None:
    rows = run_simulations()
    out_path = write_csv(rows)
    print(f"模拟完成，结果写入：{out_path}")
    for row in rows:
        print(
            f"{row['scenario']:<12} L{row['level']:>2}: "
            f"mean={row['rounds_mean']}, median={row['rounds_median']}, "
            f"p10={row['rounds_p10']}, p90={row['rounds_p90']}"
        )


if __name__ == "__main__":
    main()
