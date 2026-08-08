# 设计表列说明与代码适配审计

> 2026-08-06。解释 `weapons.csv` / `heart_methods.csv` / `skills.csv` / `weapon-skills.md`
> 挂载池各列的作用，逐列审计其在现有代码架构中的落点：是否有现成接口可直接应用，
> 数值机制是否适配引擎运作方式，还是仍需开发。
>
> **状态图例**：✅ 现成接口直接可用 ｜ ⚠️ 接口在但有注意事项 ｜ ❌ 需开发/修复 ｜ 🚫 设计层专用，不落 config

## 0. 数据流总览

```
设计 CSV ──(转换脚本 scripts/sync_content_to_config.py,已落地)──> config/*.json ──> config_manager._load_items_data
     │                                        （按 name 键控，注入 _group）
     │                                        ↓
     └── ref_source/design_note/status        skill_manager.get_battle_loadout
        仅设计层使用，不进 config               models.get_total_attributes
                                              shop / 装备校验 / 闭关悟道
```

**两个引擎 bug 均已修复（change `skill-engine-fit-and-content-sync`，2026-08-06 落地、08-07 归档）**：

| # | bd | 原症状 | 根因 | 修复方式 |
|---|---|---|---|---|
| 1 | `lvb`（已关） | 6 个 config 功法触发技**静默不触发** | config 用 `effect` 键，引擎只读 `effect_type`，归一化不改名 | config 全量改名 `effect`→`effect_type`（设计表同步）；`EFFECT_HANDLERS` 注册表分发，功法/武器共用入口 |
| 2 | `iup`（已关） | 两个大招**从不触发** | config ultimate 无 `trigger_rate`，引擎默认 0.0，`random < 0` 永假 | **必放制**：归一化层注入 `trigger_rate=1.0`，config 不得填概率；加解锁门槛 `min_action_index` + 血量阈值（skills-ultimates.md §1.3） |

## 1. weapons.csv（19 列）

| 列 | 作用 | config 落点 / 消费代码 | 状态 |
|---|---|---|---|
| `id` | 设计层唯一标识 | config 保留 `id` 字段；**注意 config 按 `name` 键控**（`_load_items_data`），`player.weapon` 存的是名字 | ⚠️ |
| `name` | 展示名 + 实际键 | 必须全表唯一，否则加载互相覆盖 | ⚠️ |
| `weapon_category` | 类别（剑/刀/枪…） | config 同名字段（120 件已有），商店/装备界面分组 | ✅ |
| `size_class` | 体量（轻/中/重） | **不落 config**——体量由 K 值（0.4/0.5/0.6）实际体现，仅用于预算分带 | 🚫 |
| `rank` | 品级 | config `rank`，商店/展示直接消费字符串 | ✅ |
| `required_level_index` | 境界门槛 | 装备校验 `player.level_index < required_level_index` | ✅ |
| `base_damage` | Muxxu 基础伤害 | `get_battle_loadout → base_damage`，每击主输出 | ✅ |
| `weapon_coefficient_k` | 伤害转化率 | 同上；预算约束 K<1（引擎无校验，靠 validate 把关） | ✅ |
| `bonus_damage` | 属性词条伤害 | **config 键名是 `damage`**（非 bonus_damage），`get_total_attributes` 平加进伤害属性，**受 route_mult 乘算** | ⚠️ |
| `armor_value` | 护甲 | 新公式 armor/(armor+100+10L)，`combat_manager._apply_armor_and_reduction` | ✅ |
| `price` / `shop_weight` | 经济 | 商店售价/刷新权重 | ✅ |
| `route_mult_ling/ti` | 路线系数 | config `route_multiplier{灵修,体修}`，`models.get_total_attributes` 经 `item.get_route_multiplier(route)` 应用——**但只乘属性词条（damage/agility/hp…），不乘 base_damage/K**；标杆件无词条时该列无实际效果 | ⚠️ |
| `trigger_skills_json` | 挂载触发技 | config `trigger_skills`（schema 已存在，120 件全空），loadout **原样透传不归一化** → 必须用引擎键（`trigger_timing`/`effect_type`），见 `weapon-skills.md` §0 | ⚠️ |
| `description` | 展示 | ✅ | ✅ |
| `ref_source` / `design_note` / `status` | 溯源/笔记/流转 | 不落 config；转换脚本按 status 过滤（只取 draft/final，排除 legacy） | 🚫 |

**武器结论**：v1 标杆件与变体的全部数值列**零开发可入库**；仅需 ① 转换脚本
（含 name 键控、bonus_damage→damage 键名映射）② 挂载技遵守引擎键格式。

## 2. heart_methods.csv（13 列）

| 列 | 作用 | config 落点 / 消费代码 | 状态 |
|---|---|---|---|
| `id` | 设计层标识 | config 保留字段；键控同样按 `name`（`player.main_technique` 存名字） | ⚠️ |
| `name` / `description` / `rank` | 展示与键 | 装备界面展示 | ✅ |
| `required_level_index` | 境界门槛 | 装备校验（与武器同链路） | ✅ |
| `passive_bonus_json` | 被动词表 | `models.get_total_attributes`（item_type=main_technique）：`hp_percent`/`damage_percent`/`agility_percent`/`speed_percent` 乘算总值 + `armor_value` 平加。**词表外键会被静默忽略**——不要自造键名 | ⚠️ |
| `exp_multiplier` | 修炼效率 | `player_handler:359 → cultivation_manager.calculate_cultivation_exp(technique_bonus)`，与灵根/丹药连乘；链路已确认 | ✅ |
| `skill_pool_json` | 配套功法 | 闭关悟道消费（每 2h 15% 判定，限配套池+修习目标）；v1 留空 `[]` 合法 | ✅ |
| `route` | 路线标签 | 字段存在但**未见消费点**（不参与装备校验，预留）；v1 全部「通用」是正确决策 | ⚠️ |
| `shop_weight` | 商店权重 | ✅ | ✅ |
| `ref_source` / `design_note` / `status` | 设计层 | 🚫 | 🚫 |

**心法结论**：v1 池 18 个**零开发可入库**。唯一风险是自造被动键名（词表只有 5 个键）。

## 3. skills.csv（15 列）与武器挂载技

| 列 | 作用 | config 落点 / 消费代码 | 状态 |
|---|---|---|---|
| `id` / `name` / `rank` | 标识与展示 | 功法以名修习/装备 | ✅ |
| `pool` | 所属功法池 | skills.json 顶层分组（dict-of-list，`_group` 注入）；参悟/传承按池消费 | ✅ |
| `learn_coefficient` | 参悟系数 | skill_manager 参悟判定消费 | ✅ |
| `trigger_condition` | 触发时机 | `skill_manager` timing_map 注入 `trigger_timing`（attack/defend/crit/round_start/once_per_battle 五值已验证） | ✅ |
| `trigger_rate` | 触发率 | 引擎逐次 `random < rate` 判定 | ✅ |
| `effect_type`（原 effect 列） | 效果类型 | **原 bug#1（lvb）已修**：config 与设计表统一用引擎键 `effect_type`，经 `EFFECT_HANDLERS` 注册表分发 | ✅ |
| `effect_value` | 效果值 | 加性倍率语义（0.4 = 该击 ×1.4）；combo 受 `_combo_cap` 栈限；counter 只吃 damage 属性 | ✅（语义需设计者知悉） |
| `ultimate_json`（原 ultimate_name 列） | 大招 | **原 bug#2（iup）已修**：必放制下引擎注入 `trigger_rate=1.0`，config 不填概率；门槛 `min_action_index`/血量阈值已支持 | ✅ |
| `ultimate_effect` | 大招效果类型 | **引擎不读**——ultimate 分支一律 `ultimate_mult += effect_value`，此列仅描述性 | ⚠️ |
| `ultimate_effect_value` | 大招倍率 | ×(1+value)；3.0/3.5 超 G2 预算，降档至 2.0 档随 bd `dhh` | ⚠️ |
| `route_mult_ling/ti` | 功法路线系数 | config `route_multiplier` 存在（御剑术 灵修1.2/体修0.6），但 **grep 全库无消费点**（skill loadout 不按路线乘算）——需开发或删除字段 | ❌ |
| `ref_source` / `design_note` / `status` | 设计层 | 🚫 | 🚫 |

**武器挂载技**（`weapon-skills.md` v1 池 13 个）：全部用引擎键直写
（`trigger_timing`/`effect_type`/`trigger_rate`/`effect_value`），**零开发可用**，
不受 bug#1 影响（绕过归一化恰好绕开了坏路径）。

## 4. 适配总结与开发清单

**可直接入库（零开发）**：武器 v1 标杆件与变体（含挂载技）、心法 v1 池 18 个。
**被阻塞**：功法池落地，前置是 P1 双 bug。

| 优先级 | 事项 | 性质 | 状态 |
|---|---|---|---|
| P1 | bug#1 `lvb` | 修复 | ✅ 已修（键名统一 + `EFFECT_HANDLERS` 注册表，2026-08-06） |
| P1 | bug#2 `iup` | 修复 + 数值 | ✅ 已修（必放制 + 解锁门槛）；3.0/3.5 降档随 bd `dhh` |
| P2 | 功法 `route_multiplier` 消费（loadout 按 `player.cultivation_type` 乘 rate/value）或删字段 | 小开发/清理 | ⬜ 未做（bd `f4t` 跟踪心法 route_mult，功法侧同源） |
| P2 | CSV → config 转换脚本（name 键控、bonus_damage→damage、status 过滤） | 工具开发 | ✅ 已落地 `scripts/sync_content_to_config.py`（weapons/heart_methods 已入库；skills 同步随功法池重做，脚本 docstring 注明） |
| P3 | needs_code 效果（heal/必中/真伤/DOT/免死走大招） | v2 引擎扩展 | ⬜ bd `tt3` |
| P3 | `validate_budget.py` 支持挂载技「含税期望」校验 | 工具增强 | ⬜ 未做 |
| P4 | 心法 `route` 装备校验（若做路线专属心法） | 可选开发 | ⬜ 未做 |
