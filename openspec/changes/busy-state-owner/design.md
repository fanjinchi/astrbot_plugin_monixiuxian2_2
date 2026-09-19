# Design — busy-state-owner

## Context

写侧盘点（全部运行时代码）：`player.state` 仅 4 处写入——`handlers/player_handler.py:335-338`（闭关，"修炼中"）、`:455-459`（出关，"空闲"）、`core/gm_manager.py:908-910` / `:1237-1240`（GM 双清）。写侧原子性：3 处仍非原子（先 `update_player` commit、再 `set_user_busy/free` 独立 commit）；清全部冷却那处已由 `fix-two-stage-commit-atomicity`（S9）把步骤 1-5 包进 CM（`core/gm_manager.py:1234`），**2.4 替换 `clear(player)` 时必须留在该 CM 内**，否则退回两段提交。`user_cd` 写点另见于 adventure（:222-224/:313-314）、rift（:325-327/:418-421/:485）、sect（:917-920，唯一已在事务内的）、GM force-settle（:986,:1060）。读侧：所有 `player.state` 读取都是忙碌检查——6 处 Python 读取（`utils.py:116,121`、`player_handler.py:323,353,618`、`gm_manager.py:1236`）+ 1 处 SQL WHERE（`gm_manager.py:77`），无任何展示/序列化用途。

`UserStatus` 枚举五值（`models_extended.py:12-31`）：IDLE/CULTIVATING/ADVENTURING/EXPLORING/SECT_TASK。镜像只覆盖 CULTIVATING；SECT_TASK 实为时间戳冷却（`scheduled_time` 到期由 sect_manager:857 判定），不是活动状态。`set_user_busy` 已是带回归测试的 upsert（`database_extended.py:705-738`，`test_user_busy_upsert.py`）。

守卫现场：12 处手抄块（sect 5、combat 4、alchemy 1、player_handler 2），绕开 `@player_required` 的原因已查实——注入签名冲突（路由位置参数）、自定义文案、双人检查；manager 层另有 6 处重复（adventure:198、rift:301、alchemy:181、dual_cultivation:188/209、boss:403）。

## Goals / Non-Goals

**Goals:**
- 忙碌/冷却写入单点化：任何人想改变玩家的 busy/cooldown 状态，只有 `BusyState` 一条路。
- R1（条件 upsert 堵 race）+ R2（双写单事务）落地；R3-(ii) 删装饰器冗余层。
- 12 处守卫收编为 `assert_idle`，文案零变化。

**Non-Goals:**
- 删 `players.state` 列（后续 (b) 阶段；前置 spike：审计 webtest 平台/fixture/用例 JSON 的外部读取）。
- 守卫文案统一（内容管线另立任务）。
- `player_handler.py:109,117` 创角文案"精神力"遗留（已在 unify-combat-power-formula tasks 4.3 登记 bd）。
- 改 `BUSY_STATE_ALLOWED_COMMANDS` 清单内容（本 change 不动白名单语义）。

## Decisions

**D1 · 落点 `core/busy_state.py`，类形态 `BusyState(db)`，方法收 `player`/`user_id`。**
db 层保持模型无关（`database_extended` 只依赖 `UserStatus` 枚举）；owner 是业务不变量的编排者，符合 core/ 既有 `(db, cfg)` 构造惯例。持久化仍由 `db.ext.set_user_busy/set_user_free` 承担（其 upsert 语义与回归测试不动）。

**D2 · 双语义 API（Q4 决策 = a）：`set_busy` 与 `set_cooldown` 分设。**
`set_busy` = 活动状态（闭关/历练/秘境），写 user_cd + 维护 state 镜像（CULTIVATING → "修炼中"，其余活动 → 镜像"空闲"——镜像只认 CULTIVATING 是现状语义，忠实保留）；配对 `clear`。`set_cooldown` = 时间戳冷却（SECT_TASK），只写 user_cd 不配镜像，不提供 clear 入口——**注意预存怪癖**：现状无任何逻辑在到期时自动把 `type` 复位（到期判定 `:856-862` 只用于放行，不清状态），玩家完成宗门任务后实际靠接下一个任务或 GM 清除才脱离 SECT_TASK——本 change 忠实保留该行为，登记 bd 跟进而非顺手修改（超范围）。

**D3 · R1/R2 实现：锁内复查 + `db.transaction()`。**
`set_busy`/`clear` 内部 `async with self.db.transaction():`（前置 change 提供，其 design D1 已钉死 abort 契约：abort 只置标记；标记后 clean exit = rollback 不 re-raise）：锁内复查当前 `type == IDLE`（或目标活动态），不满足则 `txn.abort()` 返回失败文案；满足则 `set_user_busy` + 镜像赋值 + 单次提交。race loser 得到"正在X中"报错而非静默覆盖。**注意**：`set_user_busy` 的 SQL upsert 本身不改（`test_user_busy_upsert.py` 保持有效），竞争控制在 owner 侧事务内完成。**行为说明**：R1 改变了并发竞争的结果（修复向），需在更新日志按 bug 修复记录。

**D3.1 · `player_handler.py:323/:353` 两处残留读取的处置**：`:323`（闭关前的 state 复查）装饰器 user_cd 层已等价拦截，属死代码——删除；`:353`（出关时"并未闭关"的 idle 用户应答）是合法流程分支——保留（注意它仍是镜像读取，user_cd 语义可等价改写，实施时顺手改为查 user_cd 更彻底）。`:438-441` 出关"先 commit state、后结算传承"的时序注释在 R2 单事务化后须更新（clear 与传承结算的先后关系不变，但"两次 commit 窗口"的说法失效）。

**D4 · R3-(ii) 读侧：装饰器删第二层，守卫保留文案。**
`player_required`（`utils.py:102-123`）删除 `player.state == "修炼中"` 分支——镜像由 owner 单写后，user_cd 是唯一真相，第二层是纯冗余（它存在的历史意义就是糊漂移）。12 处守卫换成 `BusyState.assert_idle(user_id)`（返回 `str | None`），各站点传入自己的原文案模板或接受默认——**文案逐字不变**，平台用例锚点不受影响。注意 sect 的 5 个入口（`:433,448,459,469,481`）共享一个 `_get_busy_message`（:421-427），收编一处即覆盖 5 点。manager 层 6 处重复守卫同法收编。弃道重修（`:612-622`）有两条守卫消息：user_cd 基（:615）与 state 基（:620）——收编时保留 :615 的专属文案，state 基冗余检查随 D3.1 同法删除。

**D5 · GM 与 `_TIME_SKIP_RULES` 改道不改语义。**
`cmd_clear_cd` / `cmd_clear_all_cooldowns` 的手动双重置改为单次 `clear(player)`；`:77` 的 `WHERE state = '修炼中'` 选择器保持（镜像由 owner 维护，语义不变）。

## Risks / Trade-offs

- [写回陈旧镜像：`update_player` 动态拼 UPDATE（`data_manager.py:126-135`），~30 处调用会把内存 `player.state` 原样落库] → owner 是最后写镜像的人；读侧已改只信 user_cd，镜像仅存/只为 `_TIME_SKIP_RULES` 选择器服务，陈旧写回不再影响正确性。约定：业务代码不再直接赋值 `player.state`（代码评审把关）。
- [SECT_TASK 误清] → `set_cooldown` 无 clear 入口从构造上杜绝；sect 完成任务的既有到期路径不动。
- [R1 的报错时机变化：race loser 从"静默进入活动"变"收到忙碌报错"] → 修复向行为，更新日志记录；functional_tests 相关用例重跑确认。
- [`update_player` 与 owner 写镜像同块时的字段覆盖] → R2 后双写在同一事务同一内存对象上，无跨对象竞争。
- [decorator 删第二层的残留假设：某 handler 依赖 state 字符串判断] → 已全量 grep（探索报告 §1），6 处 Python 读取 + 1 处 SQL WHERE，全为忙碌检查，且 :323/:353/弃道重修的处置已在 D3.1/D4 明确；tasks 中逐项核对。

## Migration Plan

前置 change `add-transaction-unit-of-work` 合入后实施。本 change 无 DB 迁移/配置变更；镜像列保留（删列为后续阶段）。回滚 = revert。

## Open Questions

无——设计树已在 grilling 中收敛（Q1=(a)、Q2=(c) 已属候选3、Q3=R1+R2 纳入/R3=(ii)、Q4=(a)、Q5=3→2 独立 change）。外部消费者 spike 属后续 (b) 阶段，不在本 change。
