# content-sync-pipeline Specification

## Purpose

设计表（design_docs/content-design/*.csv）到运行时配置（config/*.json）的同步管道：让设计内容可入库、可校验、可测试，并防止契约断裂与预算超标内容进入线上配置。
## Requirements
### Requirement: 设计表合并同步

（reconcile 全量重导语义不变，仅修订 legacy 行的处置——2026-08-27 审查发现：宗门技能池/青云心典等现存内容未登记设计表时会被 reconcile 静默删除）系统 SHALL 提供设计 CSV → config JSON 的同步脚本，以设计表为唯一来源进行全量重导：脚本 SHALL 导入 status 为 draft/final 的设计行（按 `name` 键合并：同名更新字段、新名新增），并 SHALL 删除 config 中完全不在 CSV 中的既有条目。status=legacy 的行是"未收编现存内容"的登记位（如 `export_config_to_canon.py` 补登记的宗门池/镇派心法）：不参与导入、闸门违例仅 WARN，且其 config 同名条目 MUST NOT 被 reconcile 删除（要删除内容 = 从 CSV 整行移除该行）。legacy 行中的设计有效条目由设计表修正为 draft 并过预算闸门后纳入导入。

#### Scenario: 表外条目删除

- **WHEN** config 中存在完全不在 CSV（任何 status 行）中的旧条目
- **THEN** 同步后该条目被删除，config 仅保留 CSV 已登记条目（draft/final 导入 + legacy 保护）

#### Scenario: 同名条目更新

- **WHEN** CSV 中 status=draft 的行与 config 既有条目同名
- **THEN** 该条目的字段被 CSV 值更新，config 其余条目保持不变

#### Scenario: 新条目新增

- **WHEN** CSV 行的 name 不存在于 config
- **THEN** 脚本在 config 中追加该条目

#### Scenario: legacy 行跳过

（语义修订：旧版为"不导入即删除"，2026-08-27 起改为"不导入但保护"，场景名沿用原标识）

- **WHEN** CSV 行的 status=legacy 且 config 存在同名条目（如补登记的宗门技能池）
- **THEN** 该行不参与同步导入，其 config 条目在 reconcile 阶段被保留；该行的闸门违例只计 WARN 不阻塞同步

### Requirement: 键名映射与引擎契约校验

同步脚本 SHALL 执行设计列名到 config 键名的映射（如 weapons.csv 的 `bonus_damage` 映射为 weapons.json 的 `damage` 键）。触发技数据 MUST 通过引擎契约校验：`trigger_timing` / `effect_type` / `trigger_rate` / `effect_value` 四键齐全且值域合法，否则脚本 MUST 报错中止且不写盘。大招数据 MUST NOT 含 `trigger_rate` 字段（必放制由引擎默认提供）；发现时脚本 MUST 报错中止。

#### Scenario: 挂载技缺键拒绝

- **WHEN** 武器 trigger_skills 中某技能缺少 `effect_type`
- **THEN** 脚本报错指出条目与字段，中止执行，config 文件不被修改

#### Scenario: 大招概率字段拒绝

- **WHEN** 功法 ultimate 数据含 `trigger_rate`
- **THEN** 脚本报错并中止，提示必放制下该字段由引擎默认提供

### Requirement: 预算验算闸门

同步脚本 SHALL 在写盘前运行 validate_budget.py 对全部 draft/final 设计行进行预算验算；存在 FAIL 行时脚本 MUST 中止且不写盘，legacy 行产生的 WARN MUST NOT 阻塞同步。

#### Scenario: 预算超标拒绝入库

- **WHEN** 某 draft 武器的每击伤害超出其体量/品级预算带
- **THEN** 脚本输出该行的验算明细并中止，config 文件不被修改

### Requirement: 叙事文案 lint 闸门

同步管道 SHALL 提供叙事文案 lint 脚本（`design_docs/content-design/lint_narrative.py`），对设计 CSV 的 `description` 列与对应 `config/*.json` 的描述字段执行检查；存在 FAIL 项时 lint MUST 以非零码退出并逐条输出位置与原因。入库同步（sync）SHALL 在预算验算之外接入 lint 作为第二道闸门：lint FAIL 时脚本 MUST 中止且不写盘。lint 检查项 SHALL 至少覆盖：

- **禁用词**：`world-bible.md` §5.3 禁用词清单中的现代/出戏词与机制承诺词不得出现在文案正文
- **数值承诺**：文案不得含百分数、阿拉伯数字数值表述（如"+30%"、"伤害 15"）等机制承诺
- **长度上限**：单条描述不超过设定上限（默认 60 字，可配置）
- **品级冠词**：品级词（凡/灵/玄/地/天）只作名称冠词，不进描述正文
- **名字一致性**：CSV `name` 列与 config 同 id 条目的 `name` 字段 MUST 一致；不一致即 FAIL 并输出两处名字

#### Scenario: 禁词拒绝入库

- **WHEN** 某 draft 心法描述含"被动技能加成 +10%"字样
- **THEN** lint 输出该行的位置与违例词并以非零码退出；同步脚本中止，config 文件不被修改

#### Scenario: 名字不一致拒绝

- **WHEN** `weapons.csv` 中 `sword_006` 的 name 为"青云天剑"而 config 同名 id 条目 name 为"裂空神剑"
- **THEN** lint 报告两处名字差异并以非零码退出，同步不写盘

#### Scenario: legacy 行不阻塞

- **WHEN** CSV 中 status=legacy 的参照行存在 lint 违例
- **THEN** lint 以 WARN 报告该行但不计入 FAIL，不阻塞同步

### Requirement: Canon 叙事元数据列

内容设计表 SHALL 以固定列承载每条内容的叙事身份（canon）：`canon_origin`（叙事出处，取值 MUST 可在 `world-bible.md` 的州域/秘境/势力章节查证，或标注"散修日常/上古遗宝"等 bible 认可的通用出处类）、`tone_tier`（文风档，取值 MUST 为 bible §1.3/§3.2 定义的档位：正经 / 正经+冷幽默 / 玩梗灰 / 平淡）、`story_hook`（一句话叙事钩子，不计入描述长度上限）、`narrative_status`（取值 MUST 为 `占位` / `待写` / `定稿` 之一）。lint MUST 校验四列的存在与取值域合法性，非法取值即 FAIL。数值状态列 `status` 与叙事状态列 `narrative_status` MUST 独立维护：数值定稿（draft/final）不代表叙事定稿。

#### Scenario: 文风档非法取值拒绝

- **WHEN** 某行 `tone_tier` 填了"幽默风"（非 bible 定义档位）
- **THEN** lint 报告非法取值并 FAIL，同步中止

#### Scenario: 出处不可查证拒绝

- **WHEN** 某行 `canon_origin` 填了"云州·落星湖"而 bible 地理章无"落星湖"
- **THEN** lint 以 FAIL 报告"出处未在 bible 登记"，提示要么先在 bible 补设定、要么改用已登记出处

#### Scenario: 占位状态可入库但标记

- **WHEN** 某行数值 status=draft 且 narrative_status=占位
- **THEN** lint 对该行描述按"占位文案"规则放宽检查（允许平实功能描述），但仍 MUST 检查禁用词与名字一致性，并以 WARN 提示该行叙事待写

### Requirement: 数值字段零值保留

同步脚本对数值字段的默认值处理 SHALL 保留设计值 0（含 0.0 与 0），MUST NOT 用默认值替换合法零值。心法 `exp_multiplier` 为 0 时 SHALL 写入 0（表示无修炼加成），MUST NOT 被默认 1.0 覆盖。已有 config 中因历史默认值错误被写入 1.0 的条目，在本变更中 SHALL 按设计表修正为 0。

#### Scenario: 无修炼加成心法保留 0

- **WHEN** 心法设计行 `exp_multiplier = 0.0`（设计=无修炼加成）且该行同步入库
- **THEN** config 条目 `exp_multiplier` 写入 0，玩家修炼不获得该心法的修为倍率加成

#### Scenario: 存量错误值修正

- **WHEN** config 中某心法 `exp_multiplier = 1.0` 而设计表为 `0.0`
- **THEN** 修正后 config 写入 0，该心法不再提供意外 +100% 修为加成

### Requirement: 技能表同步

同步脚本 SHALL 支持 skills.csv → config/skills.json 的合并同步，语义与武器/心法一致：仅处理 draft/final 行，按 `name` 键合并，不触碰 CSV 之外的既有条目。技能条目 SHALL 经引擎契约校验：触发技四键齐全且值域合法（复用武器挂载技校验）；大招数据 MUST NOT 含 `trigger_rate`；`trigger_condition` 设计列 SHALL 原样持久化（config 条目持久化键为 `trigger_condition`，引擎归一化层在加载时注入契约键 `trigger_timing`，见 skill-system）。**同名覆盖时 SHALL 保留既有 config 条目的 `id`**（`player_skills` 已学记录按 skill_id 关联，id 变更会断裂已学状态）；CSV 的 `id` 仅在新增条目时生效。CSV 中与既有条目同名但 id 不同的行（如「万剑归宗（重做）」对应既有 `spirit_001/万剑归宗`）SHALL 在写入前将 CSV 行名修正为既有名（本变更直接修正设计表）。同名条目在 CSV 中删除触发技/大招声明（触发列留空）时，脚本 SHALL 将既有条目的 `trigger_skill`/`ultimate` 置空，不得残留旧块；`pool` 列变更时 SHALL 将条目迁移至新分组。

#### Scenario: 同名技能覆盖保留 id

- **WHEN** 设计表新增/重做技能行与 config 既有技能同名（如万剑归宗）且 CSV id 不同
- **THEN** 同步后 config 中该技能 id 保持既有值（spirit_001），仅数值字段按 CSV 更新；玩家已学记录不因 id 变化而断裂

#### Scenario: 技能列映射

- **WHEN** 技能行 `trigger_condition` 值为 `attack`
- **THEN** 入库后的 config 条目持久化 `trigger_condition: "attack"`，引擎归一化层加载时注入 `trigger_timing: "on_attack"`，其余契约键原样保留

### Requirement: 技能数值 0.x 加性契约

经技能同步入库的 config/skills.json 条目 SHALL 遵循 0.x 加性语义：`effect_value = x` 表示该效果把当次效果基数提升为 `×(1 + x)`（与战斗引擎 `ultimate_mult += effect_value` 等消费方式一致）。技能同步以设计表（CSV）为数值唯一来源，覆盖 config 中同名的旧大数值（数学形式同为 ×(1+value)，数值变更即强度变更，作为玩法变更处理）。同步脚本 SHALL 拒绝 0.x 域外的效果数值（效果类 `effect_value` MUST ∈ [0, 3] 且非伤害类效果 ≤ 1，由预算闸门保证，见 validate_budget）。

#### Scenario: 旧数值被设计值覆盖

- **WHEN** config 中【基础吐纳】`effect_value = 1.2`（旧值=×2.2）而设计表为 `0.2`（=×1.2）
- **THEN** 同步后 config 写入 0.2，战斗结算按 ×1.2 执行；玩家已学技能的强度变化在变更说明中标注为玩法变更

