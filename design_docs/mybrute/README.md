# My Brute Wiki 设计参考索引

> 本目录为文字自动战斗修仙游戏的“数值/战斗/技能”重设计收集的核心参考：My Brute（随机 Build + 全自动战斗 + 被动技能配装趣味）。
> 所有材料均来自目标站点 [My Brute Wiki](https://mybrute.fandom.com/wiki/My_Brute_Wiki)，并补充了少量 MyBrute Muxxu 社区公式作为设计参考。

---

## 文件清单与一句话摘要

| 文件 | 摘要 |
|------|------|
| [wiki-attributes.md](wiki-attributes.md) | 汇总 Strength/Agility/Speed/Health 四项核心属性的作用、升级时随机成长方式，以及经验需求表与宠物对 HP 的影响。 |
| [wiki-combat.md](wiki-combat.md) | 梳理全自动战斗的回合/出手判定、命中/闪避/格挡/反击/缴械机制、Super 技能战斗内结算，并给出社区推导的伤害公式。 |
| [wiki-skills.md](wiki-skills.md) | 完整列出 28 个技能（9 个 Super + 19 个常规 Speciality），保留原文效果、触发条件、概率与评分。 |
| [wiki-weapons.md](wiki-weapons.md) | 收录全部 26 把武器的类型标签、稀有度、伤害区间、特殊效果（Multi hit/Counter/Disarm/Block）与获取方式。 |
| [wiki-progression.md](wiki-progression.md) | 整理等级/经验、每日战斗次数、锦标赛单败淘汰结构、Ranking 段位表、Pupil/邀请机制与 IP 防刷规则。 |

---

## 对“自动战斗配装游戏重设计”最有价值的 5 个设计要点

### 1. 随机 Destiny Build：让玩家“看命”但保留核心身份

My Brute 的核心乐趣在于角色升级时随机获得武器/技能/属性，形成独一无二的 Build。玩家无法选择，但每个 Brute 因此有了“性格”。重设计时可借鉴：
- 每次突破/渡劫/升级时随机给出 **功法/法宝/属性** 三选一；
- 提供“转世/重修”机制（类似 Tournament 重置后的 Same/New destiny），让玩家保留或不保留原有 Build，形成长期养成与重新 roll 的博弈。

### 2. 四属性分工 + 隐藏属性：简单规则支撑丰富战斗文本

Strength（伤害）、Agility（闪避/命中/连击/投掷）、Speed（攻击频率/先攻）、Health（生存）分工清晰，社区又总结出 Dodge/Block/Counter/Combo/Accuracy/Interval 等隐藏属性。重设计时可：
- 用类似“力道/身法/气运/根骨”四主属性映射；
- 自动战斗结算中依次判定 **闪避→格挡→反击→护甲→伤害**，产生丰富可读战斗日志。

### 3. 被动/概率技能 + 一次性 Super：降低理解成本，提升戏剧高潮

28 个技能中大部分是被动或概率触发（如 Armour、Untouchable、Impact、Tornado of Blows），而 9 个 Super 每局一次（Hammer、Deluge、Net、Hypnosis 等）。这种分层：
- 让玩家容易看懂“我的角色为什么会赢/输”；
- 一次性 Super 在自动战斗中制造翻盘/翻车的高潮，适合文字演绎。

### 4. 武器标签系统：用少量标签表达大量差异化

Fast/Slow/Heavy/Thrown/Melee + Multi hit/Counter/Disarm/Block 标签，让 26 把武器各具特色。重设计时可：
- 将法宝/武器分为“剑/刀/枪/杖/符/暗器”等类型；
- 用“破甲/连击/反击/缴械/格挡/吸血”等标签形成与功法（Master of Arms/Strong Arm/Martial Arts）的强耦合。

### 5. 每日次数 + 社交邀请 + 周期性锦标赛：构建长线留存循环

- 每日 6–8 次 Arena 限制形成“日常打卡”；
- Pupil 邀请机制提供社交裂变与额外经验；
- 锦标赛单败淘汰 + 段位重置 destiny，形成周期性的“赛季”高潮。

对应到修仙游戏：
- 每日“闭关/试炼”次数限制；
- 师徒/道友邀请带来额外收益，但需防刷；
- 周期性“宗门大比/飞升大会”单败淘汰，获胜者境界重置但保留称号，并可选择重修。

---

## 主要来源

- 目标站点主页：[My Brute Wiki](https://mybrute.fandom.com/wiki/My_Brute_Wiki)
- 各主题详细来源见各子文件末尾的“来源页面汇总”。

---

*本目录由研究子代理整理，全部内容以中文撰写，游戏术语保留英文原名，数值/概率均保留 Wiki 原文数据。*
