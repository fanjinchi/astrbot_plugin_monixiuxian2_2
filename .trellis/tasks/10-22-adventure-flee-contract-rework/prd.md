# 逃跑契约重拍落地：全风险段给选择 + 逃跑收益 ×0.3/不掉落/不滚传承

## Goal

把历练结算域的逃跑契约从首版（仅高/极高风险给选择；逃跑成功全额收益 + 照常滚掉落/传承）对齐到 2026-10-19 用户拍板的重拍契约：逃跑 = 给玩家的后路/止损键，代价全在收益侧。

- 设计权威：`design_docs/content-design/pve-enemy-design.md` §Q4「逃跑的交互与结算契约（2026-10-19 重拍）」+ 附录 B 决策记录④ 追记（含 2026-10-20 追记：败场也不滚传承）。
- bd 跟踪：`astrbot_plugin_monixiuxian2_2-w07`（discovered-from `-9hq`，已零改动封板收口）。
- plan 闸门：2026-10-20 已过 grilling（五问全按推荐：挂父任务独立 child / 父 PRD 旧条款交付时同步修订 / sect 存量用例归本任务 / `-2v2` 排本任务之后 / 文案 AI 起草随 PRD 审）。
- 计划审查：2026-10-20 两轮子代理审查（技术事实 + 测试影响面）+ 主代理逐条实锤复核，6 个 P1 已全部修入本计划（见 design.md §5/§6 与 implement.md）。

## Requirements

- R1（触发范围）：`_offers_choice` 去掉 `HIGH_RISK_LEVELS` 闸门——低/中/高/极高风险凡遇敌（snapshot 含 combat）均停 `pending_choice`。注意 combat 存在性判定是**承重**的（`_lock_encounter` 对未遇敌 run 也调 `_offers_choice`，未遇敌直通 `resolved_win` 靠它），不得当成保险简化掉。`flee.enabled=false` 的 kill switch 语义不变（全段直通战斗，不产生待选择态）。
- R2（逃跑收益收紧）：`resolved_fled` 的修为/灵石 = 快照 `base_reward`（已含事件倍率）×0.3（int 截断，对标败场修为的取整口径 `pve_combat_manager.py:272`）。注意口径差：败场灵石是**归零**（`:273`）而非 ×0.3，逃跑灵石 ×0.3 比败场宽——这是 §Q4「逃跑严格落在胜负之间」的原意，不是偏差。不滚掉落、不滚传承机缘。以下现行行为保持不变：气血不变（按结算时刻全时段恢复落定后的实时值记账）、无败场 +600s 休整、`win_pve` 不推进、悬赏/师承「完成历练」类进度照常推进。
- R3（传承门控，2026-10-20 拍板）：`_grant_legacy_trigger` 只在 `resolved_win`（含未遇敌完成）执行；`resolved_loss` / `resolved_fled` 跳过。传承机缘 =「走完全程的人」专属彩头。
- R4（文案，共 4 处）：① pending 提示写清逃跑代价（成算之外补「白跑大半：收益只留三成、无掉落、无传承机缘」）；② 逃跑成功结算行（💨 脱身）同步新口径；③「历练信息」帮助文案 `handlers/adventure_handlers.py:32` 的「仅高、极高风险路线」改为全风险段口径；④ 修仙帮助 `handlers/misc_handler.py:144` 同款旧表述同步。文案草案见 design.md §4，随本 PRD 一并审。
- R5（数值不动）：逃跑成功率已封板（0.95/0.05/0.35/0.60/1.00，bd `-9hq` 零改动收口），本任务不改 `config/adventure_config.json` 与 `data/default_configs.py` 的**数值**；两处的旧契约**注释**（`default_configs.py:596-597`「高/极高风险遇敌时提供」「数值未封板」、代码内 `DEFAULT_FLEE_PARAMS` 的「临时默认值」表述、`adventure_manager.py:325/:334` 日志警告「临时默认系数」）按封板口径修正。
- R6（测试对齐，实扫口径——两份子代理审查 + 主代理复核后的完整清单）：
  - pytest 共 **16 条**会翻红（清单与逐条修法见 design.md §6）：状态机文件 15 条（harness 默认必遇敌，LOW_ROUTE finish 全停 pending）+ 跨文件 1 条（`tests/test_sect_content_link.py::test_adventure_settlement_marks_sect_event`，真随机约 51% 概率红）。反向盘点结论：现存**没有**任何用例钉「fled 照常滚掉落/传承」或「loss 照常滚传承」，无需改旧断言，只需补新反向用例。
  - functional_tests sect 域共 **3 条**存量用例需适配（plan 闸门 Q3 归本任务）：`sect-bounty-lifecycle.json`、`sect-master-chain-gm.json`、`sect-adventure-event-marker.json`。修法统一为 GM「强制历练迎战」双分支断言（design.md §5，**不能**用玩家「迎战」——pending 分支 GM 结算失败不清疲劳，玩家迎战写入休整后会拦死 bounty 用例下一轮开始历练）。
  - 迎战/逃跑真实管线新用例归 `-2v2`（已加 blocks 依赖排本任务之后），本任务不重复覆盖。
- R7（文档同步）：交付时把父 PRD（`10-10-pve-enemy-world-boss-redesign/prd.md`）第 51 行与第 118 行的首版逃跑契约条款改为重拍口径并标注「2026-10-19 重拍，见 §Q4」；子任务地图补记本 child。design_docs §Q4 已是权威、无需改动；排查首版契约残留描述并同步，已知残留点：`README.md:138-139` 指令表、`main.py:1509` 注释「基础收益照常发放」、`design_docs/current-design-report.md`（实现时全量 grep 复核）。

## Out of Scope

- 秘境兽/传承守护者的 PVE 气血地板收口（归 child E / bd `-8oh`）。
- 逃跑成功率数值复算（名册 sync 后的复算挂钩另议，预期不变）。
- functional_tests 迎战/逃跑新用例（归 `-2v2`）。
- 世界 Boss 域任何行为。

## Acceptance Criteria

- [ ] AC1：低/中/高/极高风险路线遇敌均停 `pending_choice`；未遇敌完成仍直通 `resolved_win`；`flee.enabled=false` 时全段直通战斗（kill switch 语义不变）。pytest 用例钉住三种分支。
- [ ] AC2：逃跑成功结算：修为/灵石 = 快照 base_reward ×0.3（int 截断）、无掉落、无传承 roll、气血不变、无 +600s、悬赏/师承「完成历练」进度照常；重放同一张单不重复发放、不重新博概率。
- [ ] AC3：`resolved_loss` 不再滚传承机缘；`resolved_win`（含未遇敌完成）传承 roll 行为不变。
- [ ] AC4：pending 提示、💨 脱身结算、历练信息、修仙帮助共 4 处文案按 design.md §4 新口径渲染，写清逃跑代价。
- [ ] AC5：`uv run ruff format . && uv run ruff check .` 干净；`uv run python -m pytest tests/ -v` 全绿（含按新契约改写的 16 条用例与新补的反向用例）。
- [ ] AC6：`functional_tests/cases/sect/` 的 `sect-bounty-lifecycle.json`、`sect-master-chain-gm.json`、`sect-adventure-event-marker.json` 三条用例在全段 pending 下保持确定性（GM 强制历练迎战双分支断言；真实平台回归由用户发起）。
- [ ] AC7：父 PRD 两条首版契约条款已修订为重拍口径，子任务地图已补记本 child；README 指令表、main.py 注释、design_docs 无首版契约残留描述。
- [ ] AC8：config **数值**零改动（`git diff config/adventure_config.json data/default_configs.py` 只允许出现注释修正，不允许任何数值/键变化）。

## Notes

- 现网行为在代码落地前仍为首版契约（§Q4 实施边界注记），本任务即该「另开任务」。
- 并发/事务纪律沿用 child C 既定形态：终态 CAS、效果 claim 恰好一次、事务外确定性计算——本任务只改效果集合的触发条件和收益数额，不动这套骨架。
