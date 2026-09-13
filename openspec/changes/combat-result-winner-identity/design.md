# Design — combat-result-winner-identity

## Context

`CombatEngine.resolve_combat`（`managers/combat_manager.py:259`）返回 `CombatResult`（:168-177），其 `winner` 是裸 user_id 字符串（或 `"draw"`）。身份编码的分配方是 `EnemyManager.spawn_enemy/spawn_enemy_from_group`（`enemy_`/`guardian_` 前缀），但解析责任落在每个调用方：`pve_combat_manager` 两处 `isinstance(winner, str) and winner.startswith("enemy_")`（:236,:274）、`boss_manager` 的 `winner == "draw"` 分支（:480）、`impart_pk_manager` 的 `== "draw"` / `== attacker.user_id`（:115,:119）。`isinstance` 防御的存在本身说明非字符串 winner 曾泄漏过。

引擎在 :341-363 的四个结算分支里**已经知道**哪一侧获胜（`winner = fighter2.user_id` 等），把侧信息直接带出即可让全部调用方免于解析。 shipped bug 与两次 archive 设计文档（add-rift-encounters design :11,:72）的「禁止前缀判定」补丁约定证明：只要解析责任在调用方，新敌人类型（新前缀）就会再次制造误判。

全仓消费者清单（实施前重新核实）：运行时 4 文件 12 处；`design_docs/attribute-growth/` 模拟脚本 5 个（直接 `load_module` 引擎，属引擎接口的直接消费者）；测试 6 文件。`CombatManager.player_vs_player` 的 legacy dict `"winner"` 键（:1518）的运行时消费者为空（`handlers/combat_handlers.py:152,211` 只取 hp/log），仅测试断言其值（`test_trigger_effect_extensions.py:739`）。

## Goals / Non-Goals

**Goals:**
- `CombatResult` 携带结构化胜负：`winner_side` 为权威判定，`winner_id` 为便捷查询（平局 `None`）；调用方只做「侧比较」或「与已知 id 的相等比较」，**任何位置不再出现 `startswith("enemy_")` / isinstance 防御**。
- 战斗数值、战报文本（含 :341-363 全部 banner/flavor 分支）、胜负玩法口径（平局/失败惩罚/免死）逐位不变——纯重构。
- `EnemyManager` 的 id 前缀约定收缩为其内部实现细节；`challenge_rift_beast` 为绕开前缀解析而做的特殊化（:409-418）得以回归与 `challenge_legacy_guardian` 同构的简单代码。

**Non-Goals:**
- 不修改任何战斗判定公式、出手权、伤害/护甲结算（`combat-core` 契约行为）。
- 不改动 `EnemyManager` 的 id 生成规则（`enemy_`/`guardian_` 前缀保留；它只是不再被消费者解析）。
- 不重构 legacy dict（`player_vs_player` 返回 dict）的整体形态，只更新其 `"winner"` 值的来源。
- 不处理 `design_docs` 模拟脚本的其它技术债（如 `sim_route_matchup.py` 的播种逻辑，属 bd 9j1 校准留档范围）。

## Decisions

**D1 · 删除 `winner` 字段而非并存过渡，改为 `winner_side` + `winner_id`。**
全仓消费者可数（运行时 12 处 + 测试 + 5 个脚本），并存期会制造第二个真相（调用方该读哪个？），过渡成本大于一次性改名。`winner_side: Literal["fighter1", "fighter2", "draw"]` 是位置语义——所有调用方都自己构建双方 FighterState（`build_fighter_from_player` 在先），天然知道自己站在哪一侧；`build_fighter_from_player(is_attacker=...)` 的语义不对称不影响侧比较的正确性，因为比较的是「我传入的 fighter1」，与我是不是攻击者无关。

**D2 · 保留 `winner_id` 便捷字段（而非纯 `winner_side`）。**
`challenge_rift_beast` / `challenge_legacy_guardian` / `impart_pk` 的契约（archive add-rift-encounters design :72）要求「胜负必须显式比较」——显式比较的正确形态是 `result.winner_id == player.user_id`（与已知 id 相等），而非前缀解析。引擎在 :344-361 已持有获胜 FighterState，附带其 user_id 成本为零；`winner_id` 同时支撑 legacy dict 的 `"winner"` 值（:1518）与测试桩构造。平局时 `winner_id = None`，`winner_side == "draw"` 是唯一平局判据。

**D3 · 引擎 :341-363 结算分支原样改为 side 赋值，banner/flavor 逻辑不动。**
`winner = fighter2.user_id` → `winner_side = "fighter2"; winner_id = fighter2.user_id`；三个平局分支 → `winner_side = "draw"; winner_id = None`。逐分支机械替换，战报文本生成路径一行不碰。

**D4 · legacy dict `"winner"` 键保留，值 = `result.winner_id or "draw"`（行为不变）。**
该 dict 是 PvP handler 的历史接口，运行时无 winner 消费者；保持键与值域（user_id 或 `"draw"`）不变，避免无收益的级联改动，测试断言（`test_trigger_effect_extensions.py:739` 的 `in ("p1","p2","draw")`）原样通过。

**D5 · `design_docs/attribute-growth/` 模拟脚本随引擎接口同步更新。**
5 个脚本（`sim_route_matchup.py:154-160,388,413-419`、`sweep_route_growth.py:124-129`、`sim_balance_regression.py:317`、`sim_xiuxian_turns.py:275`、`rebalance_equipment.py:517`）用 `result.winner == "draw"` / `== "体修"`（按名字判定）读取胜负，改为 `winner_side`（`== "fighter1"/"fighter2"` 视脚本站位而定）——这些脚本直接加载引擎模块，是接口变更的正当消费者；改动只触碰胜负读取行，模拟数值输出必须逐位不变（校准留档可复现，bd 9j1 的约束）。

## Risks / Trade-offs

- [字段改名在全仓的涟漪（测试桩构造、断言）] → 消费者清单已在 Context 枚举并在 tasks 逐项列出；`CombatResult` 为 keyword 构造的 dataclass，改名即编译期报错（fail fast），无静默漂移面。
- [模拟脚本改动破坏校准留档复现] → 只改胜负读取行、不改随机流与公式；实施后对 `sim_route_matchup.py` 做一次改造前后同种子输出比对（bd 9j1 已有逐局播种基础设施）。
- [调用方误用 `winner_id` 做前缀/包含匹配复活解析] → 无新增 lint 可禁；以 tasks 收尾 grep（`startswith("enemy_")`、`isinstance(winner` 全仓零命中）+ code review 把关。
- [`winner_side` 位置语义在多层传递中被张冠李戴] → 调用点均在同函数内构建双方 FighterState 后立即结算，无跨层传递；任务核对每个调用点的 fighter1 归属（玩家侧）。
- [与在飞变更的行号冲突] → `busy-state-owner`/`add-transaction-unit-of-work` 主要触碰 handler/manager 层守卫与事务，不触碰 `combat_manager.py` 结算段；实施前按当时代码重新锚定 tasks 行号。

## Migration Plan

无部署/迁移步骤：纯代码重构 + 测试/脚本同步，随插件重载生效；无数据库与配置变更。回滚 = revert 单个 commit。

## Open Questions

无（设计树已收敛：删除式改名、side+id 双字段、legacy dict 值域不变、脚本同步更新）。
