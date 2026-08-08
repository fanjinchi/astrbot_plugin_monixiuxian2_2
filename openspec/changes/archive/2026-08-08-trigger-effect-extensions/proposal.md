## Why

技能池 v1（20 行，2026-08-08 落地）只实现了 5 种触发技效果（damage_bonus / combo / stun / counter / damage_reduction），设计文档 content-design/skills-ultimates.md §2.2/§6 标记的 needs_code 效果（治疗/吸血、持续 BUFF/DEBUFF、DOT、必中/不可反击、真伤/破甲、免死、反弹、副作用/疲劳）全部未实现，导致设计表无法表达续航、持续压制、高境界防拖等玩法（bd `tt3` 归口）。实现这些效果后，设计侧可释放对应技能入池，并为后续数值配平（bd `dhh`）提供引擎基础。

## What Changes

- **扩展战斗引擎效果分发**（managers/combat_manager.py EFFECT_HANDLERS）：新增 effect_type——
  - `heal`：治疗/吸血（吸血＝造成伤害的百分比回复，攻击方视角；治疗＝按最大气血百分比回复）
  - `dot`：持续伤害（每回合结算、可叠加、设叠加上限）
  - `buff` / `debuff`：持续增益/减益（攻防速等属性修正，回合数限制，同名刷新/叠加规则）
  - `pierce`：真伤/破甲（无视护甲减伤，或按比例穿透）
  - `unavoidable`：必中/不可反击标记（dodge/格挡/counter 豁免）
  - `survive`：免死（致命一击时保留 1 点气血并触发护盾/回复，每场限次）
  - `reflect`：反弹（受到伤害时按比例反伤）
  - `fatigue`：副作用/疲劳（增益换取后续减益，如天魔解体方案）
- **持续状态机制**（新能力 battle-status-effects）：回合数、叠加规则、到期清除、状态展示；DOT/BUFF/DEBUFF/疲劳共用该结构
- **大招分支效果分发**：ultimate 目前仅支持伤害放大，扩展为非伤害大招（治疗/免死/控制）与复合大招走同一分发
- **round_start 自我增益限制调整**：目前仅放行 damage_bonus/combo，扩展 buff 类自我增益
- **技能契约扩展**（skill-system）：effect_type 词表扩展、新效果字段（duration / tick_rate / heal_percent / pierce_rate / reflect_rate / survive_count 等）、0.x 加性语义延续
- **同步与校验**：scripts/sync_content_to_config.py 词表与契约校验同步扩展；design_docs/content-design/validate_budget.py 新效果预算口径
- **设计表释放**：skills-ultimates.md §2.2/§6 状态翻转（needs_code → 可入池），按优先级补少量验证技能（治疗/吸血、DOT、免死大招等）入 CSV，数值配平留待 bd `dhh` 功法池重做
- 关闭 bd `tt3`（本 change 落地后），反弹单独排期并入

**范围说明（规划假设）**：一次性实现全部 9 种效果并按优先级分批落地（heal/dot/buff/debuff 优先，pierce/unavoidable/survive/reflect 次之，fatigue 随天魔解体方案）；本 change 只补验证用技能，不重做功法池数值（dhh）。

## Capabilities

### New Capabilities
- `battle-status-effects`: 战斗持续状态机制——回合数、叠加/刷新规则、到期清除与状态展示，供 DOT/BUFF/DEBUFF/疲劳效果共用

### Modified Capabilities
- `combat-core`: 触发效果分发注册表扩展（新 effect_type 语义与结算）、round_start 自我增益放行范围、ultimate 非伤害分发
- `skill-system`: 触发技/大招契约扩展——effect_type 词表、新效果字段、0.x 加性语义延续

## Impact

- managers/combat_manager.py：EFFECT_HANDLERS 注册表、回合结算循环（持续状态 tick）、dodge/格挡/counter 判定（unavoidable）、致命结算（survive）、反伤挂接
- core/skill_manager.py：get_battle_loadout 归一化（新字段透传）、路线倍率对新效果字段的适用（rate/value 语义）
- scripts/sync_content_to_config.py：SKILL_EFFECT_TYPES 词表、_build_skill 新字段映射与校验
- design_docs/content-design/：skills-ultimates.md §2.2/§6、schema-and-engine-fit.md（P3 勾选）、validate_budget.py 预算口径
- config/skills.json：新增验证技能条目（有限）
- bd：关闭 `tt3`；反弹评估随本 change 决策
