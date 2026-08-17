# Tasks: fix-functional-test-bugs

## 1. 修复 handle_spar UnboundLocalError（bd tbp）

- [x] 1.1 阅读 `managers/combat_manager.py` 的 `player_vs_player`，确认切磋对应的 `combat_type` 取值（`handle_duel` 使用 `combat_type=2` 表示决斗）
- [x] 1.2 在 `handlers/combat_handlers.py` 的 `handle_spar` 中，`p1`/`p2` 校验通过后补上 `result = await self.combat_mgr.player_vs_player(p1, p2, combat_type=<切磋值>)`（含中文注释说明切磋语义）
- [x] 1.3 在 `tests/test_combat_handlers.py`（或就近的切磋测试文件）补充回归用例：mock 战斗引擎后调用 `handle_spar`，断言不再抛 `UnboundLocalError` 且输出包含战斗日志

## 2. 修复 set_user_busy 不落库（bd qv9）

- [x] 2.1 确认 `user_cd.extra_data` 列在 `data/migration.py` 所有迁移路径的表结构上均存在（upsert 语句将引用该列）
- [x] 2.2 将 `data/database_extended.py` 的 `set_user_busy` 改为单条 `INSERT ... ON CONFLICT(user_id) DO UPDATE`（见 design.md D2），并同步更新 docstring
- [x] 2.3 在 `tests/` 补充用例：对无 `user_cd` 行的用户调用 `set_user_busy` 后，`get_user_cd` 能查到对应忙碌记录；对已有行调用则更新字段

## 3. GM 发放支持心法等全部物品类型（bd 7px）

- [x] 3.1 按 design.md D3，在 `core/gm_manager.py` 的 `_item_exists` 中扩展检查清单（至少纳入 `heart_methods_data`，以 `config_manager.load_all` 实际加载的物品类表为准）
- [x] 3.2 在 `tests/` 补充用例：`_item_exists("长春功")` 返回 True；不存在物品仍返回 False
- [x] 3.3 确认 `storage_ring_manager.store_item` 对心法类型可正常入戒（失败时有错误提示即可，不静默）

## 4. 验证与收尾

- [x] 4.1 运行 `uv run python -m pytest tests/ -v` 全部通过
- [x] 4.2 运行 `uv run ruff format . && uv run ruff check .` 无问题
- [x] 4.3 重载插件后通过测试平台重跑 `pvp-basic-spar`（预期由失败转为通过）及 `gm-basics` 相关用例
- [x] 4.4 按版本更新 checklist 更新 `metadata.yaml` 版本号与 `README.md` 更新日志；本次为纯 Bug 修复，不改 `design_docs/` 玩法资料
- [x] 4.5 验证通过后关闭 bd issue `astrbot_plugin_monixiuxian2_2-tbp` / `-qv9` / `-7px`（`bd close --reason`）
