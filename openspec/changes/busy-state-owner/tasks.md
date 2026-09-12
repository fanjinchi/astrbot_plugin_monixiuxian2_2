# Tasks — busy-state-owner

## 0. 前置检查

- [ ] 0.1 确认 `add-transaction-unit-of-work` 已合入（`DataBase.transaction()` 可用）；未合入则本 change 挂起

## 1. owner 核心（core/busy_state.py）

- [ ] 1.1 新增 `BusyState(db)`：`set_busy(player, status, scheduled_time=0) -> tuple[bool, str | None]`（事务内锁内复查，竞争 loser 返回忙碌文案；CULTIVATING 镜像"修炼中"、其余活动镜像"空闲"）、`set_cooldown(user_id, status, scheduled_time)`（纯冷却，无镜像无 clear）、`clear(player)`（`set_user_free` + 镜像"空闲"，单事务）、`assert_idle(db, user_id) -> str | None`（读侧单点）；英文 Google 风格 docstring 写明双语义与 race 语义
- [ ] 1.2 新增 owner 单测：双写原子性（注入失败全回滚）、race 条件 upsert（并发 set_busy 仅一胜）、`set_cooldown` 不配镜像、assert_idle 各状态分支

## 2. 写侧改道（~8 文件）

- [ ] 2.1 `handlers/player_handler.py:335-338`（闭关）/`:455-459`（出关）改道 `BusyState.set_busy/clear`——R2 双写并入单事务
- [ ] 2.2 `managers/adventure_manager.py:222-224/:313-314`、`managers/rift_manager.py:325-327/:418-421/:485` 改道（顺带收编两 manager 的手抄守卫 :198/:301 到 assert_idle）
- [ ] 2.3 `managers/sect_manager.py:917-920` 改道 `set_cooldown`（SECT_TASK 冷却语义）；`:857` 到期判定逻辑不动
- [ ] 2.4 `core/gm_manager.py:908-910` / `:1236-1239` 手动双重置改 `clear(player)`；`:986/:1060` force-settle 的 `update_user_cd` 保持直连（非常态忙碌写入，评审确认无需改道）
- [ ] 2.5 核对全仓残留：grep 确认运行时代码不再直接赋值 `player.state`（owner 之外零写入）

## 3. 读侧收编（R3-ii）

- [ ] 3.1 `handlers/utils.py:116-123`：删除 `player_required` 的 `player.state == "修炼中"` 第二层检查（user_cd 成为唯一真相）；docstring 更新
- [ ] 3.2 12 处手抄守卫改 `assert_idle`，**文案逐字保留**：sect_handlers ×5、combat_handlers ×4、alchemy_handlers ×1、player_handler ×2（:328 冗余复查直接删除——装饰器已守；:612-618 弃道重修换 assert_idle + 保留其专属文案）
- [ ] 3.3 manager 层 6 处重复守卫（adventure/rift/alchemy/dual_cultivation ×2/boss）同法收编
- [ ] 3.4 测试更新：`test_gm_manager.py`(:377-389 双重置断言）、装饰器相关测试；全量 pytest 绿

## 4. 文档与收尾

- [ ] 4.1 `CONTEXT.md` 追加 `BusyState` 条目（文件已由 add-transaction-unit-of-work 创建）：定义、双语义 API、seam 位置
- [ ] 4.2 AGENTS.md §2 双层检查条目改写：义务由 BusyState 承接（新增活动系统 = 调 `set_busy`），不再要求"两处手动同步"
- [ ] 4.3 functional_tests 守卫相关用例重跑（R1 报错时机变化；文案未动预期全过）；更新日志按 bug 修复记录 R1/R2
- [ ] 4.4 用 `bd` 登记后续 (b) 阶段 spike（外部消费者审计：webtest 平台/fixture/用例 JSON 对 `players.state` 的读取）与文案统一内容任务；`openspec validate --changes busy-state-owner` 通过；conventional commit
