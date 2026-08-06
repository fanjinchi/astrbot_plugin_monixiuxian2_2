# combat-core delta — skill-engine-fit-and-content-sync

## MODIFIED Requirements

### Requirement: 统一判定链

每次出手 SHALL 按固定顺序判定：出手权 → 闪避 → 格挡 → 暴击 → 触发技 → 大招 → 伤害结算。闪避率由双方身法差决定且 MUST 设上限（初值 50%，config 可调）；暴击伤害倍率初值 ×1.5（config 可调）。大招环节 MUST 先判定解锁门槛（行动数门槛与可选血量阈值，见 skill-system 的大招规则）：未解锁时 SHALL 跳过该大招且不消耗其每场一次的资格；已解锁的大招 SHALL 按必放制触发（见 skill-system）。

#### Scenario: 闪避优先于伤害结算

- **WHEN** 防守方闪避判定成功
- **THEN** 本次攻击不造成任何伤害，战报记录闪避事件

#### Scenario: 暴击

- **WHEN** 攻击通过闪避与格挡判定且暴击判定成功
- **THEN** 本次伤害乘以暴击倍率后进入护甲减伤结算

#### Scenario: 大招未解锁不触发

- **WHEN** 攻击方的大招未满足解锁门槛（行动数不足或血量条件未达成）
- **THEN** 本次行动跳过该大招的伤害加成，大招保留至后续行动

## ADDED Requirements

### Requirement: 触发效果分发契约

战斗引擎 SHALL 通过效果注册表按 `effect_type` 分发触发技效果，功法触发技与武器挂载技 MUST 共用同一分发入口。遇到注册表外的 `effect_type` 时，系统 MUST 记录 warning 日志并跳过该效果，MUST NOT 静默忽略，MUST NOT 中断战斗。

#### Scenario: 未知效果告警

- **WHEN** 结算中遇到注册表外的 effect_type
- **THEN** 系统记录 warning 日志、该效果不生效、战斗正常继续

#### Scenario: 功法与挂载共用分发入口

- **WHEN** 同一 effect_type 分别出现在功法触发技与武器挂载技上
- **THEN** 两者经同一注册表处理器结算，结算语义一致
