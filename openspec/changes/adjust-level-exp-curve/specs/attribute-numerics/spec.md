# attribute-numerics Specification (delta for adjust-level-exp-curve)

## REMOVED Requirements

### Requirement: 属性来源：境界基础 + 随机成长

**Reason**: level_config 不再逐級提供 `base_damage/base_agility/base_speed/base_hp`，「境界基础值」失去配置来源；升级属性已全部改为突破随机成长，初始属性在创角时随机生成。

**Migration**: 玩家属性来源改为「初始属性 + 突破随机成长」，由「属性来源：初始属性 + 随机成长」需求替代；依赖 `base_*` 的 Boss/PvE 属性生成随功能开关关闭，待 PvE 重做时按新的数值基准实现。

## ADDED Requirements

### Requirement: 属性来源：初始属性 + 随机成长

主属性 SHALL 由创角初始值与突破随机成长累加构成，MUST NOT 从修为（exp）直接派生战斗属性，MUST NOT 从境界配置读取逐級基础属性。随机成长 SHALL 采用 Q宠模式：突破成功时随机一项主属性 +N（N 为 config 可调）；属性奖励仅在突破成功时发放，突破失败无属性奖励。

#### Scenario: 创角获得初始属性

- **WHEN** 新玩家创建角色
- **THEN** 伤害/身法/迅捷/气血按创角随机区间生成，不读取任何境界配置的基础值

#### Scenario: 突破成功获得随机属性

- **WHEN** 玩家突破成功
- **THEN** 系统在伤害/身法/迅捷/气血中随机一项为其增加 N 点，并累计到玩家属性上

#### Scenario: 突破失败无属性奖励

- **WHEN** 玩家突破失败
- **THEN** 主属性不发生任何变化（修为惩罚与功法领悟判定按各自规则独立进行）

## MODIFIED Requirements

### Requirement: PvE 数值生成基准

历练/秘境敌人与世界 Boss 的属性 SHALL 基于新四主属性框架生成；MUST NOT 使用旧的「敌人 exp 派生 hp/atk」公式，MUST NOT 读取 level_config 的逐級 `base_*` 字段（该字段已移除）。在 Boss/PvE 功能开关关闭期间，系统 SHALL NOT 生成任何敌人或 Boss 属性；强度锚定的境界基准区间 SHALL 在 Boss/PvE 模块重做时以独立于 level_config 的基准表落地。

#### Scenario: 开关关闭期间不生成 PvE 属性

- **WHEN** boss.enabled 或 pve.enabled 为 false
- **THEN** 系统不生成世界 Boss 或秘境敌人属性，对应玩法入口不可用

#### Scenario: 敌人强度与境界匹配（重做后）

- **WHEN** Boss/PvE 重做后为筑基期玩家生成历练敌人
- **THEN** 敌人的伤害/身法/迅捷/气血按筑基境界基准区间乘以难度系数生成，且基准区间不来自 level_config

### Requirement: 数值配置化

本框架涉及的全部数值参数 SHALL 写入 `config/*.json` 可调，包括但不限于：领悟概率、领悟概率系数、随机成长步长 N、判定链概率上限、行动次数上限、战报默认合并条数、武器系数 K、难度系数。修炼升级曲线 SHALL 由公式生成（见 level-progression 的经验曲线公式化需求），其全部公式参数 MUST 走 config 可调。

#### Scenario: 调整概率无需改代码

- **WHEN** 运营将 config 中突破成功领悟概率从 0.20 改为 0.30 并重启
- **THEN** 突破成功时按 30% 判定领悟，无需修改任何代码

#### Scenario: 调整曲线参数无需改代码

- **WHEN** 运营将 config 中经验曲线参数 early_a 从 1800 改为 2400 并重启
- **THEN** 各等级升级所需修为按新参数公式重新计算，无需修改任何代码
