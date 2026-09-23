# Tasks — decouple-handler-to-handler-calls

## 0. 前置检查

- [ ] 0.1 **行号重新锚定（composition-root 已合入）**：`composition-root`（main.py 装配段重构为 `_wire_core_services()`、`SectHandlers` 改经构造注入 `ranking_handlers`、删原 main.py:350 回填）已于 2026-09-22 合入归档，本 change 的 main.py 引用已按其装配结构重锚（构造点现位于 `_wire_core_services()` 内 `:414-420`，`rank_mgr` 在 `:333-338`）。`busy-state-owner`（sect_handlers.py 守卫收编，2026-09-23 合入归档）已移动 sect_handlers.py 行号，本文档行号已按其后工作树重锚（镜像 busy-state-owner tasks 0.1 的约定）。**已定序（2026-09-21）：`composition-root` → `busy-state-owner` → 本 change**——busy-state 先合入时，`SectHandlers.__init__` 已带 `busy_state` 参数，本 change 的 1.4 步在其上**叠加** `rank_mgr`（不得改名/删除 `busy_state`），构造调用点同步传两者。
- [ ] 0.2 ⚠ **开工前用户前置动作（任何编辑之前完成）**：在真实 bot 会话、**当前（重构前）代码**上抓取 4 组输出快照——全局「悬赏令」「接取悬赏」「宗门 排行」「宗门 贡献排行」。**AI 不代跑**（按 AGENTS.md「真实环境功能测试由用户手动发起」），快照由用户保存、2.4 复核依赖之。快照清单**不含「宗门 悬赏」**：宗门侧格式已被功能用例钉住（`functional_tests/cases/sect/sect-bounty-lifecycle.json:56` footer 正则、`sect-bounty-split.json:74`、无宗门守卫 `lifecycle:63`），豁免。若用户选择跳过，2.4 的逐字比对降级为「以 functional_tests 宗门用例 + 既有 pytest 为准」，须在 2.4 勾选时注明。

## 1. 排行子命令收编（消除 handler→handler 调用）

- [ ] 1.1 `handlers/ranking_handlers.py`：删除 `handle_rank_sect`（:30-33）与 `handle_rank_sect_contribution`（:40-56）两方法；类 docstring（:9）「sect, and sect-contribution」表述同步收敛；`main.py:1271-1297` 的四个全局排行路由不受影响（删除后 `self.db` 将无读者，但**构造签名 `(db, rank_mgr)` 保持不变**——`main.py:413` 照传，不顺手"清理"产生无关 diff）
- [ ] 1.2 `handlers/sect_handlers.py`：新增 `handle_sect_rank`（原 `handle_rank_sect` 实现体，直调 `self.rank_mgr.get_sect_ranking()`，返回 `(success, msg)`）与 `handle_sect_contribution_rank`（仅保留「❌ 你尚未加入任何宗门，无法查看宗门贡献排行。」拒绝分支；**删除原 `:45-49`「未踏入仙途」分支——经 `handle_sect_entry` 的 `@player_required` 兜底该分支不可达，属死代码**）。**形态定案：两新方法为普通 async 方法，返回 `(success, msg)`（非生成器）**；`_sub_rank*` 调用后 `yield event.plain_result(msg)` 转发。docstring 用英文 Google 风格（AGENTS.md：新代码一律英文 docstring），保留原方法的中文一行 docstring 语义（"宗门排行" / "宗门贡献排行（当前所在宗门）"）翻译即可
- [ ] 1.3 `handlers/sect_handlers.py:30-43`：`__init__` 签名 `ranking_handlers=None` 参数替换为 `rank_mgr=None`（`self.rank_mgr = rank_mgr`）；`_sub_rank` / `_sub_rank_contribution`（:198-210）改为直调新方法与 `rank_mgr`，`rank_mgr=None` 时保留输出「❌ 排行功能不可用！」（与现状逐字一致）
- [ ] 1.4 `main.py`（`_wire_core_services()` 装配段，`:245-508`）：原 `:350` 回填语句与 `:340` 构造注释已随 composition-root 删除，现为构造注入 `sect_handlers = SectHandlers(self.db, sect_mgr, bounty_mgr, ranking_handlers=ranking_handlers, busy_state=busy_state)`（`:414-420`，注入点 `:418`）——本步把 `ranking_handlers=ranking_handlers` 入参改为 `rank_mgr=rank_mgr`（**busy-state 先合入，构造调用示例定型为 `SectHandlers(db, sect_mgr, bounty_mgr, busy_state=busy_state, rank_mgr=rank_mgr)`，`busy_state` 与 `rank_mgr` 并存**）。**`ranking_handlers = RankingHandlers(self.db, rank_mgr)`（`:413`）必须保留**——四个全局排行路由（:1271-1297）仍依赖该实例。`rank_mgr` 在装配段 `:333-338` 已先构造，顺序约束已解除

## 2. 悬赏编排共享化（消除 _sub_bounty 复制）

- [ ] 2.1 `handlers/bounty_handlers.py` 新增模块级无状态函数（英文 Google 风格 docstring，注明 stateless 约定）：`format_bounty_entry(b: dict) -> str`（两入口逐字相同的条目 `_format` 块，`bounty_handlers.py:26-34` / `sect_handlers.py:256-264` 去重；独立理由见 design D3——复杂度例外）；`render_bounty_list(bounty_mgr, player, scope) -> str`（按 `scope` 分支标题 `📜 悬赏令 · 今日委托`/`🏯 宗门悬赏 · 本宗委托`、footer 用法行、空态行为：全局无空态早退、宗门空列表输出「🏯 宗门悬赏\n━━━━━━━━━━━━━━━\n本宗当前无可接取的宗门悬赏。」）；`render_bounty_action(bounty_mgr, player, action, args: list[str], scope) -> tuple[bool, str] | None`（**`args` 收字符串列表**，返回 `None` = 未识别 action；接取分支含编号防御：**编号缺失/非数字/<=0 → `scope` 分支编号提示**（「❌ 请指定悬赏编号，例如：/接取悬赏 1」/「❌ 请指定悬赏编号，例如：/宗门 悬赏 接取 307」），防御在共享函数内一次做全、调用方不得绕过；进度/完成/放弃直调 manager 同名方法）。**三函数同步加入 `bounty_handlers.py` 的 `__all__`**（模块公开面，替代仅 `BountyHandlers` 的现状）
- [ ] 2.2 `handlers/bounty_handlers.py`：`handle_bounty_list` / `handle_accept_bounty` / `handle_bounty_status` / `handle_complete_bounty` / `handle_abandon_bounty`（:21-74）改为薄委托调用共享函数（`scope="global"`）；**`✅/❌` 前缀包装保留在全局委托方法内**——共享函数返回 `(success, msg)`，委托方法 `success, msg = result` 后加前缀 `f"{'✅' if success else '❌'} {msg}"`；状态方法不加前缀、直接输出 `msg`（与现状一致）；共享函数本身不加前缀。**5 个委托方法的 docstring 同步改写为「委托 `render_bounty_*`」**（AGENTS.md：docstring 与实现不一致视为 bug）；全局接取的 `bounty_id <= 0` 预检可保留在委托方法内、也可依赖共享函数防御，二者**不得重复输出编号提示**
- [ ] 2.3 `handlers/sect_handlers.py:_sub_bounty`（:214-270）改为调用共享函数（`scope="sect"`）：无参 → `render_bounty_list`；接取/进度/完成/放弃 → `render_bounty_action` 非 None 结果 `(success, msg)` 输出 `msg`（宗门侧无前缀，与现状一致；success 不使用）；`action` 未识别时保留宗门特有提示「❌ 未识别的悬赏操作「{action}」。可用：接取 <编号>｜进度｜完成｜放弃」；**不引入对 `BountyHandlers` 实例的引用**。**落地定案（2026-09-23 评审补）**：① `sect_handlers.py` 顶部新增 `from .bounty_handlers import format_bounty_entry, render_bounty_list, render_bounty_action` 具名导入——不受 `bounty_handlers.py:11` 的 `__all__=["BountyHandlers"]` 影响，且无双循环风险（bounty_handlers 不依赖 sect_handlers）；② 共享函数 `args` 形态：收**字符串列表**——全局委托侧 `handle_accept_bounty` 的 bounty_id 已被 filter 解析为 int（`bounty_handlers.py:44-45`），委托时显式 `args=[str(bounty_id)]`（不发明其它映射；2.4 快照比对兜底）
- [ ] 2.4 逐字比对复核（review checklist）：以 **0.2 用户快照**为基准（未快照则按 0.2 的降级口径执行并注明），核对差异化与守卫清单（①–⑤）全部保持现状——① 两入口标题/footer/空态文案；② 编号缺失用法示例（`/接取悬赏 1` vs `/宗门 悬赏 接取 307`）；③ 全局接取/完成/放弃有 `✅/❌` 前缀、宗门无；④ 全局列表无空态早退；⑤ `_sub_bounty` 重构后仍保留两处前置守卫（`sect_handlers.py:216-218` `bounty_mgr=None` →「❌ 悬赏功能不可用！」；`:219-223` 无宗门 →「❌ 你还未加入宗门！加入宗门后可使用「宗门 悬赏」。」），共享函数调用不得绕过或改动这两段

## 3. 测试与质量门

- [ ] 3.1 `tests/test_sect_handlers.py` 既有用例（`:168,:301,:328,:354,:380` 等构造点不传排行依赖）原样全绿；新增最小断言：(a) `rank_mgr=None` 时 `/宗门 排行` 输出「排行功能不可用」；(b) MagicMock `bounty_mgr` 场景下 `/宗门 悬赏` 列表经共享函数渲染（标题「宗门悬赏 · 本宗委托」）；全局悬赏 handler 用例：**tests/ 无任何 `bounty_handlers` 用例**（grep 零命中），薄委托改造无测试面影响；全局侧行为由 2.4 快照兜底
- [ ] 3.2 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过
- [ ] 3.3 宗门域功能用例回归：`uv run python scripts/test_suite_ctl.py run --tag sect`（按 AGENTS.md 约定由用户发起，AI 只保证 pytest/ruff 质量门）

## 4. 文档同步与收尾

- [ ] 4.1 `design_docs/api-overview.md`：`:56` SectHandlers 行补「排行/贡献排行 → `RankingManager` 直调（原 RankingHandlers 两方法已收编）」；`:69` RankingHandlers 行收敛为「境界/战力/灵石/存款排行」（移除宗门/贡献）
- [ ] 4.2 检查 `handlers/misc_handler.py:100,:120` 帮助文本无需改动（本就指向「宗门 排行」「宗门 贡献排行」入口）；核对 `AGENTS.md` 与 `README.md` 无「SectHandlers 持有 ranking_handlers」类实现描述需要同步（本次纯重构无玩法变化，按 §7 checklist 通常无需升版本号，核对后定论）
- [ ] 4.3 `openspec validate --changes decouple-handler-to-handler-calls` 通过；本地 conventional commit（不 push）
