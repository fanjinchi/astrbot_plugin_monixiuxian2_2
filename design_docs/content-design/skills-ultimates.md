# 触发技与奥义（大招）设计素材总结

> 2026-08-06。整合 My Brute / Q宠大乐斗 / researcher 同类游戏调研三份素材，
> 对照本插件战斗代码现状，产出触发技与奥义的效果类型总表、数值区间与适配决策。
> 后续扩充功法池（`skills.csv`）时以本文为准选效果、定数值。
>
> 素材来源：
> - `design_docs/mybrute/wiki-skills.md` —— MB 28 个 Specialities + 9 个 Super 全文
> - `design_docs/qpet-daledou/weapons-skills.md` —— QPet 武器特效 + 技能四类全文
> - `researcher-similar-games.md` —— 一念逍遥/想不想修真/无极仙途/修仙家族模拟器/乱斗堂
>   的 20 类效果 taxonomy 与数值区间（原 subagent 产出，本次已拷入本目录）

---

## 1. 本插件结算框架（代码事实，设计的硬约束）

结算链（`managers/combat_manager.py` 头部注释）：
**闪避 → 格挡 → 暴击 → 触发技 → 奥义 → 伤害（Muxxu 公式）→ 护甲减免**

### 1.1 触发时机

config 的 `trigger_condition` 经 `core/skill_manager.py`（timing_map, ~L326-334）
映射为引擎内部 `trigger_timing`：

| config 值 | 引擎时机 | 结算位置 |
|---|---|---|
| `attack` | `on_attack` | 每次出手结算伤害前 |
| `defend` | `on_defense` | 受击后（若存活） |
| `crit` | `on_crit` | 暴击时（先于 on_attack） |
| `round_start` | `round_start` | 每回合开始，效果存 `next_attack_mult` **下回合**生效 |
| `once_per_battle` | `ultimate` | 走奥义通道（见 §1.3） |

### 1.2 触发技效果词表（`_process_trigger_skills`，~L374-425）

| `effect` | 语义 | 备注 |
|---|---|---|
| `damage_bonus` | 当次攻击 `damage_mult += value` | 倍率叠加 |
| `combo` | 同 damage_bonus，但占用 `combo_stack`（受 `_combo_cap` 上限） | **并非原型的"额外打一回合"**，是带栈上限的倍率叠加 |
| `stun` | `target.skip_next_action = True` | 对手跳过下一次行动 |
| `counter` | 仅 `on_defense`：立即反击 `int(自身伤害 × value)` | 反击不吃当次攻击倍率 |
| `damage_reduction` | 下一次受击 `incoming_damage_mult ×= (1 − value)` | 一次性减伤 |

> ✅ **键名 bug 已修复（2026-08-06 change `skill-engine-fit-and-content-sync` 落地，已归档）**：
> 原问题——引擎只读 `effect_type`，但 config 功法用 `effect` 键、归一化不改名，导致
> 6 个 config 功法触发技静默不触发。修复方式：config/skills.json 全部改名
> `effect` → `effect_type`（设计表 skills.csv 同步改为 `effect_type` 列），
> `combat_manager` 重构为 `EFFECT_HANDLERS` 注册表分发，功法与武器挂载技共用入口，
> 未知 effect_type 记 warning 并跳过、不中断战斗。
> **遗留：修复生效后现有功法超 G2 预算**（御剑术 25%×1.5=+37.5%、撼山劲 20%×1.8=+36%），
> 由 bd `dhh` 跟踪，随功法池重做一并下调（未上线可接受）。
> 武器挂载技（绕过归一化）必须直接用引擎键，见 `weapon-skills.md` §0。

### 1.3 大招机制（必放制，change `skill-engine-fit-and-content-sync` 落地）

- 每个大招**每场战斗限一次**（`used_ultimates` 集合）；一次行动最多触发一个；
  多本功法的大招相互独立。
- **必放制**：`_apply_star_to_def` 为未显式声明概率的大招注入 `trigger_rate = 1.0`，
  config 大招数据 **不得** 填写 `trigger_rate` 字段（同步脚本会校验拒绝）。
- **解锁门槛**（config 可调，AND 语义）：自身已行动数 ≥ `min_action_index`，且满足
  全部已声明血量条件（`trigger_self_hp_below` 自身 HP% ≤ 阈值 / `trigger_opponent_hp_below`
  敌方 HP% ≤ 阈值）；未达门槛时跳过且**不消耗**限次资格。支持斩杀型（敌方低血）、
  逆袭型（自身低血）、延迟型（纯行动数）。
- **当前实现不读 `effect` 类型**：一律 `ultimate_mult += effect_value`，即当次伤害
  **×(1 + effect_value)**。config 里的 `massive_damage` 只是描述性标签。
  → 万剑归宗 3.0 = 当次 ×4.0；开天辟地 3.5 = 当次 ×4.5（降档至 2.0 档 ×3.0 随 bd `dhh`）。
- 要做非伤害型大招（治疗/控制/免死）需要先在 ultimate 分支加 effect 分发（bd `tt3`）。

### 1.4 升星（`core/skill_manager.py`，change `skill-engine-fit-and-content-sync` 落地）

- 星级上限 `max_star = 3`（读 config）；重复获得同名功法自动升星，满星后不再 +1。
- 升星系数单一 config 值 `STAR_UP_BONUS = 0.10`（替代旧的双系数
  STAR_UP_RATE_BONUS/STAR_UP_EFFECT_BONUS 0.20）；触发率与效果值均按
  **乘法** `(1 + 0.10)^(星级-1)` 缩放（3 星 = 1.21×），触发率截断至 1.0。
- **满星重复参悟**：不再升星，按品级修为基数 × 折算比例（默认 50%，config 可调）
  补偿修为并提示。
- 设计基础值时要按目标星级倒推（除以对应乘数）。

---

## 2. 触发技效果总表

按适配状态分三组。原型数值保留原文；「建议适配」列给出 condition / rate / effect·value。

### 2.1 已支持（可直接入池）

| 效果 | 原型（出处·数值） | 建议适配 | 平衡要点 |
|---|---|---|---|
| **攻击增伤** | QPet 晴天霹雳 15+等级×1.5、龙卷风 20+力量×80%；修仙家族模拟器 单体 1.2x–2.5x（常见 1.5x）；一念逍遥法宝「伤害/2 时间」词缀 | `attack` / 15–25% / `damage_bonus` 0.2–0.8 | 期望增幅 = rate×value，计入 G2 ≤30% 预算（御剑术 25%×0.5=+12.5%、撼山劲 20%×0.8=+16% 为先例） |
| **暴击增伤** | MB Fierce Brute 下一次直接攻击 +100%（可"保留"机制）；一念逍遥会心倍率 1.5x | `crit` / 20–30% / `damage_bonus` 0.3–0.5 | 暴击率本身有 cap（G2 已设暴击 50%），期望 = 暴击率×rate×value，天然低方差 |
| **回合蓄力** | 无极仙途 BUFF 类 +20–100% 持续数回合；乱斗堂蓄力类 | `round_start` / 15–20% / `damage_bonus` 0.5–1.0 | 延迟一回合生效是天然代价，value 可高于 attack 版 |
| **连击** | QPet 短剑 20%、接力棒 15%、红缨枪 10%、真·关刀 40%、无影手 20%；MB Tornado of Blows；researcher 30–40% 额外一击 | `attack` / 10–20% / `combo` 0.5–1.0 | 受 `_combo_cap` 栈上限约束；语义与原型不同（见 §1.2），绑定轻/中体量 |
| **眩晕（跳过回合）** | QPet 充气锤 10% 忽略 1 回合、胶水 10% 黏 3 回合、企鹅吼；researcher 控制 15–40%、持续 1–3 回合；乱斗堂 15% 眩晕 | `attack` / 8–15% / `stun` | 本插件 stun 恒为 1 回合；等效「己多一窗口 + 敌少一回合」≈ 双向收益，**概率必须压低**；无冷却系统，暂不设多回合版 |
| **受击减伤** | MB Armour / Extra-thick Skin 减伤 10–50%；QPet 皮糙肉厚 −20%、霸气护体 2 次格挡 50% | `defend` / 15–25% / `damage_reduction` 0.3–0.5 | 铁布衫先例（20%/0.5，体修 1.2 加成）；减伤 cap 40% 已在框架内 |
| **反击** | QPet 第六感 30%、双截棍 10% 被击反击、宽刃剑 15% 闪避反击；乱斗堂 17%×144%；MB Pugnacious +30% Reversal | `defend` / 10–20% / `counter` 0.5–1.0 | 反击伤害 = 自身面板×value，期望增幅 ≈ rate×value（每回合至多一次受击窗口） |

### 2.2 已实现（2026-08-08 `trigger-effect-extensions`，效果引擎化 bd `tt3` 已闭环）

> 以下效果原为 needs_code；引擎已通过 EFFECT_HANDLERS 注册表扩展全部实现
> （managers/combat_manager.py），**现可直接入池**。同步契约词表与
> validate_budget 折算已随扩展更新。真伤/破甲、秒杀、多段连发仍未实现（见 §6 表）。

| 效果 | 原型（出处·数值） | 适配设想 | 说明 |
|---|---|---|---|
| **治疗/吸血** | QPet 矿泉水 回复 25%（至少 25）；Tragic Potion 12–500；想不想修真 吸血+10%；researcher 吸血 10–30% | `attack`/`defend` / `heal`（heal_percent 默认 effect_value；`vampire: true` 吸血模式） | 已实现；续航维度空白，优先级高；按 HP(L) 百分比定 value |
| **属性 Buff/Debuff** | QPet 残影 速度+50% 2–3 回合；龙蛇弓 力量−50% 3 回合；修仙家族 +20–200% 持续 2–4 回合 | `buff`/`debuff` 带持续回合（duration；buff 施加自身、debuff 施加目标） | 已实现：持续状态结构（StatusEffect，叠加 cap=3）；round_start 白名单放行 |
| **持续伤害 DOT** | 真·青龙戟 带毒；企鹅挠痒 5+敏捷×0.2×6 回合 | `dot`（effect_value×tick_rate 每回合，duration 回合数，快照=触发攻击预期伤害） | 已实现；同源刷新、异源 cap=3；叠加上限=status_stack_cap。注：快照取触发时刻的累计倍率，同轮后续 damage_bonus 技能不并入快照 |
| **必中 / 不可反击** | 狂魔镰 必中不可反击；判官笔 必中；幻影枪 不可反击 | `unavoidable`（一次性标记：跳过 dodge/block/counter） | 已实现；克制闪避/反击流的关键反制件 |
| **真实伤害 / 破甲** | 想不想修真 混沌真伤（10% 触发）；一念逍遥破防按百分比削防 | `pierce`（无视 X% 护甲减伤） | **已实现（pierce）**：新护甲公式下按 pierce_rate 绕过减伤；真伤（无视全部减伤）未单独实现 |
| **免死（装死）** | QPet 装死「第一神技」致死留 1 血；MB Survival 同效果 | `survive`（survive_count 层数 + survive_recovery 恢复比例） | 已实现；建议做**奥义**而非触发技（每场一次），避免触发版反复生效 |
| **反弹** | QPet 大海无量 100% | `reflect`（reflect_rate × 实际伤害，每回合至多 1 次、不反射反射） | 已实现；可入池但需单独评估强度 |
| **副作用/疲劳** | 乱斗堂爆裂一击 250%+疲劳 | `fatigue`（自我 debuff，×max(0,1−value)） | 已实现；天魔解体可选配，value 已降 1.8 贴线（§6） |
| **闪避/命中提升** | MB Untouchable；QPet 凌波微步 +7%、铁铲 20%、青龙戟 10% | 常驻属性 → **走心法**，不做触发技 | 闪避 cap 40% 已设；触发版闪避收益不稳定，不建议 |

### 2.3 不适用（本插件无对应系统，明确排除）

| 效果 | 原型 | 排除理由 |
|---|---|---|
| 宠物交互 | MB Hypnosis / Cry of the Damned / Bomb 打宠物 | 无宠物/召唤系统 |
| 武器库操控 | MB Thief 偷武器 / Sabotage 摧毁备用武器 / Deluge 抽 6 武器投掷；QPet 缴械 50% | 本插件为单装备制（穿一件武器），非 MB 武器库轮换制 |
| AOE 多目标 | 修仙家族 全体 0.5x–1.2x；Bomb 打全体 | 战斗恒为 1v1 |
| 秒杀 | QPet 神来一击 5–8% 降至 1 血；如来神掌 打半血 | 直接摧毁 TTK 预算；若做只能是低率奥义 + 对 Boss 无效（见 §3） |

---

## 3. 奥义（大招）设计总表

框架：每场一次、概率触发、当前仅支持伤害倍率（×(1+value)）。
预算折算：奥义期望增幅 ≈ **effect_value ÷ 镜像 TTK × trigger_rate**（把多打的
value 击摊到全场）。中体量 TTK≈7、rate=100% 时 value≤2.1 才满足 G2 ≤30%。

| 奥义类型 | 原型（出处·数值） | 建议 value / 机制 | 代码支持 | 备注 |
|---|---|---|---|---|
| **爆发倍率**（现有） | MB Hammer 空手 400%；Deluge 投 6 武器不可格挡；乱斗堂爆裂一击 250%+下回合疲劳 | `massive_damage` 2.0–3.5（→ 当次 ×3–4.5） | ✓ | **现有万剑归宗 3.0 / 开天辟地 3.5 超 G2 预算**（×4/+43%、×4.5/+50%，按 rate=100% 估），核对 trigger_rate 后定下调方案 |
| **治疗** | QPet 矿泉水 25% 并立即攻击；师傅驾到 20%+下次必中；Tragic Potion | `heal` 0.25–0.40 × 最大气血 | ✗ | 体修/气血流续航大招；value 对标 2–3 击伤害 |
| **控制** | MB Net 困住至受击；QPet 胶水 3 回合 | `stun` 1–2 回合（必中版） | ✗ | 等效 1–2 个攻击窗口，强度对标 value 2–4，但体验更戏剧化 |
| **免死** | QPet 装死；MB Survival；霸气护体 2 次格挡 50% | `survive_lethal`（致死留 1 血，每场一次） | ✗ | 防守向招牌，传播性好；净收益 ≈ 对手 1 击，天然贴合预算 |
| **斩杀** | QPet 神来一击 5–8% 降至 1 血；如来神掌 半血、无视反弹 | `hp_execute` 目标气血降至 X% | ✗ | **谨慎**：高传播但破坏预算；若做需低 rate + Boss/高境界无效 + 数值按"至多当 3–4 击"封顶 |
| **连发** | QPet 势如暴雨 投 3 武器；真·流星球 连扔 3 次 | 现有 `combo` 机制近似（value 叠加），或 `multi_hit` ×2–3 | ✗（combo 可近似） | 总倍率参照 researcher 多段 2.4x–7.6x 取下段 |

---

## 4. 数值区间与平衡规则（落 `skills.csv` 前逐条核对）

1. **G2 预算**：单一功法「触发技期望增幅 + 奥义期望增幅」≤ 30%（对镜像基准）。
   - 攻击增伤/连击：期望 = rate × value
   - 反击：期望 ≈ rate × value（每回合至多一个受击窗口）
   - 减伤：生存端期望 = rate × value，与输出端分列，不双重计入
   - 眩晕：粗估 ≈ 2 × rate ÷ TTK（己方窗口 + 敌方停摆），必须额外压低 rate
   - 奥义：effect_value ÷ TTK × trigger_rate
2. **触发率区间**（综合 QPet/researcher 收敛）：攻击触发 15–25%；受击触发 10–20%；
   控制 8–15%；奥义 30–100%（现有配置待核对）。
3. **控制平衡三线**（researcher：冷却 / 单场次数 / 持续回合）——本插件无冷却系统，
   现阶段用「低概率 + 恒 1 回合 + 单场机制（奥义通道）」替代；引入持续状态结构后再放开。
4. **体量/路线绑定**（QPet 三角：小连击、中均衡、大高伤）：
   连击/必中 → 轻、中体量与灵修；高倍率/蓄力 → 重体量与体修；减伤/反击/免死 → 体修；
   控制 → 中体量通用。路线差异用 `route_mult`（±20%，铁布衫 体修1.2/灵修0.8 先例）。
5. **升星倒推**：升星为乘法 `(1 + STAR_UP_BONUS)^(星级−1)`（STAR_UP_BONUS = 0.10，
   见 §1.4，3 星 = 1.21×），基础值按目标星级 ÷(1.1)^(星级−1) 倒推；
   G2 预算按 0 星还是满星核算仍为开放问题（倾向满星，偏保守；v1 池暂按 0 星录入，见 §6）。
6. **高境界防拖**（researcher §3）：元婴以上池子优先考虑真伤/破甲/百分比类，
   避免固定值被境界属性稀释。

## 5. 开放问题

- [x] 两大招 trigger_rate 核对 → 已定案：**必放制**（§1.3），config 不填概率；3.0/3.5 超预算降档随 bd `dhh`
- [x] `combo` 语义 → 已接受现状：倍率叠加+栈上限，不做「额外打一回合」（§1.2 备注）
- [x] 非伤害型奥义分发 → 已实现（2026-08-08 `trigger-effect-extensions`：大招统一走 EFFECT_HANDLERS，非伤害效果经 gate+限次后分发；legacy 无 effect_type 默认 damage_bonus 兼容）
- [x] 副作用/疲劳机制 → 已实现（`fatigue` effect_type，自我 debuff）；天魔解体（§6）已降 value 至 1.8 闭环，疲劳副作用可选配
- [ ] G2 的 30% 按 0 星 / 满星核算？（v1 池暂按 0 星录入，见 §6）

---

## 6. v1 功法池扩充记录（2026-08-07）

按文件头三大素材来源（MB / QPet / researcher）照搬适配，`skills.csv` 由 3 行扩至 **20 行**
（2 legacy + 18 draft；新增 17 行：通用 5 / 灵修 3 / 体修 4 / 传承 5）。
`validate_budget.py` 全 PASS（校验公式统一为加性语义 `rate × effect_value`，与武器挂载技
及 schema-and-engine-fit §3 契约一致；check_skills 已支持 combo/counter/stun/纯大招行）。

**分配规则**：
- 连击/蓄力/暴击增伤 → 通用 + 灵修（draft_kuangfeng / juxing / zhanyi / qingfeng / leizhen）
- 反击/减伤/眩晕/逆袭 → 体修（draft_yiyahuan / zhenshan / tieshan / baxia / hunyan / jinshen）
- 斩杀/延迟/复合大招 → 传承池，learn_coefficient 0.3–0.5 稀有（draft_zhenlong / jiujian / xiuluo / tianmo / zhonghun）
- 大招全为伤害型（加性 value 1.5–2.0 = 当次 ×2.5–3.0），必放制不填概率，全部带解锁门槛
  （斩杀型 opp_hp_below / 逆袭型 self_hp_below / 延迟型 min_action_index）
- 万剑归宗重做：3.0 → 2.0（bd `dhh` 降档）；已于 2026-08-08 同步 config（name 覆盖 + id 保留 `spirit_001`，player_skills 引用不中断）

**待实现部分（needs_code，未入 CSV 或已入但需引擎扩展；归口 bd `dhh`）**：

> 2026-08-08 `trigger-effect-extensions` 后：heal/吸血、持续 BUFF/DEBUFF、DOT、必中、
> 免死、反弹、疲劳均已引擎实现（EFFECT_HANDLERS 14 族），**可入池**；
> 以下为仍未实现项。

| 原型效果 | 出处 | 去向 | 阻塞 |
|---|---|---|---|
| 治疗/吸血（矿泉水 25%、吸血+10%） | QPet/想不想修真 | **已实现**（heal/vampire），未入 CSV，验证技能见 §6.1 | — |
| 持续 BUFF/DEBUFF（残影 速度+50%、降攻、BUFF 20–100%） | QPet/无极仙途 | **已实现**（buff/debuff+StatusEffect），未入 CSV | — |
| DOT（企鹅挠痒、真·青龙戟带毒） | QPet | **已实现**（dot+snapshot），未入 CSV | — |
| 必中/不可反击（判官笔、狂魔镰、天使之翼） | QPet | **已实现**（unavoidable 一次性标记），未入 CSV | — |
| 真伤/破甲（混沌真伤、破防） | 想不想修真/一念逍遥 | 破甲已实现（pierce，无视 X% 减伤）；**真伤（无视全部减伤）未实现** | dhh 高境界防拖 |
| 免死（装死、Survival） | QPet/MB | **已实现**（survive 层数+recovery），建议大招位，验证技能见 §6.1 | — |
| 反弹（大海无量 100%） | QPet | **已实现**（reflect，1/回合、不反射反射）；强度需单独评估 | — |
| 副作用/疲劳（爆裂一击 250%+疲劳） | 乱斗堂 | **已实现**（fatigue）；天魔解体已入 CSV 且已降 value 至 1.8（贴线缓解） | 可选配 |
| 多段连发（势如暴雨、真·铅球） | QPet | 用 combo 近似入池 | multi_hit 可选 |
| 秒杀（神来一击 5–8% 降至 1 血） | QPet | 排除（§2.3）；以真龙诀斩杀替代 | 需 hp_execute 才可做 |

> 跟踪：总进度 bd `hz7`；数值配平/降档 bd `dhh`；效果引擎化 bd `tt3`（2026-08-08 已闭环）。
> 入库：skills.csv → config 已同步（2026-08-08 `implement-content-design`：reconcile 全量重导 20 行、`spirit_001` 万剑归宗、天魔解体 1.8；schema-and-engine-fit.md §4 已更新）。
> 验证技能：§6.1 新增 5 行（治疗/吸血/DOT/免死大招/必中），2026-08-08 随 `trigger-effect-extensions` 同步入库。

### 6.1 验证技能（2026-08-08 `trigger-effect-extensions`）

为验证新效果引擎而加入的少量技能（0.x 加性值、单行预算内），非完整玩法扩充：

| id | name | 池 | 触发 | effect | value | 说明 |
|---|---|---|---|---|---|---|
| verify_heal_001 | 回春诀 | 通用 | attack 20% | heal | 0.25 | 治疗 25% 最大气血 |
| verify_vampire_001 | 噬血剑意 | 灵修 | attack 20% | heal (vampire) | 0.20 | 吸血 20% 实际伤害 |
| verify_dot_001 | 蚀骨咒 | 通用 | attack 25% | dot | 0.15（duration 3） | 每回合 15% 快照伤害 |
| verify_survive_001 | 涅槃诀 | 通用 | 大招（必放，门槛 5） | survive | 0 | survive_count 1 |

### 6.2 新效果入池扩充（2026-08-08 v2，`trigger-effect-extensions` 后）

效果引擎化闭环后，按文件头三大素材来源 + researcher taxonomy 新增 **12 行**正式技能
（skills.csv 25 → 37 行；config 同步 25 → 37），新效果族首次入池：

| id | name | 池 | 触发 | effect（value） | 参考原型 | 预算 |
|---|---|---|---|---|---|---|
| draft_wandu | 万毒掌 | 通用 | attack 20% | dot 0.10（duration 3） | QPet 真·青龙戟带毒 | 6.0% ✓ |
| draft_ningshen | 凝神诀 | 通用 | attack 15% | buff 0.30 stat=speed（2回合） | QPet 残影 速度+50% | ≈9% WARN |
| draft_yingji | 鹰击诀 | 灵修 | attack 15% | unavoidable | QPet 判官笔/幻影枪 | WARN |
| draft_qingming | 青冥剑诀 | 灵修 | attack 20% | buff 0.30 stat=damage（3回合） | 修仙家族 BUFF 20–100% | ≈18% WARN |
| draft_lingshe | 灵蛇缠身 | 灵修 | attack 15% | debuff 0.20 stat=damage（3回合） | QPet 龙蛇弓 −50%×3 | ≈9% WARN |
| draft_tieji | 铁棘功 | 体修 | defend 10% | reflect 0.30 | QPet 大海无量 100% | WARN |
| draft_xuanwu | 玄武诀 | 体修 | defend 15% | buff 0.25 stat=armor（3回合） | 修仙家族 免伤 20–100% | ≈11% WARN |
| draft_liaoshang | 疗伤诀 | 体修 | defend 15% | heal 0.25 | QPet 矿泉水 25% | 26.2% ✓ |
| draft_jiuyou | 九幽噬魂咒 | 传承 | 大招（门槛4） | dot 0.25（4回合） | QPet 企鹅挠痒 6回合 | ≈14% ✓ |
| draft_huitian | 回天圣手 | 传承 | 大招（门槛3） | heal 0.25 | QPet 矿泉水/师傅驾到 | ≈25% ✓ |
| draft_shiling | 噬灵魔功 | 传承 | attack 14% | heal 0.30（vampire） | 想不想修真 吸血+10% | 29.4% ✓ 贴线 |
| draft_pojun | 破军诀 | 传承 | attack 15% | pierce 0.5 | 一念逍遥破防 | 11.2% ✓ |

**分配**：DOT/速度 BUFF → 通用；必中/增伤/降攻 → 灵修（route 1.2/0.8）；反弹/护甲/受击治疗 → 体修（0.8/1.2）；DOT 大招/治疗大招/吸血/破甲 → 传承（learn 0.3–0.5）。

**契约列补充**：skills.csv 新增 `duration/tick_rate/heal_percent/pierce_rate/reflect_rate/survive_count` 与 `stat` 列
（sync 契约扩展：`stat` 为 buff/debuff 作用属性 `damage/armor/speed`，缺省 damage，引擎 skill.get("stat","damage")）；
**修正遗留 bug**：verify_dot_001 蚀骨咒设计 duration=3 此前无列未入库（引擎按缺省 1 生效），已补列后生效 3 回合。
| verify_unavoidable_001 | 破风剑意 | 灵修 | attack 20% | unavoidable | 0 | 必中一击 |
