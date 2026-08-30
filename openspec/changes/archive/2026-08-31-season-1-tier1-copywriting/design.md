# Design: season-1-tier1-copywriting

## Context

- 写作规范全部就绪：`world-bible.md`（基调 §1.2 动作→画面→结果三拍、玩梗尺度 §1.3、擦边尺度 §1.3b、禁词 §5.3、变体量 §1.7、双路线词汇表 §4.1/§5.5、NPC 三件套 §3.2.6、冲突矩阵 §3.6）；`season-1-outline.md` 幕表（各等级段世界状态）与内容预算（§2）
- 载体工程 `externalize-narrative-texts` 提供 `narrative_config.json` 的场景结构与变体池 schema（本变更的文案最终导入那里）
- 事件变体按 bd `tyt` 的境界段分桶结构组织文案；分桶运行时机制由 `externalize-narrative-texts` 交付（bd `tyt` 工程侧已并入）

## Goals / Non-Goals

**Goals:**
- 梯队 1 全部高频文案在 design_docs 成稿，lint 全绿（定稿行 0 FAIL）
- 每条变体可查证：文风档合法、落州名/世界状态与幕表一致、不犯禁词
- CSV 结构可直接驱动后续导入脚本

**Non-Goals:**
- 不导入 config（等用户确认 + 载体落地）
- 不写梯队 2/3/4 内容
- 不改任何代码运行时行为

## Decisions

### D1：变体文案用 CSV 单表 `copy_variants.csv`，不用 Markdown

列：`domain,scene,level_band,state,route,variant_no,text,tone_tier,narrative_status,note,group`

- `domain`：breakthrough / cultivation / combat / adventure_event
- `scene`：场景 key（与载体工程 `narrative_config.json` 的场景 key 一一对应，导入时按键映射）
- `level_band`：通用 / 练气 / 筑基 / 金丹 / 元婴（境界段分桶，bd `tyt` 结构；事件域每事件 11 条 = 5 情景帧段位覆盖 练气-筑基×2 / 全段×1 / 金丹-元婴×2 + 6 州条默认全段通用）
- `state`：州域（云州/沧州/朔州/蛮州/青州/中州；非地域文案填"通用"）。事件域州条两模式：非宗门事件 = 六州各 1；宗门事件 = 本宗州 6 帧本州见闻（不落他州、不落他宗内容，帧名即内景据点）
- `route`：灵修 / 体修 / 通用（意象语系分轨，bible §4.1：境界名统一，体修"结丹"写"气血凝丹"、"元婴"写"丹破婴出"）
- `group`：组属性登记（散修/通用域留空；宗门行 = sect_qingyun / sect_jingang / sect_tianji / sect_wandu / sect_xuemo）。四宗与青云门复用同源 scene key（elder_guidance/sect_errand/sect_duel/sect_trial），variant_no 唯一性按 (domain, scene, group) 三元组判定；lint 依据 group 值拆分同源键。config 立组随 bd `n6o`，导入任务按 group 落组。
- **理由**：变体是批量数据（事件域 15 事件 × 11 + 四宗 4 组 × 44 ≈ 341 条），CSV 可被 lint 机器校验、被导入脚本机械消费；Markdown 表格做不到闸门校验。

### D2：写作规范强制引用点

每条变体写作时对照：bible §1.2 三拍结构（一句场景、一句动作、一句结果，1~3 行）；§1.3/§1.3b 尺度（2026-08-29 定：`正经+冷幽默` 档正/冷约各半、幽默写进正文、禁括号补丁，括号彩蛋位专属 `玩梗灰` 档）；§5.3 禁词（lint 机器守门）；事件文案落幕表对应等级段的世界状态（复苏阶段/妖乱强度/宗门态度）；州专属变体落 §2.2 地貌烙印；NPC 取材分轨：宗门事件只挂 §3.2.6 本宗门 NPC 三件套，散修事件（如 ally_help 州条）挂 §3.2.7 州域散修，不落宗门 NPC；可挂 §3.6 冲突矩阵取材。

### D3：导入路径（本变更只到"就绪待确认"）

文案成稿（剧本册定稿或直接写表，narrative_status=定稿、lint 0 FAIL）→ **用户手动确认** → 灌入 `copy_variants.csv`（事件域由剧本册机械灌入，见 D5）→ 载体就绪后由导入任务把 `copy_variants.csv` 转换进 `narrative_config.json` / `adventure_config.json`（转换脚本是导入任务的一部分，可扩展 `sync_content_to_config.py` 或另写一次性脚本）。注意载体按域不同：突破/战斗/修炼/机缘域的载体是 `externalize-narrative-texts` 的 narrative_config.json；事件域的载体是 adventure_config 的变体池 schema（题材标签位 + 境界段分桶，bd `tyt` 工程侧已并入 `externalize-narrative-texts`，随该 change 落地）。

### D4：与载体工程的对齐约定（导入零转换歧义）

- `domain=adventure_event` 时 `scene` 列填 `adventure_config.json` 的事件 key（如 `beast_skirmish`）；其余域填 `narrative_config.json` 的场景 key。
- `level_band` 列值与载体桶键一一对应（`通用/练气/筑基/金丹/元婴`），直接映射事件 `desc_variants` 桶与 narrative_config 分桶场景；导入按"当前段+通用"合并规则落桶。
- `route` 列映射池条目的 `route` 标注（灵修/体修分轨条目仅对对应路线玩家轮换）；`通用` 不标注。
- `state`（州）是**纯内容维度**：载体与运行时均无州定向（历练路线不绑定州域），州专属变体导入时并入 `通用` 桶、靠池内随机轮换露出；州烙印靠 §2.2 写作落实，不靠 schema。
- `text` 中的 `{var}` 插值只允许引用该场景在载体工程声明的变量白名单；白名单随 scene key 登记表（tasks 1.4）在写作前先行维护，lint 机器校验，写错变量在成稿期即拦截，不等导入时暴雷。

### D5：事件域写作载体：Markdown 剧本册先行，CSV 后灌

事件域（含四宗）不在 CSV 里直接写作，而是两级：① `design_docs/剧情/` 9 册剧本成稿（册 1-4 散修 11 事件 / 册 5-9 五宗 20 事件组；每事件 5 情景帧 + 6 州条，帧名/段位/tone 标注在标题行，册头带自查清单）→ **用户审阅**；② 定稿后机械灌入 `copy_variants.csv`（设计表，lint 闸门）→ 导入任务消费。理由：剧本册适合人工逐条审阅与跨册一致性比对（两轮全量审阅按此进行）；CSV 保留为机器校验/导入载体（canon 行注"剧本已写待灌 copy_variants"即此状态）。

灌入映射约定：`scene` = 事件 key（15 个基础 key；四宗组复用 elder_guidance/sect_errand/sect_duel/sect_trial 同源 key）；`level_band` 按帧头段位标注（5 情景帧 2/1/2，州条全段通用）；`state` 按州条模式（非宗门 = 六州各 1；宗门 = 本宗州 6 帧全填本州）；`tone_tier` 按册头档位（正/冷各半的册按帧逐条标）；`note` 填帧名。四宗册同样灌入，组属性（sect_jingang/sect_tianji/sect_wandu/sect_xuemo）先行登记，config 立组随 bd `n6o`。

## Risks / Trade-offs

- [变体数量大、文风漂移] → lint 闸门 + tone_tier 逐行标注；写作按域分批自验
- [scene key 与载体工程落地后的实际 key 不一致] → 写作前按 tasks 1.4 先行登记 scene key 与变量白名单对照表，载体工程 tasks 完成后再回核一遍（tasks 6.1）
- [州专属变体凑数变水文] → 每州专属变体必须落 §2.2 该州地貌/势力烙印，lint 之外人工抽查（验收措辞见 tasks 5.2）
- [分桶标注被误读为按段倍增条数] → level_band 是**标注**（同一条变体归属的适用段），143 条预算不因此膨胀；导入/运行时按"当前段 + 通用"取用

## Migration Plan

无运行时迁移。新增一张设计 CSV + lint 扩展。回滚 = git revert。
