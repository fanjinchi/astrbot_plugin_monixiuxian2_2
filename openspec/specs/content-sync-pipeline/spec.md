# content-sync-pipeline Specification

## Purpose

设计表（design_docs/content-design/*.csv）到运行时配置（config/*.json）的同步管道：让设计内容可入库、可校验、可测试，并防止契约断裂与预算超标内容进入线上配置。

## Requirements

### Requirement: 设计表合并同步

系统 SHALL 提供设计 CSV → config JSON 的同步脚本，按 `name` 键合并：config 中已存在同名条目时 SHALL 更新其字段，不存在时 SHALL 新增；脚本 MUST NOT 修改或删除 CSV 中不存在的既有 config 条目。脚本 SHALL 仅处理 status 为 draft/final 的设计行，legacy 参照行 MUST 跳过。

#### Scenario: 同名条目更新

- **WHEN** CSV 中 status=draft 的行与 config 既有条目同名
- **THEN** 该条目的字段被 CSV 值更新，config 其余条目保持不变

#### Scenario: 新条目新增

- **WHEN** CSV 行的 name 不存在于 config
- **THEN** 脚本在 config 中追加该条目

#### Scenario: legacy 行跳过

- **WHEN** CSV 行的 status=legacy
- **THEN** 该行不参与同步，config 中对应旧条目保持原样

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
