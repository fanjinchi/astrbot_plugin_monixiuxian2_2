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
