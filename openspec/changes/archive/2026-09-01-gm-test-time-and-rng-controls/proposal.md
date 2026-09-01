# Proposal: gm-test-time-and-rng-controls

## Why

功能测试存在两类能力缺口（均登记于 `functional_tests/platform-gap-report.md`）：时间推进——平台无虚拟时钟/时间加速，闭关、历练、冷却等长周期玩法不可真实等待（「时间推进」Partially supported 行与「时间加速/虚拟时钟」Unsupported 行），现状用例只能靠"入口可达"冒烟 + GM 强制结算规避；概率行为——平台 `deterministic`+`seed` 为"尽力而为"（宿主异步活动可能耗掉 RNG 序列，见「随机/概率效果验证」行），概率类验证点无法稳定复现。来源 bd issue：`astrbot_plugin_monixiuxian2_2-3pu`（GM 时间加速/冷却清除）、`astrbot_plugin_monixiuxian2_2-y0m`（GM 注入固定 RNG seed）。测试平台侧的虚拟时钟/RNG 增强不在本仓库（平台插件是独立仓库），本变更从修仙插件侧用 GM 命令补齐这两个测试能力缺口。

## What Changes

- **新增 GM 子命令「时间快进」**：`修仙GM 时间快进 <秒> 确认`——将数据库中已枚举的未来到期类时间戳统一前移 N 秒（`user_cd.scheduled_time`、`players.cultivation_start_time`、`combat_cooldowns.last_duel_time/last_spar_time`、`dual_cultivation.last_dual_time`、`bounty_tasks.expire_time`、`bank_loans.due_at`、`system_config` 中的 `bounty_abandon_cd_*`/`boss_next_spawn_time`/`spirit_eye_next_spawn_time` 等），使冷却与长周期玩法的等待立即到期。破坏性操作，沿用既有「确认」约定。对正在 `asyncio.sleep` 中的定时任务（Boss/灵眼生成循环）不做唤醒承诺——前移 `boss_next_spawn_time` 只保证其下次醒来立即触发，需要立即生成 Boss 仍走既有「生成Boss」。
- **新增 GM 子命令「清除全部冷却」**：`修仙GM 清除全部冷却 [@玩家/ID] 确认`——按用户一键归零全部冷却与忙碌状态：`user_cd` 忙碌记录、战斗冷却（`combat_cooldowns`）、双修冷却（`dual_cultivation.last_dual_time`）、悬赏放弃冷却（`bounty_abandon_cd_<uid>`）、传承挑战冷却与被夺保护期、历练路线内存休整冷却等；语义为既有「清除CD」「清除悬赏」「清除传承状态」的并集超集，供测试用例首尾清洗状态。
- **新增 GM 子命令「随机种子」**：`修仙GM 随机种子 <整数>` 为当前进程注入固定 `random.seed(n)`，`修仙GM 随机种子 重置` 恢复系统熵。种子状态不持久化，进程重启自动恢复随机；非破坏性，不要求「确认」，但回复中明示"仅限测试场景"。
- 三个子命令全部走 `GMManager._commands` 路由表注册，遵守既有 GM 约束：`GM_ADMINS` 白名单拦截（`main.py` 入口 `_check_gm_admin`）、每次调用写审计日志（`_log_operation`，含失败）、目标解析沿用 `_resolve_target` 约定。

**明确不在本变更内**：

- 插件内统一时间读取点（可覆盖 `now()`）或虚拟时钟框架——影响面大（`time.time()` 散布 20+ 文件 85+ 调用点，定时任务基于事件循环单调时钟），本变更只做字段改写路线，虚拟时钟作为未来方向记入 design Open Questions
- 测试平台侧增强（`run.time_offset`/`POST /api/ops/tick` 等）——平台是独立仓库
- 战斗引擎专用 `Random` 实例改造（把 16 个文件 86 处全局 `random` 调用点改为可注入 RNG）——侵入面与"测试工具最小侵入"目标冲突
- 任何玩法数值/概率本身的变化（纯测试工具，正常运行路径行为不变）

## Capabilities

### New Capabilities

（无——新子命令归入既有 GM 命令能力域。）

### Modified Capabilities

- `gm-commands`: 新增「时间快进」「清除全部冷却」「随机种子」三个测试向子命令的行为契约：参数与目标解析、破坏性确认约定、安全边界（仅 GM 白名单/测试场景）、审计日志要求、以及种子恢复（重置/进程重启）语义。

`functional-test-suite` 的 requirement 无变化：PvP 用例的 deterministic-first 策略（平台级 `deterministic`+`seed`）保持既有要求不变，本变更是插件侧补充手段；gap 报告内容更新属既有「Platform capability gap report」requirement 下的文档维护，不产生新 requirement。

## Impact

- **代码**：`core/gm_manager.py`（新增三个子命令实现与路由注册、帮助文本）、必要时 `data/database_extended.py`（按表批量前移时间戳的只改该表字段的更新方法，或在 gm_manager 内用既有连接执行；不新增表、无 migration）
- **测试**：`tests/test_gm_manager.py` 新增三命令的单测（参数校验、确认约定、字段前移断言、seed 设定/重置）；`functional_tests/cases/gm/` 后续可补平台用例（由用户手动发起真实环境回归）
- **文档**：`handlers/misc_handler.py` `/修仙帮助` 文本（GM 命令区）、`functional_tests/platform-gap-report.md`（「时间推进」「随机/概率效果验证」两行更新绕行方式为插件 GM 命令）
- **安全边界**：随机种子为进程级全局影响（同进程其他插件的 `random` 也进入固定序列），仅限测试实例使用，文档与命令回复中明示；不持久化、重启自愈
- **玩法数值**：零影响——不改变任何正常路径的冷却时长、概率或结算逻辑，仅提供 GM/测试场景的直达通道
- **bd**：落地后关闭 `astrbot_plugin_monixiuxian2_2-3pu`、`astrbot_plugin_monixiuxian2_2-y0m`
