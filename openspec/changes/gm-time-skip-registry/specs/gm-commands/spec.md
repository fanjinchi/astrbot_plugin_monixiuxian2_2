## MODIFIED Requirements

### Requirement: GM 时间快进

系统 SHALL 提供 GM 子命令「时间快进」，将到期判定类时间戳统一前移指定秒数，使冷却与长周期玩法的等待立即到期，供功能测试消除真实 sleep 等待。覆盖清单由**字段属主声明、注册表装配**提供：每个拥有到期/冷却时间戳字段的模块以 `TIME_SKIP_ENTRIES` 常量声明其覆盖条目（域标签 + 参数化 UPDATE），GM 侧注册表在装配期汇总；新增等待类冷却域时声明即自动获得快进覆盖与 GM 帮助列出，MUST NOT 要求手改 GM 管理器内的集中清单。注册表 MUST 至少覆盖以下清单：`user_cd.scheduled_time`（忙碌状态计划完成时间）、`players.cultivation_start_time`（闭关开始时间）、`combat_cooldowns.last_duel_time/last_spar_time`（决斗/切磋冷却）、`dual_cultivation.last_dual_time`（双修冷却）、`bounty_tasks.expire_time`（进行中悬赏过期时间）、`bank_loans.due_at`（贷款到期时间）、`system_config` 中的 `bounty_abandon_cd_<user_id>`（悬赏放弃冷却）、`boss_next_spawn_time` 与 `spirit_eye_next_spawn_time`（定时任务下次刷新时间）、传承挑战冷却与被夺保护期时间戳。该子命令 SHALL 沿用破坏性操作的「确认」约定，并 SHALL 在回复中列出各域受影响的记录条数。该子命令 SHALL NOT 修改任何冷却/周期的时长配置本身，SHALL NOT 承诺唤醒正处于 `asyncio.sleep` 等待中的定时任务循环（前移 `boss_next_spawn_time` 仅保证该任务下次醒来时立即触发）；正常运行路径在无 GM 调用时行为 MUST 完全不变。

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

#### Scenario: 新冷却域经声明自动覆盖

- **WHEN** 某玩法模块新增一个参与到期判定的时间戳字段，并在其属主模块声明 `TIME_SKIP_ENTRIES` 常量、将该模块登记进注册表 provider 列表
- **THEN** 该字段自动被「时间快进」覆盖并在 GM 帮助的覆盖域列表中列出，无需修改 GM 管理器内部逻辑；注册表的最小清单钉住测试漏登记即失败
