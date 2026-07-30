"""Mirror My Brute battle simulator.

Estimates the number of rounds for two identical Brutes to fight each other
across a level gradient and a small set of weapon scenarios.  Uses only the
Python standard library and a fixed random seed so the run is reproducible.

Run from the AstrBot root directory:

    uv run python /home/guigui/code/AstrBot/data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/sim_mybrute_turns.py

The script writes:

    design_docs/attribute-growth/mybrute-battle-turns.csv
    design_docs/attribute-growth/mybrute-model-assumptions.md
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path

SEED = 42
BATTLES_PER_CONFIG = 5000
MAX_ACTIONS = 5000  # safety cap to avoid infinite loops / very long tails
LEVELS = (1, 5, 10, 15, 20, 25, 30)
SCENARIOS = ("unarmed", "typical-weapon", "heavy-weapon")

# ---------------------------------------------------------------------------
# Assumed progression (sources and justifications are documented separately in
# mybrute-model-assumptions.md).  No official level-by-level stat table exists
# in the local source material, so these are deliberately conservative guesses.
# ---------------------------------------------------------------------------


def assumed_stats(level: int) -> tuple[int, int, int, int]:
    """Return (hp, strength, agility, speed) for a typical Brute of `level`."""
    hp = 60 + 10 * level
    strength = 5 + level
    agility = 5 + level
    speed = 5 + level
    return hp, strength, agility, speed


# ---------------------------------------------------------------------------
# Weapon definitions taken from the local wiki-weapons.md table.
# The Muxxu damage formula is Damage = floor((B + N*K) * S * R - A) * H.
# The strength coefficient K is not published in the local material, so we
# assume K = 1.0 for every weapon as a simplification.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Weapon:
    name: str
    base: float
    strength_coeff: float = 1.0
    has_block: bool = False
    has_counter: bool = False
    notes: str = ""


WEAPONS: dict[str, Weapon] = {
    "unarmed": Weapon(
        name="Fists",
        base=3.0,
        notes="synthetic unarmed proxy; base damage is a guess",
    ),
    "typical-weapon": Weapon(
        name="Broadsword",
        base=11.5,
        has_block=True,
        has_counter=True,
        notes="Common weapon, base 8-15, melee/counter/block tags",
    ),
    "heavy-weapon": Weapon(
        name="Stone Hammer",
        base=62.5,
        notes="Rare weapon, base 50-75, heavy/slow tags; no block/counter",
    ),
}


# ---------------------------------------------------------------------------
# Combat helpers
# ---------------------------------------------------------------------------


def dodge_probability(agility: int) -> float:
    """Agility-driven dodge chance.  This is a modelling guess, not official."""
    return min(0.30, max(0.0, 0.05 + 0.002 * agility))


def block_probability(has_block: bool) -> float:
    """Block chance when wielding a weapon with the Block tag.  Guess."""
    return 0.05 if has_block else 0.0


def counter_probability(has_counter: bool) -> float:
    """Counter chance when wielding a weapon with the Counter tag.  Guess."""
    return 0.05 if has_counter else 0.0


def damage_roll(
    base: float, strength: int, strength_coeff: float, rng: random.Random
) -> int:
    """Roll damage using the Muxxu community formula without armor."""
    raw = (base + strength * strength_coeff) * rng.uniform(1.0, 1.5)
    # floor, minimum 0
    return max(0, int(raw))


def expected_mean_damage(base: float, strength: int, strength_coeff: float) -> float:
    """Analytic mean of floor((B + N*K) * R) with R uniform in [1.0, 1.5]."""
    scale = base + strength * strength_coeff
    return max(0.0, scale * 1.25 - 0.5)


@dataclass
class Brute:
    max_hp: int
    hp: int
    strength: int
    agility: int
    speed: int
    weapon: Weapon
    alive: bool = True
    acted_this_round: bool = False

    def reset(self) -> None:
        self.hp = self.max_hp
        self.alive = True
        self.acted_this_round = False


def apply_attack(
    attacker: Brute,
    defender: Brute,
    rng: random.Random,
    allow_counter: bool = True,
) -> None:
    """Resolve one attack, including dodge, block, damage and counter."""
    if not defender.alive:
        return

    # Dodge check
    if rng.random() < dodge_probability(defender.agility):
        return

    # Block check (only if the defender's current weapon has the Block tag)
    if defender.weapon.has_block and rng.random() < block_probability(True):
        return

    dmg = damage_roll(
        attacker.weapon.base, attacker.strength, attacker.weapon.strength_coeff, rng
    )
    defender.hp -= dmg
    if defender.hp <= 0:
        defender.alive = False
        return

    # Counter-attack: a small chance for the defender to strike back immediately.
    if allow_counter and defender.weapon.has_counter:
        if rng.random() < counter_probability(True):
            apply_attack(defender, attacker, rng, allow_counter=False)


def simulate_battle(
    hp: int,
    strength: int,
    agility: int,
    speed: int,
    weapon: Weapon,
    rng: random.Random,
) -> tuple[int, int]:
    """Simulate one mirror fight and return (rounds, total_actions)."""
    a = Brute(hp, hp, strength, agility, speed, weapon)
    b = Brute(hp, hp, strength, agility, speed, weapon)

    rounds = 0
    total_actions = 0

    while a.alive and b.alive and total_actions < MAX_ACTIONS:
        # If both brutes have already acted in the current round, advance the
        # round counter and reset the per-round flags.
        if a.acted_this_round and b.acted_this_round:
            rounds += 1
            a.acted_this_round = False
            b.acted_this_round = False

        total_speed = a.speed + b.speed
        if total_speed <= 0:
            attacker_idx = rng.randint(0, 1)
        else:
            attacker_idx = 0 if rng.random() < a.speed / total_speed else 1

        attacker = a if attacker_idx == 0 else b
        defender = b if attacker_idx == 0 else a

        apply_attack(attacker, defender, rng)
        attacker.acted_this_round = True
        total_actions += 1

    # A round that ended mid-pair still counts as one complete round for the
    # purpose of this metric (see assumptions document).
    if a.acted_this_round or b.acted_this_round:
        rounds += 1

    return rounds, total_actions


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def percentile(sorted_values: list[int], p: float) -> float:
    """Return the p-th percentile using linear interpolation."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values) - 1
    k = n * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_values[int(k)])
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    out_csv = script_dir / "mybrute-battle-turns.csv"
    out_md = script_dir / "mybrute-model-assumptions.md"

    rows: list[dict[str, object]] = []
    rng = random.Random(SEED)

    for scenario in SCENARIOS:
        weapon = WEAPONS[scenario]
        for level in LEVELS:
            hp, strength, agility, speed = assumed_stats(level)
            rounds_list: list[int] = []
            capped = 0

            for _ in range(BATTLES_PER_CONFIG):
                rounds, actions = simulate_battle(
                    hp, strength, agility, speed, weapon, rng
                )
                rounds_list.append(rounds)
                if actions >= MAX_ACTIONS:
                    capped += 1

            rounds_sorted = sorted(rounds_list)
            mean_rounds = sum(rounds_list) / len(rounds_list)
            median_rounds = percentile(rounds_sorted, 0.5)
            p10 = percentile(rounds_sorted, 0.10)
            p90 = percentile(rounds_sorted, 0.90)

            mean_dmg = expected_mean_damage(
                weapon.base, strength, weapon.strength_coeff
            )
            ttk_analytic = math.ceil(hp / max(1.0, mean_dmg))

            rows.append(
                {
                    "scenario": scenario,
                    "level": level,
                    "str": strength,
                    "agi": agility,
                    "spd": speed,
                    "hp": hp,
                    "weapon": weapon.name,
                    "battles": BATTLES_PER_CONFIG,
                    "rounds_mean": round(mean_rounds, 2),
                    "rounds_median": round(median_rounds, 2),
                    "rounds_p10": round(p10, 2),
                    "rounds_p90": round(p90, 2),
                    "rounds_min": min(rounds_list),
                    "rounds_max": max(rounds_list),
                    "draw_or_cap_rate": round(capped / BATTLES_PER_CONFIG, 4),
                    "ttk_analytic": ttk_analytic,
                    "notes": weapon.notes,
                }
            )

    # Write CSV
    columns = [
        "scenario",
        "level",
        "str",
        "agi",
        "spd",
        "hp",
        "weapon",
        "battles",
        "rounds_mean",
        "rounds_median",
        "rounds_p10",
        "rounds_p90",
        "rounds_min",
        "rounds_max",
        "draw_or_cap_rate",
        "ttk_analytic",
        "notes",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    # Write assumptions document
    assumptions = f"""# My Brute 镜像战斗模型假设文档

> 本文件由 `sim_mybrute_turns.py` 自动生成，所有假设均基于
> `/design_docs/mybrute/` 下的本地调研资料，缺失精确公式的地方已标注为
> 推测/社区总结。

## 1. 回合定义

原始资料中未给出“回合”的精确算法，因此本模型采用以下统一定义：

- **1 回合 = 双方各获得一次行动机会**（或有一方在回合内击倒对手导致
  回合提前结束）。
- 每回合内行动顺序由 Speed 加权随机决定；同属性镜像战中双方 Speed 相同，
  因此每回合实际为 50/50 的先后手。
- 回合数在战斗结束时统计：若最后一击发生在某回合的第一次行动中，该回合
  仍然计为 1 回合。

出处：wiki-combat.md（“Speed 决定攻击更快/更频繁的probability”）。
不确定性：**高**——原始动画与后台逻辑可能与此不同。

## 2. 属性取值假设

本地资料未给出每级具体属性，因此采用如下保守猜测：

| 属性 | 公式 | 说明 |
|------|------|------|
| HP   | `60 + 10 * level` | 猜测：升级带来的耐力/天赋综合提升 |
| STR  | `5 + level` | 猜测：每级平均获得约 1 点力量 |
| AGI  | `5 + level` | 猜测：与 STR 同步增长 |
| SPD  | `5 + level` | 猜测：与 STR 同步增长 |

出处：wiki-attributes.md、wiki-progression.md（仅说明升级会随机提升属性，无具体数值）。
不确定性：**高**——实际升级奖励是随机的，且可能受技能（Herculean Strength 等）大幅偏离。

## 3. 伤害公式

采用 Muxxu 社区伤害公式（原始 Wiki 未公开精确公式）：

```
Damage = floor((B + N * K) * S * R - A) * H
```

本模型取值：

- `B`：武器基础伤害，取 wiki-weapons.md 表中伤害区间的平均值。
- `N`：Brute 的力量（STR）。
- `K`：武器力量系数。**资料未给出具体数值**，统一假设为 `K = 1.0`。
- `S`：技能倍率，统一为 `1.0`（不装备任何技能）。
- `R`：均匀分布在 `[1.00, 1.50]` 的随机数。
- `A`：护甲减法，统一为 `0`（无 Armour / Extra-thick Skin）。
- `H`：锤倍率，统一为 `1.0`（非 Hammer 攻击）。

出处：wiki-combat.md 第 3 节。
不确定性：**中**——`K` 与 `R` 的分布若被官方调整，结果会明显变化。

## 4. 武器取值

| 场景 | 武器 | 基础伤害 B | 来源 |
|------|------|------------|------|
| unarmed | Fists（空手） | 3.0 |  synthetic proxy，资料未给出空手 B |
| typical-weapon | Broadsword | 11.5 | wiki-weapons.md：Common，8-15，Melee/Counter/Block |
| heavy-weapon | Stone Hammer | 62.5 | wiki-weapons.md：Rare，50-75，Heavy/Slow |

不确定性：

- **高**：空手基础伤害无官方数据。
- **中**：B 取区间平均，实际每击可能在区间内浮动。

## 5. 防御与反击机制（均为推测）

资料提到 Dodge、Block、Counter 存在，但未给出概率公式。本模型采用极保守的简化：

- **Dodge 概率**：`min(0.30, 0.05 + 0.002 * AGI)`。
- **Block 概率**：仅当武器带 Block 标签时为 `5%`。
- **Counter 概率**：仅当武器带 Counter 标签时为 `5%`；反击本身不能再触发反击。

出处：wiki-combat.md 第 4 节。
不确定性：**高**——这些数值仅为让模型出现“偶尔被闪避/格挡/反击”而设，没有官方或社区精确值支持。

## 6. 其他简化

- 无宠物、无技能（包括 Martial Arts / Master of Arms / Strong Arm 等）。
- 无缴械（Disarm）、无 Super、无 Net / Hammer / Deluge 等一次性技能。
- 无武器切换：整场战斗只使用同一种武器。
- 战斗被硬上限为 `{MAX_ACTIONS}` 次行动；达到上限仍不决出胜负则记为 cap。
- 随机种子固定为 `{SEED}`，每场战斗模拟 `{BATTLES_PER_CONFIG}` 次。

## 7. 模拟结果文件

- CSV：`mybrute-battle-turns.csv`
- 脚本：`sim_mybrute_turns.py`

"""
    out_md.write_text(assumptions, encoding="utf-8")

    print(f"Wrote {out_csv}")
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
