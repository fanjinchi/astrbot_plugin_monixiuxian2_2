# Implementation Plan: 普通 PVE 持久结算与逃跑疲劳

## Dependencies and Gate

1. 玩家气血 child（A）已完成：`base_hp/current_hp/health_recovered_at`、Health Domain、Fighter 取 `current_hp` 均已 merged，本 child 直接消费。
2. 固定敌人目录 child（B）已完成 preview 链路与单一 Enemy→Fighter mapper；**正式名册 sync 不是本 child 的门**——名册未获批期间按 PRD R3 的 legacy 身份口径落库（`profile_id` 留空），不得为填字段手改 `config/`。
3. 持久化/事务基座 child（P）的 v36/v37/v38 schema、repository、commit 审计、fatigue time-skip provider 已过 Gate 2；本 child 在此之上**授权新增 v39 增量列**（PRD Dependencies），不改写 v36 已发布定义。
4. `handlers/combat_handlers.py:75` 裸 `conn.commit()`（bd `astrbot_plugin_monixiuxian2_2-qbo`）必须在把战斗结算包进 `db.transaction()` 之前门控为按 `conn._txn_depth` 叶子提交；与 world-boss child 共享，先接入方负责。
5. 逃跑**启用**门：系数经地板/标模/天花板模拟并回写 `design_docs/content-design/pve-enemy-design.md` §Q4 之后才允许打开；未封板时 fail-closed（只呈现迎战）。

## Steps

1. **先落 PRD R6（恢复闸门移除）**：删 `core/health.py:104-115 _is_busy()` 与 `settle()` 的 :147-152 busy 分支（先确认 `_is_busy` 无其他引用）；反转 `tests/test_player_health_foundation.py:391-403`、移除/改写 :406-413 为「忙碌期间仍恢复」；同步 `pve-enemy-design.md:813` 与附录 C.6 `:906` 口径 + 父 PRD R2 措辞（**已在本轮规划阶段先行改毕**）。此步独立可回滚，且后续所有结算测试的 HP 语义都以它为准。
   - 同一步内还要改的是**描述当前实现的文档**（之前不能提前改）：`design_docs/api-overview.md:108`（现写「空闲每分钟恢复 1% 上限…忙碌转换先结算并推进锚点」）、`core/health.py` 模块与 `settle()` docstring（docstring 与实现不一致视为 bug）、`README.md` 更新日志 + `metadata.yaml` version + `/修仙帮助`（§7）。
   - `.trellis/spec/backend/database-guidelines.md` 未编码「busy 期间不恢复」契约，无需改；:62 关于锚点被回刷的坑仍然成立。
2. **qbo 门控**：`handlers/combat_handlers.py:75` 改叶子门控，跑该文件既有战斗测试确认无中间提交。
3. **v39 迁移**：在 `data/migration.py` 的共享建表函数 `_create_adventure_persistence_tables` 内为 `adventure_settlements` 增列 `state`（默认值 + 取值域）、`route_key`、`snapshot`（JSON），加 `(user_id, state)` 索引；**`adventure_fatigue` 保持原样不动**（乙案：每人一行，沿用基座单行 API，见 design §2.1）；`@migration(39)` 与 `_create_all_tables` 两条路径都同源走该共享函数，`LATEST_DB_VERSION` 升到 39；更新 `tests/test_pve_persistence_foundation.py` 版本矩阵/表所有权/`PRAGMA table_info` parity。SQLite 若拒绝 `ADD COLUMN` 带 CHECK，则退化为仓储层枚举校验并在 parity 测试固定，禁止重建 `adventure_settlements` 表。
4. **结算服务改造**：把 `AdventureManager.finish_adventure`（:255-355）拆成 持久 run → 完成时锁定敌人+seed 写 `snapshot` → 状态推进 `adventuring→pending_choice|ready_combat` → 事务外确定性计算 → `cas_update_settlement(WHERE state=<前态> AND cas_version=?)` 短写事务（玩家 HP 写回、疲劳、`busy_state.clear`、终态事实同边界）→ 提交后 inline `claim_effect`（`base_reward`/`route_drops`/`legacy_trigger`）。删除无记录同步旁路；`outcome` 只作 `state` 派生标签。**claim 划账成功但执行抛异常**（如写储物戒失败）：不回滚 claim、不重试，结算仍进终态，但必须在结算回复末尾追加玩家可见提示「⚠️ 部分奖励发放失败，已记入日志，请联系管理员」并写带 `settlement_id`/`effect_type` 的 error 日志；此分支要有专门测试。**claim 已划账但执行抛异常**：不重试、不回滚 claim，结算仍进终态，但必须在结算回复末尾追加中文提示「⚠️ 部分奖励发放失败，请联系管理员（结算单 {settlement_id}）」并写 error 日志（带 `settlement_id`/`effect_type`/异常）——这条分支要有专门测试。
5. **疲劳两端切换 + 文案**：写端替换 `adventure_manager.py:337-344` 为 `set_fatigue(...)`（时长 = 基础 `route.fatigue_cooldown` + 仅 `resolved_loss` +600；每人一行，写入取 `max(现有, now+时长)` 不回退）；读端替换 :224-229 休整闸门为 `get_fatigue(user_id)`；删除 `event.get("injury")` +600 分支（:335）与 `_route_cooldowns`（:130），不留长期双写。同步改两处玩家可见文案：:229「该路线尚在休整中」与 :344「该路线休整：X 分钟」→ 全局表述（语义已变，不能再暗示按路线独立）。
6. **气血写回与保底**：接 Health Domain 写 `current_hp`；**战败保底改为 `max(引擎剩余, ceil(0.01 * 动态 max_hp))`**（2026-10-12 用户拍板 1%，取代原 25%；用 `apply_current_hp_change(..., floor=...)`），删除 `:306` 的 `player.current_hp = 1`。**胜场不保底**，按引擎实际剩余血量写回。地板数值须用 `main.py`/manager 里的命名常量或 config 键承载，注释标明出处 `design_docs/content-design/pve-enemy-design.md` §Q4（AGENTS.md §14）。
7. **逃跑**：实现以 `FighterState.agility` 为输入的单调有界函数 + 配置槽 + roll 取自 `snapshot.rng_seed`；跑地板/标模/天花板模拟并按 gate 5 决定开关。参数未封板时战前选择面整体 disabled（高/极高风险直接进 `ready_combat`，不写 pending），封板后只翻开关。
8. **指令入口**：`main.py` 注册 `CMD_ADVENTURE_FIGHT = "迎战"`、`CMD_ADVENTURE_FLEE = "逃跑"`（`@filter.command` 外 / `@require_whitelist` 内，docstring 按路由格式）→ 路由到 `handlers/adventure_handlers.py`；两者加进 `handlers/utils.py:22 BUSY_STATE_ALLOWED_COMMANDS`，并清理该清单里的死条目 `结束历练`/`结束秘境`；`历练状态` 显示待选择态与可执行指令。
   - **两处出路提示（甲案，与指令入口同步交付）**：① 进入 `pending_choice` 的结算回复内联遭遇对象 + 「发送「迎战」… / 发送「逃跑」…」说明；② 挂 pending 期间被忙碌拦截时（`handlers/utils.py:108-113` 固定文案只提「我的信息/签到/银行」），历练态追加一句「可发送「迎战」或「逃跑」结束本次历练」，其它状态文案逐字不变。实现用 `BusyState.assert_idle(template=)` 或拦截器 status 分支，不新增 API、不改 `UserStatus`。
9. **AGENTS.md §7 文档同步**：`metadata.yaml` version、`README.md` 更新日志、`handlers/misc_handler.py` 的 `/修仙帮助`、`design_docs/api-overview.md`（新指令/新服务链路）、`design_docs/project-architecture.md`（settlement 状态机与 v39 列；:74「休整=疲劳 300s」需改为新口径）、`design_docs/current-design-report.md:276`（「休整 = 路线疲劳 300s（+600 受伤 / +600 PvE 战败）」——受伤 +600 已取消、粒度改全局，描述现实现的两处必须与代码同步改）、`pve-enemy-design.md` §Q4（疲劳构成 + 全局粒度 + 逃跑契约 + 回血全时段；规划阶段已先行改毕，实现时核对与代码一致）。
10. **测试**：pending 两处出路提示（结算内联 + 拦截文案含迎战/逃跑，其它忙碌文案不变）、状态机全路径与非法跳转、run 唯一性、并发双击迎战/逃跑、计算前/计算后/CAS 前三个崩溃点恢复、replay 不重掷、三类 effect 的 claim 冲突与「已提交未 claim」注入、异常全回滚、疲劳构成（含 `max` 不回退、**一条路线的休整会挡住另一条路线**＝全局一份的有意语义）与 time-skip、休整闸门跨重启、休整提示与收益提示的输出文案为全局表述、R6 回血（历练/闭关/pending 期间均恢复）、1% 战败保底与胜场不保底、`迎战`/`逃跑` 在 busy 下可达、v39 fresh==upgrade parity、逃跑函数单调性/上下界/未封板 fail-closed。
11. **质量门**：`uv run ruff format . && uv run ruff check .`；`uv run python -m pytest tests/ -v`（插件目录内用 AstrBot uv 环境）。

## Rollback Point

v39 是纯增量列，旧调用方读不到即无影响；handler 切流前新状态机与服务可保持未被调用。切流失败则恢复旧 `finish_adventure` 调用路径（列保留、无破坏性）。Step 1（回血闸门）与 Step 2（qbo 门控）各自独立可回滚。禁止旧内存 fatigue 与新持久 fatigue 长期双写。

## Completion Evidence

- v39 迁移日志 + fresh/upgrade parity 与版本矩阵测试输出；
- 状态机/并发/三崩溃点/claim 幂等/time-skip 测试通过清单；
- 疲劳构成（基础 300/600/900/1200 + 仅败场 600）与 injury 分支移除的测试证据；
- 逃跑函数模拟报告及 `pve-enemy-design.md` §Q4 回写（或在未封板时明确记录功能保持 fail-closed）；
- R6 回血口径变更的设计文档 diff 与反转测试；
- PVE 统计回归与完整 ruff/pytest 摘要。
