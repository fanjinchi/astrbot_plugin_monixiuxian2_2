# Design: narrative-content-pipeline

## Context

现状（详查于 2026-09-03，动机见 proposal.md）：

- `world-bible.md` 已是文案唯一事实来源，含基调/地理/势力/命名规范/收编清单（§6 全枚举）
- `design_docs/content-design/` 已有数值设计 CSV 三件套（`weapons.csv`/`skills.csv`/`heart_methods.csv`），列含 `description`/`ref_source`/`design_note`/`status`，经 `content-sync-pipeline` 规范全量重导入 config，入库闸门为 `validate_budget.py`（数值预算）
- `enemies.json`/`adventure_config.json`/`rift_config.json` 等**无对应设计 CSV**，描述字段直接活在 config
- `rift_config.json` 无 description 字段；突破/战斗/修炼结算文案硬编码在 handlers/managers 代码里

## Goals / Non-Goals

**Goals:**
- 建立三层大纲结构：bible（世界层，恒常）→ season outline（季度层，增量）→ canon 表（条目层，日常）
- 每条内容有可查证的叙事身份（出处/文风档/钩子/叙事状态）
- 文案质量有机器闸门（lint），不依赖人记 §5.3
- bible §6 从"全枚举副本"退化为"裁决规则 + 引用"，消除双份维护

**Non-Goals:**
- 不撰写任何最终文案（梯队写作是后续内容任务）
- 不改任何 config 数值、不改运行时代码
- 不做文案外移工程（突破/战斗文案 config 化）与 rift description 字段——另行提案
- 不改 content-sync-pipeline 既有 reconcile/键映射/预算验算语义，只加 lint 闸门调用点

## Decisions

### D1：canon 叙事列并入现有设计 CSV，不建平行表

为 `weapons.csv`/`skills.csv`/`heart_methods.csv` 增 4 列：`canon_origin`、`tone_tier`、`story_hook`、`narrative_status`。

- **理由**：现有 CSV 已是 config 的同步来源，且已有 `status`（数值态）列先例——`narrative_status` 与之正交（数值 draft 不代表文案定稿）。另建平行 canon 表会引入第二张 id↔name 对照表，同步脚本与人工都要双份维护，正是本次要消灭的腐臭模式。
- **备选**：独立 `canon.csv` 大宽表（所有内容类型合一）——放弃：三类内容的数值列不同，宽表大量空列，且与 sync 管道的按类同步结构冲突。

### D2：无设计 CSV 的域用轻量叙事表

`events-canon.csv` / `enemies-canon.csv` / `rifts-canon.csv` 只含 `id, name, canon_origin, tone_tier, story_hook, narrative_status`（+ 域特有少量列如事件组 key），**不含数值列**。

- **理由**：这些域数值归 config 管辖，叙事表只登记叙事身份，避免制造第二个数值来源。lint 对它们只做名字一致性 + 叙事列校验，description 文本本身留在 config 里被 lint 扫描。

### D3：lint 独立脚本，sync 只加调用点

新建 `lint_narrative.py`（与 `validate_budget.py` 同级、同风格），同步脚本在预算验算后调用它；不改 `validate_budget.py`。

- **理由**：数值预算与文本规范是两种失败模式（前者算数、后者查词表），单一职责；lint 也应能脱离 sync 单独跑（写作期自检），独立脚本天然满足。
- 禁词表来源：初版硬编码 bible §5.3 清单于脚本顶部常量（附 bible 出处注释），bible 修订时人工同步脚本——bible 是文档不是数据文件，解析它得不偿失，变更频率低。

### D4：剧情幕表放 season-1-outline.md，不放 bible

- **理由**：bible §1.1 的主线时间轴是恒常设定；而"玩家筑基期时世界处于复苏第几潮、第二波妖乱何时来"是**第一季专属的运营计划**，会随每季重写。恒常/增量分层后，第二季只需新建 outline，不动 bible。bible 只补一句"剧情幕表归各季 outline"的指针。

### D5：文案载体清单放 bible 新节（§1.6 或附录）

一张表列出：文案类别 → 物理位置（哪个 config 字段 / 哪个代码文件）→ 外移优先级。理由：载体是"恒常的结构事实"（哪个系统在哪说话），归 bible；而"本季先写哪批"归 outline。两者分离正好对应恒常/增量分层。

### D6：bible §6 退役方式——规则保留、清单迁出

§6 保留：收编状态词定义（收编/改名/待删/延后/待补）、裁决规则、"bible 不能无视存量"原则、规划位表（§6.1 五宗内容位保留，因为那是规划而非清单）；删除逐条全枚举段（§6.2~§6.9 的名录），改为指向 canon 表的一句话 + 示范样例两行。变更记录注明迁移。

- **风险对冲**：保留规划位表是因为它是"未来内容位的占位宣告"，属于设定；全枚举段是"现存名副本"，属于注定腐臭的冗余。两者性质不同，区别对待。

### D7：填充顺序写入 season outline，作为四梯队计划

第 0 步剧情幕表 → 梯队 1（高频界面文案：突破/修炼结算/战斗/历练事件变体）→ 梯队 2（里程碑：秘境入口、悬赏职阶、敌人背景）→ 梯队 3（低频条目：武器护甲心法丹药材料描述重写，改名随此梯队逐条进行）→ 梯队 4（长线留白：新手宗门链/四宗落地/合欢宗回归，依赖系统就绪）。

- **理由**：按"玩家经过率 × 情绪强度"排序；改名不单独发起轮次，与描述重写同批进行避免二次触碰。该顺序是季度计划而非 bible 规则，放 outline。

### D8：擦边尺度作为基调点缀（2026-09-03 用户确认）
基调允许"擦边"（暧昧/暗示/情趣向但**不露骨**）作为文案点缀，可适度加入各类文案（开场、心法、历练、NPC 台词等）。约束四条，bible §1.3 新增"擦边尺度"小节与玩梗尺度并列：

1. **暗示不直白**：点到为止，不写露骨画面与生理细节；
2. **点缀不喧宾夺主**：擦边是彩蛋位/氛围位，正文仍以叙事为主，不得通篇为擦边而擦边；
3. **不物化到出戏**：角色形象服务于世界观人设，不写成脱离设定的人形立牌；
4. **禁用词仍生效**：现代/机制词汇照旧禁入正文（§5.3）。

开场「巨乳肥臀的冷面仙子」属该尺度的正当用例，保留；现有 §1.3 玩梗尺度、§5.3 禁用词与其并列不冲突——擦边只在"性暗示"维度放开，现代词与数值承诺维度照旧收紧。

### D9：legacy 行从"不导入即删除"改为"不导入但保护"（2026-08-27 审查修正）

`sync_content_to_config.py` 原 reconcile 语义：legacy 行的 config 同名条目一并删除。审查发现宗门技能池（sect_qingyun/sect_huanxi）与青云心典（heart_qy_001）、青云镇山剑（wpn_qy_001）等现存内容未登记设计表，下次 sync 会被静默删除。

- **决策**：legacy 行改为"未收编现存内容"的登记位——不导入、闸门违例仅 WARN、config 同名条目受 reconcile 保护；要删除内容须从 CSV 整行移除。配套新建 `scripts/export_config_to_canon.py` 把 config 中缺失条目逆向补登记进 CSV（数值照抄 config、status=legacy、叙事列占位起步），并新建 `bounty-canon.csv`。
- **理由**：这些条目数值先于三族规范存在，直接标 draft 会被预算闸门 FAIL（如 qy_001 路线系数 1.1/0.9 越带），而改数值属于另一个设计决策，不能随"登记"夹带进 config。收编路径不变：flip 为 draft 并过预算闸门。
- **风险**：sword_003（碧水灵剑）这类"已按旧语义删除"的条目不受影响（config 中已不存在，legacy 行只是存档）；工作流变化点（删除=整行移除）已写进脚本 docstring 与 content-design/README。

## Risks / Trade-offs

- [lint 禁词误报：正经文案恰含禁词子串（如"传承"任务文案含"任务"）] → 禁词按子串匹配 + 正当整词白名单常量兜底（中文分词得不偿失，误报逐条评审后入白名单）；占位状态行放宽
- [canon 列回填工作量大（三表约 80 行 + 三张新表）] → 回填本身即梯队 0 任务，按域分批；lint 对空 canon_origin 只 WARN 不 FAIL，允许渐进回填
- [bible §6 退役后，外部引用具体条目处失联] → 保留 §6 标题与裁决规则，名录处注明"见 canon 表"；变更记录写明迁移日期
- [lint 接入 sync 可能阻塞既有工作流] → sync 的 lint 闸门初版只对 `narrative_status=定稿` 的行 FAIL，其余 WARN；全量收紧为后续变更，给回填留窗口

## Migration Plan

纯文档/工具变更，无运行时迁移。步骤（细节在 tasks.md）：bible 增补 → outline 新建 → CSV 加列回填 → 新叙事表建立 → lint 脚本 → sync 调用点 → README 登记 → §6 退役改写。回滚 = git revert，无副作用。

## Open Questions

- 描述长度上限 60 字是否适配所有域（武器触发技名较长）：lint 参数化，按域设限，初版统一 60 可调
