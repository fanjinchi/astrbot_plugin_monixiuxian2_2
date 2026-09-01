# Design: fix-fake-atomic-transactions

## Context

失效机理与逐块侦察结论见 proposal.md（Why / Impact）。设计侧只需明确以下现状约束：

- 全库单一 `aiosqlite` 连接（`data/data_manager.py:60-62`，`db.ext` 的 `DatabaseExtended` 与 `DataManager` 共享同一 `conn`），`BEGIN IMMEDIATE` 在连接级生效；任何路径上的 `conn.commit()` 都会终结当前事务并释放写锁，与同连接上还有几个语句未执行无关——这是"假原子"的物理根因：外层块内第一个自提交 helper（如 `update_player`，`data/data_manager.py:137`）执行后，后续语句退化为逐条自动提交，中途异常时 `rollback()` 已无可回滚内容。
- 已确立的修复模式（宗门路径，commit `c39c42a` 起）：数据层 helper 加 `commit: bool = True` 参数——`True` 时自行提交（存量独立调用方行为不变），`False` 时只执行语句、假定外层事务统一提交（样板：`database_extended.py:454` `set_active_legacy_instance` 的 docstring 约定；调用样板：`sect_manager.py:888-890`、`impart_manager.py:235-242`、`player_handler.py:519-520`）。
- 既有中间层先例：`storage_ring_manager.store_item` 与 `data_manager.decrement_shop_item_stock` 已有 `external_transaction: bool` 参数——但该参数只跳过自身的 `BEGIN/COMMIT/ROLLBACK`，**不阻止**其内部再调用的 `update_player` 自提交（`storage_ring_manager.py:139`），所以商店购买事务（`shop_handler.py:208`）即使全程 `external_transaction=True` 仍被击穿。
- review 复查补认两处事实（均已带行号复核采纳）：商店购买块内还有第二个自提交点 `_apply_legacy_pill_effects`（`shop_handler.py:261` 调用，其 :454 `update_player` 默认 commit=True）；同一临界区内存在成功路径丢货扣钱 bug（见 D5）。
- 干净的块不动：bounty 三块、spirit_eye 一块、impart/player_handler/sect 已修块（清单见 proposal Impact）。
- 测试基建：`tests/helpers.py` 的 `load_module()` / `load_package_module()` 绕过 `__init__.py` 链；`conftest.py` 已 mock astrbot；既有用例用临时文件 sqlite（如 `test_sect_master.py`、`test_shop_handler.py` 的 fixture 模式）。

## Goals / Non-Goals

**Goals:**

- 9 个假原子事务块恢复真实原子性：块内所有写要么随外层 commit 一并落盘，要么随 rollback 全部撤销
- 商店购买成功路径不再丢货扣钱：物品写入与扣款写回落在同一 player 对象（D5）
- 修复模式与宗门路径完全一致（helper 加 `commit` 参数、外层统一提交），不引入第二种事务风格
- 全部存量调用方行为不变（`commit` 参数默认 `True`），既有测试保持绿
- 新增回归测试能机器化地防回退：helper 在 `commit=False` 下不得触碰 commit；购买装备类商品成功路径有断言

**Non-Goals:**

- 不给"完全没有事务"的路径补事务（`bank_manager.claim_interest`、`check_and_process_overdue_loans`——缺事务是另一类问题，另立 bd 评估）
- 不引入 `SAVEPOINT`、连接池、上下文管理器式事务封装等架构改造——本变更只收敛到既有模式
- 不动数据层自包含事务（`decrement_shop_item_stock`/`increment_shop_item_stock`/`set_active_legacy_instance`/`learn_or_star_up`）——它们无外层嵌套调用方，行为正确
- 不改任何数值、流程与玩家可见行为

## Decisions

### D1：统一采用"helper 加 `commit: bool = True` 参数"，不引入 `external_transaction` 式新开关

- 数据层补齐：`data_manager.delete_player_cascade`；`database_extended` 的 `update_bank_account`、`create_loan`、`close_loan`、`mark_loan_overdue`、`add_bank_transaction`。`commit=False` 时只执行语句不提交；docstring 沿用 `database_extended.py:454` 的既有措辞（True 自行提交/False 假定外层事务）。
- manager/handler 层透传：`bank_manager._add_transaction`、`pill_manager.add_pill_to_inventory`、`shop_handler._apply_legacy_pill_effects`（handler 私有方法，透传给其 :454 的 `update_player`）加同名参数并透传。
- **理由**：与宗门修复完全同构，reviewer 只需核对一种模式；默认 `True` 保证 `player_handler.py:629`、`breakthrough_manager.py:400`、`bank_manager.py:384` 等独立调用方零改动。备选"给块内调用包一层 `conn.execute` 直写 SQL"放弃：绕过 helper 会复制 helper 内的 SQL 与字段映射，制造第二处漂移源（`delete_player_cascade` 的级联语句清单尤其不能复制）。

### D2：`create_loan` 的 `last_insert_rowid` 查询随 commit=False 留在事务内

`database_extended.py:1268-1271` 当前是 INSERT → commit → `SELECT last_insert_rowid()`。改 `commit=False` 后查询仍在同一连接同一事务内执行，`last_insert_rowid()` 语义不变（连接级状态，与是否提交无关）。实现时只需把 commit 包进 `if commit:`，查询语句保持原位。

### D3：储物戒三方法按"自身事务归属"决定 `update_player` 的 commit 传参

- `store_item`：`external_transaction=True`（外层有事务）→ `update_player(player, commit=False)`；`False`（自身 BEGIN）→ 同样 `commit=False`，由自身块尾统一 commit——两种路径下块内都不允许出现提前提交。
- `retrieve_item` / `discard_item`：无 `external_transaction` 参数，自身 BEGIN 的块内 `update_player` 一律 `commit=False`。
- **理由**：`external_transaction` 参数维持原语义（只管 BEGIN/COMMIT 归属），不扩展其含义；内层写的提交归属统一由 `commit` 参数表达，两个开关各管一层、语义不纠缠。修复后 `shop_handler.py:234/:270/:283` 的调用点无需改动即自动受益。
- 注：D3 只解决"提前提交"；`store_item` 内部重取 fresh_player 导致的成功路径覆盖问题由 D5 另行决策。

### D4：逐块修复策略（块内 helper 全量改 commit=False，外层唯一提交点）

| 块 | 位置 | 块内改动 |
|---|---|---|
| 银行-存款 | `managers/bank_manager.py:109` `deposit` | `update_player`→`commit=False`；`update_bank_account`→`commit=False`；`_add_transaction`→`commit=False` |
| 银行-取款 | `managers/bank_manager.py:152` `withdraw` | 同上三处 |
| 银行-贷款 | `managers/bank_manager.py:252` `borrow`（方法定义 :236） | `create_loan`/`update_player`/`_add_transaction`→`commit=False` |
| 银行-还款 | `managers/bank_manager.py:310` `repay` | `update_player`/`close_loan`/`_add_transaction`→`commit=False` |
| 储物戒-存入 | `core/storage_ring_manager.py:119` `store_item` | `update_player`→`commit=False`（D3）；重取行为按 D5 调整 |
| 储物戒-取出 | `core/storage_ring_manager.py:164` `retrieve_item` | `update_player`→`commit=False` |
| 储物戒-丢弃 | `core/storage_ring_manager.py:201` `discard_item` | `update_player`→`commit=False` |
| 商店-购买 | `handlers/shop_handler.py:208` | `update_player`（:301）→`commit=False`；`add_pill_to_inventory`（:254）与 `_apply_legacy_pill_effects`（:261 → 其 :454 `update_player`）透传 `commit=False`；`decrement_shop_item_stock`/`store_item` 的 `external_transaction=True` 调用保持不变 |
| 逾期追杀 | `handlers/utils.py:161` `_check_loan_status` | `delete_player_cascade`/`mark_loan_overdue`/`add_bank_transaction`→`commit=False` |

每块的 `commit`/`rollback` 结构与早退分支保持原样，只改 helper 传参——失败路径的 `rollback()` 修复后才真正生效，这正是本变更要恢复的行为。

### D5：商店购买成功路径的陈旧 player 覆盖修复（review 复查实证，纳入本变更）

**实证过程简述**：审查者在临时 sqlite 上实证——`store_item(external_transaction=True)` 内部重取 fresh_player 并把局部变量重绑定到新对象（`storage_ring_manager.py:121-126`），物品写入该新对象后整行写回（:139）；而 `shop_handler.py:210` 持有的 player 是事务开始时的另一对象，`storage_ring_items` 仍是旧值，:300-301 扣款后用它再次整行写回，把 :139 刚写入的物品**覆盖回旧值**。结果：武器/防具/心法/功法/饰品（:227-252）、材料（:269-281）、功法（:282-294）分支购买成功但丢货扣钱。pill（:253-259，经 `add_pill_to_inventory` 在传入的同一对象上改背包并写回）与 legacy_pill（:260-268，经 `_apply_legacy_pill_effects` 在同一对象上改属性/背包，:454 写回）分支因全程操作同一对象而不受影响。

**方案对比**：

- 方案 A（shop 侧在最终 `update_player` 前重取 player）：改动局部于 shop_handler；但 pill/legacy_pill 分支在旧对象上累积的背包/属性改动会被统一重取丢弃，只能"仅 store 分支后重取"的差异化处理——同一事务块内分支间对象来源不一致，易留坑，且没消除"两个 player 对象整行写回"的结构性根源。
- 方案 B（**推荐**：`store_item` 在 `external_transaction=True` 时不再内部重取，直接作用于调用方传入的 player 对象）：`BEGIN IMMEDIATE` 写锁内无并发写者，shop 块入口 :210 已重取过，二次重取本就冗余；物品 mutation 与 :300-301 扣款写回落在同一对象，结构性消除整行覆盖。`external_transaction=False` 的独立调用路径保持重取语义不变（无外层事务时重取仍有"读最新"价值）。影响面核查：全库 `external_transaction=True` 仅 `shop_handler.py:235/:271/:284` 三个调用点，行为变化范围可控。

**配套约束**：`store_item` docstring 须注明 `external_transaction=True` 要求外层事务入口已重取 player（写锁内该对象即最新）；实施者若发现 shop 侧还有其他在 store 之后基于旧对象的写，需在实施时一并核对（当前仅 :300-301 一处）。

**回归断言**：纳入 D6 测试——购买装备类商品（武器/材料各一）成功路径断言"储物戒确有该物品且灵石正确扣除"（修复前必红、修复后转绿）；pill 购买断言背包正确入账（防方案 B 引入回归）。

### D6：并发/回滚回归测试思路（pytest，纯单元层，不依赖 webtest 平台）

新增 `tests/test_transaction_atomicity.py`（用 `tests/helpers.py` 的 `load_package_module` 加载 data 层、`load_module` 加载 manager 层，fixture 用临时文件 sqlite，模式对齐 `test_sect_master.py`）：

1. **helper 守约测试**：对每个改了签名的数据层 helper，以 `commit=False` 调用后同连接 SELECT 可见、rollback 可撤销（证明未自行提交）；以默认 `commit=True` 调用验证落盘（证明存量语义不变）。
2. **中途失败回滚测试**：对 9 个块中的代表性路径（银行存款、储物戒取出、商店购买、逾期追杀各一），在块内最后一个写操作处注入异常（monkeypatch 对应 ext helper 抛错），断言：已写的中间状态全部回滚（玩家灵石/银行账户/贷款记录/流水均保持调用前快照）。修复前这些断言必然失败（第一个 helper commit 后 rollback 失效），修复后转绿——即回归闸门。
3. **嵌套防护**：断言修复后的事务块在执行期间连接始终处于事务内（`conn.in_transaction` 在块内每个 helper 调用后仍为 True），直接机器化"无人提前提交"。
4. **购买成功路径不回退**（D5 配套）：装备类（武器/材料）购买后断言储物戒确有物品且灵石正确扣除；pill 购买后断言背包正确——修复前装备类断言必红。
- 既有 `test_shop_handler.py` 等用 AsyncMock 替代 helper 的用例不受影响（mock 透传 `commit=False` 关键字参数即可，若断言签名严格则需同步补参）。

## Risks / Trade-offs

- [漏改块内某个 helper 调用，该块仍是假原子] → D4 表格逐块逐调用点列清单（review 复查已补认 `_apply_legacy_pill_effects` 遗漏点），tasks 按块勾选；D6-3 的 `in_transaction` 断言对每块机器化兜底
- [`commit` 参数默认值写错（默认 False）导致存量调用方不落盘] → 统一默认 `True`；D6-1 的默认路径测试卡住
- [D5 方案 B 改变 `store_item` 在外层事务下的对象语义，若未来新调用方在外层事务内却未先重取 player，将基于旧对象操作] → 当前全库仅商店三个调用点且 :210 已重取；docstring 注明前置约束；D6-4 成功路径断言兜底
- [`delete_player_cascade` 的 `safe_execute` 吞错语义与 rollback 交互变化：修复前单语句失败被吞且已提交，修复后随外层回滚] → 这是恢复设计意图（追杀致死要么完整生效要么不生效）；其独立调用方（`player_handler.py:629` 等）仍走默认 commit=True，行为不变
- [AsyncMock 型既有测试对新关键字参数断言不通过] → 修复时全量跑 `pytest tests/`，签名严格断言处同步补 `commit=False` 传参（属测试适配，不改断言意图）

## Migration Plan

纯代码变更，无 schema/配置迁移：helper 默认参数保证灰度为零（未改传参的调用方行为逐字节不变）。部署 = 重载插件；回滚 = git revert。落地后关闭 bd `rc0`，并把"缺事务"的两个顺带观察（`claim_interest` / `check_and_process_overdue_loans`）登记为新 bd。

## Open Questions

（无——逐块侦察已在 proposal 阶段完成并经 review 复查补正，修复模式有宗门先例，无疑惑需要推迟。）
