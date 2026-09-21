# decouple-handler-to-handler-calls

## Why

架构评审（command routing + handler 层）发现 handler 层存在两处跨缝耦合与一份复制粘贴，使「宗门」知识的 locality 变差：

1. **handler 调 handler**：`SectHandlers._sub_rank` / `_sub_rank_contribution`（`handlers/sect_handlers.py:191-203`）通过 `async for r in self.ranking_handlers.handle_rank_sect(event)` 调用另一个 handler 的生成器方法；该依赖靠 `main.py:349-350` 在 `RankingHandlers` 构造**之后**向已构造的 `SectHandlers` 实例做属性回填（`self.sect_handlers.ranking_handlers = self.ranking_handlers`），`SectHandlers.__init__` 为此保留可变默认参 `ranking_handlers=None`（`:31,:36`）。而 `RankingHandlers.handle_rank_sect` / `handle_rank_sect_contribution`（`handlers/ranking_handlers.py:30-56`）**没有任何顶层指令路由**——`main.py` 只注册了境界/战力/灵石/存款四个排行路由（`:1154-1179`），这两个方法的唯一入口就是 `/宗门 排行`、`/宗门 贡献排行` 子命令。「宗门排行」的知识被劈进两个文件，仅为这一次调用付出构造顺序约束。
2. **悬赏编排复制**：`SectHandlers._sub_bounty`（`handlers/sect_handlers.py:207-263`）内联了接取/进度/完成/放弃 + 列表排版的完整指令编排，与 `handlers/bounty_handlers.py:21-74` 的全局悬赏流程逐字同构（条目 `_format` 块完全重复）。`BountyManager` 业务方法已收 `scope` 参数，被复制的只有解析/排版这层编排。

## What Changes

- 确立规则：**handlers 永不调 handlers**（生成器转发或实例注入均不允许）；跨 handler 的复用一律下沉为「manager 直调」或「handler 模块级无状态函数」。
- 把 `handle_rank_sect` / `handle_rank_sect_contribution` 从 `RankingHandlers` 移入 `SectHandlers`（其唯一调用者），内部直调 `RankingManager.get_sect_ranking()` / `get_contribution_ranking()`；`SectHandlers.__init__` 的 `ranking_handlers=None` 回填参数替换为 `rank_mgr=None`（保留「❌ 排行功能不可用！」降级文案，行为与现状一致），删除 `main.py:349-350` 的回填语句及其注释（`:340`）。
- `handlers/bounty_handlers.py` 暴露模块级文本型复用入口（`format_bounty_entry(b)` / `render_bounty_list(bounty_mgr, player, scope)` / `render_bounty_action(bounty_mgr, player, action, args, scope)`），全局路由方法与宗门 `_sub_bounty` 共用同一份解析/排版实现；各自入口的差异化文案（标题/footer/空态提示/编号用法示例）由 `scope` 参数在共享函数内部分支，保证逐字不变。
- 纯行为保持重构：所有用户可见文案、输出文本、成功/失败语义与现状逐字一致；不触碰 `BountyManager` / `RankingManager` 业务方法。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 纯重构：`openspec/specs/sect-commands` 的「排行子命令并入」（:42-45）与「宗门悬赏独立入口」生命周期（:56 起）需求描述的是行为契约（入口、输出、分流），本变更不修改任何需求级行为，故 `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **代码**：`handlers/sect_handlers.py`（+排行两方法、`_sub_bounty` 改用共享入口；构造签名变更）、`handlers/ranking_handlers.py`（-两方法）、`handlers/bounty_handlers.py`（+模块级共享函数，原方法改为薄委托）、`main.py`（-`:349-350` 回填及其注释）。
- **测试**：`tests/test_sect_handlers.py` 现有构造点（`:168,:282,:307,:331,:355` 等）均不传 `ranking_handlers`，迁移到 `rank_mgr=None` 签名后无需改动即可通过；补 `_sub_rank` 退化提示与 `_sub_bounty` 共享排版的最小断言。
- **文档**：`design_docs/api-overview.md:55`（SectHandlers 行补「排行/贡献排行 → RankingManager 直调」）、`:68`（RankingHandlers 行收敛为四个全局排行）。
- **无**数据库迁移、无配置变更、无对外行为变化。
- **同文件编辑冲突提示**：`handlers/sect_handlers.py` 也是进行中的 `openspec/changes/busy-state-owner/`（busy-state 守卫收编）的触碰面（后者把 `:291-295,:302-306,:313-317,:335-339,:423-427` 等守卫替换为装饰器）。两者无逻辑冲突（本变更不动任何状态守卫），但同文件落地会产生 rebase/审阅噪音，**实施顺序已定（2026-09-21）：`composition-root` → `busy-state-owner` → 本 change**——理由：本变更的移动段（`:191-263`）位于 busy-state 守卫清单（`:292+`）之前，若本变更先合入，busy-state 的守卫行号清单会再漂移一次；让守卫清单先落在静止的代码上，本变更后合入时吸收其成果即可（勿同批次合并）。**参数叠加规则**：busy-state 会给 `SectHandlers.__init__` 加 `busy_state` 参数，本 change 再加 `rank_mgr`——后合入者**叠加**、不得改名/删除先合入者的参数。
- **并发变更重叠**：`openspec/changes/composition-root/` 同样删除 `main.py:350` 的 `sect_handlers.ranking_handlers` 回填（其 tasks 1.2/2.7）并把 main.py 装配段重构为 `_wire_core_services()`、给 `SectHandlers` 构造签名补可选协作者参数。与本 change 目标态一致（构造期注入），无逻辑冲突；但其合入会移动本变更引用的行号（main.py 装配段、sect_handlers 构造区），**后合入者须按先合入者的 `SectHandlers` 签名与装配结构落地**（见 tasks 前置检查）。
