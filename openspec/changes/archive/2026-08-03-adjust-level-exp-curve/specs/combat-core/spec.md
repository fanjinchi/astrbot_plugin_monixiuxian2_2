# combat-core Specification (delta for adjust-level-exp-curve)

## ADDED Requirements

### Requirement: Boss 与 PvE 功能开关

系统 SHALL 提供两个独立的功能开关（config 静态配置，重启生效）：`boss.enabled` 控制世界 Boss 玩法（定时生成任务与 Boss 相关指令），`pve.enabled` 控制秘境等 PvE 战斗玩法。开关关闭时对应玩法入口 SHALL 不可用并提示玩家；历练（不依赖境界基础属性的纯收益玩法）SHALL 不受开关影响。战斗引擎本身 SHALL 不受开关影响，切磋/决斗/传承 PK 保持可用。

#### Scenario: Boss 开关关闭

- **WHEN** boss.enabled 为 false 且玩家发送「世界Boss」或「挑战Boss」指令
- **THEN** 系统回复玩法维护中的提示，且 Boss 定时生成任务未在运行

#### Scenario: PvE 开关关闭

- **WHEN** pve.enabled 为 false 且玩家尝试进入秘境 PvE 战斗
- **THEN** 系统回复玩法维护中的提示，不发生战斗结算

#### Scenario: 开关不影响 PvP 与历练

- **WHEN** boss.enabled 与 pve.enabled 均为 false
- **THEN** 切磋、决斗、传承 PK 与历练玩法仍正常可用
