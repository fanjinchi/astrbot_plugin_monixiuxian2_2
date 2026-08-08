## Context

动机与审计结论见 proposal.md（A 类 6 项字段修正、B 类 4 项设计意图实现、C 类已确认落地项）。

现状要点：
- `scripts/sync_content_to_config.py` 已实现 weapons/heart_methods 同步：`_build_weapon` / `_build_heart` 字段映射、`_merge` 按 name 键控、`_validate_trigger_skills` 四键契约校验、写盘前 `validate_budget.py` 闸门、原子写（tmp+replace）。技能同步被 docstring 声明冻结（bd dhh）。
- 心法 bug 已污染 config：`_build_heart` 中 `"exp_multiplier": _num(...) or 1.0` 把设计 0.0 写成 1.0（+100% 修为，见 cultivation_manager.py:365 `root_speed * (1.0 + technique_bonus)`），10 件纯战斗心法受影响。
- `core/skill_manager.py:522 get_battle_loadout` 导出武器/功法触发技与大招，功法技能无路线倍率应用；`Player.cultivation_type`（models.py:102，默认"灵修"）与武器侧路线倍率消费（models.py:253）已存在。
- `handlers/equipment_handler.py` equip 流程：item_config 命中心法 → `item_type="main_technique"`，无 route 校验；`core/equipment_manager.py:190` 已有 required_level_index 门槛校验（模板参照）。
- config/skills.json 是 dict（键=技能名），`_find_skill_id_by_name`（skill_manager.py:511）直接 `skills_data.get(name)`；`player_skills` 已学记录按 skill_id 关联。config 技能条目结构：`{id, name?, trigger_skill: {四键}, ultimate: {name, effect_type, effect_value, min_action_index, 血量阈值}}`。
- 大招/触发技消费已实现：combat_manager.py:594-621（必放制+门槛+每场一次）、EFFECT_HANDLERS 分发（:415）。

## Goals / Non-Goals

**Goals:**
- 修正 exp_multiplier 同步 bug（脚本 + config 10 处存量值）
- 修正 skills.csv 三处（legacy 三行→draft、万剑归宗 name/id 对齐、天魔解体 2.1→1.8）
- 扩展 sync 脚本支持 skills.csv → config/skills.json（契约校验、同名保留 id、0.x 数值、route_multiplier）
- 功法路线倍率在战斗结算中生效（触发技乘 rate、大招乘 effect_value）
- 心法 route 装备匹配校验
- 全量回归（validate_budget、pytest、sim_balance_regression）

**Non-Goals:**
- 新效果类型（疲劳副作用等 bd tt3 其余项；天魔解体按降值处理）
- 旧 config 中不在 CSV 设计表内的条目不保留、不迁移（用户指示：全量重导，旧设计内容不关心）——删除条目的存量玩家影响仅记录，不提供补偿或转换
- 新功法获取途径：突破通用池 / 修习目标 / 心法配套池为既有渠道；**部分心法已挂载配套功法用于领悟池机制验证**（12/18 心法，覆盖通用/灵修专属/体修专属/传承四类池与系数梯度 1.0/0.8/0.6/0.5/0.3，见 heart_methods.csv），挂载明细随平衡迭代调整；"灵修/体修专属"按数值分化理解（route_multiplier），非获取独占
- 技能 learn_coefficient 列入库（引擎无独立消费点，心法 skill_pool 已承载系数语义）
- **平衡完成后将最终配置固化进 data/default_configs.py**（未来项，bd 跟踪；本变更期间 default_configs 保持旧值，删 config 重开会回退旧数值，属平衡中临时态）

## Decisions

**D1. exp_multiplier 修复**：`_build_heart` 改为 `_num(row.get("exp_multiplier", "")) if (v := _num(...)) is not None else 0.0`（保留 0，空 cell 默认 0.0——与 equipment_manager.py:129 默认值一致）。config 存量修正：一次性脚本将 10 件心法（烈火功/金罡诀/玄影功/战神诀/不动明王功/疾风迅雷功/太虚功/乾坤功/无我功/混元一气功）`exp_multiplier: 1.0 → 0.0`。属 bug 修复（设计值恢复），非玩法变更。

**D2. skills.csv / heart_methods.csv 修正**（设计表为本，同步前落盘）：
- common_001/002/draft_leiji `status: legacy → draft`（注记已声明入库重做意图，legacy 会导致被跳过）
- heart_001 长春功 `status: legacy → draft`（新手默认心法：凡品 HP+10%、shop_weight 100；test_config_manager.py:30 依赖；设计有效故保留而非删除）
- 万剑归宗：`name: "万剑归宗（重做）" → "万剑归宗"`、`id: draft_wanyu → spirit_001`（与 config 既有条目同 name 同 id，sync 走 UPDATE 路径；双保险：脚本同名覆盖时也保留既有 id）
- 天魔解体：ultimate `effect_value: 2.1 → 1.8`（÷7≈25.7%，与金身诀同档，满足大招预算约束）
- **心法 skill_pool 挂载（用户指示，随提案完成）**：12/18 心法挂载配套功法（heart_004 狂风诀1.0；heart_101 雷震剑诀0.8；heart_102 混元护体诀0.8；heart_201 基础吐纳1.0+震山锤0.6；heart_202 以牙还牙0.6；heart_301 铁布衫1.0+金身诀0.5；heart_401 战意诀1.0+八式崩拳0.6；heart_501 聚星诀0.8；heart_601 青锋连斩0.6；heart_701 真龙诀0.3；heart_801 九剑归一0.5+天魔解体0.3；长春功已有 基础吐纳1.0+铁布衫0.8），目的：让心法领悟池机制（skill-system「领悟随机池与来源规则」）有真实可测内容——此前 v1 心法池全空，该机制从未被实际触发

**D3. 技能同步字段映射**（`_build_skill` 新增）：
- 触发技：`trigger_skill = {trigger_timing: 映射(trigger_condition), trigger_rate, effect_type, effect_value}`；映射表 `attack→on_attack / defend→on_defense / crit→on_crit / round_start→round_start`（与 skill-system 归一化层同源；combat 引擎消费 on_attack/on_defense/on_crit/round_start——注意 CSV 用 crit 而引擎键为 on_crit，需映射表显式处理）
- 大招：`ultimate = ultimate_json` 原样（契约校验复用现有：无 trigger_rate、effect_value 数值、min_action_index、血量阈值键）
- 技能条目附加 `route_multiplier: {"灵修": mult_ling, "体修": mult_ti}`（与武器入库结构一致，默认 1.0）
- `pool` / `learn_coefficient` / `ref_source` / `design_note` / `trigger_name` / `status` 不入库（领悟渠道语义由 skill-system 覆盖、无消费点）
- merge 按 name 键（config 技能 dict 键=name）；同名 UPDATE 时保留既有 `id`；新名 ADD
- 校验：触发技四键齐全 + timing 在映射表内 + rate ∈ (0,1] + effect_value 数值；大招必放校验复用 `_validate_trigger_skills` 思路的 ult 版

**D4. 路线倍率应用点 = get_battle_loadout 导出时**（集中一处，combat 引擎零改动）：
```
route = player.cultivation_type
mult = skill_def.get("route_multiplier", {}).get(route, 1.0)   # 缺失视为 1.0
触发技: trigger_copy["trigger_rate"] = min(1.0, rate * mult)    # value 不变
大招:   ult_copy["effect_value"] = value * mult                 # rate 恒 1（必放）
```
理由：两者均等价于期望增益 ×mult（触发技 G=rate×value；大招 G=value÷7）；触发技乘 rate 使 value=0 的控制类（stun/震山锤）也获得路线分化；大招乘 value 因必放制 rate 恒 1。与升星（rate 与 value 同乘 (1.1)^(star-1)）正交乘法叠加，仍在预算内（最坏雷震剑诀 3 星灵修：0.12×1.5×1.2×(1.1)²≈26%）。备选方案（combat 结算时按路线重读配置）被否：loadout 已是导出快照，结算期读 player 路线需穿透，且与 star 应用层（_apply_star_to_def 后）顺序耦合。

**D5. 心法 route 校验**：equipment_handler equip 流程在 `item_type="main_technique"` 分支后、写入前插入：
```
route = heart_def.get("route", "通用")
if route != "通用" and route != player.cultivation_type:
    拒绝并提示 "该心法适用于{route}路线（当前{type}），可换用通用心法"；不卸当前心法
```
旧心法 route 缺失（config 无键）按"通用"放行（get 默认值）。只拦装备动作，存量已装备不受影响。

**D6. 全量重导（reconcile）实现**（用户指示：旧 config 设计内容全删重导）：
- `_merge` 语义扩展为 reconcile：先导入全部 draft/final 行（按 name UPDATE/ADD，技能同名保留既有 id），随后删除列表中不在导入 name 集合内的条目。删除与导入同批原子写（tmp+replace 保留）
- dry-run 输出增强：除 UPDATE/ADD diff 外，输出 DELETE 清单（每行"DELETE name [rank]"），供入库前人工核对
- 重导后规模：weapons 121→9（碧水灵剑 legacy 删除）、heart 22→18（长春功 draft 导入；焚天诀/不动明王经/传承心法×2 删除）、skills 6→20（御剑术/撼山劲/传承功法×2 删除）
- 玩家影响（记录不补偿）：已装备删除条目的战斗无效（get_battle_loadout 中 `_find_skill_definition` 返回 None 静默跳过，无崩溃）；`player_skills` 中 spirit_001 旧记录（御剑术）因 id 复用自动对应新版万剑归宗；已装备功法名悬空者卸下后不可重装（无对应配置）

**D7. 验证**：sync 跑通后 `validate_budget.py` 对 20 行技能全量 PASS；`sim_balance_regression.py` 数值回退对比；新增 pytest：exp_multiplier 0.0 保留、技能同步（含万剑归宗 id 保留、timing 映射、大招无 rate）、reconcile 删除表外条目、路线倍率 loadout（灵修/体修/通用三分支、stun 乘 rate）、心法 route 校验（拒绝+通用放行）、**领悟池机制集成测试（装备挂载心法的玩家经突破/闭关领悟判定后能按 learn_coefficient 加权抽到配套池内功法）**；**审计存量测试对旧条目的断言**（spirit_001 语义已变、焚天诀/御剑术等被删）并修正。

## Risks / Trade-offs

- **旧玩家技能强度变化（玩法变更）**：基础吐纳 ×2.2→×1.2、雷击诀 ×3.0→×2.0（铁布衫 ×1.5 不变）；17 个新技能上线。变更说明中标注，无补偿（设计既定）。
- **全量重导的删除影响**：御剑术/撼山劲/焚天诀/旧 111 武器等全部消失；已装备者战斗中无效（静默跳过）但不崩溃；spirit_001 旧记录迁移为万剑归宗属巧合性语义变化（id 复用）。玩家可见配置信息（已装备列表）与实际效果不一致属临时态，重导后随重装/更新自然收敛。
- **领悟池开放**：心法挂载后，装备挂载心法的玩家经突破（20%）/闭关（15%）领悟判定可抽到配套池功法——新 17 功法由此获得主要获取渠道，稀有度由 learn_coefficient 控制（真龙诀/天魔解体 0.3 极稀有）；测试阶段挂载明细非最终平衡，随迭代调整。
- **default_configs 滞后**：本变更不更新 data/default_configs.py；config 文件被删重开时回退旧数值（平衡中临时态，bd 跟踪后续固化）。
- **路线倍率 × 升星复合**：乘法叠加上限约 26%（≤30% 预算）✓。
- **心法 route 校验对存量玩家**：只拦新装备动作，不卸装；焚天诀（灵修）被删后该场景仅存在于测试夹具；校验逻辑保留（防未来路线心法）。
- **同步幂等性**：重复运行 sync 应无 diff（reconcile 后 config 与 CSV 一致）；exp_multiplier 修复后需重跑确认 config 不再被污染。
