# Tasks — busy-state-owner

## 0. 前置检查

- [x] 0.1 确认 `add-transaction-unit-of-work` 已合入（`DataBase.transaction()` 可用，abort 契约按其 design D1）；未合入则本 change 挂起。**契约核对**：合入后 diff 实际落地的 `transaction()`/`txn.abort()` 语义与提案 D1 契约（幂等标记、clean exit 走 rollback 不 re-raise、TxnState 随 owner 退出丢弃）是否一致，如有偏差以代码为准并同步修正本 change 的引用——不能照提案文本读。**注意：其合入会移动本 change 引用的行号（尤其 sect_manager 块），实施前按当时代码重新锚定所有行号引用**

## 1. owner 核心（core/busy_state.py）

- [x] 1.1 新增 `BusyState(db)`：`set_busy(player, status, scheduled_time=0, **extra_data) -> tuple[bool, str | None]`（事务内锁内复查，竞争 loser `txn.abort()` 返回忙碌文案；CULTIVATING 镜像"修炼中"、其余活动镜像"空闲"；**无 template 参数**——锁内复查失败返回默认文案，专属文案由调用方预检（assert_idle 带 template）承载，双文案仅在 race 窗口可见，见 3.2 闭关预检）、`set_cooldown(user_id, status, scheduled_time) -> None`（纯冷却，无镜像无 clear；**不做锁内复查**——保留现状：SECT_TASK 写入本就在 `perform_sect_task` 的事务（sect_manager:842）内无复查，R1 race 控制不扩展到冷却路径）、`clear(player) -> None`（`set_user_free` 幂等 upsert + 镜像"空闲"，单事务；**无条件复位、返回 None**——"目标是否忙碌"的错误判断留在调用方（GM `cmd_clear_cd` :909-911 预检保持原样），clear 不内置该判断）、`assert_idle(user_id, template: str = DEFAULT) -> str | None`（读侧单点；**user_cd 无行 = idle 放行**，与现状 `user_cd and user_cd.type != IDLE` 的 None 语义一致；**template 参数必填项**——16 处守卫文案各异：战斗系"你当前正在{status}，无法进行战斗！"/对方版、sect"无法进行此操作！"、历练/秘境/炼丹/弃道重修各有专属后缀且弃道重修用「{status}」括号格式，收编时逐站传入原文案模板）；英文 Google 风格 docstring 写明双语义与 race 语义
- [x] 1.1b 接线方式定案（**已由先行 change `composition-root` 定案并预留落点**）：`BusyState` 实例由 main.py 装配段 `_wire_core_services()` 构造（`BusyState(db)`）注入 handler/manager——core 服务一律经装配段注入、禁止消费方自构造；gm_manager 位于 core、直接持有 db，同样注入。实施前确认 `composition-root` 已合入，BusyState 追加进其装配段即可，无需再定接线方式。**注入边界（2026-09-22 定）**：新增 `busy_state` 协作者一律**必填**注入，遵循 composition-root D2 总则，Sect/Rift/Adventure 例外白名单**不扩展**——守卫型协作者缺失即构造错误，不留静默None；落地时按必填逐一更新全部直构造测试点（实测 **55 处**：test_sect_growth 22、test_sect_manager 13、test_sect_master 10、test_sect_handlers 7、test_sect_content_link 1、test_transaction_atomicity 2——2026-09-23 实测数，替换原 ~50 估算），判据②「新协作者不服务既有测试路径」对守卫型协作者不成立，白名单不再适用）；race 单测写法参考 `tests/test_transaction_atomicity.py` 的并发模式（两协程竞争、断言仅一胜）
- [x] 1.2 新增 owner 单测：双写原子性（注入失败全回滚）、race 锁内复查（并发 set_busy 仅一胜）、`set_cooldown` 不配镜像、assert_idle 各状态分支与各 template、**assert_idle 的 user_cd 无行（None）分支 = 放行**

## 2. 写侧改道（5 文件）

- [x] 2.1 `handlers/player_handler.py:330-333`（闭关）/`:447-458`（出关）改道 `BusyState.set_busy/clear`——R2 双写并入单事务。**机制定案（2026-09-23，原"或"二选一已定）**：**owner 只改内存对象（player.state 镜像 + user_cd），不落库；调用方把待持久化的 player 字段（`cultivation_start_time` 等）与 owner 调用排在**同一个** `async with self.db.transaction():` 内，owner 内部 CM no-op join，调用方在 owner 调用后、同一事务内 `update_player(player)`**——不得留在事务外形成第二次提交。调用形态示例：①闭关——`async with db.transaction(): ok, msg = busy.set_busy(player, CULTIVATING); if not ok: yield event.plain_result(msg); return; player.cultivation_start_time = now; await db.update_player(player)`——**失败分支必须在任何后续写之前 return**：owner 内部 `txn.abort()` 置标记后，同一事务块内的后续写会在 clean exit 被静默回滚（abort 契约），`if not ok` 放 `update_player` 之前即为防此坑；②出关——`async with db.transaction(): busy.clear(player); player.cultivation_start_time = 0; await db.update_player(player)`（传承结算保持在事务外、clear 之后，先后关系不变）；③GM `cmd_clear_cd`——预检保持原样，写段 `async with db.transaction(): busy.clear(player); await db.update_player(player)`；**更新 `:431-434` 的时序注释**（两次 commit 窗口已消失，clear 与传承结算的先后关系保持）
- [x] 2.2 `managers/adventure_manager.py:222-224/:314`、`managers/rift_manager.py:305-307/:401/:465` 改道（顺带收编两 manager 的手抄守卫 :198/:281 到 assert_idle）
- [x] 2.3 `managers/sect_manager.py:919-921` 改道 `set_cooldown`（SECT_TASK 冷却语义）；`:858-862` 到期判定逻辑不动
- [x] 2.4 `core/gm_manager.py:912-914` / `:1249-1251` 手动双重置改 `clear(player)`；`:997/:1071` force-settle 的 `update_user_cd`（仅 bump `scheduled_time`，非常态忙碌写入）保持直连，在 owner docstring 里注明此例外。⚠ `:1249-1251` 已在 `fix-two-stage-commit-atomicity`（S9）的 CM 内（`core/gm_manager.py:1245`）：`clear(player)` 必须留在该 CM 块内，否则该处退回两段提交。**附带升级（2026-09-23 评审补）**：`:912-914` 的 `cmd_clear_cd` 现状是裸两段写（不在任何事务内，仅 clear-all 在 CM 内），改道后自动从非原子变原子（R2 隐性收益，非行为回归）；更新日志按 bug 修复记录
- [x] 2.5 残留核对：grep 确认运行时代码不再直接赋值 `player.state`；**显式排除** `scripts/test_suite_ctl.py:1134`（fixture SQL 直写，测试工具性质）、`tests/test_gm_manager.py:377`、`tests/test_sect_handlers.py:463`（测试桩写入）；用 `bd` 登记预存问题：`scripts/test_suite_ctl.py:1148` 注释 "set_user_busy 只 UPDATE 不 INSERT" 已过时（bd qv9 起为 upsert）

## 3. 读侧收编（R3-ii）

- [x] 3.1 `handlers/utils.py:116-123`：删除 `player_required` 的 `player.state == "修炼中"` 第二层检查（user_cd 成为唯一真相；两层共用同一 `BUSY_STATE_ALLOWED_COMMANDS`，白名单语义不变）；docstring 更新
- [x] 3.2 16 处手抄守卫改 `assert_idle`，**文案逐字保留**：sect ×9——5 入口经共享 helper `_get_busy_message`（调用点 :433,448,459,469,481，helper :421-427，收编 helper 即覆盖这 5 点）+ 4 处直连守卫需逐站收编（:292 建宗、:303 入宗、:314 退宗、:336 捐献，文案同 helper 体）、combat ×4、alchemy ×1、player_handler ×2 = **:321-324（闭关 user_cd 基预检"❌ 道友当前正{status}，无法闭关修炼！"，保留为快速路径，改 `assert_idle` 传专属模板）+ :601-604（弃道重修 user_cd 基"❌ 你当前正在「{status}」，无法弃道重修。"，同法收编）**——race 兜底由 set_busy 锁内复查承担（其失败文案为默认模板，仅 race 窗口可见，可接受；set_busy 不加 template 参数）。**清单外处置项（不计入 16，勿混入）**：:317-320（state 基"已在闭关中"重复预检，死代码——"闭关"不在 `BUSY_STATE_ALLOWED_COMMANDS`，装饰器 user_cd 层必先拦截，直接删除）、:607-610（弃道重修 state 基冗余检查，随 D3.1 同法删除）、:348-351（出关 state 基预检，tasks 3.3 已列改写为 user_cd 基）
- [x] 3.3 `handlers/player_handler.py:348`（出关 idle 应答）保留流程分支，实现改为查 user_cd（user_cd 语义等价改写，顺手去掉最后一个镜像读取）；manager 层 6 处重复守卫（adventure:198、rift:281、alchemy:154、dual_cultivation:203,224、boss:403）同法收编。**落地偏离补记（2026-09-23 实施评审定案）**：出关预检最终保留 `or player.state == "修炼中"` 镜像兜底，未去掉镜像读取——理由是改前该预检就是 state 基，兜底使漂移数据玩家（state=修炼中 且 user_cd=IDLE/无行）保持改前行为（可出关结算=自愈，与 design Risks 脏数据条目的自愈口径一致）；纯 user_cd 判定反而对这类玩家造成"正在闭关却说无需出关"的新可见回归。读侧其余位置仍只信 user_cd（本兜底是唯一的镜像读取保留点）
- [x] 3.4 测试更新：`test_gm_manager.py`——`:377-389` 双重置断言形状变化（从"set_user_free/update_player 各调一次"变为断言 `busy_state.clear` 被调用，**fixture 需注入 busy_state** 桩）；装饰器相关测试；全量 pytest 绿

## 4. 文档与收尾

- [x] 4.1 `CONTEXT.md` **替换/落实** `BusyState` 预留条目（文件由 add-transaction-unit-of-work 创建时已含预留占位）：定义、双语义 API、seam 位置
- [x] 4.2 AGENTS.md §2 双层检查条目改写：义务由 BusyState 承接（新增活动系统 = 调 `set_busy`），不再要求"两处手动同步"
- [x] 4.3 functional_tests 守卫相关用例重跑（R1 报错时机变化；文案未动预期全过）；更新日志按 bug 修复记录 R1/R2 **以及遗留脏数据放行变化**（删装饰器第二层后，`state="修炼中"` 且 `user_cd=IDLE` 的历史漂移玩家发「闭关」从拦截变放行——design Risks 新条目，2026-09-23 评审补）**注（2026-09-23 落地）**：更新日志已写入 README v3.17.5 条目；functional_tests 守卫用例真实环境回归按项目约定（2026-08-30 定）由用户手动发起，AI 不主动跑 webtest，本地质量门 = pytest + ruff（已全绿：914 passed, 1 xfailed）
- [x] 4.4 用 `bd` 登记：后续 (b) 阶段 spike（外部消费者审计：webtest 平台/fixture/用例 JSON 对 `players.state` 的读取——含 `scripts/test_suite_ctl.py` fixture 直写点）、文案统一内容任务、**SECT_TASK 到期不自动复位的预存怪癖**（design D2 脚注）；`openspec validate --changes busy-state-owner` 通过；conventional commit
