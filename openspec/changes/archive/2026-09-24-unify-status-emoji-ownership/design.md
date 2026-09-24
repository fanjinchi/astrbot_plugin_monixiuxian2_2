# unify-status-emoji-ownership — Design

## Context

动机与范围见 proposal.md。前置事实（2026-09-24 审计确认）：

- 约定已就位：AGENTS.md §8 规定「服务层自带状态符、handler 裸渲染；嵌入包装头先 `removeprefix` 去重；`\n\n` 拼接片段豁免」。
- 被包的 4 个 core 服务（`skill_manager`/`equipment_manager`/`pill_manager`/`storage_ring_manager`）当前**被包消息全部裸文案**（无任何 ❌/✅；`storage_ring_manager` 的 upgrade 域已收敛 v3.17.7，不在裸列）；8 处 handler 包装因此无 bug，但违反成文约定，且 `set_study_target` 双入口、GM/equipment/聚合列表存在嵌入点，是漂移风险区。
- 嵌入点 4 处（内嵌消息在迁移后会自带状态符，必须同步去重）：
  - `core/gm_manager.py:871` `❌ 卸下失败：{msg}`
  - `core/gm_manager.py:888` `✅ 已卸下…：{msg}{store_msg}`（成符号 ✅ 头 —— 注意是 ✅ 不是 ❌）
  - `handlers/equipment_handler.py:210` `❌ 无法从储物戒取出装备：{retrieve_msg}`
  - `handlers/storage_ring_handler.py:577` `handle_retrieve_all` 失败聚合 `failed.append(f"{item_name}：{msg}")`（`:585` 头行 `"\n❌ 失败："` 为 handler 组装列表的标签行、非包装头，保留）
- `pill_manager` 成功消息**已自带内容符号** `✨ 服用【…】成功！`（:130/:156/:282，与 `borrow` 的 💰、bounty 的 🎯 同类先例）；`storage_ring_handler` 丢弃成功动态包装 `🗑️ {message}`（:199，全仓唯一非 ✅/❌ 的动态包装符号）。
- 冲突评估（2026-09-24）：活跃 change `decouple-handler-to-handler-calls`（动 sect/bounty/ranking handlers）、`narrative-contract-module`（叙事文案域）、`gm-time-skip-registry`（gm_manager time-skip 域，与 :871/:888 非同一区域）、`combat-result-winner-identity`（managers/ 战斗域：combat/pve_combat/boss/impart_pk）与本 change **无文件级重叠**；唯一留意点是 gm_manager 三路合并，风险低。

## Goals / Non-Goals

**Goals:**

- 8 处 handler 包装全部拆除，四个入口（装备/功法/丹药/储物戒）与其余域一样：handler 裸渲染、服务层自带状态符。
- 4 个 core 服务消息达成统一形态：失败路径一律 `❌` 开头；成功路径若已带内容符号（✨/💰/🗑️ 类）保留不叠，裸文本成功消息补 `✅`。
- 4 处嵌入点按 §8 规则去重，迁移后不产生任何「❌ ❌」「✅ ✅」。
- tests/ 与 functional_tests/cases/ 中受影响的文案断言同步到位。

**Non-Goals:**

- 不改文案内容（只动前缀/首行符号，多行布局逐字保留）。
- 不处理 `sect_manager.handle_owner_death`（无消费方遗留 API）与 `dual_cultivation_manager.reject_request` 成功裸文案（单入口、无漂移风险）。
- 不要求每条消息都带状态符：查询/空态消息与 `\n`/`\n\n` 开头拼接片段（如装/卸消息尾部自造的「已存入储物戒」片段——来自 `_store_old_equipment`/equipment_handler/gm_manager 的调用方文案，非 store_item 返回消息）按 §8 例外保留裸；`store_item`/`can_store_item` 原因文本保持裸为本 change 公共前提（见 D5/Risks）。

## Decisions

**D1 — 成功消息符号形态：已有内容符号不叠加，裸文本补 ✅；丢弃成功由 manager 首行自带 🗑️。**

`pill_manager` 成功已带 `✨`；若再叠 `✅` 会产出「✅ ✨ 服用…成功」——与既有先例（borrow 💰、bounty 🎯 的成功消息自带内容符号、handler 不包 ✅）冲突。故规则为：首行已带头部内容符号 → 保留；裸文本成功（已装备/已卸下/已取出/已设为修习目标/已取消修习目标）→ 补 `✅`。失败路径无例外，一律 `❌`。

丢弃成功特判：`storage_ring_handler` 现状动态包装 `🗑️ {message}`（:199，全仓唯一非 ✅/❌ 的动态包装符号）。拆包装若补 `✅` 开头会丢掉「永久销毁」语义并造成可见文案变化（违反 Non-Goal「文案逐字保留」）；故丢弃成功由 `discard_item` 首行自带 `🗑️ 已丢弃…`（同 ✨/💰 先例，成功不叠 ✅），输出与现状逐字一致，仅归属从 handler 移至 manager。

备选「成功统一叠 ✅ 覆盖一切」→ 叠符形态，否决。

**D2 — 嵌入去重规则泛化为 ❌/✅ 双前缀。**

现有 §8 只写了 `removeprefix('❌ ')`，但 GM 卸下成功路径是 `✅ 已卸下…：{msg}`，迁移后 inner 自带 ✅ → 需要 `removeprefix('✅ ')`。故：本 change 一并将 AGENTS.md §8 嵌入规则措辞从仅 ❌ 泛化为「`removeprefix('❌ ')`/`removeprefix('✅ ')`」，并以 GM cmd_unequip 为文内示例。
备选「嵌入点要求服务层保证内嵌消息不带符号」→ 直接破坏「服务层自带状态符」前提，否决。

**D3 — 三组改动在同一 commit 落地，无中间态。**

manager 补符、嵌入点去重、handler 拆包装三者互依赖：只做前两步会短暂让「handler 包装 + 自带符」双符复现（与 v3.17.7 前状态相同），只做第三步会丢失状态符。全部编辑完成后再提交，插件重载即达完成态。编辑顺序（manager → 嵌入点 → handler）仅为逻辑顺序，不产生可运行中间版本。

**D4 — 消息内容与结构逐字保留，只动首行符号。**

多行布局（━━ 分隔、数值行、提示行）不做任何调整，缩小测试与功能用例波动面。功能用例 `re:` 为子串语义（v3.17.6 审计证实），前导符号追加通常不破坏无符号起点断言；审计确认本域用例均无符号起点断言（见 tasks 4.2）。`handle_retrieve_all` 的头行 `❌ 失败：` 属 handler 组装标签、非服务层消息，不适用本决策，保留。

**D5 — `store_item`/`can_store_item` 原因文本保持裸（公共前提，非本 change 改造面）。**

`:93/:97/:162` 的检查原因文本是**被嵌入/silent 消费**的原因文本，8 处嵌入方依赖其裸形态：GM 存入/卸下路径（gm_manager :833/:883）、商店购买入戒（shop_handler :257/:286/:299——购武器/防具/材料/功法路径）、赠予接收（`handle_accept_gift` storage_ring_handler :366）、装备替换回存（equipment_manager `_store_old_equipment` :361 区域）、装备卸下回存（equipment_handler :295 store_msg 拼接）。若本 change 或未来改动给它们补状态符，上述嵌入点将同时产出叠符。本 change 维持裸，依赖清单在 Risks 长期追踪。

## Risks / Trade-offs

- [嵌入点漏改：迁移后 GM/装备取出/聚合列表路径产出新「❌ 卸下失败：❌ …」双符] → 4 处嵌入点列为 tasks 显式步骤（带精确行号），与 manager 改动同 commit，不许分拆提交。其中 `handle_retrieve_all` 为第 4 处——初始 tasks 遗漏、评审 G1 补入，其余三处行号按评审修正（:869/:886 → :871/:888）。
- [`store_item` 裸裁决被误读为「也应该补符」→ 8 处嵌入方全部产出叠符] → D5 显式记录裁决与依赖清单，tasks 1.4 含「保持裸」核查项，且已核实「存入」命令为禁用桩（storage_ring_handler:110-124，不调 store_item）。
- [单测对裸文案的部分匹配断言被「❌/✅ 」前缀破坏] → 审计结论：`tests/` 装备/丹药/功法/储物戒域断言**全部为子串匹配**（`in msg`），`functional_tests/cases/` 对应域无可符号起点断言（equipment-armor.json:56/:80/:98、equipment-heart-weapon.json:56、pvp-heart-passive.json:65/:125 均为裸子串 `re:` 模式），预期零改动（tasks 4 已按核查写实）；编辑完成后 grep 复核一轮，意外精确断言按 tasks 4.1 更新。
- [「已设为修习目标」等成功消息从 handler 的 ✅ 转为 manager 的 ✅，文本位置不变，但若未来某入口漏改会退化为裸文本] → 该入口已有双入口先例，拆包装即消除；AGENTS.md §8 参考实现补全装备/丹药/储物戒域，供后续对照。
- [后续新增嵌入点再次遗漏去重] → §8 规则泛化为 ❌/✅ 并含 GM 示例（D2），本 change 即活文档。
- [gm_manager 与 `gm-time-skip-registry` change 合并冲突] → 评审结论：该 change 只动 time-skip 域（`_TIME_SKIP_RULES` 等），与 :871/:888 非同一区域，三路合并风险低（见 Context 冲突评估）。

## Migration Plan

单 commit 落地顺序：

1. 4 个 core 服务补状态符（skill_manager：set/clear_study_target 5 条 + can_equip_technique 防御性 4 条；equipment_manager：equip_item/unequip_item 失败 8 条 + 成功消息含替换路径与功法已装备；pill_manager：失败 6 条、成功不动；storage_ring_manager：retrieve/discard 失败 4 条 + 取出成功 ✅ + 丢弃成功首行 🗑️）；
2. 4 处嵌入点去重：gm:871 `removeprefix('❌ ')`、gm:888 `removeprefix('✅ ')`、equipment_handler:210 `removeprefix('❌ ')`、storage_ring_handler handle_retrieve_all 聚合内嵌 `removeprefix('❌ ')`；
3. 4 个 handler 文件拆包装（equipment_handler 3 处、technique_handler 2 处、pill_handler 1 处、storage_ring_handler 取出/丢弃各 1 处）；
4. tests/ 与 functional_tests/cases/ 断言核查与同步（预期零改动，见 Risks）；
5. AGENTS.md §8 规则措辞泛化（✅ 双前缀 + `\n`/`\n\n` 豁免）+ 参考实例补全；README 更新日志 + 版本号 v3.17.8。

回滚：`git revert` 该 commit 即恢复全部裸文案（纯文本变化，无数据/DB 影响）。

## Open Questions

无。