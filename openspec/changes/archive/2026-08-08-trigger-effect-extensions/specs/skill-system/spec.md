## MODIFIED Requirements

### Requirement: 随机触发技能结算

随机触发技能 SHALL 在战斗判定链的触发技环节按各自触发时机（攻击时/受击时/暴击时/回合开始等）与触发概率自动判定；触发概率 MUST 为 config 可调。触发技配置（功法 `trigger_skill` 与武器 `trigger_skills`）MUST 统一使用引擎契约键名 `trigger_timing` / `effect_type` / `trigger_rate` / `effect_value`；系统 MUST NOT 维护第二套同义键名（如 `effect`），功法归一化层 SHALL 负责将 `trigger_condition` 映射为 `trigger_timing`，其余契约键 MUST 由配置原样提供。

`effect_type` 词表 SHALL 覆盖：`damage_bonus`、`combo`、`stun`、`counter`、`damage_reduction`、`heal`、`dot`、`buff`、`debuff`、`pierce`、`unavoidable`、`survive`、`reflect`、`fatigue`。数值语义 SHALL 延续 0.x 加性契约：`effect_value = x` 表示当次结算 ×(1+x)（如 heal 0.25 = 回复最大气血的 25%；dot 0.1 = 每回合造成当次伤害 10% 的持续伤害）。持续类与保命类效果的附加参数 SHALL 为可选契约键：`duration`（持续回合数，缺省 1）、`tick_rate`（dot 每回合伤害系数，缺省取 effect_value）、`heal_percent`（heal 回复比例，缺省取 effect_value）、`pierce_rate`（破甲穿透比例，0-1）、`reflect_rate`（反弹比例）、`survive_count`（免死次数，缺省 1）；可选键 MUST 经契约校验（类型与值域）后方可入库，非法值 SHALL 报错中止。

#### Scenario: 受击触发反击

- **WHEN** 防守方装备的武器带有「受击时 30% 概率反击」触发技且本次判定成功
- **THEN** 防守方立即对攻击方执行一次反击攻击，战报记录触发事件

#### Scenario: 功法与武器挂载共用键名契约

- **WHEN** 功法 trigger_skill 与武器 trigger_skills 中出现相同 `effect_type`
- **THEN** 两者按同一契约键名解析并获得一致的结算行为

#### Scenario: 治疗触发技

- **WHEN** 功法触发技 effect_type=heal、effect_value=0.25 且触发成功
- **THEN** 装备者回复最大气血 25%，战报记录治疗量，不产生伤害

#### Scenario: 可选键非法值拒绝入库

- **WHEN** 设计表技能行声明 `pierce_rate` 为 1.5（超出 0-1 值域）或 `duration` 为负数
- **THEN** 同步脚本报错中止且不写盘

### Requirement: 大招限次

每本功法的大招 SHALL 每场战斗最多触发一次；装备多本功法时各功法的大招 MUST 相互独立判定。大招 SHALL 采用必放制：归一化层 SHALL 为未显式声明触发概率的大招按 `trigger_rate = 1.0` 处理，设计配置 MUST NOT 要求填写概率字段。大招触发 MUST 先通过解锁门槛判定：「自身已行动数 ≥ `min_action_index`」且满足全部已声明的可选血量条件（`trigger_self_hp_below`：自身 HP% ≤ 阈值；`trigger_opponent_hp_below`：敌方 HP% ≤ 阈值）后方可触发；未达门槛时大招 MUST 保留至后续行动，不消耗其限次资格。门槛参数 MUST 为 config 可调，以支持斩杀型（敌方低血量）、逆袭型（自身低血量）、延迟型（纯行动数）等时机风格。大招效果 SHALL 支持全部词表 effect_type：伤害放大（现语义）、治疗、免死、控制、反弹等非伤害大招 MUST 与触发技共用效果处理器（见 combat-core 触发效果分发契约），effect_value 语义与可选契约键规则与触发技一致。

#### Scenario: 大招单场限一次

- **WHEN** 玩家装备功法的【大招】在一场战斗中已触发过一次
- **THEN** 本场战斗该大招不再触发，但玩家装备的其他功法的大招仍可触发

#### Scenario: 未达门槛不触发

- **WHEN** 攻击方已行动数小于 `min_action_index` 或血量条件未满足
- **THEN** 本次行动不触发该大招，大招保留至后续行动

#### Scenario: 斩杀型大招在敌方残血时必放

- **WHEN** 大招配置 `trigger_opponent_hp_below = 0.4` 且敌方 HP 降至 40% 以下且行动数门槛已满足
- **THEN** 攻击方下一次攻击行动必触发该大招

#### Scenario: 免死大招

- **WHEN** 大招配置为 effect_type=survive（免死）且解锁门槛满足
- **THEN** 大招触发后为装备者附加免死状态（限次按 survive_count），本场战斗不再重复触发该大招
