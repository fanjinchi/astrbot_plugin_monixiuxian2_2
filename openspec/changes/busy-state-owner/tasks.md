# Tasks — busy-state-owner

## 0. 前置检查

- [ ] 0.1 确认 `add-transaction-unit-of-work` 已合入（`DataBase.transaction()` 可用，abort 契约按其 design D1）；未合入则本 change 挂起。**契约核对**：合入后 diff 实际落地的 `transaction()`/`txn.abort()` 语义与提案 D1 契约（幂等标记、clean exit 走 rollback 不 re-raise、TxnState 随 owner 退出丢弃）是否一致，如有偏差以代码为准并同步修正本 change 的引用——不能照提案文本读。**注意：其合入会移动本 change 引用的行号（尤其 sect_manager 块），实施前按当时代码重新锚定所有行号引用**

## 1. owner 核心（core/busy_state.py）

- [ ] 1.1 新增 `BusyState(db)`：`set_busy(player, status, scheduled_time=0) -> tuple[bool, str | None]`（事务内锁内复查，竞争 loser `txn.abort()` 返回忙碌文案；CULTIVATING 镜像"修炼中"、其余活动镜像"空闲"）、`set_cooldown(user_id, status, scheduled_time)`（纯冷却，无镜像无 clear）、`clear(player)`（`set_user_free` + 镜像"空闲"，单事务）、`assert_idle(user_id, template: str = DEFAULT) -> str | None`（读侧单点；**template 参数必填项**——16 处守卫文案各异：战斗系"你当前正在{status}，无法进行战斗！"/对方版、sect"无法进行此操作！"、历练/秘境/炼丹/弃道重修各有专属后缀且弃道重修用「{status}」括号格式，收编时逐站传入原文案模板）；英文 Google 风格 docstring 写明双语义与 race 语义
- [ ] 1.1b 接线方式定案（**已由先行 change `composition-root` 定案并预留落点**）：`BusyState` 实例由 main.py 装配段 `_wire_core_services()` 构造（`BusyState(db)`）注入 handler/manager——core 服务一律经装配段注入、禁止消费方自构造；gm_manager 位于 core、直接持有 db，同样注入。实施前确认 `composition-root` 已合入，BusyState 追加进其装配段即可，无需再定接线方式。**注入边界（2026-09-22 定）**：新增 `busy_state` 协作者一律**必填**注入，遵循 composition-root D2 总则，Sect/Rift/Adventure 例外白名单**不扩展**——守卫型协作者缺失即构造错误，不留静默None；落地时按必填逐一更新全部直构造测试点（含 ~50 处 `SectManager(db, FakeConfigManager())` 等，实施前先 grep 登记实测点清单，判据②「新协作者不服务既有测试路径」对守卫型协作者不成立，白名单不再适用）
- [ ] 1.2 新增 owner 单测：双写原子性（注入失败全回滚）、race 锁内复查（并发 set_busy 仅一胜）、`set_cooldown` 不配镜像、assert_idle 各状态分支与各 template

## 2. 写侧改道（5 文件）

- [ ] 2.1 `handlers/player_handler.py:330-333`（闭关）/`:447-458`（出关）改道 `BusyState.set_busy/clear`——R2 双写并入单事务。**机制明确**：调用方（handler）整体包在 `async with self.db.transaction():` 里，owner 内部 CM no-op join；`update_player`（含 `cultivation_start_time` 等同行字段）也在**同一事务内**调用——owner 方法签名需支持传入待持久化的 player 变更（或文档约定调用方在 owner 调用后、事务内自行 `update_player`），不得留在事务外形成第二次提交；**更新 `:431-434` 的时序注释**（两次 commit 窗口已消失，clear 与传承结算的先后关系保持）
- [ ] 2.2 `managers/adventure_manager.py:222-224/:314`、`managers/rift_manager.py:305-307/:401/:465` 改道（顺带收编两 manager 的手抄守卫 :198/:281 到 assert_idle）
- [ ] 2.3 `managers/sect_manager.py:919-921` 改道 `set_cooldown`（SECT_TASK 冷却语义）；`:858-862` 到期判定逻辑不动
- [ ] 2.4 `core/gm_manager.py:912-914` / `:1249-1251` 手动双重置改 `clear(player)`；`:997/:1071` force-settle 的 `update_user_cd`（仅 bump `scheduled_time`，非常态忙碌写入）保持直连，在 owner docstring 里注明此例外。⚠ `:1249-1251` 已在 `fix-two-stage-commit-atomicity`（S9）的 CM 内（`core/gm_manager.py:1245`）：`clear(player)` 必须留在该 CM 块内，否则该处退回两段提交
- [ ] 2.5 残留核对：grep 确认运行时代码不再直接赋值 `player.state`；**显式排除** `scripts/test_suite_ctl.py:1134`（fixture SQL 直写，测试工具性质）、`tests/test_gm_manager.py:377`、`tests/test_sect_handlers.py:463`（测试桩写入）；用 `bd` 登记预存问题：`scripts/test_suite_ctl.py:1148` 注释 "set_user_busy 只 UPDATE 不 INSERT" 已过时（bd qv9 起为 upsert）

## 3. 读侧收编（R3-ii）

- [ ] 3.1 `handlers/utils.py:116-123`：删除 `player_required` 的 `player.state == "修炼中"` 第二层检查（user_cd 成为唯一真相；两层共用同一 `BUSY_STATE_ALLOWED_COMMANDS`，白名单语义不变）；docstring 更新
- [ ] 3.2 16 处手抄守卫改 `assert_idle`，**文案逐字保留**：sect ×9——5 入口经共享 helper `_get_busy_message`（调用点 :433,448,459,469,481，helper :421-427，收编 helper 即覆盖这 5 点）+ 4 处直连守卫需逐站收编（:292 建宗、:303 入宗、:314 退宗、:336 捐献，文案同 helper 体）、combat ×4、alchemy ×1、player_handler ×2（`:318-320` 死代码复查直接删除——装饰器已守；弃道重修 `:601-611` 保留 :604 的 user_cd 基专属文案，删除 :607 state 基冗余检查）
- [ ] 3.3 `handlers/player_handler.py:348`（出关 idle 应答）保留流程分支，实现改为查 user_cd（user_cd 语义等价改写，顺手去掉最后一个镜像读取）；manager 层 6 处重复守卫（adventure:198、rift:281、alchemy:154、dual_cultivation:203,224、boss:403）同法收编
- [ ] 3.4 测试更新：`test_gm_manager.py`(:377-389 双重置断言）、装饰器相关测试；全量 pytest 绿

## 4. 文档与收尾

- [ ] 4.1 `CONTEXT.md` **替换/落实** `BusyState` 预留条目（文件由 add-transaction-unit-of-work 创建时已含预留占位）：定义、双语义 API、seam 位置
- [ ] 4.2 AGENTS.md §2 双层检查条目改写：义务由 BusyState 承接（新增活动系统 = 调 `set_busy`），不再要求"两处手动同步"
- [ ] 4.3 functional_tests 守卫相关用例重跑（R1 报错时机变化；文案未动预期全过）；更新日志按 bug 修复记录 R1/R2
- [ ] 4.4 用 `bd` 登记：后续 (b) 阶段 spike（外部消费者审计：webtest 平台/fixture/用例 JSON 对 `players.state` 的读取——含 `scripts/test_suite_ctl.py` fixture 直写点）、文案统一内容任务、**SECT_TASK 到期不自动复位的预存怪癖**（design D2 脚注）；`openspec validate --changes busy-state-owner` 通过；conventional commit
