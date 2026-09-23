# Design — decouple-handler-to-handler-calls

## Context

`SectHandlers` 是「宗门」单入口分发器（`handlers/sect_handlers.py:79-100` 的 dispatch table），其中排行与悬赏两个子命令组的知识不在本文件：

- `_sub_rank` / `_sub_rank_contribution`（`:198-210`）把事件生成器原样转发给 `RankingHandlers` 的两个方法（`handlers/ranking_handlers.py:30-56`）。这两个方法无顶层路由（`main.py:1271-1297` 仅注册境界/战力/灵石/存款），唯一调用方就是宗门分发器；依赖现经装配段构造注入建立——`_wire_core_services()` 在 `main.py:413-420` 构造 `RankingHandlers`（`:413`）后于 `:418` 以 `ranking_handlers=ranking_handlers` 入参传入 `SectHandlers`（原 `main.py:349-350` 属性回填已随 composition-root 删除），`SectHandlers.__init__`（`:30-43`）为此携带可变默认参 `ranking_handlers=None`。`handle_rank_sect_contribution` 内的「未踏入仙途」分支（`ranking_handlers.py:45-49`）经由 `/宗门` 入口实际不可达——`handle_sect_entry` 已被 `@player_required` 兜底（玩家不存在时先行拒绝），是死代码。
- `_sub_bounty`（`:214-270`）与 `BountyHandlers`（`handlers/bounty_handlers.py:21-74`）各自实现同一套五动作编排：接取（编号解析+校验提示）、进度、完成、放弃、列表（条目排版 `_format` 逐字重复，仅标题/footer/空态文案因入口而异）。业务方法 `BountyManager.accept_bounty/check_bounty_status/complete_bounty/abandon_bounty/get_bounty_list` 已全部接收 `scope` 参数，编排层的重复没有任何业务理由。

`openspec/specs/sect-commands/spec.md:42-45`（排行子命令并入）与 `:56-66`（宗门悬赏独立入口与生命周期）约束的是行为（入口唯一、输出内容、全局/宗门分流），本变更保持其全部 Scenario 逐字成立，故 `skip_specs: true`。

## Goals / Non-Goals

**Goals:**
- 消除 handler→handler 调用与构造后属性回填：`SectHandlers` 排行子命令直调 `RankingManager`；属性回填已由 composition-root 删除（改建为装配段构造注入 `ranking_handlers=ranking_handlers`，`main.py:418`），本变更再把该注入参数换成 `rank_mgr`，初始化顺序约束随之消失。
- 悬赏五动作编排收敛为一份实现：全局路由与宗门子命令共用同一模块级文本函数，差异化文案（标题/footer/空态/编号用法示例）集中在该函数内按 `scope` 分支。
- 行为逐字保持：所有用户可见输出与现状一致（包括全局入口对接取/完成/放弃加 `✅/❌` 前缀而宗门入口不加、全局列表无空态早退而宗门列表有空态文案等差异）。

**Non-Goals:**
- 不改 `BountyManager` / `RankingManager` 的任何业务方法、签名与返回值（纯 handler 层重构）。
- 不做架构评审 finding #1（main.py 路由注册表化）与 finding #3（删除浅 handler 类）——那是独立变更的切面。
- 不统一全局/宗门两入口的差异化文案（那是产品决策，不是重构）。
- 不处理 `_sub_shop` 等其余宗门子命令的 manager 直调形态（现状已合理）。

## Decisions

**D1 · 排行两方法整体移入 `SectHandlers`，直调 `RankingManager`。**
`handle_rank_sect` 的实现体（一次 manager 调用）与 `handle_rank_sect_contribution` 的实现体（`sect_id` 存在性检查 + 一次 manager 调用）搬入 `SectHandlers` 并改造为「player 已注入」形态：`_sub_rank_contribution` 直接使用 `handle_sect_entry` 的 `@player_required` 注入的 `player`，不再自查玩家存在（原检查本就不可达），仅保留「未加入任何宗门」拒绝分支。
- 备选 A：保留方法于 `RankingHandlers`，`SectHandlers` 注入 `rank_mgr` 直调 manager。—— 拒绝：方法的唯一调用语境就是宗门分发器，留在 `RankingHandlers` 会让「宗门排行」知识继续跨文件，且 `RankingHandlers` 文档/帮助文本（`handlers/misc_handler.py:120`「宗门排行与贡献排行见『宗门 排行』」）已视其为宗门功能。
- 备选 B：把两方法下沉为 `RankingManager` 的文本方法。—— 拒绝：超出纯重构切面，触碰 Non-Goal；manager 返回 `(success, msg)` 的现状签名已够用。

**D2 · `SectHandlers.__init__` 用 `rank_mgr=None` 替换 `ranking_handlers=None` 注入参，保留「排行功能不可用」降级。**
`main.py` 装配段已先构造 `rank_mgr`（`_wire_core_services()` 内 `main.py:333-338`，经返回字典挂载为 `self.rank_mgr`），`:414-420` 构造 `SectHandlers` 时把现有入参 `ranking_handlers=ranking_handlers`（`:418`，composition-root 由旧回填改建）替换为 `rank_mgr=rank_mgr` 即可（busy-state 已合入的 `busy_state=busy_state` 入参并存不动）。`rank_mgr=None` 时 `_sub_rank*` 输出与现状相同的「❌ 排行功能不可用！」（现有测试 `:168,:301,:328,:354,:380` 等构造点不传该参，保持通过）。

**D3 · 悬赏共享入口落为 `bounty_handlers.py` 模块级无状态函数，而非 `BountyHandlers` 实例方法或 `BountyManager` 方法。**
三函数形态：
- `format_bounty_entry(b: dict) -> str`：条目多行排版（两入口逐字相同的 `_format` 块）。**独立成函数的理由**：去重后虽仅 `render_bounty_list` 一个调用点，但条目渲染是高复杂度展示块（多行拼装），且未来入口（如 GM 查看）可能复用；内联会让 list 编排函数混两种抽象层级——按 AGENTS.md「无必要不抽 helper」的**复杂度例外**成立。
- `render_bounty_list(bounty_mgr, player, scope) -> str`：列表编排，按 `scope` 分支标题（`📜 悬赏令 · 今日委托` / `🏯 宗门悬赏 · 本宗委托`）、footer（`/接取悬赏 <编号>` / `/宗门 悬赏 接取 <编号>` 用法行）与空态行为（全局无空态早退、宗门空列表输出「本宗当前无可接取的宗门悬赏」块）。
- `render_bounty_action(bounty_mgr, player, action, args: list[str], scope) -> tuple[bool, str] | None`：接取（含编号解析与防御——编号缺失/非数字/<=0 统一回 `scope` 分支编号提示，与现状逐字一致；`args` 收**字符串列表**）/进度/完成/放弃；返回 `None` 表示 `action` 未识别（全局无此路径，不新增；宗门调用点输出其特有「未识别的悬赏操作」提示）。**返回 `(success, msg)` 元组**（2026-09-23 评审修正，原 `str | None` 与下条前缀约定矛盾）：`✅/❌` 前缀差异不进共享函数——全局薄委托方法按 `success` 自行加前缀（`f"{'✅' if success else '❌'} {msg}"`），宗门调用点保持无前缀只输出 `msg`，逐字保持现状。
- 备选 A：挂在 `BountyHandlers` 实例上由 `SectHandlers` 注入调用。—— 拒绝：会以另一种形式重建本变更要消除的 handler→handler 实例依赖。
- 备选 B：下沉到 `BountyManager`。—— 拒绝：manager 已按 Non-Goal 冻结；且排版（帮助性 header/footer）属 handler 层呈现职责，与既有「manager 返回业务 msg、handler 负责版面」的分工一致。

**D4 · 验证策略：行为快照比对 + 既有测试全绿，不新增行为级测试面。**
`tests/test_sect_handlers.py` 现有用例覆盖宗门分发（导航/缺参提示/无宗门拒绝/忙碌拦截），重构后必须原样全绿；新增最小断言只钉「`_sub_rank` 在 `rank_mgr=None` 时输出降级文案」与「宗门悬赏列表经共享函数渲染」（MagicMock bounty_mgr 场景）。全局悬赏路径的文本比对以 `_sub_bounty` 与 `BountyHandlers` 改造前的输出快照逐字核对为准（review checklist 项）。

## Risks / Trade-offs

- [共享函数 `scope` 分支漏改导致一侧文案变化] → tasks 显式列出三处差异化清单（标题/footer/空态/编号示例/✅❌ 前缀），review checklist 逐条核对；宗门侧跑 `--tag sect` 功能用例回归。
- [`handle_rank_sect_contribution` 迁移时误保留不可达的「未踏入仙途」分支] → tasks 注明该分支为死代码（`@player_required` 已兜底），迁移时删除并在 review 中确认无其他调用方。
- [`RankingHandlers` 删除两方法后文档/帮助文本引用漂移] → `api-overview.md:69` 与 `misc_handler.py:120` 的表述本来就指向宗门入口，仅需收敛 RankingHandlers 职责描述；无用户可见文本变化。
- [与 `busy-state-owner` 变更同文件冲突] → `sect_handlers.py` 是该变更的守卫收编触碰面；两者逻辑无交集但 diff 会交叠，按 proposal Impact 约定错开落地顺序。
- [模块级函数被后续误加状态] → 三函数 docstring 明确无状态约定（只编排调用 bounty_mgr 并排版）；未来需要在 `openspec` 评审中拦。

## Migration Plan

无部署/迁移步骤：纯代码重构，随插件重载生效；无数据库与配置变更。回滚 = revert 单个 commit。`SectHandlers` 构造签名变化属内部接线（仅 `main.py` 与测试构造点），无插件 API 兼容面。

## Open Questions

无（设计树已收敛：规则确立、方法搬迁落点、共享函数形态、降级文案保留、验证口径）。
