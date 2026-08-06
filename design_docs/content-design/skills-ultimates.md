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

> ⚠️ **键名 bug（2026-08-06 发现，未修）**：引擎只读 `effect_type`，但
> config/skills.json 的 trigger_skill 用的是 `effect` 键，而
> `skill_manager._apply_star_to_def` 只注入 `trigger_timing`、不改名 →
> **现有 6 个 config 功法的触发技在战斗中全部静默不触发**。测试没抓到是因为
> tests/test_combat_engine.py 直接注入引擎格式 dict，绕过了 config 路径。
> 修法建议：`_process_trigger_skills` 与 `_process_round_start_skills` 的取值改
> `skill.get("effect_type") or skill.get("effect", "")` 一行兜底。
> 注意修复生效后现有功法将**超 G2 预算**（御剑术 25%×1.5=+37.5%、
> 撼山劲 20%×1.8=+36%），需随功法池重做一并下调。
> 武器挂载技（绕过归一化）必须直接用引擎键，见 `weapon-skills.md` §0。

### 1.3 奥义机制（~L481-495）

- 每个奥义**每场战斗限一次**（`used_ultimates` 集合）；一次行动最多触发一个（`break`）。
- 触发本身**带概率**：`random < trigger_rate` 才生效——config 里奥义的
  `trigger_rate` 待逐个核对（决定期望强度）。
- **当前实现不读 `effect` 类型**：一律 `ultimate_mult += effect_value`，即当次伤害
  **×(1 + effect_value)**。config 里的 `massive_damage` 只是描述性标签。
  → 万剑归宗 3.0 = 当次 ×4.0；开天辟地 3.5 = 当次 ×4.5。
- 要做非伤害型奥义（治疗/控制/免死）需要先在 ultimate 分支加 effect 分发。

### 1.4 升星（`core/skill_manager.py` L27-29）

每星 `STAR_UP_RATE_BONUS = 0.20`、`STAR_UP_EFFECT_BONUS = 0.20`（触发率与效果值
各 +20%/星，乘算）。设计基础值时要按目标星级倒推。

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

### 2.2 未支持（needs_code，落代码后才可入池）

| 效果 | 原型（出处·数值） | 适配设想 | 说明 |
|---|---|---|---|
| **治疗/吸血** | QPet 矿泉水 回复 25%（至少 25）；Tragic Potion 12–500；想不想修真 吸血+10%；researcher 吸血 10–30% | `attack`/`defend` / `heal` | 续航维度空白，优先级高；按 HP(L) 百分比定 value |
| **属性 Buff/Debuff** | QPet 残影 速度+50% 2–3 回合；龙蛇弓 力量−50% 3 回合；修仙家族 +20–200% 持续 2–4 回合 | `buff`/`debuff` 带持续回合 | 需引入"持续状态"结构，工程量中等 |
| **持续伤害 DOT** | 真·青龙戟 带毒；企鹅挠痒 5+敏捷×0.2×6 回合 | `dot` | 依赖持续状态结构；researcher 建议设叠加上限 |
| **必中 / 不可反击** | 狂魔镰 必中不可反击；判官笔 必中；幻影枪 不可反击 | 武器特效 / 攻击标记位 | 克制闪避/反击流的关键反制件；需 dodge/counter 豁免标记 |
| **真实伤害 / 破甲** | 想不想修真 混沌真伤（10% 触发）；一念逍遥破防按百分比削防 | `true_damage` / `armor_pen` | 高境界防拖节奏的阀门（researcher 建议 §3）；新护甲公式下可做"无视 X% 护甲" |
| **免死（装死）** | QPet 装死「第一神技」致死留 1 血；MB Survival 同效果 | `survive_lethal` | 强传播性；建议做**奥义**而非触发技（每场一次），避免触发版反复生效 |
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
5. **升星倒推**：每星 +20% rate 与 value，基础值按目标星级 ÷(1+0.2×星) 倒推；
   G2 预算按 0 星还是满星核算为开放问题（倾向满星，偏保守）。
6. **高境界防拖**（researcher §3）：元婴以上池子优先考虑真伤/破甲/百分比类，
   避免固定值被境界属性稀释。

## 5. 开放问题

- [ ] 现有两大招（3.0/3.5）的 `trigger_rate` 待核对；按 rate=100% 估算超 G2，需定下调或维持方案。
- [ ] `combo` 语义（倍率叠加+栈上限）与原型「额外打一回合」不同，接受还是改引擎？
- [ ] G2 的 30% 按 0 星 / 满星核算？
- [ ] 非伤害型奥义（heal/stun/survive）需要 ultimate 分支加 effect 分发，排期随功法池扩充一起定。
