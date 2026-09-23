# unify-status-emoji-ownership

## Why

AGENTS.md §8 已把「消息状态符（❌/✅/⚠️/🎯）由服务层自带完整文案、handler 裸渲染」成文（2026-09-24 全仓审计落定，悬赏/银行域已收敛），但全仓仍有 **8 处旧式「handler 包前缀」写法**残留在装备/功法/丹药/储物戒四个入口：handler 包装 4 个**裸文案** core 服务（`skill_manager`/`equipment_manager`/`pill_manager`/`storage_ring_manager`）的返回消息。悬赏双 ❌（v3.17.6）与储物戒双 ❌（v3.17.7）同根——handler 包装与服务层自带状态符重叠；剩余 8 处目前无 bug（被包消息全裸），但 `set_study_target` 已是双入口消费（装备 `equipment_handler.py:188` + 功法 `technique_handler.py:98`），且存在 **4 处嵌入点**（GM `cmd_unequip` 的卸下失败/成功、装备取出补偿、`handle_retrieve_all` 失败聚合）正在嵌入这些消息——正是约定要防的漂移类风险：一旦任一消息日后自带状态符（本 change 就要这么做）或新入口裸渲染，就会静默产出「❌ ❌」。约定成文后，它们就是唯一的违规存续区。

## What Changes

- **4 个 core 服务消息补状态符**：失败路径一律 `❌` 开头，成功路径按已有形态处置——
  - `core/skill_manager.py`：`set_study_target`（:501/:504/:507）、`clear_study_target`（:512/:515）及 `can_equip_technique` 装备功法分支（:578/:581/:586/:589）——该分支已核实无生产消费方（仅单测子串断言调用），属防御性补符，保证服务层形态统一
  - `core/equipment_manager.py`：`equip_item`/`unequip` 全部失败（:229/:279/:283/:295/:310/:318/:326/:340）与成功消息——含全新装备（:244/:258/:272）、替换路径「已将【X】替换为…{storage_msg}」（:241/:255/:269）、功法已装备（:289-292）
  - `core/pill_manager.py`：`use_pill` 全部失败（:76/:81/:90/:112/:143/:376）补 `❌ `；成功消息已自带 `✨`（:130/:156/:282）不叠加（D1）
  - `core/storage_ring_manager.py`：`retrieve_item`/`discard_item` 失败（:191 不存在、:196-199 数量不足；:223 不存在、:228-231 数量不足）补 `❌ `；取出成功（:211）补 `✅ `；丢弃成功（:245）改首行自带 `🗑️ 已丢弃…`（与现状 handler 包装输出逐字一致，见 design D1）——**注意 :93/:97/:162（`can_store_item`/`store_item` 检查原因）不属于本改造面**，见「store_item 保持裸裁决」；`upgrade_ring` 已收敛（v3.17.7）不动
- **handler 移除前缀包装、裸渲染**：`equipment_handler.py`（:193-195 修习目标、:245-251 装备、:293-299 卸下）、`technique_handler.py`（:101-104/:125-127 修习目标；:213「✅ 已卸下功法【X】」为 handler 自有文案、非包装点，不动）、`pill_handler.py`（:67 用丹失败；成功路径本就是裸渲染）、`storage_ring_handler.py`（:158-163 取出、:199-203 丢弃）
- **4 处嵌入点同步（关键连带面）**：迁移后 inner 消息自带 ✅/❌，必须按 AGENTS.md §8 嵌入规则去重——迁移前 inner 全裸所以安全，**不先处理则迁移必炸**：
  - `core/gm_manager.py` `cmd_unequip`：`❌ 卸下失败：{msg}`（:871）与 `✅ 已卸下…：{msg}{store_msg}`（:888）
  - `handlers/equipment_handler.py:210`：`❌ 无法从储物戒取出装备：{retrieve_msg}`
  - `handlers/storage_ring_handler.py` `handle_retrieve_all`（:571-587）：`:577` 失败聚合 `failed.append(f"{item_name}：{msg}")` 的内嵌消息去重（`:585` 头行 `"\n❌ 失败："` 为 handler 组装列表的标签行、非包装头，保留）
- **测试与功能用例同步**：核对 `tests/` 与 `functional_tests/cases/` 中对此类文案的断言（审计结论：均为子串断言、无精确全文匹配，预期零改动，见 tasks 4）
- **AGENTS.md §8 参考实现补全**：把装备/丹药域列为已收敛实例（储物戒域已在 §8 在列）；嵌入去重规则泛化为 `removeprefix('❌ ')/removeprefix('✅ ')`，拼接片段豁免泛化为 `\n` 或 `\n\n` 开头（GM `store_msg` 实为单换行起头）

**store_item 保持裸裁决（公共前提）**：`store_item`/`can_store_item` 的原因文本（:93/:97/:162）不补状态符——它们被 silent 或嵌入场景消费，依赖方共 **8 处**：GM 存入/卸下路径（gm_manager :833/:883）、商店购买入戒（shop_handler :257/:286/:299——购武器/防具/材料/功法路径，丹药购买走 `add_pill_to_inventory` 不在此列）、赠予接收（`handle_accept_gift` storage_ring_handler :366）、装备替换回存（equipment_manager `_store_old_equipment` :361 区域）、装备卸下回存（equipment_handler :295 store_msg 拼接）。此裁决一旦改变，上述嵌入点全部产出叠符（依赖清单与追踪见 design D5/Risks）。

边界：**不含**内容改造（文案不动、只加前缀）；**不含** `sect_manager.handle_owner_death`（无消费方遗留 API）、`dual_cultivation_manager.reject_request` 成功裸文案（单入口、无漂移风险，保留原文）；拼接片段（`\n` 或 `\n\n` 开头）按 §8 例外处理。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 —— 本 change 只改消息状态符前缀的归属与形态，不构成任何现有 spec 的 REQUIREMENT 变更；`skip_specs: true`，与 `busy-state-owner` 同类：工程性约定收敛而非行为契约变更）

## Impact

- **handlers**：`equipment_handler.py`、`technique_handler.py`、`pill_handler.py`、`storage_ring_handler.py`
- **core**：`skill_manager.py`、`equipment_manager.py`、`pill_manager.py`、`storage_ring_manager.py`、`gm_manager.py`（cmd_unequip 嵌入点）
- **用户可见**：装备/卸下/修习目标/取出 相关消息前缀从裸文本变为 ❌/✅（文案内容不变）；丢弃成功输出与现状逐字一致（🗑️ 归属从 handler 移至 manager 首行）；丹药失败消息补 ❌、成功消息不变（已带 ✨）；赠予消息不变
- **测试面**：`tests/` 中装备/丹药/功法/储物戒相关用例（审计确认均为子串断言，预期无改动）
- **文档**：AGENTS.md §8、README 更新日志（v3.17.8）