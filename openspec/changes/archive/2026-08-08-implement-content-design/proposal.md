## Why

content-design 三表（weapons/heart_methods/skills）是战斗数值重做的设计蓝本，但目前落地不完整：武器/心法已同步入库，却带有一个数值 bug（心法 `exp_multiplier` 0.0 被写成 1.0 = 意外 +100% 修为），技能表整体冻结未同步（bd dhh），且多处设计意图（功法路线倍率、心法路线校验、大招预算）尚未进入引擎。需要一次完整落地变更，先审计修正字段偏差，再实现设计意图。

## What Changes

### 审计结论（字段级）

**A. 需按项目修正的字段/问题**（设计表与项目契约的偏差，本变更修正）：

1. **心法 `exp_multiplier` 同步 bug（最严重）**：`scripts/sync_content_to_config.py` 中 `_build_heart` 用 `_num(...) or 1.0`，CSV 的 `0.0`（设计=无修炼加成）被吞成 `1.0`。消费公式 `total_multiplier = root_speed × (1.0 + technique_bonus)`（cultivation_manager.py:365，technique_bonus 直接=exp_multiplier）→ **1.0 = 修为获取 ×2（双倍）**。已污染 config 中 10 件纯战斗心法：烈火功、金罡诀、玄影功、战神诀、不动明王功、疾风迅雷功、太虚功、乾坤功、无我功、混元一气功。→ 修脚本（None→0.0，保留 0.0）+ 修正 config 已污染值。
2. **skills.csv「万剑归宗（重做）」id/name 与 config 冲突**：CSV `id=draft_wanyu`、`name=万剑归宗（重做）`，而 config 已有 `spirit_001/万剑归宗`。sync 按 name merge 会 ADD 新条目而非覆盖 → 技能重复 + `player_skills` 已学记录（按 skill_id）断裂。→ CSV 改为 `name=万剑归宗`、`id=spirit_001`。
3. **skills.csv 表头 `trigger_condition` 与引擎契约 `trigger_timing` 不同名**：值本身是 timing（attack/defend/crit/round_start）+ 大招 once_per_battle。→ 列名对齐为 `trigger_timing`（与 schema-and-engine-fit.md 已改的 effect_type/ultimate_json 一致）。
4. **legacy 技能行标注与设计意图矛盾**：skills.csv 中 common_001 基础吐纳 / common_002 铁布衫 / draft_leiji 雷击诀 三行 status=legacy（同步跳过），但设计注记声明"入库重做时按新契约改 0.x"——若保持 legacy 则旧玩家无法获得新数值。→ CSV status 改为 draft（让三行进入同步范围）。同类的 heart_001 长春功（新手默认心法，凡品 HP+10%，shop_weight 100，test_config_manager.py:30 依赖）也 legacy→draft 保留。注：config 旧值数学形式本就是 ×(1+value)（combat_manager.py:621 `ultimate_mult += effect_value`），无混合语义问题，仅强度变化。
5. **legacy 技能行 effect_value 语义迁移**：config 现值 1.x（×2.2 等大数值），CSV 新契约 0.x（0.2=×1.2）。skills 同步启用后按 CSV 覆盖 → **旧玩家已学技能强度变化**（设计注记已声明此意图），作为玩法变更处理。

**B. 设计意图需实现**（引擎缺口，本变更实现）：

5. **功法技能路线倍率未消费（bd f4t）**：17 个新功法中 12 个 `route_mult_ling/route_mult_ti` ≠ 1.0（灵修/体修强度分化），但 `get_battle_loadout`（core/skill_manager.py:522）不应用 → 路线区分无效。→ 按玩家 cultivation_type 应用倍率。
6. **心法路线无装备校验（P4）**：config 心法有 `route` 字段（旧 5 件中焚天诀=灵修、不动明王经=体修），装备时不校验 cultivation_type 匹配。→ 装备主修心法时校验，不匹配拒绝（提示换装，不卸装）。
7. **skills.csv 同步启用（bd dhh 冻结解除）**：脚本扩展支持 skills.csv → config/skills.json，含触发技四键契约校验、大招契约校验（必放制不填 trigger_rate）、effect_value 0.x 语义、按 name 覆盖、同名保留既有 id。
8. **天魔解体预算超标（bd tt3）**：传承功法·天魔解体 ultimate 2.1（÷7≈30% 贴 G2 上限）且无副作用。→ 按设计注记降 value 至 1.8（≈25.7%，与金身诀一致的安全线）。

**C. 审计确认无需动作**（设计意图已落地，仅记录）：武器 10 件入库正确（bonus_damage→damage 仅在非空时写入、触发技 verbatim、装备门槛校验 equipment_manager.py:190 已实现）；武器 route_multiplier→面板属性已消费（models.py:253）；心法 passive_bonus/skill_pool/required_level_index 入库正确；战斗引擎 EFFECT_HANDLERS 分发、大招必放+门槛（min_action_index + HP 阈值 AND）、升星机制均已实现。

### 落地动作清单

- **范围确认（用户指示）**：本次变更采用**全量重导（reconcile）**——以设计表为唯一来源，删除 config 中不在 CSV draft/final 范围内的旧设计内容，不再保留任何旧条目：
  - weapons.json 121 → 9 件（CSV draft 行；碧水灵剑 legacy 删除）
  - heart_methods.json 22 → 18 件（删焚天诀/不动明王经/传承心法×2；长春功改 draft 保留）
  - skills.json 6 → 20 件（删御剑术/撼山劲/传承功法·护体/传承功法·破敌；万剑归宗以 spirit_001 入库，旧玩家该 id 已学记录迁移为新版）
  - 旧玩家已装备的删除条目：装备列表保留名称但战斗中无效（_find_skill_definition 返回 None 静默跳过），不崩溃；spirit_001 旧记录自动对应新版万剑归宗
- 修 `_build_heart` exp_multiplier bug + 修正 config/heart_methods.json 已污染 10 处
- 改 skills.csv / heart_methods.csv：万剑归宗 id/name、trigger_condition→trigger_timing 列名、legacy→draft 四行（基础吐纳/铁布衫/雷击诀/长春功）、天魔解体 2.1→1.8
- sync 脚本改为 reconcile 模式（导入 draft/final 后删除表外条目，dry-run 展示删除清单），扩展支持 skills.csv
- 实现功法 route_multiplier 消费（get_battle_loadout 按路线乘增益）
- 实现心法 route 装备校验
- 天魔解体降 value 至 1.8（config + CSV 同步）
- 回归验证：validate_budget 全 PASS、sim_balance_regression 数值回退对比、全量测试（含依赖旧条目断言的修正）
- **未来项（本变更不做，bd 跟踪）**：平衡完成后将最终配置固化进 data/default_configs.py，供未来使用者开箱即用。本变更期间的 default_configs 保持旧值（已知不一致：删 config 重开会回退旧数值，属平衡中临时态）

**记录假设**（用户可推翻）：① 天魔解体选降值而非实现疲劳副作用（副作用需新 EFFECT_HANDLER + 状态系统，scope 大，KISS）；② 新功法获取途径 = 突破通用池 + 修习目标秘籍 + 心法配套池；为验证领悟池机制，部分心法（12/18）已挂载配套功法（覆盖四类池与系数梯度），挂载明细随平衡迭代调整；③ 旧玩家技能数值按 CSV 0.x 覆盖（设计注记已声明）且删除条目无补偿（用户指示：旧 config 设计内容不关心）；④ 长春功作为新手默认心法保留（legacy→draft）；⑤ default_configs 固化留待平衡完成后（bd 跟踪）。

## Capabilities

### New Capabilities

（无——本变更全部落在既有 spec 的能力范围内；心法路线校验并入 skill-system 既有「路线装备池」Requirement）

### Modified Capabilities

- `content-sync-pipeline`: 同步契约修正（exp_multiplier 0.0 保留）与范围扩展（skills.csv 启用、同名覆盖时 id 保留对齐、effect_value 0.x 数值契约）。
- `skill-system`: 功法技能路线倍率消费机制、心法路线装备匹配校验、大招数值预算约束。

## Impact

- **脚本**：`scripts/sync_content_to_config.py`（_build_heart 修复、_build_skill 新增、merge→reconcile 全量重导）
- **配置（重导后规模）**：`config/weapons.json` 121→9、`config/heart_methods.json` 22→18（含 10 处 exp_multiplier 1.0→0.0）、`config/skills.json` 6→20（0.x 契约）
- **设计表**：`design_docs/content-design/skills.csv`（万剑归宗 id/name、列名、legacy→draft 三行、天魔解体）、`heart_methods.csv`（长春功 legacy→draft）、`weapons.csv`（无改动）
- **引擎**：`core/skill_manager.py`（get_battle_loadout 路线倍率）、`handlers/equipment_handler.py`（心法 route 校验）、`core/cultivation_manager.py`（无改动预期，消费点已存在）
- **测试**：新增 sync 修复/路线倍率/route 校验用例；**审计并修正依赖旧 config 条目的存量断言**（如 spirit_001 语义变化）；回归 sim_balance_regression.py
- **玩家影响**：已学技能强度变化（基础吐纳 ×2.2→×1.2 等）；10 件心法双倍修为消失（bug 修复）；删除条目（御剑术/撼山劲/焚天诀等）已装备者战斗中无效但无崩溃；spirit_001 旧记录迁移为万剑归宗
- **未来项**：平衡后固化 default_configs（bd 跟踪，本变更不做）
