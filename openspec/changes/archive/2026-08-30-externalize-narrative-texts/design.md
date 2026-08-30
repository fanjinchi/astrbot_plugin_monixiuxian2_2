# Design: externalize-narrative-texts

## Context

现状（详查于 2026-08-28 代码审查）：

- 高频叙事文案硬编码热点：突破 6 分支模板（`core/breakthrough_manager.py:311-469`）+ 机缘三句（`core/breakthrough_fortune.py:194-219`）；战斗 ~20 条句式（`managers/combat_manager.py:202-265`、`_resolve_attack` `:885-1056` 与免死 `_try_survive` `:1058-1074`，PvP/PvE/Boss/传承共用）；修炼结算（`handlers/player_handler.py:304-476`）+ 灵根评价大表 ~48 条（`core/cultivation_manager.py:203-263`）
- 成功率说明文本（`core/breakthrough_manager.py:138-191` 的 `rate_info`）属数值说明类，**不在外移范围**（见 D6）
- 秘境：`rift_config.json` 只有 `name` 无 `description`；探索事件 5 条变体硬编码（`rift_manager.py:324-328`）
- 历练事件：`event_groups` 5 组（safe/standard/risky/disaster/sect_qingyun）仅按风险档分桶，每事件单条 `desc`，无题材维度、文案不随玩家境界段变化（bd `tyt` 工程侧并入本变更，见 D7）
- 传承之地文案：`adventure_manager.py:397-407` / `rift_manager.py:400-405` 两处"偶遇传承之地"近似重复；`sect_manager.py:1697/1748-1752` 为领取制（"需先战胜守护者"）同主题文案，含宗门专属机制行
- adventure/bounty/enemy 三个 manager 各自内嵌 DEFAULT fallback 副本（如 `managers/adventure_manager.py:55-120`）并自行加载 config（不经 `_load_config_with_default`），`data/default_configs.py` 目前无这三个域的默认值，内嵌副本与 config 文件内容漂移
- `utils/config_loader.py` 的 `ConfigLoader` 无人调用（死代码）
- 现成加载模式：`_load_config_with_default`（`config_manager.py:298`，默认值在 `data/default_configs.py`）、`_load_items_data`（`config_manager.py:321`，name→dict 条目型）

## Goals / Non-Goals

**Goals:**
- 梯队 1 全部高频文案有可配置载体，文案改内容不再需要改代码
- 文案模板支持变体池（同场景多条随机轮换），为 §1.7 变体量标准提供容器
- 模板插值变量有机器校验，文案侧写错变量名启动即报错
- 消除文案双份维护（fallback 副本、三处传承文案）

**Non-Goals:**
- 不改任何文案内容本身（逐字搬运），不改任何数值与流程逻辑
- 不写历练事件题材文案内容、不做 disaster 组扩量与四宗专属组补齐（bd `tyt` 内容侧，走 design_docs 管线）；不做 Boss 名号池/灵眼/银行广播外移（后续变更）
- 不重构突破/战斗/结算的流程代码，只替换文案取数点

## Decisions

### D1：单一 `narrative_config.json` 按域分节，灵根大表独立文件

- `narrative_config.json` 结构：`{ "breakthrough": {...}, "combat": {...}, "cultivation": {...}, "fortune": {...}, "legacy_encounter": {...} }`，每节下按场景（scene）挂模板或变体池。
- 灵根/体质评价 ~48 条是 name→条目大表，体量远超其他节，独立为 `config/spirit_root_descriptions.json`，用 `_load_items_data` 条目型模式。
- **理由**：高频文案集中一处，梯队 1 写作时只开一个文件；灵根大表单列避免 narrative_config 失衡。备选"每域一个文件"放弃：6+ 个小文件的加载样板代码收益为负。

### D2：变体池 schema 与插值契约

- 单模板场景：`"scene_key": "模板文本 {var}"`；变体池场景：`"scene_key": ["变体1", "变体2", ...]`（运行时均匀随机取一）。
- 插值用 Python `str.format_map` 风格的 `{var}` 占位；代码侧每个渲染点声明提供的变量集合（如战斗结算提供 `{name}/{final_damage}/{skill_name}/...`）。
- **加载时校验**：模板中引用的变量名必须是该场景声明变量的子集，否则启动时报错并拒绝加载该场景（fallback 到内嵌最小默认文案，保证不崩）。
- **测试兼容**：narrative 访问器挂在 config_manager 上时，须容忍测试的 fake config 实现——访问器缺省/场景缺失时静默回退内嵌最小默认文案（与契约校验的回退路径同一套），避免 `tests/test_combat_engine.py` 等 FakeConfigManager 用例变红。
- **理由**：审查发现战斗插值约 7-8 类变量（name/final_damage/reflect/heal/skill_name/ult_name/剩余气血等）、突破/结算也都是固定变量集，契约校验成本低；实现时以各渲染点实际变量为准逐场景声明，不照抄估计数。变体池用 list 还是单条用 str，loader 统一归一为 list 处理。
- **分桶与路线标注（对齐内容侧写法，给梯队 1 导入预留）**：场景值除 str/list 外支持第三种形态——按境界段分桶的 dict（桶键 `通用/练气/筑基/金丹/元婴`，与 D7 事件分桶同一组键、同一个"当前段桶+通用桶合并随机"的取用 helper）；池条目除纯字符串外允许 `{"text": "...", "route": "灵修"|"体修"}` 形式，route 标注条目仅对对应路线玩家参与轮换（未标注=全路线通用）。初版逐字搬运全部用"池长 1 纯字符串"，分桶/路线形态本变更只建 schema 与取用逻辑，不预填内容。

### D3：rift 配置扩展（og9）

- `rift_config.json` 每秘境加 `description`（入口叙事）与 `settlement_desc`（结算叙事位）；探索事件变体池从 `rift_manager.py` 外移为顶层 `explore_events` 数组（key/desc/权重结构沿用现硬编码字段）。
- **存储走 config-only**：description 不落 DB 列、不需要 migration——UI 展示时读 config 条目（沿用 `rift_manager.py:148`/`:180` 现有 `_get_rift_config_entry` 模式），DB 里的秘境记录保持不变。
- `rift_manager` 读取链路同步扩展；UI 列表（`rift_manager.py:200-208`）展示 description。
- 字段默认值兼容存量：无 description 的旧配置加载不报错（空串），lint/内容侧后续补齐。

### D4：fallback 收敛为单源（迁移 + 改引用两步）

- 第一步：把三 manager 内嵌 DEFAULT 副本的默认值**迁移进 `data/default_configs.py`**（该文件当前无这三个域的默认值）；
- 第二步：三 manager 改为引用 `default_configs.py` 的单源默认值（经 `_load_config_with_default` 或等价路径），删除内嵌副本。
- **理由**：三 manager 目前自行加载 config（不经 `_load_config_with_default`），内嵌副本并非纯冗余而是唯一兜底，故必须先迁移默认值再删副本；副本与 config 漂移已被审查证实为漏检源。

### D5：文案外移逐字搬运，内容零变更

本变更是工程变更：所有外移文案逐字复制现有代码文本进 config（含 emoji 与零宽空格等既有细节），diff 审查时逐条核对"配置文本 == 原代码文本"。任何措辞优化留给内容任务。

### D6：数值说明类文本不外移（2026-08-28 定）

向玩家解释机制数值的文本——突破成功率分解 `rate_info`（`core/breakthrough_manager.py:138-191`）、结算数值行、属性面板说明行——保持简洁直白、不做修仙风格化，**留在代码原位、不外移进配置**（world-bible §1.3 注）。本变更只外移 flavor 文案；`breakthrough_manager.py:281` 连败奖励句属 flavor 文案，仍在外移范围。

### D7：历练事件文案载体——题材标签位 + 境界段分桶变体池（bd `tyt` 工程侧，2026-08-28 并入）

- `adventure_config.json` 事件条目新增两个可选字段：`tags`（题材标签位，如 妖域/势力冲突/NPC/遗宝，默认空列表；具体取值由内容侧挂 bible §2.3/§3.6/§3.2.6 弹药库）与 `desc_variants`（按境界段分桶的文案池：`{ "通用": [...], "练气": [...], "筑基": [...], "金丹": [...], "元婴": [...] }`，桶键对齐 season-1 幕表等级段 Lv1-9/10-19/20-29/30-39）。
- 运行时取文案：玩家当前境界段桶 + `通用` 桶合并随机取一（与 D2 分桶场景同一 helper、同一组桶键）；当前段无桶或合并池为空时回落现有 `desc`（逐字保留为兜底）。桶键未覆盖的境界段（如 Lv40 化神初期）按空桶处理回落兜底。事件 `desc_variants` 池条目同样支持 D2 的 `route` 标注形式。
- **数值零变更**：`exp_mult`/`gold_mult`/`item_chance`/`bonus_progress` 等字段不动——路线 base+level_bonus 已平滑覆盖成长，分桶只影响文案。
- 存量条目无新字段正常加载（`tags` 视为空、无 `desc_variants` 直接用 `desc`）。内容填充（≈143 条变体、disaster 组扩量、四宗专属组补齐）走 design_docs 管线，不在本变更。
- **理由**：事件域是梯队 1 文案的最大头，没有分桶载体则 `season-1-tier1-copywriting` 的事件文案无处可导入；schema 一次到位（标签位 + 分桶池），避免内容侧开工后返工。

## Risks / Trade-offs

- [模板变量与代码渲染点脱节（文案新增了代码不提供的变量）] → D2 加载时契约校验 + 场景级 fallback
- [变体池随机轮换改变战斗日志快照的测试断言] → 测试侧对涉及变体的断言改为"匹配变体池其一"或注入固定选择；既有测试若断言原文案，外移后保持单变体（池长 1）保证断言不变
- [外移点位多、逐字搬运易漏] → tasks 按域拆分 + 每域收尾跑该域既有测试 + functional_tests 对应域用例
- [玩家已有存档/外部脚本直接读 rift_config] → description 为纯新增可选字段，向后兼容
- [境界段判定与幕表段不一致导致事件文案桶错位] → 段边界集中在 adventure_manager 一处映射（Lv1-9/10-19/20-29/30-39，对齐 season-1 幕表），未知桶键告警不报错

## Migration Plan

纯新增配置 + 代码取数点替换。`narrative_config.json` 首次启动由 `_load_config_with_default` 自动从 `default_configs.py` 落盘；rift description 缺省空串。回滚 = git revert（config 文件残留无害）。

## Open Questions

- 战斗变体池在 PvP 双方同屏场景是否需要"不连续重复上一条句式"的去重逻辑：初版不做（池长 1 无影响），梯队 1 内容填充时若需要再补。
