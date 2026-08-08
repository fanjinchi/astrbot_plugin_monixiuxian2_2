# content-sync-pipeline Specification

## Purpose

设计表（design_docs/content-design/*.csv）到运行时配置（config/*.json）的同步管道：让设计内容可入库、可校验、可测试，并防止契约断裂与预算超标内容进入线上配置。
## Requirements
### Requirement: 设计表合并同步

（本变更将主 spec 的 merge-only 语义替换为 reconcile 全量重导）系统 SHALL 提供设计 CSV → config JSON 的同步脚本，以设计表为唯一来源进行全量重导：脚本 SHALL 导入 status 为 draft/final 的设计行（按 `name` 键合并：同名更新字段、新名新增），并 SHALL 删除 config 中不在导入范围内的既有条目（legacy 参照行不导入即删除）。legacy 行中的设计有效条目（如新手默认心法长春功）由设计表修正为 draft 后纳入导入。

#### Scenario: 表外条目删除

- **WHEN** config 中存在不在 CSV draft/final 范围内的旧条目（如焚天诀、御剑术、旧武器）
- **THEN** 同步后该条目被删除，config 仅保留 CSV draft/final 行对应条目

#### Scenario: 同名条目更新

- **WHEN** CSV 中 status=draft 的行与 config 既有条目同名
- **THEN** 该条目的字段被 CSV 值更新，config 其余条目保持不变

#### Scenario: 新条目新增

- **WHEN** CSV 行的 name 不存在于 config
- **THEN** 脚本在 config 中追加该条目

#### Scenario: legacy 行跳过

- **WHEN** CSV 行的 status=legacy
- **THEN** 该行不参与同步导入，reconcile 删除阶段中 config 对应旧条目被一并删除（设计有效且需保留的 legacy 条目应由设计表修正为 draft 后纳入导入）

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

