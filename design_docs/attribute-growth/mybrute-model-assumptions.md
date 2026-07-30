# My Brute 镜像战斗模型假设文档

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
- 战斗被硬上限为 `5000` 次行动；达到上限仍不决出胜负则记为 cap。
- 随机种子固定为 `42`，每场战斗模拟 `5000` 次。

## 7. 模拟结果文件

- CSV：`mybrute-battle-turns.csv`
- 脚本：`sim_mybrute_turns.py`

