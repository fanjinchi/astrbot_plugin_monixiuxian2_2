# Proposal: narrative-content-pipeline

## Why

`world-bible.md`（2026-08-24 建立）解决了"世界是什么、文案怎么写"的基调问题，但审查发现它仍缺落地支撑，无法直接指导批量内容填充：

1. **没有剧情大纲**：bible 是设定集，缺"玩家等级轴 × 世界时间轴"的剧情幕映射——同一批历练/秘境文案在玩家筑基时和元婴时该呈现什么世界状态，无处可查。
2. **收编清单（§6）全枚举、注定腐臭**：bible 逐条列出 config 全部现存名（45+ 功法逐一罗列），每增删改一条内容都要回改 bible，而物品真名实际活在 config 里——"唯一事实来源"与"全枚举副本"自相矛盾。
3. **内容缺少"叙事身份"登记处**：每条内容的叙事出处、文风档、写作状态只存在于脑子里，改名/按剧情优化时无册可查；现有 content-design CSV（数值设计表）有 `ref_source`/`design_note`/`status` 列但无叙事维度。
4. **禁词/文风规范（§5.3）靠手检**：没有任何机器层面的守门，批量填充时质量会漂移。
5. **势力间无冲突线、NPC 无三件套**：事件/悬赏/师承文案缺弹药库。

在批量填充剧情文本（梯队化写作计划见 design.md）之前，必须先建叙事内容管线。

## What Changes

- **`design_docs/world-bible.md` 增补**（纯文档）：
  - 新增剧情幕表：玩家等级段（练气/筑基/金丹/元婴）× 世界状态（复苏阶段、妖乱强度、秘境开启叙事、宗门态度）映射
  - 新增势力冲突矩阵：五宗 + 散修 + 妖域之间的利益冲突/历史结怨清单（事件与悬赏的弹药库）
  - NPC 人格化三件套：每个已具名 NPC 补性格关键词 + 口头禅 + 派活类型
  - 新增文案载体清单：哪些文案字段在 config、哪些硬编码在代码、外移优先级
  - 事件文案变体量标准（每组 ≥5 通用 + 每州 ≥1 专属）
  - §1.3 新增"擦边尺度"小节（与玩梗尺度并列）：擦边（暗示不直白、点缀不喧宾夺主、不物化到出戏）允许适度加入各类文案；开场「巨乳肥臀的冷面仙子」据此保留
  - 小修正：清X山 X 取值规则写死、"不留钩子"措辞修准为"不留需兑现的悬念"、§2.2 表加类型列
  - **§6 收编清单改造**：全枚举退役，改引用 canon 表，bible 只保留裁决规则与示范样例
- **新建 `design_docs/season-1-outline.md`**（季度层大纲）：第一季剧情幕详表 + 内容预算 + 四梯队文案填充顺序规划
- **Canon 表体系**（条目层）：
  - 现有 `weapons.csv` / `skills.csv` / `heart_methods.csv` 增补叙事列：`canon_origin`（叙事出处，须可在 bible 地理/势力章查证）、`tone_tier`（文风档，引 bible §1.3/§3.2）、`story_hook`（一句话叙事钩子）、`narrative_status`（占位→待写→定稿）
  - 新增无数值内容的叙事表：`events-canon.csv` / `enemies-canon.csv` / `rifts-canon.csv`（仅 id 对照 + 叙事列）
- **文案 lint 脚本** `design_docs/content-design/lint_narrative.py`：扫描 CSV description 列与 config description 字段，检查禁用词（bible §5.3）、数值承诺词（"+N%"、阿拉伯数值表述）、长度上限、品级冠词规则（§5.1）、CSV ↔ config 名字一致性；作为 content-sync-pipeline 除预算验算外的第二道入库闸门
- `design_docs/README.md` 登记新资料

**明确不在本变更内**（拆为后续 change / bd 任务）：
- 高频文案外移工程（突破/战斗/修炼结算文案从代码抽到 config）——独立工程变更
- `rift_config.json` 增加 description 字段——独立工程变更
- 梯队 1~4 的实际文案撰写与改名执行——内容任务，管线建成后按 season-1-outline 顺序进行

## Capabilities

### New Capabilities

（无——本变更不引入新的运行时行为）

### Modified Capabilities

- `content-sync-pipeline`: 新增"叙事文案 lint 闸门"要求——同步脚本入库前除预算验算外，SHALL 通过叙事 lint（禁词/数值承诺/长度/品级冠词/名字一致性），FAIL 行中止写盘；canon 叙事列（canon_origin/tone_tier/story_hook/narrative_status）作为设计表叙事元数据的契约字段。

## Impact

- **文档**：`design_docs/world-bible.md`（增补 + §6 改造）、新建 `design_docs/season-1-outline.md`、`design_docs/README.md` 登记
- **设计表**：`design_docs/content-design/weapons.csv` / `skills.csv` / `heart_methods.csv` 增 4 叙事列；新增 `events-canon.csv` / `enemies-canon.csv` / `rifts-canon.csv`
- **工具**：新建 `design_docs/content-design/lint_narrative.py`（纯校验脚本，与 `validate_budget.py` 同级）；同步脚本 `sync` 流程接入 lint 闸门（若同步脚本本次改造，仅加调用点，不改 reconcile 语义）
- **运行时**：无代码、无数据库、无 API 影响；不改任何 config 数值与现有文案内容本身
- **流程**：后续内容填充（改名/描述重写/事件文案）必须先过 lint，bible §6 全枚举段退役
