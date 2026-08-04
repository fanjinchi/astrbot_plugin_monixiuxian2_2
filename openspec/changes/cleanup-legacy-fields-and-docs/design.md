# Design: cleanup-legacy-fields-and-docs

## Context

战斗系统已迁移到 CombatEngine 四主属性框架（damage/agility/speed/hp + Muxxu 公式 + 减法护甲），`attribute-numerics` spec 的"旧数据废弃"需求明确旧五维与旧装备词条应被废弃。但实际审计发现四类遗留/问题：

1. **装备遗留字段仍生效**：`config/weapons.json` 是唯一仍含遗留五维键的配置（全部 120 个词条，且词条均无显式 `damage` 键）。`core/equipment_manager.py:104-111`、`managers/combat_manager.py:310-318`、`core/shop_manager.py:554-561` 三处存在相同的五维回退映射（`damage = max(damage, physical_damage + magic_damage)`）。该回退**当前实际决定武器数值**——例如青铜剑解析出 `damage=15`（10+5 遗留求和），而非新字段语义。武器级 `mental_power` 键无任何代码读取（死数据）。
2. **PvE 死代码**：`managers/pve_combat_manager.py` 的 `calculate_equipment_atk_bonus`/`calculate_equipment_defense`（标注"旧接口，保留兼容"）生产代码零引用，仅被 `tests/test_pve_combat.py` 自测。
3. **level_up_rate 死字段**：`models.py:110` 定义、`handlers/player_handler.py:180` 显示"突破成功率+X%"，但全库无写入点，`core/breakthrough_manager.py:calculate_breakthrough_success_rate` 未消费。成功率流水线为：`base + temp_bonus` → 破境丹 `min(+breakthrough_bonus, max_success_rate)` → 连败保底叠加（cap 100%）。
4. **文档过时**：`design_docs/current-design-report.md` 描述旧五维体系；`design_docs/level-exp-curve/exp-curve-report.md` 把 v3.7.0 已修复的旧失败惩罚/旧双修漏洞当作现存问题分析。

## Goals / Non-Goals

**Goals:**

- 装备数值**零变化**前提下，从 weapons.json 与三处解析代码中移除五维遗留字段/回退。
- 删除 PvE 死代码函数及其测试。
- `level_up_rate` 接入突破成功率计算（永久加成源），显示语义真实化。
- 两份文档与当前代码现实一致。

**Non-Goals:**

- 装备数值重新平衡（归属 bd-9u2 / 装备重做线，本变更严格保持现状数值）。
- 丹药效果键系统（`physical_damage_multiplier`、`physical_damage_gain`、`add_mental_power` 等）改名——这些是生效中的 buff 效果键，与装备遗留字段无关。
- `equip_effects`（items.json 法器 attack/defense）映射保留，它仍是法器的生效路径。
- 数据库 schema 变更（`level_up_rate` 列已存在；players 表旧五维列清理不在本次范围）。
- weapons.json L36-L99 档位缺口（bd-wxg，用户明确暂缓）。

## Decisions

### D1：固化迁移（bake resolved values），而非删字段了事或借机重平衡

用一次性脚本对每个 weapons.json 词条计算 `damage = max(现有 damage, physical_damage + magic_damage)`、`armor_value = max(现有 armor_value, physical_defense + magic_defense)`，写入显式 `damage`/`armor_value` 键，然后删除五个遗留键。随后删除三处代码回退。

- **为什么选它**：回退当前实际生效，直接删字段会把青铜剑等武器的 `damage` 从 15 变为 0，属于数值变更，必须留给装备重做线统一决策；借机重平衡则违背本变更"清理"定位且无法回归验证。
- **备选**：(a) 直接删字段 → 数值漂移，拒绝；(b) 永久保留回退代码 → 违反 `attribute-numerics`"旧数据废弃"需求，拒绝。
- **零变化校验**：迁移前后用同一解析逻辑对全部 120 词条输出 `(damage, armor_value, agility, speed, hp)` 五元组做 diff，必须为空；并跑装备/商店/战斗相关 pytest。

### D2：level_up_rate 加在基础成功率上、破境丹 cap 之前

`final_rate = base + level_up_rate/100 + temp_bonus`，后续破境丹 cap、连败保底逻辑不变。信息行仅在 >0 时输出"永久加成：+X%"。

- **为什么选它**：永久加成语义上是角色基础资质的一部分，与 base 合并最直观；`max_success_rate` 作为破境丹的硬上限语义保持不变。当前所有玩家该值为 0，行为零变化。
- **备选**：(a) 仅从显示移除 → 字段仍死，bug 语义未真正修复，且堵死传承/丹药系统未来的加成挂点；(b) 像连败保底一样在 cap 后叠加 → 与保底机制语义混淆，且绕过丹药上限。均拒绝。
- 字段语义单位：DB 列为 INTEGER，现有显示为 `+X%`，按"百分点整数"处理（5 = +5%）。

### D3：PvE 死代码直接删除

删除 `calculate_equipment_atk_bonus`/`calculate_equipment_defense` 及 `tests/test_pve_combat.py` 中对应测试类/引用。

- **备选**：保留"兼容" → 无调用方的兼容是负担，且其统计口径（atk + 五维）与新框架矛盾，留存在 D1 删除遗留字段后会变成隐性地雷。

### D4：文档一重写一标注

- `current-design-report.md`：**重写**，内容以当前代码为准（CombatEngine 四属性、Muxxu 公式、减法护甲、99 级十境界、新 Player 模型）。
- `exp-curve-report.md`：**仅加历史标注**（"历史背景：以下问题已在 v3.7.0 修复"），不重写——它是有调研脉络的历史分析文档，重写会丢失演化上下文。

### D5：丹药效果键不动

`physical_damage_multiplier`/`_gain`、`add_mental_power` 等是 pills/utility_pills 的生效效果键，被 `pill_manager.py`、商店显示、战斗 buff 消费。改名无行为收益、波及面大，记录为明确排除项。

## Risks / Trade-offs

- [固化脚本算错数值导致装备暗改] → 迁移脚本输出前后五元组 diff 报告，diff 非空则中止；pytest 装备/战斗用例全绿才提交。
- [删除回退后存在未发现的遗留键依赖方] → 已全量扫描 19 个 config JSON，仅 weapons.json 含遗留键；enemies.json/boss_config.json/heart_methods.json 均干净。提交前再跑一次 `rg` 断言。
- [combat_manager 的回退服务 Boss/敌人装备路径] → 敌人数值由 `attribute-numerics` PvE 基准生成，不读 weapons.json 遗留键；删除后跑 `tests/test_pve_combat.py` 与战斗测试验证。
- [level_up_rate 接入后未来产出途径失衡] → 当前无产出途径、恒为 0；未来系统接入时受丹药 cap 约束，且有 spec scenario 约束语义。
- [文档重写引入新的事实错误] → 重写内容逐条对照 `managers/combat_manager.py`、`models.py`、`config/level_config.json` 现状，评审时核对。

## Migration Plan

1. 运行固化脚本更新 `config/weapons.json`（生成 diff 校验报告，五元组 diff 为空才写入）。
2. 删除三处回退代码与 PvE 死代码，接入 `level_up_rate`，修正显示。
3. 重写/标注两份文档，更新 README 更新日志与 `metadata.yaml` 版本。
4. 质量门：`uv run ruff format . && uv run ruff check .`、`timeout 120 uv run python -m pytest tests/ -q`。
5. 回滚：纯代码/配置变更，`git revert` 即可；无数据库迁移。

## Open Questions

（无重大悬而未决项。`level_up_rate` 未来的产出途径由 bd-cqt（突破保命道具）/传承系统决策，不在本变更。）
