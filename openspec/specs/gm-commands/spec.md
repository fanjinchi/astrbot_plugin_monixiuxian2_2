# gm-commands Specification

## Purpose

游戏管理员（GM）工具：为授权管理员提供统一的 `修仙GM` 命令入口，支持角色属性修改、装备/物品发放、强制结算触发与审计日志能力，降低运营与测试成本。

## Requirements

### Requirement: GM command entry point

The system SHALL expose a single GM command entry point `修仙GM` that accepts a sub-command and optional arguments.

#### Scenario: GM invokes help

- **WHEN** an authorized user sends `修仙GM帮助`
- **THEN** the system replies with a list of available GM sub-commands and usage examples

#### Scenario: Regular help lists GM help command

- **WHEN** a player sends `修仙帮助`
- **THEN** the help output includes `修仙GM帮助` in the command list, marked as GM-only

#### Scenario: Unauthorized user invokes GM command

- **WHEN** a user who is not in `GM_ADMINS` sends any `修仙GM` sub-command
- **THEN** the system replies with a permission-denied message and performs no action

### Requirement: GM identity and permissions

The system SHALL restrict all `修仙GM` sub-commands to users whose ID is listed in the `GM_ADMINS` configuration.

#### Scenario: Authorized GM executes a command

- **WHEN** a user in `GM_ADMINS` sends a valid `修仙GM` sub-command
- **THEN** the system executes the requested operation

### Requirement: Target player resolution

The system SHALL resolve the target player from the first argument using the following precedence: explicit `@mention`, numeric user ID, or the command sender when omitted.

#### Scenario: Target omitted

- **WHEN** a GM sends `修仙GM 设置灵石 1000` without specifying a target
- **THEN** the system applies the change to the GM themselves

#### Scenario: Target specified by user ID

- **WHEN** a GM sends `修仙GM 设置灵石 123456789 1000`
- **THEN** the system applies the change to the player with user ID `123456789`

#### Scenario: Target specified by mention

- **WHEN** a GM sends `修仙GM 设置灵石 @玩家 1000`
- **THEN** the system applies the change to the mentioned player

#### Scenario: Target player does not exist

- **WHEN** a GM targets a user who has not started the game
- **THEN** the system replies with an error and performs no change

### Requirement: Character attribute modification

The system SHALL provide high-level GM sub-commands to modify character attributes: 设置境界, 设置修为, 设置灵石, 设置气血, 设置真元, 设置攻击, 设置精神力.

#### Scenario: Set realm by name

- **WHEN** a GM sends `修仙GM 设置境界 @玩家 筑基期初期`
- **THEN** the system updates the target player's `level_index` to the index matching the realm name for their cultivation type

#### Scenario: Set numeric attribute

- **WHEN** a GM sends `修仙GM 设置灵石 @玩家 9999`
- **THEN** the system sets the target player's `gold` to `9999`

#### Scenario: Invalid realm name

- **WHEN** a GM sends `修仙GM 设置境界 @玩家 不存在的境界`
- **THEN** the system replies with an error listing valid realm names

### Requirement: Item and equipment distribution

The system SHALL provide GM sub-commands to give items or equipment to a target player. Items SHALL be placed in the player's storage ring, not auto-equipped. Item existence validation SHALL cover every configured item type (items, weapons, pills, heart methods, and any other item tables loaded by the configuration manager), not only the base item and weapon tables.

#### Scenario: Give equipment

- **WHEN** a GM sends `修仙GM 给予装备 @玩家 青锋剑`
- **THEN** the system adds one `青锋剑` to the target player's storage ring

#### Scenario: Give non-equipment item

- **WHEN** a GM sends `修仙GM 给予物品 @玩家 灵草 10`
- **THEN** the system adds ten `灵草` to the target player's storage ring

#### Scenario: Give heart method

- **WHEN** a GM sends `修仙GM 给予物品 @玩家 长春功` where `长春功` is a configured heart method
- **THEN** the system adds one `长春功` to the target player's storage ring

#### Scenario: Give unknown item

- **WHEN** a GM sends `修仙GM 给予装备 @玩家 不存在的物品`
- **THEN** the system replies with an error and performs no change

#### Scenario: Unequip item

- **WHEN** a GM sends `修仙GM 卸下装备 @玩家 武器`
- **THEN** the system removes the target player's equipped weapon and places it in the storage ring

### Requirement: Clear busy cooldown

The system SHALL provide a GM sub-command to clear a player's busy state. Destructive GM sub-commands SHALL require an explicit `确认` argument before taking effect.

#### Scenario: Clear cooldown with confirmation

- **WHEN** a GM sends `修仙GM 清除CD @玩家 确认`
- **THEN** the system sets the target player's `user_cd.type` to `IDLE` and `player.state` to `空闲`

#### Scenario: Clear cooldown without confirmation

- **WHEN** a GM sends `修仙GM 清除CD @玩家` without the `确认` argument
- **THEN** the system replies with a warning asking the GM to append `确认` and performs no change

### Requirement: Clear bounty state

The system SHALL provide a GM sub-command `清除悬赏` that clears a target player's bounty-related state: the active bounty record (removed with abandon semantics, no rewards settled) and the post-abandon re-accept cooldown (the `bounty_abandon_cd_<user_id>` key in `system_config`). The sub-command SHALL follow the existing GM constraints: restricted to authorized `GM_ADMINS` users, requiring the `确认` confirmation convention for destructive operations, and supporting numeric ID target resolution. When the target has neither an active bounty nor a cooldown, the system SHALL reply with a clear notice and produce no side effects.

#### Scenario: Clear active bounty and cooldown

- **WHEN** a GM sends `修仙GM 清除悬赏 <玩家ID> 确认` for a player holding an active bounty and an abandon cooldown
- **THEN** the player's active bounty is removed (no rewards granted) and the abandon cooldown key is cleared, so the player can immediately accept a new bounty

#### Scenario: Nothing to clear

- **WHEN** a GM sends `清除悬赏` for a player with no active bounty and no cooldown
- **THEN** the system replies that the target has no bounty state to clear and the player data is unchanged

### Requirement: Log rotation

The system SHALL rotate the GM audit log file when it reaches 500 MB, creating a new dated log file and preserving the old one.

#### Scenario: Log reaches size threshold

- **WHEN** `gm_operations.log` reaches 500 MB
- **THEN** the system renames the current log to `gm_operations_YYYYMMDD_HHMMSS.log` and starts writing to a new `gm_operations.log`

### Requirement: Force settlement triggers

The system SHALL provide GM sub-commands to immediately finish an ongoing adventure or rift exploration, applying the normal random rewards.

#### Scenario: Force adventure settlement

- **WHEN** a GM sends `修仙GM 触发历练结算 @玩家` and the target is currently adventuring
- **THEN** the system immediately completes the adventure and grants normal rewards

#### Scenario: Force rift settlement

- **WHEN** a GM sends `修仙GM 触发秘境结算 @玩家` and the target is currently exploring a rift
- **THEN** the system immediately completes the rift exploration and grants normal rewards

#### Scenario: Force settlement while not in correct state

- **WHEN** a GM sends `修仙GM 触发历练结算 @玩家` but the target is not adventuring
- **THEN** the system replies with an error and performs no change

### Requirement: System triggers

The system SHALL provide GM sub-commands to trigger system-level events.

#### Scenario: Spawn boss

- **WHEN** a GM sends `修仙GM 生成Boss`
- **THEN** the system spawns a world boss and broadcasts the spawn message

### Requirement: Audit logging

The system SHALL write a single log line to `gm_operations.log` for every GM command invocation, including timestamp, GM user ID, target user ID, sub-command, arguments, and success status.

#### Scenario: Successful GM operation logged

- **WHEN** a GM successfully executes any `修仙GM` sub-command
- **THEN** the system appends a JSON log entry to `gm_operations.log`

#### Scenario: Failed GM operation logged

- **WHEN** a GM executes a `修仙GM` sub-command that fails validation
- **THEN** the system appends a JSON log entry with `success: false` and the error reason

### Requirement: GM 传承测试支持

GM 系统 SHALL 提供传承实例的预置与清除子命令，用于功能测试与数据修复：「给予传承 [目标] [类型]」为指定玩家创建指定类型的传承实例；「清除传承 [目标] [编号]」删除指定玩家全部或指定编号的传承实例。两个子命令 SHALL NOT 修改传承值、修为或战斗属性。

#### Scenario: 给予传承指定类型

- **WHEN** GM 发送「给予传承 900000002 adventure」
- **THEN** 目标玩家获得一条 adventure 类型传承实例（impart_value=0，is_active=0），回复包含实例编号与类型名

#### Scenario: 给予传承默认类型

- **WHEN** GM 发送「给予传承」（省略目标与类型，作用于发送者自身；类型支持 common/sect/adventure/rift 或中文短名如「秘境」）
- **THEN** 目标玩家获得一条 common 类型传承实例

#### Scenario: 类型参数非法

- **WHEN** GM 发送「给予传承 900000002 foo」
- **THEN** 系统拒绝并列出可选类型，不产生数据变更

#### Scenario: 给予宗门传承需目标有宗门

- **WHEN** GM 发送「给予传承 900000002 sect」且目标玩家当前无宗门
- **THEN** 系统拒绝并提示「无宗门，宗门传承需绑定所属宗门」，不产生数据变更

#### Scenario: 给予宗门传承绑定当前宗门

- **WHEN** GM 发送「给予传承 900000002 sect」且目标玩家当前在宗门（sect_id=7）
- **THEN** 创建 sect 类型实例且 `sect_id=7`，回复包含实例编号与类型名

#### Scenario: 清除全部传承

- **WHEN** GM 发送「清除传承 900000002 全部」或「清除传承」（省略编号，作用于发送者自身或 @目标）
- **THEN** 目标玩家的全部传承实例被删除，回复删除数量

#### Scenario: 清除指定编号传承

- **WHEN** GM 发送「清除传承 900000002 3」
- **THEN** 仅编号 3 且属于该玩家的实例被删除，其余保留；编号不存在或不属于该玩家时拒绝且不产生变更

#### Scenario: 清除传承状态

- **WHEN** GM 发送「清除传承状态 900000002」
- **THEN** 该玩家作为挑战者的全部挑战冷却记录被删除，其被夺保护期被删除；传承实例本身不受影响；回复包含移除的冷却条数与保护期条数

#### Scenario: 非 GM 拒绝

- **WHEN** 非 GM_ADMINS 用户发送上述子命令
- **THEN** 系统拒绝且不产生任何数据变更

### Requirement: GM 时间快进

系统 SHALL 提供 GM 子命令「时间快进」，将数据库中明确枚举的未来到期类时间戳统一前移指定秒数，使冷却与长周期玩法的等待立即到期，供功能测试消除真实 sleep 等待。覆盖清单至少包含：`user_cd.scheduled_time`（忙碌状态计划完成时间）、`players.cultivation_start_time`（闭关开始时间）、`combat_cooldowns.last_duel_time/last_spar_time`（决斗/切磋冷却）、`dual_cultivation.last_dual_time`（双修冷却）、`bounty_tasks.expire_time`（进行中悬赏过期时间）、`bank_loans.due_at`（贷款到期时间）、`system_config` 中的 `bounty_abandon_cd_<user_id>`（悬赏放弃冷却）、`boss_next_spawn_time` 与 `spirit_eye_next_spawn_time`（定时任务下次刷新时间）、传承挑战冷却与被夺保护期时间戳。该子命令 SHALL 沿用破坏性操作的「确认」约定，并 SHALL 在回复中列出各域受影响的记录条数。该子命令 SHALL NOT 修改任何冷却/周期的时长配置本身，SHALL NOT 承诺唤醒正处于 `asyncio.sleep` 等待中的定时任务循环（前移 `boss_next_spawn_time` 仅保证该任务下次醒来时立即触发）；正常运行路径在无 GM 调用时行为 MUST 完全不变。

#### Scenario: 快进使历练立即到期

- **WHEN** GM 发送 `修仙GM 时间快进 3600 确认`，且某玩家历练的 `user_cd.scheduled_time` 距今不足 3600 秒
- **THEN** 该玩家的 `scheduled_time` 前移 3600 秒变为已到期，执行「完成历练」可立即正常结算；回复列出各域前移的记录条数

#### Scenario: 快进使闭关结算时长增加

- **WHEN** GM 发送 `修仙GM 时间快进 3600 确认`，且某玩家正在闭关
- **THEN** 该玩家的 `cultivation_start_time` 前移 3600 秒，出关结算按增加后的时长正常计算

#### Scenario: 无确认拒绝执行

- **WHEN** GM 发送 `修仙GM 时间快进 3600` 而未在末尾追加「确认」
- **THEN** 系统回复破坏性操作警告并要求追加「确认」，任何时间戳均不被修改

#### Scenario: 非法秒数拒绝执行

- **WHEN** GM 发送 `修仙GM 时间快进 abc 确认` 或秒数为零/负数
- **THEN** 系统回复参数错误提示，任何时间戳均不被修改

#### Scenario: 定时任务睡眠边界

- **WHEN** GM 执行时间快进时 Boss 生成定时任务正处于 sleep 等待中
- **THEN** 该任务不被立即唤醒，仅在本次 sleep 结束后读到已前移的 `boss_next_spawn_time` 时立即生成；需要立即生成 Boss 的测试场景使用既有「生成Boss」子命令

#### Scenario: 正常路径不受影响

- **WHEN** 未调用时间快进时玩家进行历练、闭关、决斗等操作
- **THEN** 冷却与周期行为与既有规则完全一致

### Requirement: GM 清除全部冷却

系统 SHALL 提供 GM 子命令「清除全部冷却」，按目标玩家一键归零其全部冷却与忙碌状态，语义为既有「清除CD」「清除悬赏」「清除传承状态」的并集超集：`user_cd` 忙碌记录（重置为空闲）、战斗冷却（`combat_cooldowns`）、双修冷却（`dual_cultivation.last_dual_time`）、悬赏进行中记录（`bounty_tasks`）与放弃冷却、传承挑战冷却与被夺保护期、历练路线内存休整冷却。目标解析沿用既有 GM 约定（@mention / 数字 ID / 省略时作用于发送者），破坏性操作 SHALL 要求末尾追加「确认」，回复 SHALL 列出实际清除的各域条目数；目标无任何可清除状态时应明确回复且不产生副作用。

#### Scenario: 一键清除后可立即重入

- **WHEN** GM 发送 `修仙GM 清除全部冷却 900000002 确认`，且该玩家正处于历练中且有决斗冷却
- **THEN** 该玩家 `user_cd` 重置为空闲、`player.state` 置为「空闲」、决斗/切磋/双修冷却归零、悬赏与传承冷却一并清除，可立即发起下一次历练与决斗

#### Scenario: 无确认拒绝执行

- **WHEN** GM 发送 `修仙GM 清除全部冷却 900000002` 而未追加「确认」
- **THEN** 系统回复破坏性操作警告并要求追加「确认」，不产生任何数据变更

#### Scenario: 无可清除状态

- **WHEN** GM 对一名当前完全空闲且无冷却记录的玩家执行「清除全部冷却 确认」
- **THEN** 系统回复该玩家没有可清除的冷却状态，不产生数据变更

### Requirement: GM 随机种子注入与恢复

系统 SHALL 提供 GM 子命令「随机种子」，为当前进程注入固定的全局随机种子，使战斗、掉落、突破等概率类行为在种子固定期间可复现，供功能测试将统计性验证升级为确定性验证。`修仙GM 随机种子 <整数>` 设置种子；`修仙GM 随机种子 重置` 恢复为系统熵随机。种子状态 SHALL NOT 持久化——进程重启后自动恢复随机。该子命令为非破坏性操作，不要求「确认」，但成功回复 SHALL 明示「仅限测试场景」及恢复方式；种子参数非法时应拒绝并保持当前随机状态不变。

#### Scenario: 设定固定种子后可复现

- **WHEN** GM 发送 `修仙GM 随机种子 42`，随后以固定前置状态重复执行同一概率型操作
- **THEN** 系统回复种子已设定（含测试场景警示），且同种子下同一操作序列的随机结果序列可复现

#### Scenario: 重置恢复随机

- **WHEN** GM 发送 `修仙GM 随机种子 重置`
- **THEN** 系统恢复系统熵随机源并回复确认，后续随机行为不再按固定序列产出

#### Scenario: 非法种子参数拒绝

- **WHEN** GM 发送 `修仙GM 随机种子 abc`（非整数且非「重置」）
- **THEN** 系统回复参数错误提示，当前随机状态保持不变

#### Scenario: 进程重启自动恢复

- **WHEN** 设定固定种子后插件进程重启
- **THEN** 随机源恢复为未固定状态，无需任何手动清理

### Requirement: GM 测试命令安全边界

「时间快进」「清除全部冷却」「随机种子」三个测试向子命令 SHALL 遵守既有 GM 约束全集：仅限 `GM_ADMINS` 白名单用户（非授权用户拒绝且不产生任何变更）、每次调用（含失败）写入 GM 审计日志（含时间戳、GM ID、目标 ID、子命令、参数与成功状态）、在 GM 帮助输出中列出用法。鉴于随机种子为进程级全局影响（同进程内其他使用全局随机源的组件亦进入固定序列），该子命令的回复与 GM 帮助文本 SHALL 明示其作用域与「仅限测试实例使用」的警示。

#### Scenario: 非 GM 用户拒绝

- **WHEN** 不在 `GM_ADMINS` 中的用户发送上述任一子命令
- **THEN** 系统回复权限拒绝，时间戳、冷却记录与随机状态均不发生变化

#### Scenario: 调用写入审计日志

- **WHEN** GM 成功执行「随机种子 42」或「时间快进 3600 确认」
- **THEN** `gm_operations.log` 追加一条包含子命令、参数、GM 用户 ID 与 `success: true` 的 JSON 日志记录

#### Scenario: 帮助文本列出测试命令

- **WHEN** GM 发送 `修仙GM 帮助`
- **THEN** 帮助输出包含「时间快进」「清除全部冷却」「随机种子」的用法说明，并标注测试场景用途
