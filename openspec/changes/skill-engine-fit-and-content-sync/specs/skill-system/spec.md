# skill-system delta — skill-engine-fit-and-content-sync

## MODIFIED Requirements

### Requirement: 随机触发技能结算

随机触发技能 SHALL 在战斗判定链的触发技环节按各自触发时机（攻击时/受击时/暴击时/回合开始等）与触发概率自动判定；触发效果类型 SHALL 覆盖伤害追加、连击、反击、控制、增益/减益等。触发概率 MUST 为 config 可调。触发技配置（功法 `trigger_skill` 与武器 `trigger_skills`）MUST 统一使用引擎契约键名 `trigger_timing` / `effect_type` / `trigger_rate` / `effect_value`；系统 MUST NOT 维护第二套同义键名（如 `effect`），功法归一化层 SHALL 负责将 `trigger_condition` 映射为 `trigger_timing`，其余契约键 MUST 由配置原样提供。

#### Scenario: 受击触发反击

- **WHEN** 防守方装备的武器带有「受击时 30% 概率反击」触发技且本次判定成功
- **THEN** 防守方立即对攻击方执行一次反击攻击，战报记录触发事件

#### Scenario: 功法与武器挂载共用键名契约

- **WHEN** 功法 trigger_skill 与武器 trigger_skills 中出现相同 `effect_type`
- **THEN** 两者按同一契约键名解析并获得一致的结算行为

### Requirement: 大招限次

每本功法的大招 SHALL 每场战斗最多触发一次；装备多本功法时各功法的大招 MUST 相互独立判定。大招 SHALL 采用必放制：归一化层 SHALL 为未显式声明触发概率的大招按 `trigger_rate = 1.0` 处理，设计配置 MUST NOT 要求填写概率字段。大招触发 MUST 先通过解锁门槛判定：「自身已行动数 ≥ `min_action_index`」且满足全部已声明的可选血量条件（`trigger_self_hp_below`：自身 HP% ≤ 阈值；`trigger_opponent_hp_below`：敌方 HP% ≤ 阈值）后方可触发；未达门槛时大招 MUST 保留至后续行动，不消耗其限次资格。门槛参数 MUST 为 config 可调，以支持斩杀型（敌方低血量）、逆袭型（自身低血量）、延迟型（纯行动数）等时机风格。

#### Scenario: 大招单场限一次

- **WHEN** 玩家装备功法的【大招】在一场战斗中已触发过一次
- **THEN** 本场战斗该大招不再触发，但玩家装备的其他功法的大招仍可触发

#### Scenario: 未达门槛不触发

- **WHEN** 攻击方已行动数小于 `min_action_index` 或血量条件未满足
- **THEN** 本次行动不触发该大招，大招保留至后续行动

#### Scenario: 斩杀型大招在敌方残血时必放

- **WHEN** 大招配置 `trigger_opponent_hp_below = 0.4` 且敌方 HP 降至 40% 以下且行动数门槛已满足
- **THEN** 攻击方下一次攻击行动必触发该大招

### Requirement: 功法槽位与升星

玩家 SHALL 最多同时装备 4 本功法（与 game_config.max_technique_slots 一致）。重复获得同名功法时 SHALL 自动升星强化（提升触发概率/效果数值），而非占用新槽位。星级 SHALL 以 3 星为上限；升星加成 SHALL 按乘法计算：触发概率与效果数值均按 `(1 + 升星系数)^(星级 - 1)` 缩放，升星系数 SHALL 为单一 config 值（实验初值 0.10），触发概率缩放结果 MUST 截断至 1.0。已满星时再次获得同名功法 SHALL 不再升星，系统 SHALL 按比例折算修为给予补偿（修为基数与折算比例 MUST 为 config 可调）。

#### Scenario: 重复功法自动升星

- **WHEN** 玩家获得一本已拥有且已装备的同名功法（未满 3 星）
- **THEN** 该功法星级 +1，其触发概率/效果按乘法升星系数提升

#### Scenario: 满星重复参悟折算修为

- **WHEN** 玩家的【御剑术】已达 3 星，再次通过领悟获得【御剑术】
- **THEN** 星级保持 3 星不变，玩家获得按 config 基数与比例折算的修为补偿

#### Scenario: 乘法升星幅度

- **WHEN** 升星系数为 0.10 且功法升至 3 星
- **THEN** 其触发概率与效果数值为基础值的 1.21 倍（1.1²）
