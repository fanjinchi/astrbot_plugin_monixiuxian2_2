# unify-status-emoji-ownership — Tasks

参考：proposal.md（范围/why）、design.md（D1-D5 决策）。行号以 2026-09-24 审计快照为准，编辑时以实际代码为准。

## 1. core 服务补状态符

- [x] 1.1 `core/skill_manager.py`：`set_study_target` 失败（:501 未拥有/:504 已领悟）补 `❌ `、成功（:507）补 `✅ `；`clear_study_target` 失败（:512）补 `❌ `、成功（:515）补 `✅ `；`can_equip_technique` 装备功法分支（:578/:581/:586/:589）失败补 `❌ `——已核实该分支**无生产消费方**（仅 `tests/test_skill_manager.py:465-501` 子串断言调用，成功返回 `True, ""`），属防御性补符，保证服务层形态统一（§8）
- [x] 1.2 `core/equipment_manager.py`：`equip_item` 失败（:229 透传/:279/:283/:295）补 `❌ `、成功补 `✅ `——**包括**全新装备（:244/:258/:272）、替换路径「已将【X】替换为…{storage_msg}」（:241/:255/:269）、功法已装备（:289-292，评审 G2 补入）；`unequip_item` 失败（:310/:318/:326/:340）补 `❌ `、成功（:314/:322/:330/:338）补 `✅ `
- [x] 1.3 `core/pill_manager.py`：`use_pill` 失败（:76/:81/:90/:112/:143/:376）补 `❌ `；成功消息**全部**已自带 `✨ ` 开头（:130/:156/:282，:413/:476 的 msg_parts[0] 所在 :395/:423 亦同），验证不叠加（D1）
- [x] 1.4 `core/storage_ring_manager.py`：`retrieve_item` 失败（:191 不存在、:196-199 数量不足，评审 G3 补入）补 `❌ `、成功（:211）补 `✅ `；`discard_item` 失败（:223 不存在、:228-231 数量不足，评审 G3 补入）补 `❌ `、成功（:245）首行自带 `🗑️ 已丢弃…`（D1，不叠 ✅，输出与现状逐字一致）；**裁决**：:93/:97/:162（`can_store_item`/`store_item` 检查原因）保持裸——被嵌入方消费的原因文本（依赖清单见 design D5/Risks），不在本 change 改造面；已核实 `storage_ring_handler` 存入命令（:110-124）为**禁用桩**（不调用 store_item），无独立展示包装需处理，原「另行登记」核查分支结案

## 2. 嵌入点去重（与第 1 组同 commit，缺一即双符）

- [x] 2.1 `core/gm_manager.py:871`：`f"❌ 卸下失败：{msg.removeprefix('❌ ')}"`
- [x] 2.2 `core/gm_manager.py:888`：`f"✅ 已卸下…：{msg.removeprefix('✅ ')}{store_msg}"`（`store_msg` 为换行开头拼接段——实为 `\n` 单换行起头（:880/:882-883），非 §8 字面的 `\n\n`，本任务一并按「换行开头拼接段保持裸」处理，tasks 5.1 泛化 §8 措辞）
- [x] 2.3 `handlers/equipment_handler.py:210`：`f"❌ 无法从储物戒取出装备：{retrieve_msg.removeprefix('❌ ')}"`
- [x] 2.4 `handlers/storage_ring_handler.py` `handle_retrieve_all`（:571-587，评审 G1 补入）：`:577` 失败聚合 `failed.append(f"{item_name}：{msg}")` 内嵌消息改 `msg.removeprefix('❌ ')`；`:585` 头行 `"\n❌ 失败：\n"` 为 handler 组装列表的标签行（非包装头）保留，不适用 removeprefix

## 3. handler 拆包装

- [x] 3.1 `handlers/equipment_handler.py`：修习目标（~:188-196）**保留 `if ok:` 的 `update_player` 条件落库（:191-192，解包不动）**，仅渲染行改裸 `yield event.plain_result(msg)`；装备路径（~:239-251）成功 `result_msg = f"{message}\n━━━…\n属性加成：{attr_display}"`（message 已自带 ✅，去掉 handler 的 `✅ ` 前缀）、失败 `yield event.plain_result(message)` 并**保留**失败后 `store_item(silent=True)` 放回储物戒的补偿逻辑（silent 调用无消息面，不拆）；卸下路径（~:281-299）改裸渲染（成功 `f"{message}{storage_msg}"`、失败直接 `message`）
- [x] 3.2 `handlers/technique_handler.py`：两处修习目标（:101-104/:125-127）**保留 `if ok:` 条件落库（:99-100/:123-124，解包不动）**，仅渲染行改裸 `yield event.plain_result(msg)`；:213「✅ 已卸下功法【X】」为 handler 自有文案（卸下功法走内联 list 操作，不调 skill_manager；skill_manager 无卸下功法方法），**非包装点，不动**
- [x] 3.3 `handlers/pill_handler.py:65-67`：失败路径改裸渲染（成功路径本就裸）
- [x] 3.4 `handlers/storage_ring_handler.py`：取出（:158-163）、丢弃（:199-203）改裸渲染——丢弃的 `🗑️ {message}` 包装移除、由 manager 首行 `🗑️ 已丢弃…` 承接（1.4，输出逐字一致）；赠予路径已核实**无独立包装**（`handle_accept_gift` :366 的「❌ 接收失败：{message}」为 store_item 嵌入点，依赖 1.4 的 store_item 裸裁决，**不拆不动**）；完成后本组全部 handler 文件不再含服务层消息的 `f"✅/❌ {msg/…message}"` 前缀包装，grep 复核

## 4. 测试与用例同步

- [x] 4.1 `tests/`：审计确认装备/丹药/功法/储物戒域断言**全部为子串匹配**（`in msg`，精确 `==` 断言仅在 bank/bounty/sect/gm-other/breakthrough 域，不在本 change 改动范围）；编辑完成后 grep 复核一轮，若发现意外精确断言则更新
- [x] 4.2 `functional_tests/cases/`：已核查无取出/丢弃/服用/修习目标的目标断言；equipment-armor.json:56/:80/:98、equipment-heart-weapon.json:56、pvp-heart-passive.json:65/:125 等均为裸子串 `re:` 模式（前缀追加不破坏），预期零改动；如有改动跑对应 tag（`run --sync --reload astrbot_plugin_monixiuxian2_2 --export <dir>`）复核
- [x] 4.3 质量门：`uv run ruff format . && uv run ruff check .` 全绿；`uv run python -m pytest tests/` 全量通过

## 5. 文档与版本

- [x] 5.1 `AGENTS.md` §8：嵌入规则措辞从仅 `removeprefix('❌ ')` 泛化为「`removeprefix('❌ ')`/`removeprefix('✅ ')`」并以 GM cmd_unequip 为文内示例；拼接片段豁免从「`\n\n` 开头」泛化为「`\n` 或 `\n\n` 开头」（GM store_msg 实为 `\n` 单换行起头）；参考实现补**入装备/丹药域（储物戒域已在 §8 在列，勿重复）**
- [x] 5.2 `metadata.yaml` v3.17.8 + `README.md` 版本行与更新日志（日志**顶部新增** v3.17.8 条目——README 更新日志最新在前，`tests/test_docs_version_consistency.py` 校验首个日志标题与 metadata 版本一致；含「装备/功法/丹药/储物戒入口消息补状态符」条目）；`tests/test_docs_version_consistency.py` 通过
- [x] 5.3 本地 commit（如 `fix(msg-style): 状态符归属收敛——装备/功法/丹药/储物戒域迁移至服务层自带状态符`）