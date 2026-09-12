# busy-state-owner

## Why

玩家忙碌状态由两个独立系统维护（`player.state` 字符串 + `user_cd` 表），写侧无 owner：全仓仅 4 处写 `player.state`（全部非原子双写——两次独立 commit，中途崩溃即两层漂移）；历练/秘境/宗门任务只写 `user_cd` 从不镜像；GM 清冷却要手动双重置（`core/gm_manager.py:908,1237` 的注释自证）。读侧 12 处手抄守卫话术漂移（"闭关中" vs "修炼中" 两套词）。AGENTS.md §2 把"双层同步"写成文档义务，但义务没有被任何模块承接——每次新增活动系统都再付一次税，并存在并发 start-race（两命令同读 IDLE 都放行，last write wins）。

事实基础（探索报告）：`player.state` 只是 `user_cd.type == CULTIVATING` 的纯镜像——所有运行时代码中没有非忙碌用途的读取（含"我的信息"面板，状态行取自 user_cd）。

## What Changes

- 新增 `core/busy_state.py` 的 `BusyState` 类（构造收 `db`）：忙碌/冷却状态的**唯一写路径**。
  - `set_busy(player, status, scheduled_time=0)`：一次事务内 `set_user_busy` + 维护 `player.state` 镜像（条件 upsert 堵并发 start-race）；仅 CULTIVATING 镜像，其余状态镜像回"空闲"；
  - `set_cooldown(user_id, status, scheduled_time)`：纯时间戳冷却（宗门任务 SECT_TASK 场景），不配镜像，只能等过期；
  - `clear(player)`：`set_user_free` + 镜像复位，单事务；
  - `assert_idle(db, user_id) -> str | None`：读侧单点守卫（返回报错文案或 None），收编 12 处手抄块。
- **R1**：条件 upsert（`BEGIN IMMEDIATE` + `WHERE type = 0` 语义）关闭并发 start-race；**R2**：闭关/出关双写并入单事务（依赖先行 change `add-transaction-unit-of-work` 的 `db.transaction()`）。
- **R3 走保守方案 (ii)**：装饰器 `player_required` 删第二层冗余检查（`utils.py:116-123`，该层本就极少命中）——删除后用户几乎无感；12 处守卫**保留各自原文案**只换实现（文案统一留给内容管线，另立任务，不在本 change）。
- GM 两处手动双重置、宗门任务写点、历练/秘境写点全部改道 owner；`_TIME_SKIP_RULES` 无需改动（镜像由 owner 维护后 `:77` 的 WHERE 选择器语义保持）。
- `CONTEXT.md` 登记 `BusyState` 条目（若 `add-transaction-unit-of-work` 已建文件则在其上追加）。

**前置依赖**：`add-transaction-unit-of-work` 合入后实施（owner 的单事务双写用其 `db.transaction()`；无它则本 change 需自带手工 BEGIN，违背初衷）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 忙碌检查/冷却的行为契约无 spec 需求条目；本 change 的行为变化是 bug 修复型（R1/R2）与冗余删除（R3-ii），不修改需求级定义。故 `skip_specs: true`。）

## Impact

- **代码**：新增 `core/busy_state.py`；写侧 ~8 文件（player_handler、adventure_manager、rift_manager、sect_manager、gm_manager ×2、utils.py 装饰器）；读侧守卫 ~6 文件（sect/combat/alchemy/player handlers）。
- **测试**：新增 owner 原子性 + race 测试；更新 `test_gm_manager.py`(:377-389 断言双重置）与装饰器相关测试；`test_user_busy_upsert.py` 保持有效。
- **风险标注**：R1 改变并发下的放行行为（竞争 loser 收到忙碌报错，而非静默丢状态）——用户可见但属修复；functional_tests 守卫消息锚点不变（文案未动）。
- **无**数据库迁移（本 change 不删 `players.state` 列；删列是后续 (b) 阶段，需先 spike 外部消费者）。
