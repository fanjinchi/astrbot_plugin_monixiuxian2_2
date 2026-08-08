## MODIFIED Requirements

### Requirement: 触发效果分发契约

战斗引擎 SHALL 通过效果注册表按 `effect_type` 分发触发技效果，功法触发技与武器挂载技 MUST 共用同一分发入口。注册表 SHALL 覆盖以下效果族，每族语义如下：

- 伤害类：`damage_bonus`（本次攻击伤害追加）、`combo`（追加攻击，与 damage_bonus 同族结算）、`pierce`（真伤/破甲：无视或按 `pierce_rate` 比例穿透护甲减伤）
- 控制类：`stun`（跳过对方行动）、`counter`（受击反击）、`unavoidable`（必中/不可反击：本次攻击豁免闪避/格挡/反击判定）
- 回复类：`heal`（按最大气血百分比回复；吸血语义＝攻击方按本次伤害百分比回复自身）
- 持续类：`dot`（每回合伤害）、`buff`/`debuff`（攻防速等属性修正）、`fatigue`（副作用减益）——SHALL 经 battle-status-effects 持续状态机制结算
- 保命类：`survive`（免死：受到致命伤害时保留 1 点气血，每场战斗限 `survive_count` 次，配置缺省 1）
- 反伤类：`reflect`（受到伤害时按 `reflect_rate` 比例反伤攻击方）

遇到注册表外的 `effect_type` 时，系统 MUST 记录 warning 日志并跳过该效果，MUST NOT 静默忽略，MUST NOT 中断战斗。回合开始（round_start）时机 SHALL 仅放行自我增益类效果（damage_bonus/combo/buff/debuff），其他类型 MUST 跳过并记录 warning。大招 SHALL 经同一注册表分发：非伤害大招（治疗/免死/控制/反弹）与复合大招 MUST 与触发技共用处理器语义，仅触发途径不同（必放制+门槛，见 skill-system）。

#### Scenario: 未知效果告警

- **WHEN** 结算中遇到注册表外的 effect_type
- **THEN** 系统记录 warning 日志、该效果不生效、战斗正常继续

#### Scenario: 功法与挂载共用分发入口

- **WHEN** 同一 effect_type 分别出现在功法触发技与武器挂载技上
- **THEN** 两者经同一注册表处理器结算，结算语义一致

#### Scenario: 必中豁免闪避格挡

- **WHEN** 攻击方本次攻击带 unavoidable 标记而防守方配置了闪避/格挡/反击
- **THEN** 防守方的闪避、格挡与反击判定均被豁免，本次攻击按正常伤害结算

#### Scenario: 非伤害大招分发

- **WHEN** 大招配置为 heal 型（effect_type=heal）且解锁门槛满足
- **THEN** 大招触发时按 heal 语义结算回复，不产生伤害，战报记录治疗事件

### Requirement: 胜负判定

一方气血 ≤ 0 时战斗 SHALL 立即结束，气血先归零者失败，除非该方存在可用的 `survive` 免死效果：免死触发时 SHALL 将该方气血置 1、消耗一次限次并结算免死附带效果（如按最大气血百分比回复），战斗继续；免死次数耗尽后再次致命伤害 SHALL 正常结束战斗。切磋 MUST NOT 产生实质性惩罚；决斗按现有规则结算（败者气血置 1）。

#### Scenario: 切磋结束

- **WHEN** 切磋中一方气血 ≤ 0
- **THEN** 战斗结束，双方均无实际气血损失与惩罚

#### Scenario: 免死触发保住性命

- **WHEN** 一方受到致命伤害且存在未耗尽的 survive 效果
- **THEN** 该方气血置 1、免死次数减一、战斗继续，战报记录免死触发

#### Scenario: 免死次数耗尽后正常结束

- **WHEN** 一方免死次数已耗尽后又受到致命伤害
- **THEN** 战斗按气血归零正常结束，该方失败
