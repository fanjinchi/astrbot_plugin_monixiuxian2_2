# Tasks — decouple-handler-to-handler-calls

## 0. 前置检查

- [ ] 0.1 **行号重新锚定**：进行中的 `composition-root`（main.py 装配段重构为 `_wire_core_services()`、`SectHandlers` 签名补参数、删 main.py:350 回填）与 `busy-state-owner`（sect_handlers.py 守卫收编）合入后，本 change 引用的行号（main.py:340-350、sect_handlers.py 构造区与 `:191-263` 等）会漂移。若二者中任一已先合入，实施前按当时代码重新锚定所有行号引用（镜像 busy-state-owner tasks 0.1 的约定）；两者都未合入则按现状锚点直接实施，但合并顺序仍按 proposal Impact 的冲突提示错开。**已定序（2026-09-21）：`composition-root` → `busy-state-owner` → 本 change**——busy-state 先合入时，`SectHandlers.__init__` 已带 `busy_state` 参数，本 change 的 1.4 步在其上**叠加** `rank_mgr`（不得改名/删除 `busy_state`），构造调用点同步传两者。

## 1. 排行子命令收编（消除 handler→handler 调用）

- [ ] 1.1 `handlers/ranking_handlers.py`：删除 `handle_rank_sect`（:30-33）与 `handle_rank_sect_contribution`（:40-56）两方法；类 docstring（:9）「sect, and sect-contribution」表述同步收敛；`main.py:1154-1179` 的四个全局排行路由不受影响
- [ ] 1.2 `handlers/sect_handlers.py`：新增 `handle_sect_rank`（原 `handle_rank_sect` 实现体，直调 `self.rank_mgr.get_sect_ranking()`，返回 `(success, msg)`）与 `handle_sect_contribution_rank`（仅保留「❌ 你尚未加入任何宗门，无法查看宗门贡献排行。」拒绝分支；**删除原 `:45-49`「未踏入仙途」分支——经 `handle_sect_entry` 的 `@player_required` 兜底该分支不可达，属死代码**）。**形态定案：两新方法为普通 async 方法，返回 `(success, msg)`（非生成器）**；`_sub_rank*` 调用后 `yield event.plain_result(msg)` 转发。docstring 用英文 Google 风格（AGENTS.md：新代码一律英文 docstring），保留原方法的中文一行 docstring 语义（"宗门排行" / "宗门贡献排行（当前所在宗门）"）翻译即可
- [ ] 1.3 `handlers/sect_handlers.py:26-36`：`__init__` 签名 `ranking_handlers=None` 参数替换为 `rank_mgr=None`（`self.rank_mgr = rank_mgr`）；`_sub_rank` / `_sub_rank_contribution`（:191-203）改为直调新方法与 `rank_mgr`，`rank_mgr=None` 时保留输出「❌ 排行功能不可用！」（与现状逐字一致）
- [ ] 1.4 `main.py`：**仅删除 `:350` 回填语句**（`self.sect_handlers.ranking_handlers = self.ranking_handlers`）与 `:340` 构造注释；**`:349`（`self.ranking_handlers = RankingHandlers(self.db, self.rank_mgr)`）必须保留**——四个全局排行路由（:1154-1179）仍依赖该实例。`:341` 构造点改为 `SectHandlers(self.db, self.sect_mgr, self.bounty_mgr, rank_mgr=self.rank_mgr)`（`self.rank_mgr` 在 :309 已构造，顺序约束解除）

## 2. 悬赏编排共享化（消除 _sub_bounty 复制）

- [ ] 2.1 `handlers/bounty_handlers.py` 新增模块级无状态函数（英文 Google 风格 docstring，注明 stateless 约定）：`format_bounty_entry(b: dict) -> str`（两入口逐字相同的条目 `_format` 块，`bounty_handlers.py:26-34` / `sect_handlers.py:249-257` 去重）；`render_bounty_list(bounty_mgr, player, scope) -> str`（按 `scope` 分支标题 `📜 悬赏令 · 今日委托`/`🏯 宗门悬赏 · 本宗委托`、footer 用法行、空态行为：全局无空态早退、宗门空列表输出「🏯 宗门悬赏\n━━━━━━━━━━━━━━━\n本宗当前无可接取的宗门悬赏。」）；`render_bounty_action(bounty_mgr, player, action, args, scope) -> str | None`（接取含编号解析，编号缺失提示按 scope 给「❌ 请指定悬赏编号，例如：/接取悬赏 1」或「❌ 请指定悬赏编号，例如：/宗门 悬赏 接取 307」；进度/完成/放弃直调 manager 同名方法；未识别 action 返回 `None`）
- [ ] 2.2 `handlers/bounty_handlers.py`：`handle_bounty_list` / `handle_accept_bounty` / `handle_bounty_status` / `handle_complete_bounty` / `handle_abandon_bounty`（:21-74）改为薄委托调用共享函数（`scope="global"`）；**`✅/❌` 前缀包装保留在全局委托方法内**（接取/完成/放弃加前缀、状态不加，与现状一致），共享函数本身不加前缀
- [ ] 2.3 `handlers/sect_handlers.py:_sub_bounty`（:207-263）改为调用共享函数（`scope="sect"`）：无参 → `render_bounty_list`；接取/进度/完成/放弃 → `render_bounty_action` 非 None 结果直接输出；`action` 未识别时保留宗门特有提示「❌ 未识别的悬赏操作「{action}」。可用：接取 <编号>｜进度｜完成｜放弃」；**不引入对 `BountyHandlers` 实例的引用**
- [ ] 2.4 逐字比对复核（review checklist）：先在**当前（重构前）代码**上手工跑一次全局 `悬赏令` / `接取悬赏` / `宗门 排行` / `宗门 贡献排行` 抓取输出快照——仓内无任何持久化的全局悬赏/排行输出快照（functional_tests 仅宗门侧用例），不先留快照则 2.4 无从比对。然后核对差异化与守卫清单（①–⑤）全部保持现状——① 两入口标题/footer/空态文案；② 编号缺失用法示例（`/接取悬赏 1` vs `/宗门 悬赏 接取 307`）；③ 全局接取/完成/放弃有 `✅/❌` 前缀、宗门无；④ 全局列表无空态早退；⑤ `_sub_bounty` 重构后仍保留两处前置守卫（`sect_handlers.py:209-211` `bounty_mgr=None` →「❌ 悬赏功能不可用！」；`:212-216` 无宗门 →「❌ 你还未加入宗门！加入宗门后可使用「宗门 悬赏」。」），共享函数调用不得绕过或改动这两段

## 3. 测试与质量门

- [ ] 3.1 `tests/test_sect_handlers.py` 既有用例（`:168,:282,:307,:331,:355` 等构造点不传排行依赖）原样全绿；新增最小断言：(a) `rank_mgr=None` 时 `/宗门 排行` 输出「排行功能不可用」；(b) MagicMock `bounty_mgr` 场景下 `/宗门 悬赏` 列表经共享函数渲染（标题「宗门悬赏 · 本宗委托」）；如需复用全局悬赏断言，确认 `tests/` 现有 bounty 用例覆盖不受薄委托改造影响
- [ ] 3.2 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过
- [ ] 3.3 宗门域功能用例回归：`uv run python scripts/test_suite_ctl.py run --tag sect`（按 AGENTS.md 约定由用户发起，AI 只保证 pytest/ruff 质量门）

## 4. 文档同步与收尾

- [ ] 4.1 `design_docs/api-overview.md`：`:55` SectHandlers 行补「排行/贡献排行 → `RankingManager` 直调（原 RankingHandlers 两方法已收编）」；`:68` RankingHandlers 行收敛为「境界/战力/灵石/存款排行」（移除宗门/贡献）
- [ ] 4.2 检查 `handlers/misc_handler.py:100,:120` 帮助文本无需改动（本就指向「宗门 排行」「宗门 贡献排行」入口）；核对 `AGENTS.md` 与 `README.md` 无「SectHandlers 持有 ranking_handlers」类实现描述需要同步（本次纯重构无玩法变化，按 §7 checklist 通常无需升版本号，核对后定论）
- [ ] 4.3 `openspec validate --changes decouple-handler-to-handler-calls` 通过；本地 conventional commit（不 push）
