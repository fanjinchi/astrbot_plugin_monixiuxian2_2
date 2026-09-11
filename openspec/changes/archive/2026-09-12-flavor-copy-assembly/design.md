# Design: flavor-copy-assembly

## Context

见 proposal.md - Why。现状约束：

- `render_narrative`（`utils/narrative_text.py`）从场景值取池 → `random.choice` → `format_map(variables)`；池条目缺变量 = 机械信息丢失，这是 19 个场景被导入闸门拦截的根因。
- `_validate_narrative_config`（`config_manager.py`）按 `NARRATIVE_SCENE_VARS` 做子集校验；`_iter_scene_entries` 会遍历 dict 场景值的所有键——`panel` 键的字符串值会自然成为 `[panel]#0` 条目接受变量校验，校验器只需豁免其桶键告警。
- `select_narrative_pool` 被 adventure 事件 `desc_variants` 复用（`managers/adventure_manager.py`），事件 dict 不会出现 `panel` 键，双槽识别必须不触碰该函数行为。
- **调用点从不传 `route`/`level_index`**（全部 19 个场景的调用点都只传 variables；唯一传参的是 adventure 事件路径）。CSV 中 52 条 B 场景定稿 flavor 有 47 条（90%）带段桶或路线标注，不传参时合并池恒空——这是本变更必须修复的前置缺陷，否则它们是死文案。
- `design_docs/content-design/lint_narrative.py` 的脱槽正则不匹配 `{var:spec}` 格式符，且变量白名单只从 str 形态场景提取——两个存量缺陷都被本变更放大为阻塞。
- **内容一致性风险**：路线 B 对 flavor 不做改写直接入库，而 CSV 存在与场景结局矛盾的变体（见 D9）——机制落地前必须做内容终审。

## Goals / Non-Goals

**Goals:**

- 6 个重面板场景以双槽形态落地：flavor 引子进分桶池轮换，机械面板单源保留。
- 13 个轻信息场景变体补写变量后过现有契约闸门导入。
- 场景值形态层向后兼容：旧三种形态与内嵌默认照常渲染，加载失败回退默认不崩溃。
- B 场景调用点补传 `route`/`level_index`（机械传参，不改业务逻辑），使 flavor 池真正可达。
- B 场景 flavor 过内容终审：与 panel 结局矛盾的变体改写/删除/挪池，矛盾文案不上线。

**Non-Goals:**

- 不改动 186 条州条（等世界状态系统，bd 3bt ②）。
- 不动 sect_duel/sect_trial 110 条（随 bd n6o）。
- 不为双槽形态做内嵌默认（默认保持纯字符串，双槽只出现在 config 覆盖层）。
- 不引入"panel 必须引用全部声明变量"的更强契约（仍为子集校验）。
- 不改 `select_narrative_pool` 的行为签名（adventure 复用路径锁定）。
- combat 域不补传 route/level_index（5 个 combat 场景变体全为通用桶无 route 标注，已核实无行为差别）。

## Decisions

### D1: 双槽判别用"字符串 `panel` 键且不含 `text` 键"，识别只发生在 `render_narrative`

场景值为 dict、`panel` 键的值是字符串、且不含 `text` 键 → 双槽。`render_narrative` 拼装路径：

1. flavor 池 = 对"剥掉 `panel` 键的场景值"调用 `select_narrative_pool`（复用分桶合并 + route 过滤，函数本身零改动）；
2. 池非空则 `random.choice` 取引子，按同一 `variables` 渲染（允许 flavor 引用契约内变量）；flavor 渲染异常时降级为"跳过 flavor 只出 panel"并记日志（双槽分支内单设 try/except，与整体不 raise 纪律一致）；
3. panel 模板 `format_map(variables)` 渲染，异常时降级输出原始 panel（现有 except 分支语义）；
4. 输出 `flavor + "\n" + panel`；flavor 池为空时只输出 panel——**不得落入现有"pool 空 → 回退默认池"分支**（否则 flavor 被 route 过滤清空的场景会冒出内嵌默认文案，与"只出面板"语义冲突）。

`panel` 键存在但非字符串、或 dict 同含 `text` 键 → 不是双槽：加载校验告警并整场景回退内嵌默认（宁可回退也不让"只出 flavor、机械信息静默丢失"的形态上线；含 `text` 的 dict 会被现有形态判别当单条 route 标注条目，`panel` 被静默忽略，正好绕过非字符串 panel 的回退——需显式堵住）。

**备选：导入时拼装**（导入器把每条 flavor 与 panel 拼成完整模板写入池，运行时零改动）——拒绝：panel 被复制 N 份进池，面板修订必须重跑导入器，违反文案单源；且池条目臃肿后运营难读。

**备选：识别放 `select_narrative_pool`**——拒绝：该函数被 adventure 事件路径复用，双槽是场景级概念，识别收窄到 `render_narrative` 可锁定事件路径零影响。

### D2: A/B 场景拆分按"机械信息是否构成结构化面板"

路线 B（双槽，6 个）：`breakthrough.success`（13 变量全属性面板）、`breakthrough.survive`（5 变量失败结算：next_level_name/rate_info/exp_penalty/experience/pity_msg）、`breakthrough.death`、`breakthrough.revive`（声明变量仅 2 个，但机械信息在模板字面量里——"请使用'我要修仙'命令"/"属性降低到之前的一半"——变量契约管不到，属面板）、`cultivation.retreat_settlement`（结算面板）、`cultivation.retreat_start`（状态面板含 `{end_cmd}` 指令行）。

路线 A（补写变量，13 个）：`breakthrough.comprehend_fail/comprehend_success/comprehend_universal`（各 1 变量 name）、`breakthrough.pity_hint`（streak/next_bonus/remaining 短数字）、`combat.damage_normal/damage_crit`（attacker_name/final_damage）、`combat.dodge/status_expired/ultimate_cast`（各 2 变量）、`cultivation.retreat_epiphany`（skill_name）、`fortune.heart_method_drop/weapon_drop`（name/rank）、`fortune.pill_drop`（items）。

### D3: 调用点补传 route/level_index，success 用突破后境界

B 场景相关调用点统一补传 `route=玩家路线, level_index=玩家当前境界`：`core/breakthrough_manager.py` 全部 11 处 `render_narrative` 调用（19 场景相关 9 处，顺带的 lose_streak_reward/storage_full_drop 2 处一并补，保持辅助函数签名统一）、`handlers/player_handler.py` `_render_narrative`、`core/breakthrough_fortune.py`（`format_fortune_message` 加可选参数，生产调用方仅 `breakthrough_manager.py` 一处，零破坏）。`breakthrough.success` 渲染发生在 `level_index` 已 +1 之后——直接传当前值（突破后境界）：段位桶语义按"新境界的庆功文案"理解，练气→筑基突破出筑基段文案，符合文案的叙事口吻。A 场景调用点顺带补齐（同一辅助函数签名），但 A 场景变体全在通用桶，行为不变。

**combat 域不补传**：5 个 combat A 场景（damage_normal/damage_crit/dodge/status_expired/ultimate_cast）CSV 变体全部 route=通用/band=通用（已逐场景核实），补传无行为差别；且 combat 域有攻/守双方路线歧义（PvP 两玩家可能不同路线，dodge/damage 行该取谁视角需内容规则），`FighterState` 当前也无 route 字段。本次在 `_narrative` 处留注释说明；未来 combat 文案加路线标注时再定取值规则并加字段。

### D4: 校验器扩展——panel 豁免桶键告警，flavor/panel 各自子集校验

`_check_narrative_scene` 对含 `panel` 键的 dict：

1. **先短路特判**（在 `_iter_scene_entries` 遍历之前）：`panel` 值非字符串、或 dict 同含 `text` 键 → 告警 + 整场景回退内嵌默认；
2. 桶键告警豁免写成 `bucket != "panel"`（不误伤其他未知键告警）；
3. 字符串 panel 值经 `_iter_scene_entries` 自然成为 `[panel]#0` 条目接受变量子集校验（现有机制，无需特判）；其余桶键下条目照常校验；
4. 任一条目越界 → 整场景回退内嵌默认（与现有语义一致）。

### D5: lint 工具链修复（本变更前置）

1. **格式符脱槽**：`_WHITELIST_VAR_RE` 改为同时剥离 `{var}` 与 `{var:spec}`（如 `\{([a-zA-Z_0-9]+)(?::[^}]*)?\}`——格式符部分必须非捕获组，否则 `findall` 返回元组、白名单核对全崩），脱槽后再查禁词/百分号/长度——否则 pity_hint 的百分比变体永远 FAIL。
2. **白名单来源**：`_load_var_whitelist` 改读 `NARRATIVE_SCENE_VARS`（代码声明的权威契约；lint 是纯 stdlib 脚本，`data/narrative_defaults/__init__.py` 自带按路径加载 fallback，无循环导入风险），替代"只从 str 形态场景正则提取"的盲视来源——后者在场景转 dict 后整体失效（存量缺陷，本变更把 19 个场景全部转 dict 后影响面扩到全部短句场景）。**保留 adventure_event 分支**（事件域不在声明集内）。语义从"config 已用变量"放宽为"声明变量"（声明集 ⊇ 使用集，因加载校验强制 config ⊆ 声明集），与加载校验口径一致，可接受。
3. 同步 `design_docs/content-design/scene_key_registry.md`：**按 `NARRATIVE_SCENE_VARS` 全量重生成登记表白名单列**——盲视正则的次生灾害不止 pity_hint 缺 `next_bonus`，`retreat_settlement` 也缺 `gained_exp`/`current_exp`（`{gained_exp:,}` 格式符认不出）；另登记 6 个 B 场景的双槽载体形态。

### D6: pity_hint 换行责任移入面板（内嵌默认 + 导入器同步调整）

现状：survive 面板以 `当前修为：{experience}{pity_msg}` 收尾，换行靠 pity_hint 默认文案的前导 `\n` 承担；导入器 `_to_entry` 对 text `.strip()`，CSV 变体无法携带前导换行。决策：换行责任移入面板——

- 内嵌默认（`data/narrative_defaults/breakthrough.py`）：survive 模板改为 `{experience}\n{pity_msg}`、pity_hint 默认文案去掉前导 `\n`；
- 导入器迁移 panel 时同样处理（survive 旧值搬入 `panel` 前，把 `{pity_msg}` 改为 `\n{pity_msg}`；仅 str→panel 迁移分支，二次运行取 `panel` 键原样保留）。

组合矩阵（四格）：旧+旧（存量 config，不动）✓ 单换行；新+新（新装/导入后）✓ 单换行；新 panel + 旧 pity_hint → 双换行；旧 survive + 新 pity_hint 变体 → 粘连。后两格仅在"部分导入"（一场景过闸、另一场景被跳过）时可达，为纯 cosmetic 降级且有界——7.2 的"19 场景 0 FAIL 才执行"闸门兜住计划路径，5.4 的组合测试断言的是降级有界而非美观。`pity_msg` 运行时实际永不为空（无条件渲染），空串只产生尾部换行，aiocqhttp 发送端会 strip，无害。

### D7: 导入器对 B 场景做"默认模板搬家"，幂等

`scripts/sync_copy_variants_to_config.py` 对 6 个 B 场景：旧值为字符串 → 作为 `panel`（survive 按 D6 补换行）；旧值已是双槽 dict（二次运行）→ 取其 `panel` 键原样保留。CSV flavor 行按 level_band/route 规则写入分桶，整体重建该场景值（幂等，每次从 CSV 全量重建）。B 场景 flavor 的导入校验从"⊇ 默认变量集"改为"⊆ 声明变量集"（flavor 本就不携带机械变量，与加载校验口径一致）。A 场景维持现有"变体 ⊇ 默认模板变量集"契约。

B 场景清单硬编码在导入器（与 A/B 拆分同源于本设计），后续新增双槽场景需同步清单——刻意保守，避免配置侧意外产生双槽形态。

### D8: A 场景文案补写走 design_docs 内容流程

13 个场景的变体在 `copy_variants.csv` 直接改写 `text` 织入变量，过修复后的 lint 再导入。内容阶段处理评审标记的结构性改写难点：

- `ultimate_cast` v02 是第二人称视角（"你引血成诀"），战斗中攻击方可能是敌方——改写为 `{attacker_name}` 视角，属结构性改写而非补变量；
- `weapon_drop` 三条写死兵器形态（锈剑/断枪/短刃），与 `{name}` 的任意武器（如狼牙棒）事实矛盾——改为不指定形态的表述；
- `pill_drop` v01 写"一粒滚圆丹药"，但 `{items}` 是多丹拼接串——改单复数中性表述；
- `comprehend_fail` 机制是"突破失败时 10% 软保底**领悟成功**获得功法"（默认文案"破而后立，领悟功法【{name}】"），但两条定稿变体写的都是"没悟成、捞了个空"——按机制改写为"失败中意外有所悟"的口径；
- `retreat_settlement`（B 场景）4 条 flavor 已含 `{time_str}`，与 panel 的"闭关时长"行重复——内容阶段从 flavor 去掉时长信息。

### D9: B 场景 flavor 内容终审（路线 B 不改写 flavor，矛盾必须入库前清掉）

路线 B 对 flavor 原样入库，因此入库前必须逐条审 B 场景 flavor 与 panel 结局的一致性。已查实：

- `breakthrough.death` 16 条定稿中 8 条（no=02 山涧得救、04 破庙佛前、06 同门护法、08 老教头、10 残破玉镯、12 心口一劫、14 一缕残魂、16 老龟驮骨）叙事的是"濒死获救、活了下来"，与 death 面板"身死道消、数据清除、重新修仙"直接矛盾——终审处置：改写为死亡结局、删除，或挪入 survive 池（其语义就是"活了下来"）；
- 其余 5 个 B 场景（success/survive/revive/retreat_settlement/retreat_start）逐条过一遍结局一致性（success 庆功✓ survive 存活✓ revive 复活✓ 类口吻抽查），确认无同类矛盾。

终审结论落回 `copy_variants.csv`（改写/删除/挪池均改 CSV 并在 note 列注明），走完 lint 后随导入器入库。

## Risks / Trade-offs

- [flavor 与 panel 拼接后阅读节奏不佳（散文接表格面板突兀）] → panel 模板自带 `━━━` 分隔段，flavor 作为段首引子；内容阶段对 6 个场景做样例验收，必要时调整 panel 首行。
- [双槽形态被误用到非面板场景，flavor 承担机械信息] → 规格明确"flavor MUST NOT 承担机械信息"；双槽场景清单硬编码在导入器；非字符串 panel 与 text+panel 混写均回退默认，杜绝半畸形形态。
- [panel 修订后 flavor 引子语境过时] → 接受：flavor 与 panel 的耦合仅语气层面，变体轮换本就多样化；panel 大改时同步审 flavor 池。
- [panel 为空字符串时机械信息全丢（手改配置才可达）] → 已知空洞，导入器生成的 panel 非空；子集校验无法防"空模板"，记录在案不阻塞。
- [success 的 24 条 flavor 全部带段桶+路线标注，Lv40+（化神后）玩家 flavor 池恒空只出 panel] → 可接受：season-1 幕表只覆盖到元婴段，满级玩家看到面板信息与今日一致；后续赛季补段桶文案即可，不改机制。
- [success 传突破后境界导致"练气末段文案永不被 success 抽到"] → 可接受：筑基段文案同样庆祝破境，叙事成立；若内容侧希望保留"破境瞬间回顾旧段"的口吻，后续加桶选择偏移即可，不改机制。
- [functional_tests 断言被 flavor 前置打破] → 已实读三份相关用例（gm-basics/gm-time-tools/player-lifecycle），断言均为 contains 或未锚定 `re:`，panel 全文仍在消息体内，预期不破；7.4 保留跑一遍确认作为尽职核查。

## Migration Plan

1. lint 修复 + scene_key_registry 全量重生成（解锁内容补写闸门），存量 477 行回归 0 FAIL。
2. 运行时 + 校验器扩展（纯增量，旧形态不受影响），调用点补传参，内嵌默认换行调整；pytest 叙事用例全绿。
3. A 场景文案补写 + B 场景 flavor 终审（design_docs 流程，用户确认）。
4. 跑导入器：6 个 B 场景转双槽、13 个 A 场景变体入库；pytest + ruff + validate_budget + lint_narrative + functional_tests 相关用例质量门。
5. 回滚：`config/narrative_config.json` 由 git 管理，直接回退文件即可；加载校验失败时自动回退内嵌默认，不存在崩溃路径。

## Open Questions

（无——retreat_settlement 的 time_str 去重已转入 D8；death 救回系处置已转入 D9；combat 域 route 取值规则随未来路线标注内容再定；flavor 是否允许引用变量维持规格允许的子集口径。）
