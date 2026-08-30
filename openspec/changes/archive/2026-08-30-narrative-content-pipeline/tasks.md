# Tasks: narrative-content-pipeline

## 1. world-bible.md 增补

- [x] 1.1 新增剧情幕表指针：§1.1 附近注明"各季剧情幕表归 season outline"，bible 只留主线轴
- [x] 1.2 新增势力冲突矩阵节（§3.6）：五宗 + 散修 + 妖域的利益冲突/历史结怨清单，每条含冲突双方、争夺物、可挖掘的文案场景（悬赏/历练/师承）
- [x] 1.3 NPC 人格化三件套：§3.2 各宗门人物（玄诚子/清微道长/玄渡/净持/顾望舒/裴青萝/毒无涯/蝎娘子/血屠/孔无常）补性格关键词 ×3 + 口头禅 + 常派活类型
- [x] 1.4 新增文案载体清单节（§1.6）：文案类别 → 物理位置（config 字段 / 代码文件）→ 外移优先级表
- [x] 1.5 事件文案变体量标准写入 §1.7 新节：每事件组 ≥5 条通用变体 + 每州 ≥1 条专属
- [x] 1.6 §1.3 新增"擦边尺度"小节（与玩梗尺度并列）：按 D8 四条约束（暗示不直白/点缀不喧宾夺主/不物化到出戏/禁用词仍生效）落笔，开场「巨乳肥臀的冷面仙子」据此保留
- [x] 1.7 小修正：§1.4 清X山 X 取值规则写死；§1.1"不留钩子"措辞修准为"不留需兑现的悬念，允许时代事实远景陈述"；§2.2 表加"类型（区域/秘境）"列

## 2. season-1-outline.md 新建

- [x] 2.1 新建 `design_docs/season-1-outline.md`：剧情幕表（练气/筑基/金丹/元婴四段 × 世界状态：复苏阶段、妖乱强度、秘境开启叙事、宗门对散修态度）
- [x] 2.2 第一季内容预算表：各类内容数量目标与文案变体数（武器/功法/心法/事件组/秘境/敌人）
- [x] 2.3 四梯队填充顺序计划（按 design.md D7 落笔，标注每梯队依赖的工程前置）

## 3. Canon 表体系

- [x] 3.1 `weapons.csv` 增列 `canon_origin,tone_tier,story_hook,narrative_status` 并全量回填（现有行 narrative_status 标"占位"起步，出处明确者直接填）
- [x] 3.2 `skills.csv` 同上增列回填
- [x] 3.3 `heart_methods.csv` 同上增列回填（新列追加于 status 后，经 `sync_content_to_config.py --dry-run` 验证映射不受影响）
- [x] 3.4 新建 `events-canon.csv`：遍历 `adventure_config.json` 事件组建表（id/key、name、4 叙事列 + 适用路线/州域备注列）
- [x] 3.5 新建 `enemies-canon.csv`：遍历 `enemies.json` 模板建表（含 elite_prefixes/boss_names 的叙事备注列）
- [x] 3.6 新建 `rifts-canon.csv`：遍历 `rift_config.json` 建表（注明 config 暂无 description 字段，文案待工程变更落地）

## 4. lint_narrative.py 与 sync 接入

- [x] 4.1 新建 `design_docs/content-design/lint_narrative.py`：禁词表（bible §5.3，脚本顶部常量 + 出处注释）、数值承诺正则、长度上限（默认 60 字可按域覆盖）、品级冠词检查、CSV↔config 名字一致性；非零退出码 + 逐条定位输出；`--strict` 控制占位行放宽
- [x] 4.2 canon 列校验：四列存在性、tone_tier/narrative_status 取值域、canon_origin 可在 bible 查证的词表检查（初版用 bible 州域/宗门/秘境名词表）
- [x] 4.3 同步脚本接入 lint 闸门：预算验算后调用；初版仅 `narrative_status=定稿` 行的 FAIL 阻塞同步，其余 WARN（见 design.md 风险节）
- [x] 4.4 用例自验：构造含禁词/数值承诺/名字不一致/非法文风档的样例行，确认 lint 全捕获；对现状三表全量跑通（占位行应只 WARN 不 FAIL）

## 5. §6 退役与登记

- [x] 5.1 bible §6 改造：保留收编状态词定义/裁决规则/§6.1 五宗规划位表；§6.2~§6.9 全枚举名录删除，改为指向 canon 表的说明 + 示范样例两行；变更记录注明迁移
- [x] 5.2 `design_docs/README.md` 登记：season-1-outline.md、三张 canon 新表、lint_narrative.py
- [x] 5.3 `openspec validate narrative-content-pipeline --strict` 通过；lint 对全量现状跑出基线报告（WARN 数入变更记录：0 FAIL / 70 WARN）

## 6. 审查修正（2026-08-27，评审发现问题后追加）

- [x] 6.1 幕表事实对齐：等级段修为 Lv1-9/10-19/20-29/30-39（Lv40=化神初期为满级边界）；秘境开启叙事列改为 `rift_config.json` required_level 实况（金丹/元婴段无新秘境标注为缺口，扩充与满级玩法登记 bd `trl`）
- [x] 6.2 数量勘误与术语统一：武器 11→10 件；历练"13 组"→"5 组 13 事件"；bible §1.7"每事件组"→"每事件"
- [x] 6.3 canon 覆盖缺口补登记：新建 `scripts/export_config_to_canon.py`，补登 wpn_qy_001/heart_qy_001/qy_001-003/hx_001-002（status=legacy）；新建 `bounty-canon.csv`（8 模板）
- [x] 6.4 reconcile 语义修正（D9）：legacy 行 config 条目由"删除"改为"保护"（delta spec MODIFIED 设计表合并同步）
- [x] 6.5 lint 改进：轻量 canon 表补"叙事待写" WARN（回填进度可见）；bounty 接入 canon 定严重度；新增 `tests/test_lint_narrative.py`；lint 新基线 0 FAIL / 119 WARN
- [x] 6.6 后续工作登记 bd：秘境扩充+满级玩法 `trl`；config 导入导出工作流封装 skill `mhv`
