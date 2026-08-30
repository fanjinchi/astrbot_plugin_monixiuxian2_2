# Tasks: season-1-tier1-copywriting

## 1. 设计表骨架与工具

- [x] 1.1 新建 `design_docs/content-design/copy_variants.csv`（列：domain/scene/level_band/state/route/variant_no/text/tone_tier/narrative_status/note）
- [x] 1.2 `lint_narrative.py` 扩展：扫描 copy_variants.csv 的 text 列（禁词/数值承诺/品级冠词照常；长度上限按 domain 参数化，突破/战斗短句与事件长句分档）；按 1.4 对照表的变量白名单校验 text 列的 `{var}` 引用（白名单外变量即 FAIL）；新表无 `status` 列，严重度仅按 `narrative_status` 定档（占位/待写 WARN、定稿 FAIL）
- [x] 1.3 `design_docs/README.md` 与 `content-design/README.md` 登记新表
- [x] 1.4 先行登记场景对照表（scene key ↔ 载体位置 ↔ 插值变量白名单）：突破/战斗/修炼/机缘域 scene key 按 `externalize-narrative-texts` design D1/D2 预定，事件域 scene = `adventure_config.json` 事件 key（15 个基础 key；四宗组复用同源 key，组属性随 5.5 登记）；**写作任务（2-5 节）开始前完成**，载体工程落地后由 6.1 回核

## 2. 突破文案变体

- [x] 2.1 成功分支：四境界段 × 3-5 条变体，灵修/体修双词汇表分轨（bible §4.1）
- [x] 2.2 失败分支：四境界段 × 3-5 条变体，遵守 §4.4"给失败留一条命"的出路规则
- [x] 2.3 身死道消分支：四境界段 × 3 条变体
- [x] 2.4 机缘/领悟功法 flavor 变体（fortune 节场景）

## 3. 修炼结算变体

- [x] 3.1 闭关开始/出关结算骨架的 flavor 句变体池
- [x] 3.2 闭关悟道/传承值结算 flavor 变体

## 4. 战斗说书人句式

- [x] 4.1 现有 ~20 个句式场景（出招/暴击/闪避/格挡/大招/伤害结算/反弹/吸血/免死/胜负收束等）逐场景配 2-3 条变体
- [x] 4.2 句式变体遵守"正经描述先行、梗放括号彩蛋位"（§1.3）与数值不入文案（§5.3）

## 5. 历练事件变体（≈341 条：15 事件 × 11 = 165 + 四宗 4 组 × 44 = 176）

- [x] 5.1 15 事件（11 散修 + 青云门 4，含 2026-08-29 扩类 sect_duel/sect_trial）逐条写 5 情景帧 + 6 州条（按幕表世界状态，可挂 §3.2.6 本宗 NPC / §3.2.7 州域散修 / §3.6 冲突矩阵取材）——**剧本已成稿**（`design_docs/剧情/` 册 1-5）
- [x] 5.2 四宗（金刚寺/天机阁/万毒门/血魔宗）4 组 × 4 事件 × 11 条剧本（`design_docs/剧情/` 册 6-9，scene 键与青云门同源）——**已成稿**；config 立组与导入随 bd `n6o`（不在本表）
- [x] 5.3 州条验收：非宗门事件 = 六州各 ≥1 条（人工抽查每州确为该州特有元素，非泛用凑数句）；宗门事件 = 本宗州 6 帧本州见闻（不落他州、与通用帧不撞点、不落他宗内容）
- [x] 5.4 事件变体按 level_band 分桶标注（每事件 5 情景帧段位 练气-筑基×2 / 全段×1 / 金丹-元婴×2 + 6 州条全段通用），高段变体引入高阶妖兽、宗门拉拢等世界状态元素
- [x] 5.5 **灌入 copy_variants.csv**：`design_docs/剧情/` 册 1-9（15 事件 + 四宗 4 组，共 341 条）机械灌入设计表（帧名 → note、tone_tier 按册头档位、state 按州条模式），灌后 lint 闸门扫全表；实际由 `scripts/import_copy_variants.py` 连同 01-03 册（突破/修炼/战斗，共 136 条）一次灌入 477 行，lint 0 FAIL 达成

## 6. 收尾

- [x] 6.1 scene key 与 `externalize-narrative-texts`（2026-08-30 归档）落地后的 `narrative_config.json` 回核对齐：短句域 43 键（breakthrough 9/combat 23/cultivation 8/fortune 3）与 config **逐场景完全一致**，变量白名单 lint 0 FAIL 验证；registry 同步补登 legacy_encounter 4 键（externalize 新增，CSV 不含）；事件域 desc_variants 桶为可选 schema（运行时空回落 desc），15 事件中 13 键已在 `adventure_config.json`，sect_duel/sect_trial 2 键 config 未落地待 bd `n6o`（lint 110 WARN 即此）
- [x] 6.2 lint 全量跑通：定稿行 0 FAIL；全表 narrative_status 置"定稿"（477 行均定稿，0 FAIL / 231 WARN，WARN=既有占位基线 121 + sect_duel/sect_trial 未进 config 110，后项待 bd n6o）
- [x] 6.3 `openspec validate season-1-tier1-copywriting --strict` 通过
> **用户侧（非本表任务）**：设计稿确认与导入由用户自行发起（AGENTS.md §15）；导入任务依赖载体工程 `externalize-narrative-texts` 落地
