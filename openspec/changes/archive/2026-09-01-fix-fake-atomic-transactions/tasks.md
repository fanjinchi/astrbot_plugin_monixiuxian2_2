# Tasks: fix-fake-atomic-transactions

## 1. 数据层 helper 补 commit 参数（默认 True，存量调用方零改动）

- [x] 1.1 `data/data_manager.py` `delete_player_cascade`（:144）加 `commit: bool = True` 参数，末尾 `commit`（:193）包进 `if commit:`；docstring 补参数约定（沿用 `database_extended.py:454` 措辞）
- [x] 1.2 `data/database_extended.py` `update_bank_account`（:992）、`close_loan`（:1273）、`mark_loan_overdue`（:1280）、`add_bank_transaction`（:1311）各加 `commit: bool = True`，内部 commit 包 `if commit:`
- [x] 1.3 `data/database_extended.py` `create_loan`（:1253）加 `commit: bool = True`；commit 包 `if commit:`，`SELECT last_insert_rowid()` 保持原位随事务内执行（design D2）

## 2. manager/handler 层透传参数

- [x] 2.1 `managers/bank_manager.py` `_add_transaction`（:400）加 `commit: bool = True` 并透传给 `ext.add_bank_transaction`
- [x] 2.2 `core/pill_manager.py` `add_pill_to_inventory`（:654）加 `commit: bool = True` 并透传给 `update_player`
- [x] 2.3 `handlers/shop_handler.py` `_apply_legacy_pill_effects`（:345）加 `commit: bool = True` 并透传给其 :454 的 `update_player`（review 复查补认的块内第二个自提交点）

## 3. 逐块修复：managers/bank_manager.py（4 块）

- [x] 3.1 `deposit`（:109 块）：`update_player`（:127）、`update_bank_account`（:131）、`_add_transaction`（:137）改传 `commit=False`，外层 commit/rollback 结构不变
- [x] 3.2 `withdraw`（:152 块）：`update_bank_account`（:162）、`update_player`（:167）、`_add_transaction`（:169）改传 `commit=False`
- [x] 3.3 `borrow`（:252 块，方法定义 :236）：`create_loan`（:272）、`update_player`（:277）、`_add_transaction`（:281）改传 `commit=False`
- [x] 3.4 `repay`（:310 块）：`update_player`（:331）、`close_loan`（:333）、`_add_transaction`（:337）改传 `commit=False`

## 4. 逐块修复：core/storage_ring_manager.py（3 块，design D3）

- [x] 4.1 `store_item`（:119 块）：块内 `update_player`（:139）改传 `commit=False`（`external_transaction` 两分支同样不提前提交）；`external_transaction` 参数语义不变（重取行为调整另见 6.1）
- [x] 4.2 `retrieve_item`（:164 块）：块内 `update_player`（:187）改传 `commit=False`
- [x] 4.3 `discard_item`（:201 块）：块内 `update_player`（:226）改传 `commit=False`

## 5. 逐块修复：handlers（2 块）

- [x] 5.1 `handlers/shop_handler.py` 购买事务（:208 块）：`update_player`（:301）改 `commit=False`；`add_pill_to_inventory`（:254）与 `_apply_legacy_pill_effects`（:261）透传 `commit=False`；`decrement_shop_item_stock`/`store_item` 的 `external_transaction=True` 调用保持不变（储物戒修复后自动受益，design D3）
- [x] 5.2 `handlers/utils.py` `_check_loan_status`（:161 块）：`delete_player_cascade`（:177）、`mark_loan_overdue`（:180）、`add_bank_transaction`（:183）改传 `commit=False`

## 6. 商店购买成功路径陈旧 player 覆盖修复（review 实证，design D5 方案 B）

- [x] 6.1 `core/storage_ring_manager.py` `store_item`：`external_transaction=True` 时不再内部重取 fresh_player（:121-126），直接作用于调用方传入的 player 对象（写锁内 `shop_handler.py:210` 已重取，二次重取冗余）；`external_transaction=False` 独立调用路径保持重取语义；docstring 注明该参数要求外层事务入口已重取 player
- [x] 6.2 复核 `shop_handler.py` 购买块对象一致性：store_item/pill/legacy_pill 分支的 mutation 与 :300-301 最终 `update_player(player, commit=False)` 落在同一 player 对象，pill 分支背包累加不丢失；实施时顺带核对块内是否还有其他基于旧对象的写（当前仅 :300-301 一处）

## 7. 并发回归测试（design D6）

- [x] 7.1 新增 `tests/test_transaction_atomicity.py`（`load_package_module` 载 data 层、`load_module` 载 manager 层，临时文件 sqlite fixture 对齐 `test_sect_master.py` 模式）：helper 守约测试——每个改了签名的 helper 以 `commit=False` 调用后同连接 SELECT 可见、rollback 可撤销（未自行提交），默认 `commit=True` 调用落盘（存量语义不变）
- [x] 7.2 中途失败回滚测试：银行存款、储物戒取出、商店购买、逾期追杀各一条路径，在块内最后一个写操作注入异常，断言中间状态全部回滚（灵石/账户/贷款/流水保持调用前快照）
- [x] 7.3 嵌套防护断言：修复后各事务块内每个 helper 调用后 `conn.in_transaction` 仍为 True（机器化"无人提前提交"）
- [x] 7.4 购买成功路径回归（design D6-4）：购买装备类商品（武器/材料各一）后断言储物戒确有该物品且灵石正确扣除（修复前必红）；pill 购买后断言背包正确入账
- [x] 7.5 全量跑 `uv run python -m pytest tests/ -q`；AsyncMock 型既有用例（如 `test_shop_handler.py`、`test_pill_manager.py`）若因新关键字参数签名断言失败，同步补传参适配（不改断言意图）

## 8. 收尾

- [x] 8.1 `openspec validate fix-fake-atomic-transactions --strict` 通过
- [x] 8.2 `uv run ruff format . && uv run ruff check .` 全绿；全量 `uv run python -m pytest tests/ -q` 通过
- [x] 8.3 版本 checklist（AGENTS.md §7）：`metadata.yaml` version 递增、`README.md` 更新日志追加；`/修仙帮助` 文本不涉及指令变化无需更新；本修复为纯 bug 修复不影响玩法——design_docs 无需更新（AGENTS.md §14 例外），无需 migration
- [x] 8.4 关闭 bd `astrbot_plugin_monixiuxian2_2-rc0`；顺带观察项另立 bd：`bank_manager.claim_interest`（:182）与 `check_and_process_overdue_loans`（:364）多步写无事务（缺事务，非假原子）
