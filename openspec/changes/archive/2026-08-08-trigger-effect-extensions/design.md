# Design: trigger-effect-extensions

## Context

技能池 v1 已落地（commit 68e6f12 / 47d9089），但效果引擎只支持 5 种 effect_type。本 change 扩展 EFFECT_HANDLERS 注册表、引入战斗持续状态、扩展大招分发与同步校验。动机见 proposal.md - Why，行为契约见 specs/（battle-status-effects、combat-core、skill-system delta）。

关键现状（已核实）：
- 统一战斗引擎为 `CombatEngine`（managers/combat_manager.py:116）；`CombatManager`（:749）为 legacy 适配器，PVE/PVP 均经 `engine.resolve_combat`（:831/:856），**效果分发只需改 CombatEngine 一处**
- EFFECT_HANDLERS 注册表（managers/combat_manager.py:415-420）：damage_bonus/combo/stun/counter/damage_reduction；handler 签名 `handler(fighter, target, skill, state) -> float`（返回伤害增量）
- round_start 结算（:450-477）仅放行 damage_bonus/combo，其余 warning 跳过
- 大招当前为伤害放大语义：攻击判定 `total_skill_mult = skill_mult * ultimate_mult * next_attack_mult`（:621）
- 归一化层 core/skill_manager.py:331-377 注入 trigger_timing；`get_battle_loadout` 应用路线倍率（min(1.0, rate×mult) / ult value×mult）
- sync 脚本 SKILL_EFFECT_TYPES 词表（scripts/sync_content_to_config.py:60）；validate_budget.py 0.x 期望校验

## Goals / Non-Goals

Goals:
- 8 类新效果（heal/dot/buff/debuff/pierce/unavoidable/survive/reflect/fatigue）可配置、可结算、可校验
- 持续状态机制作为共享底层（dot/buff/debuff/fatigue 共用）
- 大招支持非伤害效果（经同一注册表分发）
- 契约与同步链路（归一化层 → sync 词表/字段校验 → validate_budget）同步扩展

Non-Goals:
- 不重做功法池数值配平（bd dhh）——本 change 只补少量验证技能
- 不做秒杀效果（设计已排除，以斩杀大招替代）
- 不实现需要跨战斗持久化的状态（spec 明确状态战斗内有效）
- 不扩展继承/传承相关效果

## Decisions

- **D1 持续状态挂载在 FighterState**：新增 `status_effects: list[StatusEffect]`（dataclass：source_name/kind/effect_value/tick_rate/duration/remaining/params），挂在战斗实例状态上，战斗结束随 FighterState 弃用自然清除，零持久化改动。
  备选：独立 StatusManager 服务——过度设计；状态生命周期与战斗强绑定。
- **D2 状态 tick 挂回合开始**：在回合循环开始处（round_start 触发技结算之后）统一 tick 所有 status_effects（dot 扣血、buff/debuff 保持、duration-1、到期移除）。dot 伤害按 `max(1, 触发当次伤害 × effect_value × tick_rate)`（tick_rate 缺省 1.0）；触发当次伤害在触发时快照传入状态。
  备选：回合结束 tick——dot 与 round_start 结算顺序会引入歧义；回合开始结算使 DOT 至少跳一次伤害。
- **D3 保持单注册表 + handler 副作用**：EFFECT_HANDLERS 扩展为 13 键，handler 除返回 float 外可写 `fighter.status_effects`（持续类）或修改 `fighter.hp`（heal/吸血）、设置一次性标记（unavoidable）。不改 handler 签名——`state` dict 已可承载。
  备选：handler 返回结构化结果再统一应用——侵入现有调用点（:463/:474 与 ultimate 路径），收益低。
- **D4 一次性攻击标记放 `next_attack_*` 前缀字段**：`unavoidable` 在触发时置 `fighter.next_attack_unavoidable = True`，判定链闪避/格挡/反击检查前消费并复位（与 `next_attack_mult` 生命周期一致）。
- **D5 survive 挂胜负判定**：气血≤0 结算处（resolve_combat 内胜负判断）先查 `survive_charges > 0`：置 hp=1、charges-1、按 `survive_recovery`（缺省 0）回复、战报记录；否则正常判负。PVE/PVP 共用（CombatEngine 单点）。
- **D6 reflect 挂受击伤害结算后**：实际伤害确定后按 `reflect_rate × 实际伤害` 反伤攻击方（不吃防守方护甲，走固定伤害通道）；反伤致死同样触发对方 survive 判定（天然闭环）。
- **D7 buff/debuff 修正作用于结算输入**：状态修正实现为乘性系数作用于 FighterState 的 damage/armor/speed 读取点（伤害公式与出手权），不修改 FighterState 基础字段——与"状态不落库"（spec）天然一致；同名同源刷新、异源叠加 cap=3（config `status_stack_cap`，game_config.json）。
- **D8 fatigue 为 debuff 特例**：不新增结算分支，作为 kind=fatigue 的 debuff 由持续状态机制承载；设计侧用于"增益换减益"（如天魔解体：大招触发后给自身挂 3 回合疲劳）。
- **D9 大招统一走注册表**：大招触发（门槛判定+限次通过后）由内联 `ultimate_mult` 伤害放大改为按 `effect_type` 分发（伤害类走现路径，非伤害类走 handler）；`effect_value` 语义与触发技一致（0.x 加性）。向后兼容：无 effect_type 的旧大招配置按 damage_bonus 处理（归一化层默认注入）。
- **D10 归一化层透传 + 契约校验收口 sync**：skill_manager 归一化层对新可选键（duration/tick_rate/heal_percent/pierce_rate/reflect_rate/survive_count）原样透传并默认注入 effect_type（缺省 damage_bonus）；契约校验（值域/类型/词表）集中在 `_build_skill`/`_validate_ultimate`，归一化层不重复校验。
- **D11 validate_budget 折算口径**：新效果按「伤害当量」折算进预算——heal: value×max_hp 折算为当量伤害（1 治疗 ≈ 1 伤害）；dot: value×duration（叠加 cap 内）；pierce: value×(1+破甲收益系数 0.5)；buff/debuff/reflect/survive/unavoidable：初期按 value 折算并记 WARN（效果难量化，待 dhh 实测校准）；fatigue 不计入（代价项）。

## Risks / Trade-offs

- [legacy 双轨残留] CombatManager 适配层若存在未走 engine 的旧结算路径，新效果在旧路径不生效 → 已核实 :831/:856 均走 engine；实现时跑全量测试 + 新增效果测试覆盖 PVP/PVE 双入口
- [dot 快照伤害失真] dot 数值依赖"触发当次伤害"，若触发时攻击被闪避则伤害为 0 → 定义：触发技在伤害计算前判定，快照取触发后本次攻击的预期伤害（含 skill_mult，取判定通过后的伤害值）；闪避场景下取 0 并记录
- [持续状态叠加失控] 多来源 buff 乘性叠加导致数值爆炸 → 叠加上限 cap=3 + 预算折算 + 验证技能克制数量
- [reflect 反伤死循环] 双反伤互弹 → 反伤通道标记不触发反伤（reflect 不反射 reflect），回合内反伤次数上限 1
- [大招语义变更破坏存量] 旧大招配置无 effect_type → D9 向后兼容默认注入 damage_bonus，存量 config 行为不变（360 存量测试守护）
- [sync 词表扩展误放行] 词表扩到 13 后，未实现效果被误入 CSV → 词表与 EFFECT_HANDLERS 键严格同源（共享常量或测试断言一致），validate_budget 对未实现效果记 FAIL 而非 WARN

## Migration Plan

1. 引擎层（CombatEngine）：FighterState 扩展 + 状态 tick + 注册表扩展 + survive/unavoidable/reflect 挂点 + 大招分发——行为默认不变（新效果不配置即不触发）
2. 契约层：归一化层透传 + 默认注入；sync 词表/字段校验扩展（与引擎同源）
3. 校验与测试：validate_budget 折算口径 + 新效果单元/集成测试（每效果至少 2 场景）
4. 设计表：skills-ultimates.md §2.2/§6 状态翻转 + 少量验证技能入 CSV + sync 落盘
5. 回滚：配置回滚即可（新效果不在 config 即无行为变化）；代码回滚为纯引擎/校验层，无数据迁移

## Open Questions

- 反伤与吸血同时存在时的结算顺序（先吸血后反伤还是反之）——影响数值但不影响契约，实现时按"伤害确定→吸血→反伤"固定顺序并记录即可
- 持续状态在战报中的展示密度（每 tick 一条 vs 合并）——沿用战报合并机制（merge_count），无需本 change 决策
