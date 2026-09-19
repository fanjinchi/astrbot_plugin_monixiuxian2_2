## 1. 锚点复核与前置确认（apply 首步，必做）

- [ ] 1.1 逐 spot 复核当前 file:line 与分段边界（以 design D1 表为对照）：`grep -n "conn.commit()" managers/spirit_farm_manager.py managers/spirit_eye_manager.py managers/blessed_land_manager.py managers/dual_cultivation_manager.py core/gm_manager.py`；确认与本 change 的 9 例清单一一对应（不扩不缩），漂移的锚点在本文件回写为实际行号
- [ ] 1.2 检查 9 处函数体内是否**没有**手工 `BEGIN IMMEDIATE`（CM 不得嵌在裸 BEGIN 块内）：`grep -n "BEGIN" <5 文件>`；有冲突则停下并在 design D1 补记
- [ ] 1.3 复跑依赖的叶子门控清单（design Context 所列）确认仍然存在：`grep -rn "D2 ownership gate" data/ core/`；若某叶子门控已被删除/改写，先修正 design 再开工
- [ ] 1.4 登记活跃 change 落地状态：`git log --oneline -5 -- core/gm_manager.py managers/dual_cultivation_manager.py tests/test_transaction_atomicity.py`；据 design D6 判断 S8/S9 是否需按新形态锚定（`busy-state-owner` 落地则步骤 1 已是 `clear(player)`；`gm-time-skip-registry` 落地则 S9 步骤 3 的 SQL 可能已迁属主模块）
- [ ] 1.5 采集本 change 的失败基线：`uv run python -m pytest tests/ -q`（应为 `872 passed, 1 xfailed`），记录为验收对照

## 2. S1-S3：`managers/spirit_farm_manager.py`（灵田 3 处）

- [ ] 2.1 `create_farm`（:79，裸 commit :99）：写段包 `async with self.db.transaction():`，删 :99 裸 commit；校验读（`get_user_farm`、灵石检查）留在 CM 外
- [ ] 2.2 `harvest`（:149，裸 commit :216）：包住"发奖 `update_player` + `store_item` 循环 + `UPDATE spirit_farms SET crops`"，删 :216；`store_item` 失败分支的文案逐字保留
- [ ] 2.3 `upgrade_farm`（:241，裸 commit :265）：包住"扣费 + 等级 UPDATE"，删 :265
- [ ] 2.4 核验：`grep -n "conn.commit()" managers/spirit_farm_manager.py` 只应剩下 `create_farm` 无关的 `plant_herb`:140（单语句自包含，Non-Goal）；本文件其余 3 处裸 commit 归零

## 3. S4：`managers/spirit_eye_manager.py`（灵眼 1 处）

- [ ] 3.1 `collect_spirit_eye`（:120，裸 commit :147）：包住"发修为 `update_player` + `UPDATE spirit_eyes SET last_collect_time`"，删 :147；冷却校验（`hours_passed < 1`）留在 CM 外
- [ ] 3.2 核验：本文件裸 commit 只剩 `spawn_spirit_eye`:66 与 `release_spirit_eye`:170（均为单语句自包含，Non-Goal）；`claim_spirit_eye`:70-72 已是 CM，不动

## 4. S5-S7：`managers/blessed_land_manager.py`（洞天 3 处）

- [ ] 4.1 `purchase_blessed_land`（:72，裸 commit :116）：包住"扣费 + `INSERT INTO blessed_lands`"，删 :116
- [ ] 4.2 `upgrade_blessed_land`（:127，裸 commit :164）：包住"扣费 + `UPDATE blessed_lands`（level/exp_bonus/gold_per_hour）"，删 :164
- [ ] 4.3 `collect_income`（:174，裸 commit :208）：包住"发灵石/修为 + `UPDATE blessed_lands SET last_collect_time`"，删 :208；`max_exp_per_hour` 上限逻辑与文案不动
- [ ] 4.4 核验：`grep -n "conn.commit()" managers/blessed_land_manager.py` 应无命中

## 5. S8：`managers/dual_cultivation_manager.py`（双修四叶提交）

- [ ] 5.1 三个叶子补 D2 门控（照 `data/data_manager.py:322-325` 的形态，含注释）：`_get_pending_request`（:143，删裸 commit :151 改为门控）、`_delete_request`（:174，:179）、`_set_last_dual_time`（:330，:340）
- [ ] 5.2 `accept_request`（:237）：把"`update_player(initiator)` + `update_player(acceptor)` + `_set_last_dual_time` ×2 + `_delete_request`"整段包进一个 CM；确认无"CM 内 return"（4 处早退分支全部前置在 CM 外），故不需要 `txn.abort()`
- [ ] 5.3 核验 CM 外调用方语义不变：`send_request`（:181）与 `reject_request`（:311）在无 CM 时叶子仍独立提交（fail-open 默认 `_txn_depth == 0`）
- [ ] 5.4 核验：`grep -n "conn.commit()" managers/dual_cultivation_manager.py` 只剩门控式提交（`_create_request`:137 保持原样——不在 `accept_request` 路径上、单语句自包含）

## 6. S9：`core/gm_manager.py` 清除全部冷却（GM cosmetic；依赖 Open Question 1 的确认）

- [ ] 6.1 若用户确认纳入：`data/database_extended.py` 的 `cancel_bounty`（:1087，commit :1093）与 `set_system_config`（:1105，commit :1116）补 D2 门控（fail-open）
- [ ] 6.2 `cmd_clear_all_cooldowns`（:1204）：步骤 1-5 的 DB 写段包进 CM，删裸 commit :1246 与 :1257（步骤 2 `combat_cooldowns`、步骤 3 `dual_cultivation` 的 UPDATE 改为 CM 内执行）
- [ ] 6.3 步骤 6 的**内存态**历练路线休整冷却弹出（`adventure_manager._route_cooldowns.pop`）移到 CM 块退出**之后**（内存不可回滚，回滚时不得弹）
- [ ] 6.4 语义核验：清除范围、`cleared` 行文案、幂等性、`没有可清除的冷却状态！` 分支逐字不变；步骤 1 若 `busy-state-owner` 已落地则包裹其 `clear(player)` 调用形态
- [ ] 6.5 若用户选择"最小范围"（Open Question 1 结论为推迟）：跳过 6.1-6.4，在本文件记录决策与替代 bd 登记，其余阶段不受影响

## 7. 测试：`tests/test_transaction_atomicity.py` 追加 §8（append-only）

- [ ] 7.1 追加 §8 章节头（说明覆盖 S1-S9 两段式/四叶提交的原子性契约，引用本 change 与 bd `-2w1`）
- [ ] 7.2 S1-S7 逐 spot 三条断言：第 2 段写注入异常 → 第 1 段回滚；正常路径两段都落盘且退出后 `db.conn.in_transaction is False`；`_spy_in_transaction` 断言 CM 内每个叶子调用 `_txn_depth > 0`
- [ ] 7.3 S8 断言：第 2 个 `update_player` 之后注入异常 → 双方修为、`dual_cultivation` 时间戳、请求行全部保持操作前状态；正常路径 = 修为已加、时间戳已写、请求已删、退出后已提交
- [ ] 7.4 S9 断言：步骤 3 的 `dual_cultivation` UPDATE 注入异常 → `combat_cooldowns` 状态未被清且**内存态修炼路线冷却未被弹出**；正常路径 = 全清、回复逐字不变
- [ ] 7.5 门控叶子回归：`_set_last_dual_time`/`_delete_request`/`_get_pending_request`（及 S9 的 `cancel_bounty`/`set_system_config`）在 **CM 外**独立调用仍提交（fail-open 语义不变）
- [ ] 7.6 跑本节测试：`uv run python -m pytest tests/test_transaction_atomicity.py -v`

## 8. 质量门与验收

- [ ] 8.1 `uv run ruff format .`
- [ ] 8.2 `uv run ruff check .`
- [ ] 8.3 `uv run python -m pytest tests/ -v`：全绿（`872 + §8 新增` passed, `1 xfailed`），无新增 warning/失败
- [ ] 8.4 裸 commit 闸门：`grep -rn "await self.db.conn.commit()" managers/ core/ | grep -v tests` 与 1.1 的快照对比——本 change 的 9 例全部消失，且**未引入**其它改动
- [ ] 8.5 `uv run openspec validate --changes fix-two-stage-commit-atomicity` 通过（且 `--all` 基线 22 items 仍全过）

## 9. 关闭与文档同步

- [ ] 9.1 bd 关闭：`bd close astrbot_plugin_monixiuxian2_2-2w1 --reason "9 例 CM 收编完成，commit <hash>，测试 §8 覆盖" --json`
- [ ] 9.2 Open Question 2 落地：`managers/bounty_manager.py abandon_bounty`（:530）两次自提交叶子的同族隐患按用户结论另立 bd（`bd create ... --json`，并在 2w1 关闭说明里挂 `discovered-from`）
- [ ] 9.3 conventional commit 提交（如 `fix(transaction): wrap two-stage commits of 9 spots in unit-of-work CM`），**不 push**
- [ ] 9.4 文档同步核对：本 change 不改数值/玩法 → `design_docs/` 与 `design_docs/content-design/` 无需改动；核对 AGENTS.md §3 的转换规则段落无需新增（前置 change 已写入），`git status` 干净
