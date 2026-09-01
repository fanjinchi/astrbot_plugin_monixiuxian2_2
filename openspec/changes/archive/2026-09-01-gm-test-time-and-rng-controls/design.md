# Design: gm-test-time-and-rng-controls

## Context

现状与约束（详查于 2026-08-31 代码侦察；动机见 proposal.md Why）：

- **时间读取无统一点**：`time.time()` 散布于 20+ 文件 85+ 调用点（`handlers/`、`managers/`、`core/`、`main.py`），冷却/周期字段分散在多处存储：
  - `user_cd` 表：`type`（UserStatus 枚举）+ `scheduled_time`（计划完成时间，历练/秘境/宗门任务）
  - `players.cultivation_start_time`：闭关开始时间（出关按 `now - start` 结算，`handlers/player_handler.py:312/:334`）
  - `combat_cooldowns` 表：`last_duel_time`/`last_spar_time`（决斗/切磋冷却，`handlers/combat_handlers.py:30-68`）
  - `bounty_tasks.expire_time`（悬赏过期，表结构见 `data/migration.py:312`）与 `system_config.bounty_abandon_cd_<uid>`（放弃冷却）
  - `bank_loans.due_at`（贷款到期，逾期触发追杀，`handlers/utils.py:144-190`）
  - `dual_cultivation.last_dual_time`（双修冷却，双方均检查，`managers/dual_cultivation_manager.py:213-224`，表结构 `data/migration.py:362-366`）
  - `system_config.boss_next_spawn_time` / `spirit_eye_next_spawn_time`（定时任务下次刷新）
  - 传承挑战冷却/被夺保护期（`managers/impart_manager.py:262-286`）
  - 内存态：历练路线休整冷却 `adventure_manager._route_cooldowns`（不落库）
- **定时任务基于真实时钟睡眠**：`main.py` 的 Boss 生成（`:467`）、贷款检查（`:611`）、灵眼生成（`:688`）、悬赏过期检查（`:746`）全部用 `asyncio.sleep(remaining/interval)` 等待——事件循环单调时钟，任何"虚拟时间"都无法提前唤醒它们
- **随机源几乎全部走全局 `random` 模块**：combat/breakthrough/rift/adventure/bounty/boss/enemy/alchemy/sect/shop/skill/cultivation/pve/spirit_eye/narrative_text 等，实测 16 个文件 86 处调用点（不含 `tests/` 与 `design_docs/` 模拟脚本）；例外：`core/breakthrough_manager.py:515` 机缘轮盘传入未播种的 `random.Random()`（系统熵，全局 seed 覆盖不到）；`core/breakthrough_fortune.py` 的 `roll_breakthrough_fortune(rng, ...)` 本身支持 rng 注入（duck-typed，传 `random` 模块亦可）
- **平台侧已有机制**：测试平台 `deterministic`+`seed` 在每个 `send` 注入前重置全局随机种子（尽力而为，宿主异步活动可能耗掉序列）；时间加速在平台侧为 Unsupported（建议的 `run.time_offset`/`tick` 属平台独立仓库）
- **既有 GM 框架**：`core/gm_manager.py` `_commands` 路由表 + `dispatch`（每次调用含失败都写审计日志 `_log_operation`）、破坏性操作「确认」约定（`_pop_confirmation`）、目标解析 `_resolve_target`；先例：`cmd_force_adventure`/`cmd_force_rift` 已直接改写 `user_cd.scheduled_time = now` 再结算（`:902`/`:976`）

## Goals / Non-Goals

**Goals:**

- GM 一条命令消除任意冷却/周期等待（时间快进）与按用户归零全部冷却（清除全部冷却），冷却类功能用例不再真实 sleep
- GM 一条命令使概率行为跨步骤持续可复现（随机种子），且可随时恢复随机
- 对正常运行路径零侵入：不改冷却时长、概率、结算逻辑；不加新依赖、不加表、无 migration
- 全部子命令复用既有 GM 白名单、审计日志、确认约定与帮助文本框架

**Non-Goals:**

- 不实现插件内统一时间读取点（可覆盖 `now()`）或虚拟时钟框架（见 D1 否决理由；未来方向记 Open Questions）
- 不做战斗引擎专用 `Random` 实例依赖注入改造（见 D4 否决理由）
- 不改动测试平台仓库的任何能力；不在本变更内新增/改写 functional_tests 用例（用例跟进由用户发起）
- 不承诺唤醒 sleep 中的定时任务循环；不做种子状态持久化或查询命令

## Decisions

### D1：时间加速走「GM 直接改写时间字段」路线，否决统一 `now()` 虚拟时钟

两条路线的权衡：

- **(a) 插件内统一时间读取点（可覆盖 `now()` + 全局偏移量）**：语义最彻底，但对本代码库是错的工具——85+ 个 `time.time()` 调用点需要逐一改道统一时钟服务；更致命的是四个定时任务用 `asyncio.sleep(remaining)` 睡眠，事件循环单调时钟不受虚拟时间影响，快进后 Boss/灵眼循环仍睡到真实时点才醒，要兑现"快进即触发"还得把 sleep 循环全部改造为 tick 驱动。侵入面、回归风险与"测试工具"定位完全不匹配。**否决**。
- **(b) GM 直接改写冷却/到期字段**：把"未来才到期"的时间戳减去 N 秒，等待立即到期。有现成先例（`cmd_force_adventure` 改写 `scheduled_time` 后走 `finish_adventure` **正常结算路径**——不是绕过业务逻辑，而是让业务逻辑在"时间已到"的真实状态下运行）。影响面收敛在 `gm_manager.py` 一处。**采用**。

采用 (b) 的边界如实接受：内存态冷却（`_route_cooldowns`）不落库、不在快进覆盖范围；sleep 中定时任务不唤醒（spec 已声明该 scenario，立即生成 Boss 走既有「生成Boss」）。

### D2：「时间快进」的字段覆盖采用显式枚举清单，只动"到期判定"字段

首版覆盖清单（即 spec 枚举，实现时集中于一个映射结构：表/字段/键模式 → 前移方式）：

| 存储 | 字段 | 前移效果 |
|---|---|---|
| `user_cd` | `scheduled_time`（非 IDLE 记录） | 历练/秘境/宗门任务立即可结算 |
| `players` | `cultivation_start_time`（闭关中玩家） | 出关按更长时间结算 |
| `combat_cooldowns` | `last_duel_time`/`last_spar_time` | 决斗/切磋冷却到期 |
| `dual_cultivation` | `last_dual_time`（双修冷却，双方均检查） | 双修冷却到期 |
| `bounty_tasks` | `expire_time`（进行中悬赏） | 悬赏立即过期（走正常过期流程） |
| `bank_loans` | `due_at`（active 贷款） | 贷款立即逾期（⚠ 触发追杀，见 Risks） |
| `system_config` | `bounty_abandon_cd_*`、`boss_next_spawn_time`、`spirit_eye_next_spawn_time` | 悬赏放弃冷却归零；Boss/灵眼下次醒来立即刷新 |
| 传承表 | 挑战冷却/被夺保护期时间戳 | 传承 PK 限制解除 |

原则：只前移"参与到期/冷却判定"的时间戳；**不动**历史事件记录类时间戳（交易流水、日志、创建时间）。首版**不覆盖**的已知域点名如下，避免"枚举完备"误读：丹药 buff `expiry_time`、商店刷新、灵田 `plant_time`、`blessed_lands.last_collect_time`（洞天收取）、`spirit_eyes.last_collect_time`（灵眼收取）、`dual_cultivation_requests.expires_at`（双修请求过期）——均不阻碍冷却类测试主链路。清单以"明确枚举、按需扩域"演进——新增等待类域时须同步加入清单并更新 GM 帮助，此约束写入 tasks 的收尾项。前移量全库统一一个 N，不做按域粒度（YAGNI）。

### D3：「清除全部冷却」按域委托既有清除语义，不新写一套 SQL

新命令是编排者：对目标玩家依次执行与既有子命令同语的清除——`set_user_free` + `player.state="空闲"`（同「清除CD」）、悬赏两键（同「清除悬赏」）、传承冷却/保护期（同「清除传承状态」）、战斗冷却表清零、内存 `_route_cooldowns` 弹出（`cmd_force_adventure` 已在用同方式）。每域记录清除条数，汇总进回复。复用既有语义保证"GM 清除后状态 == 正常到期后状态"，避免第三套清除逻辑漂移。

### D4：随机种子作用域用全局 `random.seed`，否决引擎专用 Random 改造；顺带收编机缘轮盘

- **全局 `random.seed(n)`**：一行覆盖几乎全部概率路径（战斗/掉落/突破/悬赏/商店等，实测 16 个文件 86 处调用点都走全局模块）；与测试平台 `deterministic`+`seed` 同机制（平台也是重置全局种子），概念模型一致、互相兼容。
- **否决"战斗引擎专用 `Random` 实例"**：需要把 16 个文件 86 处的模块级调用改为注入式，侵入面与回归风险远超测试工具定位；且非战斗域（悬赏池、商店折扣、灵眼）同样有确定性验证需求，专用实例覆盖不全。
- **收编例外**：`breakthrough_manager.py:515` 的未播种 `random.Random()` 改为传入全局 `random` 模块（`roll_breakthrough_fortune` 的 rng 参数 duck-typed 兼容，分布完全不变，仅变得可被 seed 覆盖）。这是本变更内唯一的运行时代码行为触点，不改变任何概率分布。
- **交互说明（写入 GM 帮助与 gap 报告）**：平台用例若声明 `deterministic: true`，平台在每个 `send` 前重置全局种子会覆盖 GM 设定——GM 种子适用于未开 deterministic 的用例与手动探测；两者不冲突，后执行者生效。

### D5：恢复机制 = 显式重置 + 重启自愈，状态不持久化

- `随机种子 重置` → `random.seed()`（系统熵），立即恢复。
- 种子状态不落库、不写文件：进程/插件重启后天然恢复随机，杜绝"测试种子泄漏到生产会话"的残留风险。这也意味着不需要"种子查询"命令——回复与审计日志即状态记录。
- 「时间快进」无"恢复"概念（时间戳前移不可逆），这正是它走「确认」约定的原因。

### D6：安全边界全部复用既有 GM 框架，按破坏性分级

- 入口白名单（`main.py` `_check_gm_admin`）与 dispatch 审计日志对新命令零成本生效（路由表注册即覆盖）。
- 破坏性分级：「时间快进」（改全库字段、不可逆）与「清除全部冷却」（清状态）沿用「确认」约定；「随机种子」不改数据、可重置、重启自愈，不要求确认，但成功回复必须带"仅限测试场景/进程级生效"警示（写进 spec）。
- 进程级副作用声明：固定种子期间同进程所有全局 `random` 消费方（含宿主其他插件）进入固定序列——仅限独立测试实例使用，此警示进帮助文本与 gap 报告。

## Risks / Trade-offs

- [时间快进前移 `bank_loans.due_at` 会真实触发逾期追杀（删号级后果）] → 该效果正是贷款逾期测试场景所需；「确认」约定 + 回复逐域列出影响条数 + 帮助文本警示"仅限测试实例"；生产实例靠 GM 白名单与审计日志兜底
- [时间快进作用于全库而非单玩家，测试实例中可能波及其他测试玩家的进行中状态] → 设计上就是"时钟前进"语义（与真实时间流逝影响一致）；按玩家粒度清零用「清除全部冷却」；文档中说明两命令分工
- [枚举清单未来漏加新域 → 新冷却不被快进覆盖，测试隐性失败] → 清单集中在 gm_manager 一处映射结构 + tasks 收尾项把"新增等待类域须同步清单"登记进 AGENTS.md 状态系统节（§2 双层状态检查的同类约束）
- [固定种子污染同进程其他插件/宿主随机行为] → 不持久化 + 重启自愈 + 回复与帮助明示进程级作用域；测试在独立实例运行（既有 fixture 约定）
- [平台 deterministic 与 GM 种子叠加造成"为何我的种子不生效"困惑] → D4 交互说明进帮助文本与 gap 报告；spec scenario 只承诺插件侧行为
- [改 `breakthrough_manager.py:515` 的 rng 来源引入分布偏差] → 全局 `random` 模块与 `random.Random()` 同为 Mersenne Twister、分布相同；`tests/test_breakthrough_fortune.py` 既有 seed 化用例继续兜底

## Migration Plan

纯新增 GM 子命令 + 一处 rng 来源调整：无数据库 schema 变更、无 migration、无配置变更。上线 = 重载插件；回滚 = git revert。落地后同步：`/修仙帮助` 文本、`functional_tests/platform-gap-report.md` 两行绕行方式更新。

## Open Questions

- 未来是否需要真虚拟时钟（平台侧 `run.time_offset` / 插件侧统一 `now()`）：若定时任务类用例（Boss 周期、灵眼周期）需要"快进即触发"的完整语义再评估，届时以本变更的字段清单为输入。当前由「生成Boss」+ 字段前移的组合覆盖，不阻塞。
