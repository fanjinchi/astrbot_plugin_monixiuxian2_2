# Tasks: gm-test-time-and-rng-controls

## 1. 「时间快进」子命令

- [x] 1.1 `core/gm_manager.py` 实现字段覆盖清单：集中一个映射结构（表/字段/键模式 → 前移方式），首版覆盖 `user_cd.scheduled_time`（非 IDLE）、`players.cultivation_start_time`（闭关中）、`combat_cooldowns.last_duel_time/last_spar_time`、`dual_cultivation.last_dual_time`（双修冷却）、`bounty_tasks.expire_time`（进行中）、`bank_loans.due_at`（active）、`system_config` 的 `bounty_abandon_cd_*`/`boss_next_spawn_time`/`spirit_eye_next_spawn_time`、传承挑战冷却与被夺保护期时间戳（design D2 表）；只动到期判定字段，不动历史记录类时间戳
- [x] 1.2 实现 `cmd_time_skip`：沿用 `_pop_confirmation` 确认约定、秒数须为正整数、回复逐域列出前移记录条数；注册进 `_commands` 路由表；GM 帮助文本（`cmd_help`）加「时间快进 <秒> 确认」用法与测试场景警示
- [x] 1.3 单测（`tests/test_gm_manager.py`）：无「确认」拒绝且零副作用；非正整数/非数字拒绝；内存库预置各域时间戳后断言前移量正确（含已过期字段保持不倒排到未来以外的语义）；回复含逐域条数

## 2. 「清除全部冷却」子命令

- [x] 2.1 实现 `cmd_clear_all_cooldowns`：按域委托既有清除语义（design D3）——`set_user_free` + `player.state="空闲"`、`combat_cooldowns` 清零、`dual_cultivation.last_dual_time` 双修冷却清零、进行中悬赏移除 + `bounty_abandon_cd_<uid>` 置 "0"、传承挑战冷却/保护期删除、`adventure_manager._route_cooldowns` 弹出；目标解析沿用 `_resolve_target`（`single_token_is_target=True`），确认约定，回复列出各域清除条数，无可清除状态时明确回复且无副作用；注册路由 + 帮助文本
- [x] 2.2 单测：预置多域冷却状态后一键清除并断言各域归零（user_cd 空闲、决斗可立即发起、双修冷却归零、悬赏可立即接取）；无「确认」拒绝；空状态提示路径

## 3. 「随机种子」子命令与机缘轮盘收编

- [x] 3.1 实现 `cmd_seed`：`随机种子 <整数>` 调全局 `random.seed(n)`、`随机种子 重置` 调 `random.seed()`、其他参数拒绝且当前随机状态不变；非破坏性不要求确认；成功回复明示「仅限测试场景、进程级生效、重置或重启恢复」（design D4/D5）；注册路由 + 帮助文本（含与平台 deterministic 的交互说明：后执行者生效）
- [x] 3.2 `core/breakthrough_manager.py:515` 机缘轮盘的未播种 `random.Random()` 改为传入全局 `random` 模块（`roll_breakthrough_fortune` rng 参数 duck-typed 兼容，分布不变，仅纳入 seed 覆盖）
- [x] 3.3 单测：设定种子后连续两次同参数概率调用结果一致、重置后不再按固定序列、非法参数拒绝；`tests/test_breakthrough_fortune.py` 与突破相关既有测试保持绿

## 4. 收尾与文档同步

- [x] 4.1 质量门：`uv run python -m pytest tests/ -q` 全绿（重点 `test_gm_manager.py` / `test_breakthrough_fortune.py`）；`uv run ruff format . && uv run ruff check .` 通过
- [x] 4.2 `openspec validate gm-test-time-and-rng-controls --strict` 通过
- [x] 4.3 `handlers/misc_handler.py` `/修仙帮助` 文本 GM 区新增三个子命令说明（标注测试场景用途）
- [x] 4.4 `functional_tests/platform-gap-report.md` 更新：「时间推进」行绕行方式改为 GM 时间快进/清除全部冷却；「随机/概率效果验证」行补充插件侧 GM 随机种子（含平台 deterministic 覆盖关系说明）；「时间加速/虚拟时钟」Unsupported 行标注插件侧已补齐、平台增强建议保留给定时任务完整语义
- [x] 4.5 版本 checklist（AGENTS.md §7）：`metadata.yaml` version 递增、`README.md` 更新日志末尾追加；design_docs 侧注明——本变更为 GM 测试工具，不影响玩法数值/机制，无需同步 `current-design-report.md` 等数值资料（§14 判定：行为与数值设计意图不变）；`AGENTS.md` §2 状态检查节补一条约束：新增等待类冷却域时须同步「时间快进」覆盖清单
- [x] 4.6 关闭 bd `astrbot_plugin_monixiuxian2_2-3pu`、`astrbot_plugin_monixiuxian2_2-y0m`；`functional_tests/cases/gm/` 新用例补充与真实环境回归由用户手动发起（AGENTS.md 网页端测试平台节 2026-08-30 约定：AI 不主动跑平台用例）
