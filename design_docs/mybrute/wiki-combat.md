# My Brute 战斗机制（Combat）

> 来源：目标站点 [My Brute Wiki](https://mybrute.fandom.com/wiki/My_Brute_Wiki) 的相关页面。为保留原始数据，数值、概率、英文术语均保留原文。

---

## 1. 概述

战斗发生在 **Arena** 中。战斗完全**自动化**，玩家唯一能做的是选择对手。战斗过程中，系统会比较双方的 **Stats（属性）**、**Weapons（武器）**、**Pets（宠物）** 和 **Specialities（技能）** 进行自动结算。

来源：
- [Combat](https://mybrute.fandom.com/wiki/Combat)
- [Arena](https://mybrute.fandom.com/wiki/Arena)
- [Combat Effects](https://mybrute.fandom.com/wiki/Combat_Effects)

---

## 2. 回合流程与出手顺序

### 2.1 自动化流程

- 玩家仅选择对手，进入战斗后无需任何操作。
- Brute、武器、宠物和技能由 AI 自动使用。

来源：[Combat](https://mybrute.fandom.com/wiki/Combat)

### 2.2 出手顺序 / Initiative

原始版本 Wiki 未给出精确出手公式，但核心逻辑可归纳如下：

- **Speed** 决定攻击更快、更频繁的**概率**（原始版本描述：“Speed improves the chance to attack faster”）。
- Muxxu 版本社区资料明确说明：**Speed 决定 Interval（攻击间隔），即“轮到该 Brute 攻击的概率”**，高 Speed 意味着更大概率连续行动或抢得先机。
- 因此可理解为：每回合根据双方 Speed 属性进行随机判定，决定当前由哪一方行动；高 Speed 不仅增加行动次数，还可能影响先攻。

来源：
- [Statistics](https://mybrute.fandom.com/wiki/Statistics)
- [MyBrute Muxxu Wiki - Speed](https://mybrutemuxxu.fandom.com/wiki/Speed)
- [MyBrute Muxxu Wiki - Stats](https://mybrutemuxxu.fandom.com/wiki/Stats)

---

## 3. 伤害公式（Damage Formula）

**注意**：原始版本 My Brute Wiki 没有公开精确伤害公式。以下内容来自 MyBrute Muxxu 社区总结，结构可作为自动战斗结算的设计参考。公式保留了原文所有符号与参数。

```
Damage = floor((B + N * K) * S * R - A) * H

B = base damage of weapon（武器基础伤害，常量）
N = Strength（力量）
K = damage per strength of weapon（每点力量转化的武器伤害，常量）
S = skills multiplier（技能倍率）
R = random number between 1.00 and 1.50（1.00 到 1.50 之间的随机数）
A = Armor stat（护甲值，加法减伤）
H = hammer multiplier（x4.00 if Hammer；x1.00 if not）
```

技能倍率 S 示例（Muxxu 版本名称）：
- Weapons Master：+50%（对应原始版本 Master of Arms）
- Martial Arts：+100%（空手/拳头伤害）
- Lead Skeleton：x0.70（对重武器减伤，对应原始版本相关概念）
- Fierce Brute：+100%（激活时下一次直接攻击）

防御端：
- Armour：-5（原始版本 Wiki 描述为“减少 10%–50% 武器/宠物伤害，最低为 1”）
- Toughened Skin / Extra-thick Skin：-2（原始版本描述为“减少 10%–50% 普通攻击伤害”）

来源：
- [MyBrute Muxxu Wiki - Damage](https://mybrutemuxxu.fandom.com/wiki/Damage)
- [Armour](https://mybrute.fandom.com/wiki/Armour)
- [Extra-thick Skin](https://mybrute.fandom.com/wiki/Extra-thick_Skin)
- [Fierce Brute](https://mybrute.fandom.com/wiki/Fierce_Brute)
- [Martial Arts](https://mybrute.fandom.com/wiki/Martial_Arts)
- [Master of Arms](https://mybrute.fandom.com/wiki/Master_of_Arms)

---

## 4. 命中、闪避、格挡、反击、缴械

### 4.1 Dodge（闪避）

- **Agility** 提高闪避概率。
- 技能 **Untouchable** 大幅提高闪避率。
- 高闪避对低精度武器（如 Bumps、Halberd、Stone Hammer）尤为克制。

来源：
- [Agility](https://mybrute.fandom.com/wiki/Agility)
- [Untouchable](https://mybrute.fandom.com/wiki/Untouchable)
- [Combat Effects](https://mybrute.fandom.com/wiki/Combat_Effects)

### 4.2 Block（格挡）

- 当前手持武器影响格挡概率；部分武器自带 **Block** 标签。
- 技能 **Shield** 提供格挡概率，Community 观察称“可格挡 40% 或更多对手攻击”。
- **Block** 可以阻挡全部 incoming damage。
- 有社区理论认为 Counter（反击）会额外提供约 10% 格挡概率，部分武器（如 Glaive、Baton）可能提供约 20%，Sai 约 30%，Shield 约 30%（均为社区估算，原始 Wiki 未确认）。

来源：
- [Block](https://mybrute.fandom.com/wiki/Block)
- [Shield](https://mybrute.fandom.com/wiki/Shield)
- [Counter](https://mybrute.fandom.com/wiki/Counter)
- [Combat Effects](https://mybrute.fandom.com/wiki/Combat_Effects)

### 4.3 Counter / Counter-attack（反击）

- **Counter**：在敌人试图靠近攻击时先发制人，打断其攻击并造成伤害。长柄武器（Lance、Baton、Whip 等）反击率更高。
- **Counter-attack**：被敌人攻击后**反击**一次。技能 **Pugnacious** 增加反击概率约 **+33%**（原始版本描述为“better chance at counter-attacking”，但 Wiki 仍称“not better than 5%”）；Muxxu 版本为 **+30% Reversal**。
- 技能 **6th Sense** 也提高反击/先制概率，但 Wiki 评价不高（3/10），因为触发不稳定。

来源：
- [Counter](https://mybrute.fandom.com/wiki/Counter)
- [Pugnacious](https://mybrute.fandom.com/wiki/Pugnacious)
- [6th Sense](https://mybrute.fandom.com/wiki/6th_Sense)
- [Combat Effects](https://mybrute.fandom.com/wiki/Combat_Effects)

### 4.4 Accuracy / Hit（命中）

- **Agility** 提高 **Accuracy**（命中概率）。
- 技能 **Implacable** 大幅提高 Accuracy（原始 Wiki 提示“significantly”，但社区测试发现无法达到 100%；会被 Untouchable 抵消）。
- 不同武器自带精度差异：低精度武器如 **Bumps**、**Stone Hammer**、**Halberd** 等，容易被高 Agility 或 Untouchable 闪避。

来源：
- [Statistics](https://mybrute.fandom.com/wiki/Statistics)
- [Implacable](https://mybrute.fandom.com/wiki/Implacable)
- [Untouchable](https://mybrute.fandom.com/wiki/Untouchable)

### 4.5 Disarm（缴械）

- 部分武器自带缴械概率（如 **Sai**、**Trombone**、**Whip**）。
- 技能 **Impact** 让每次攻击都有概率缴械对手当前武器。
- **Sabotage** 每次成功造成伤害会摧毁对手**备用武器**中的一件。
- **Thief**（Super）可强制偷取对手当前武器，100% 成功（无法被闪避/格挡），一场战斗中可多次触发。
- 盾牌（Shield）**不能被 Impact 缴械**，但武器 lucky blow 可能打掉盾牌？（Wiki 存在争议，原始 Wiki 未明确）

来源：
- [Combat Effects](https://mybrute.fandom.com/wiki/Combat_Effects)
- [Impact](https://mybrute.fandom.com/wiki/Impact)
- [Sabotage](https://mybrute.fandom.com/wiki/Sabotage)
- [Thief](https://mybrute.fandom.com/wiki/Thief)
- [Weapons](https://mybrute.fandom.com/wiki/Weapons)

---

## 5. 武器相关行为

### 5.1 Throw（投掷）

- 武器可以被投掷（Throw），造成额外伤害。投掷武器的伤害主要受 **Agility** 影响，Strength 次之。
- 拥有 **Thrown** 标签的武器（Shuriken、Noodle Bowl、Piou-Piouz）专门用于投掷。
- 有时 Brute 会把武器“丢弃（Discard）”而不是投掷，这通常表示要更换武器。

来源：
- [Combat Effects](https://mybrute.fandom.com/wiki/Combat_Effects)
- [Weapons](https://mybrute.fandom.com/wiki/Weapons)
- 论坛讨论：*Agility affects ANY thrown weapon.*

### 5.2 Multi hit（连击）

- 由 **Speed** 和 **Tornado of Blows** 技能提升触发概率。
- 部分武器自带 **Multi hit** 标签（如 Baton、Knife、Fan、Sai 等）。
- Fast 标签武器也更容易获得额外攻击。

来源：
- [Tornado of Blows](https://mybrute.fandom.com/wiki/Tornado_of_Blows)
- [Weapons](https://mybrute.fandom.com/wiki/Weapons)

### 5.3 武器选择逻辑

- Brute 会自动从持有的武器中随机抽取；高 Speed 或高武器数量可能让 Brute 更频繁地更换武器。
- 社区观察：Brute 有时连续换武器，有时一直使用同一把武器，行为随机，但似乎受 Speed/Agility/武器数量影响。

来源：
- 论坛讨论：*How Stats are influencing weapons?*
- [Newbie Guide](https://mybrute.fandom.com/wiki/Newbie_Guide)

---

## 6. Super 技能在战斗中的结算

Super 技能通常每一场 Arena 战斗只能使用 **一次**（Bomb、Thief 例外，可多次使用）：

| Super | 战斗内效果 | 次数限制 |
|------|------------|----------|
| Bomb | 对敌方全体（Brute + pets）造成 10–20 伤害，可破 Net | 可多次 |
| Cry of the Damned | 令敌方宠物逃跑，成功率 **50%** | 1 次 |
| Deluge | 跳起从武器库中随机取最多 6 把武器投掷，不可格挡 | 1 次 |
| Fierce Brute | 下一次直接攻击伤害 +100% | 1 次（可被反击/Throw 不消耗） |
| Hammer | 空手抓取敌人跳起砸下，400% 伤害 | 1 次（需空手） |
| Hypnosis | 夺取敌方所有宠物 | 1 次 |
| Net | 网住对手或宠物，被任何伤害击中后解除 | 1 次 |
| Thief | 偷取对手当前武器 | 可多次 |
| Tragic Potion | 恢复 12–500 HP | 1 次 |

来源：
- [Super](https://mybrute.fandom.com/wiki/Super)
- [Combat Effects](https://mybrute.fandom.com/wiki/Combat_Effects)
- 各 Super 页面（见 wiki-skills.md）

---

## 7. 宠物在战斗中的行动

- 宠物独立行动，拥有自己的 HP 和属性。
- 宠物死亡条件：HP 降至 0。
- 宠物行动顺序类似 Brute，由 Speed 等属性决定。

来源：
- [Pets](https://mybrute.fandom.com/wiki/Pets)
- [Combat](https://mybrute.fandom.com/wiki/Combat)

---

## 8. 关键设计观察（供重设计参考）

- **全自动结算**：玩家只选对手，其余交给随机数 + 属性/武器/技能，适合放置类/文字修仙自动战斗。
- **Speed 决定行动节奏**：不是简单回合制，而是基于概率的“行动权竞争”，可制造连续攻击或连续挨打的戏剧性。
- **多层防御判定**：Dodge → Block → Counter → Armour/Extra-thick Skin → HP，形成丰富的“未命中/被格挡/被反击/被减伤”战斗文本。
- **武器与技能耦合**：Heavy 武器需 Strong Arm，Melee 武器需 Master of Arms，Fists 需 Martial Arts，Thief/Impact/Sabotage 围绕武器展开，构建 Build 核心。
- **Super 作为一次性翻盘技**：每局一次的 Hammer/Deluge/Net/Hypnosis 提供高潮点，但受随机触发时机影响，强化“戏剧性”。

---

## 9. 来源页面汇总

- 战斗总览：[Combat](https://mybrute.fandom.com/wiki/Combat)
- 竞技场：[Arena](https://mybrute.fandom.com/wiki/Arena)
- 战斗效果：[Combat Effects](https://mybrute.fandom.com/wiki/Combat_Effects)
- 属性说明：[Statistics](https://mybrute.fandom.com/wiki/Statistics)
- 格挡：[Block](https://mybrute.fandom.com/wiki/Block)
- 反击：[Counter](https://mybrute.fandom.com/wiki/Counter)
- 武器系统：[Weapons](https://mybrute.fandom.com/wiki/Weapons)
- 新手指南（含战斗细节）：[Newbie Guide](https://mybrute.fandom.com/wiki/Newbie_Guide)
- 补充公式与隐藏属性参考：[MyBrute Muxxu Wiki - Stats](https://mybrutemuxxu.fandom.com/wiki/Stats)、[Damage](https://mybrutemuxxu.fandom.com/wiki/Damage)、[Speed](https://mybrutemuxxu.fandom.com/wiki/Speed)
