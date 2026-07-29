# My Brute 属性系统（Stats / Attributes）

> 来源：目标站点 [My Brute Wiki](https://mybrute.fandom.com/wiki/My_Brute_Wiki) 的相关页面。为保留原始数据，数值、概率、英文术语均保留原文。

---

## 1. 概述

在 My Brute 中，Brute 的能力由 **Statistics（Stats / Attributes）** 决定，这些属性存在于 Brute、宠物、武器和技能中，决定了在 **Arena** 和 **Tournament** 中的表现。

来源页面：
- [Statistics](https://mybrute.fandom.com/wiki/Statistics)
- [Agility](https://mybrute.fandom.com/wiki/Agility)
- [Health](https://mybrute.fandom.com/wiki/Health)
- [Level](https://mybrute.fandom.com/wiki/Level)
- [Attributes](https://mybrute.fandom.com/wiki/Attributes)（重定向到 Statistics）

---

## 2. 四项核心属性（Original Version）

原始版本（Original Version）中，Brute 的基础属性会随着 **level** 提升自动增长。

### 2.1 Health / Endurance（生命值 / 耐力）

- **Health**（又称 **Hit Points / HP / Endurance**）表示 Brute 在倒下前能承受的伤害总量。
- 提升方式：升级时获得 **stamina increase**、技能 **Immortal**、技能 **Vitality**。
- 副作用：获得宠物（pets）会**降低** HP（见后文）。
- 战斗中唯一恢复方式是 **Super** 技能 **Tragic Potion**（一次）。

来源：[Health](https://mybrute.fandom.com/wiki/Health)

> 补充说明（来自 Muxxu 版本社区资料）：每 1 点 Endurance = 6 HP；每次升级额外 +1.5 HP；最低 HP 为 51（向下取整）。本公式在原始版本 Wiki 中未明确披露，仅供参考。
> 来源：[MyBrute Muxxu Wiki - Stats](https://mybrutemuxxu.fandom.com/wiki/Stats)

### 2.2 Strength（力量）

- 决定每次攻击造成的 **damage**（伤害）。
- 几乎所有武器的伤害都基于 Strength；投掷武器（Thrown weapons）主要受 **Agility** 影响，但 Strength 也有次要影响。
- 技能 **Herculean Strength** 可提升 Strength：原始版本为 **+5–20 点**；Muxxu 版本为 **+3 点并 +50% 总 Strength，且未来所有 Strength 提升均 +50%**。

来源：
- [Statistics](https://mybrute.fandom.com/wiki/Statistics)
- [Herculean Strength](https://mybrute.fandom.com/wiki/Herculean_Strength)
- [MyBrute Muxxu Wiki - Strength](https://mybrutemuxxu.fandom.com/wiki/Strength)

### 2.3 Agility（敏捷）

- 提高闪避（dodge） incoming attacks 的概率。
- 提高 **Accuracy**（命中）和 **multi hit**（连击）概率。
- 对投掷武器（thrown weapons）伤害有显著影响。
- 技能 **Feline Agility** 可提升 Agility：原始版本为 **+5–20 点**；Muxxu 版本为 **+3 点并 +50% 总 Agility，且未来所有 Agility 提升均 +50%**。

来源：
- [Statistics](https://mybrute.fandom.com/wiki/Statistics)
- [Agility](https://mybrute.fandom.com/wiki/Agility)
- [Feline Agility](https://mybrute.fandom.com/wiki/Feline_Agility)
- [MyBrute Muxxu Wiki - Agility](https://mybrutemuxxu.fandom.com/wiki/Agility)

### 2.4 Speed（速度）

- 提高攻击更快/更频繁的概率（原始版本描述为“improves the chance to attack faster”）。
- 在 Muxxu 版本中，Speed 决定 **Interval**（攻击间隔），即“多大概率轮到该 Brute 攻击”。
- 技能 **Bolt of Lightening**（又名 Lightning Bolt）可提升 Speed：原始版本为 **+5–20 点**；Muxxu 版本为 **+3 点并 +50% 总 Speed，且未来所有 Speed 提升均 +50%**。
- 技能 **Armour** 在 Muxxu 版本中降低 Speed 10%；**Immortal** 降低 Speed 25%（原始版本 Wiki 未精确披露）。

来源：
- [Statistics](https://mybrute.fandom.com/wiki/Statistics)
- [Bolt of Lightening](https://mybrute.fandom.com/wiki/Bolt_of_Lightening)
- [MyBrute Muxxu Wiki - Speed](https://mybrutemuxxu.fandom.com/wiki/Speed)

---

## 3. 升级时的属性成长

每次 Brute **升级**时，可能获得以下奖励之一：
- 一件 **Weapon**（武器）
- 一个 **Special**（技能/天赋）
- 一项 **Attributes improvement**（属性提升）

来源：[Level](https://mybrute.fandom.com/wiki/Level)

> “Each time your brute gains a level you may receive bonuses. This could be a Weapon or Special, or Attributes improvement.”

具体属性提升是**随机的**（ destiny / 命运路径），玩家无法选择。这也是 My Brute 的核心设计之一：每个 Brute 的 Build 完全由随机升级奖励决定。

---

## 4. 经验需求表（Level-up Table）

从 [Level](https://mybrute.fandom.com/wiki/Level) 页面提取的原始数据：

| Level | Exp Req | Total Exp | Level | Exp Req | Total Exp |
|------:|----------:|----------:|------:|----------:|----------:|
| 2     | 4         | 4         | 17    | 88        | 676       |
| 3     | 8         | 12        | 18    | 95        | 771       |
| 4     | 12        | 24        | 19    | 102       | 873       |
| 5     | 16        | 40        | 20    | 109       | 982       |
| 6     | 21        | 61        | 21    | 117       | 1099      |
| 7     | 26        | 87        | 22    | 124       | 1223      |
| 8     | 32        | 119       | 23    | 132       | 1355      |
| 9     | 37        | 156       | 24    | 139       | 1494      |
| 10    | 43        | 199       | 25    | 147       | 1641      |
| 11    | 49        | 248       | 26    | 155       | 1796      |
| 12    | 55        | 303       | 27    | 163       | 1959      |
| 13    | 61        | 364       | 28    | 163       | 1959      |
| 14    | 68        | 432       | 29    | —         | —         |
| 15    | 75        | 507       | 30    | —         | 2496      |
| 16    | 81        | 588       |       |           |           |

> 说明：Wiki 表格中部分数据缺失或用占位符（x、awaw），上方保留原文。高级别数据在 Wiki 中未完整给出。升级所需经验**不是线性增长**，随等级越来越高。

来源：[Level](https://mybrute.fandom.com/wiki/Level)

---

## 5. 宠物对属性的影响

获得宠物会降低 Brute 的 HP（Endurance）：

| Pet | 原始版本 HP 影响 | 备注 |
|-----|----------------|------|
| Dog | HP -10 | 可同时拥有最多 3 只；常见宠物 |
| Wolf / Panther | HP -23 | 只能拥有 1 只；稀有宠物 |
| Bear | HP 大幅下降 | 坦克型宠物；资料称 HP 可降回 60 左右（存在 glitch） |

来源：
- [Pets](https://mybrute.fandom.com/wiki/Pets)
- [Dog](https://mybrute.fandom.com/wiki/Dog)
- [Wolf](https://mybrute.fandom.com/wiki/Wolf)
- [Bear](https://mybrute.fandom.com/wiki/Bear)

> 补充（Muxxu 版本社区数据）：Dog 降低 Endurance 2 点；Wolf 降低 6 点；Bear 降低 8 点。若同时拥有 Immortal / Vitality，降低幅度会叠加。原始版本 Wiki 未给出精确数值，仅说明“降低 HP”。
> 来源：[MyBrute Muxxu Wiki - Stats](https://mybrutemuxxu.fandom.com/wiki/Stats)

---

## 6. 关键设计观察（供重设计参考）

- **四属性分工清晰**：Strength（伤害）、Agility（闪避/命中/连击/投掷伤害）、Speed（攻击频率/先攻）、Health（生存）。
- **升级奖励随机**：属性、武器、技能三选一随机给予，形成不可重复的 Build 路径。
- **属性与技能高度耦合**：例如高 Agility 需要配合 Untouchable/Shield；高 Strength 需要配合 Heavy 武器/Strong Arm；形成“随机天赋+装备”的配装乐趣。
- **隐藏属性（Hidden Stats）补充**：虽然原始版本未公开，但社区总结出的 Evasion、Accuracy、Combo Rate、Counter Rate、Block Rate、Interval 等概念，可作为自动战斗结算的参考维度。

---

## 7. 来源页面汇总

- 主属性说明：[Statistics](https://mybrute.fandom.com/wiki/Statistics)
- 敏捷说明：[Agility](https://mybrute.fandom.com/wiki/Agility)
- 生命值说明：[Health](https://mybrute.fandom.com/wiki/Health)
- 等级与经验：[Level](https://mybrute.fandom.com/wiki/Level)
- 宠物属性影响：[Pets](https://mybrute.fandom.com/wiki/Pets)
- 技能对属性加成：各技能页面（见 wiki-skills.md）
- 补充公式参考（Muxxu 社区）：[Stats](https://mybrutemuxxu.fandom.com/wiki/Stats)、[Strength](https://mybrutemuxxu.fandom.com/wiki/Strength)、[Agility](https://mybrutemuxxu.fandom.com/wiki/Agility)、[Speed](https://mybrutemuxxu.fandom.com/wiki/Speed)
