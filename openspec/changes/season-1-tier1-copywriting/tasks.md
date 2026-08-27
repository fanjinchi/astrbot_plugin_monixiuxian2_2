# Tasks: season-1-tier1-copywriting

## 1. 设计表骨架与工具

- [ ] 1.1 新建 `design_docs/content-design/copy_variants.csv`（列：domain/scene/level_band/state/route/variant_no/text/tone_tier/narrative_status/note）
- [ ] 1.2 `lint_narrative.py` 扩展：扫描 copy_variants.csv 的 text 列（禁词/数值承诺/品级冠词照常；长度上限按 domain 参数化，突破/战斗短句与事件长句分档）；按 1.4 对照表的变量白名单校验 text 列的 `{var}` 引用（白名单外变量即 FAIL）；新表无 `status` 列，严重度仅按 `narrative_status` 定档（占位/待写 WARN、定稿 FAIL）
- [ ] 1.3 `design_docs/README.md` 与 `content-design/README.md` 登记新表
- [ ] 1.4 先行登记场景对照表（scene key ↔ 载体位置 ↔ 插值变量白名单）：突破/战斗/修炼/机缘域 scene key 按 `externalize-narrative-texts` design D1/D2 预定，事件域 scene = `adventure_config.json` 事件 key；**写作任务（2-5 节）开始前完成**，载体工程落地后由 6.1 回核

## 2. 突破文案变体

- [ ] 2.1 成功分支：四境界段 × 3-5 条变体，灵修/体修双词汇表分轨（bible §4.1）
- [ ] 2.2 失败分支：四境界段 × 3-5 条变体，遵守 §4.4"给失败留一条命"的出路规则
- [ ] 2.3 身死道消分支：四境界段 × 3 条变体
- [ ] 2.4 机缘/领悟功法 flavor 变体（fortune 节场景）

## 3. 修炼结算变体

- [ ] 3.1 闭关开始/出关结算骨架的 flavor 句变体池
- [ ] 3.2 闭关悟道/传承值结算 flavor 变体

## 4. 战斗说书人句式

- [ ] 4.1 现有 ~20 个句式场景（出招/暴击/闪避/格挡/大招/伤害结算/反弹/吸血/免死/胜负收束等）逐场景配 2-3 条变体
- [ ] 4.2 句式变体遵守"正经描述先行、梗放括号彩蛋位"（§1.3）与数值不入文案（§5.3）

## 5. 历练事件变体（≈143 条）

- [ ] 5.1 13 事件逐条写 ≥5 条通用变体（按幕表世界状态，可挂 §3.2.6 NPC / §3.6 冲突矩阵取材）
- [ ] 5.2 每事件六州专属各 ≥1 条（落 §2.2 州域地貌烙印；验收时人工抽查每州至少一条确为该州特有元素，非泛用凑数句）
- [ ] 5.3 事件变体按 level_band 分桶标注（通用/练气/筑基/金丹/元婴），高段变体引入高阶妖兽、秘境苏醒、宗门拉拢等世界状态元素

## 6. 收尾

- [ ] 6.1 scene key 与载体工程 `externalize-narrative-texts` 落地后的 `narrative_config.json` 场景 key 回核对齐
- [ ] 6.2 lint 全量跑通：定稿行 0 FAIL；全表 narrative_status 置"定稿"
- [ ] 6.3 `openspec validate season-1-tier1-copywriting --strict` 通过
- [ ] 6.4 **提交用户手动确认设计稿**（AGENTS.md §15）；确认后发起导入任务（依赖载体工程落地）
