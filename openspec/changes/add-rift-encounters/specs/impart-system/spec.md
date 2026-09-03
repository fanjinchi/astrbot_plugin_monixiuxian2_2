## MODIFIED Requirements

### Requirement: 传承获取途径

玩家 SHALL 通过以下途径获得传承，挑战「传承之地守护 NPC」（复用战斗引擎）胜利才获得传承：

- 宗门奖励：从宗门宝库领取 `kind=legacy` 条目（详见 sect-system 的宗门传承需求），领取后立即挑战守护 NPC；
- 历练结算概率触发（`adventure_config.json` 的 `legacy_chance`）：命中后 SHALL 挂起一个来源为 `adventure` 的传承之地 pending 遭遇，由玩家在时限内主动应邀挑战（详见 rift-encounter 的传承之地遭遇需求）；
- 秘境结算概率触发（`rift_config.json` 的 `legacy_chance`）：命中后 SHALL 挂起一个来源为 `rift` 的传承之地 pending 遭遇，应邀方式同上。

触发概率 SHALL 由对应模块配置控制，配置为 0 时该途径不触发。应邀挑战 SHALL 复用守护 NPC 战斗：挑战胜利获得对应来源类型的传承实例；挑战失败或平局视同挑战失败——气血不致死（下限 1）、本次机缘消耗、不获得传承；时限内未应邀或遭遇过期 SHALL 视为机缘消散，不获得传承且无任何惩罚。守护 NPC SHALL 由 `enemies.json` 中 `enemy_groups` 列表内的专属守护者组（组 key 由 `IMPART_CONFIG.guardian.enemy_group` 指定，配置驱动）按玩家境界选取模板生成（守护组不带 `level_range`，不经普通 PvE 分组匹配）。`common` 类型仅为旧数据迁移遗留/兑底类型，无新增获取途径。

#### Scenario: 历练触发并获得传承

- **WHEN** 玩家历练或秘境结算命中传承触发概率，挂起传承之地遭遇后在时限内应邀挑战并战胜守护 NPC
- **THEN** 玩家获得一条对应来源类型（`adventure`/`rift`）的传承实例

#### Scenario: 守护挑战失败消耗机会

- **WHEN** 玩家应邀挑战守护 NPC 失败或战成平局
- **THEN** 玩家不获得传承，气血下限为 1，本次机缘消耗；下次结算重新掷概率

#### Scenario: 无视遭遇机缘消散

- **WHEN** 玩家对传承之地 pending 遭遇不做响应直至过期
- **THEN** 机缘消散，玩家不获得传承，无任何惩罚

#### Scenario: 宗门宝库路径立即挑战不变

- **WHEN** 玩家从宗门宝库领取 `kind=legacy` 条目
- **THEN** 系统立即发起守护 NPC 挑战，胜利获得传承，失败本次机会消耗

#### Scenario: 概率关闭不触发

- **WHEN** 玩家历练或秘境结算且对应 `legacy_chance` 配置为 0
- **THEN** 不触发传承事件，玩家不受影响
