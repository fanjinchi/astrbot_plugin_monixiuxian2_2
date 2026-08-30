# Proposal: season-1-tier1-copywriting

## Why

第一季剧情大纲（`season-1-outline.md`）梯队 1 的高频界面文案——突破/修炼结算/战斗说书人/历练事件变体——是玩家经过率 × 情绪强度最高的一批叙事内容（bd `bk4`）。按 AGENTS.md §15 的内容设计先行规矩，这批文案必须先在 design_docs 完成策划写作、经用户手动确认后再导入 config。本变更承担**策划阶段**：按 world-bible 的基调/尺度/变体量规范与 season-1-outline 幕表的世界状态，把梯队 1 文案成体系地写出来并过 lint 闸门。

## What Changes

- **写作载体：剧本册先行，CSV 后灌**：事件域（含四宗）文案先在 `design_docs/剧情/` 以 Markdown 剧本册成稿（9 册：册 1-4 散修 11 事件 / 册 5 青云门 / 册 6-9 四宗），经用户审阅后机械灌入设计表；其余域直接写表。
- **新建 `design_docs/content-design/copy_variants.csv`**：梯队 1 全部文案变体的设计表（列：domain / scene / level_band / state / route / variant_no / text / tone_tier / narrative_status / note），机器可校验、可导入。
- **突破文案**：四境界段（练气/筑基/金丹/元婴）× 三分支（成功/失败/身死道消）× 3-5 条变体；灵修/体修意象语系双轨（bible §4.1：境界名统一，体修"结丹"写"气血凝丹"、"元婴"写"丹破婴出"）。
- **修炼结算变体池**：闭关开始/出关结算/闭关悟道的多态变体。
- **战斗说书人句式**：现有 ~20 个句式场景（出招/暴击/闪避/格挡/大招/胜负收束等）各配变体。
- **历练事件变体**：15 事件 × 11 条 ≈165 条（bible §1.7）——11 个散修/妖域/遗迹事件 + 青云门 4 事件（elder_guidance / sect_errand / sect_duel / sect_trial，后两者为 2026-08-29 宗门事件扩类定）；另**四宗事件剧本**（金刚寺/天机阁/万毒门/血魔宗 4 组 × 4 事件 × 11 ≈176 条）同属本变更写作范围（已提前成稿），config 立组与导入随 bd `n6o`。按幕表各等级段世界状态落笔；变体按境界段分桶**标注**（通用/练气/筑基/金丹/元婴，bd `tyt` 结构；标注不倍增条数，341 条的账不变——每事件 5 情景帧 = 练气-筑基×2 / 全段×1 / 金丹-元婴×2，州条默认全段通用）。
- **lint 扩展**：`lint_narrative.py` 覆盖 `copy_variants.csv`（禁词/数值承诺/长度/品级冠词照常；length 上限按域参数化；新表无 `status` 列，严重度仅按 `narrative_status` 定档）。
- `design_docs/README.md` 与 `content-design/README.md` 登记。

**明确不在本变更内**：
- **导入 config**：文案入库须满足两个前提——用户手动确认设计稿 + 载体就绪；导入动作本身是独立任务。载体就绪按域不同：突破/战斗/修炼结算/机缘域依赖 `externalize-narrative-texts` 落地（narrative_config.json 存在）；事件域的 adventure_config 变体池 schema（题材标签位 + 境界段分桶，bd `tyt` 工程侧）已并入 `externalize-narrative-texts`，同随该 change 落地；四宗组（sect_jingang / sect_tianji / sect_wandu / sect_xuemo）在 adventure_config 的立组与导入随 bd `n6o`（四宗剧本写作已完成，归本变更）
- 事件变体按境界段分桶的**运行时机制**（bd `tyt` 工程侧，已并入 `externalize-narrative-texts`）
- 灵根/体质评价大表（~48 条）的内容重写（载体由 `externalize-narrative-texts` 外移，重写属后续内容任务）
- 梯队 2/3/4 内容（bd `lky`/`u4h`/`ys4`）

## Capabilities

### New Capabilities

（无——纯内容设计变更，不引入运行时行为；运行时契约由 `externalize-narrative-texts` 的 `narrative-text-config` capability 承担。本 change 已声明 `skip_specs: true`。）

### Modified Capabilities

（无。）

## Impact

- **文档/设计表**：新建 `design_docs/剧情/` 剧本册（9 册，事件域写作载体）与 `design_docs/content-design/copy_variants.csv`；两个 README 登记
- **工具**：`lint_narrative.py` 扩展覆盖新设计表
- **运行时**：无代码、无 config、无数据库影响
- **依赖**：写作规范依赖 `world-bible.md` 与 `season-1-outline.md`（均已就绪）；导入依赖 `externalize-narrative-texts` 落地
- **bd**：落地（用户确认设计稿）后推进 `bk4`；导入完成后关闭 `bk4`
