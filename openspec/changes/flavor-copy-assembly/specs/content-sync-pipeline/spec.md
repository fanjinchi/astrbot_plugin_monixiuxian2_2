## MODIFIED Requirements

### Requirement: 叙事文案 lint 闸门

同步管道 SHALL 提供叙事文案 lint 脚本（`design_docs/content-design/lint_narrative.py`），对设计 CSV 的 `description` 列与对应 `config/*.json` 的描述字段执行检查；存在 FAIL 项时 lint MUST 以非零码退出并逐条输出位置与原因。入库同步（sync）SHALL 在预算验算之外接入 lint 作为第二道闸门：lint FAIL 时脚本 MUST 中止且不写盘。lint 检查项 SHALL 至少覆盖：

- **禁用词**：`world-bible.md` §5.3 禁用词清单中的现代/出戏词与机制承诺词不得出现在文案正文
- **数值承诺**：文案不得含百分数、阿拉伯数字数值表述（如"+30%"、"伤害 15"）等机制承诺
- **长度上限**：单条描述不超过设定上限（默认 60 字，可配置）
- **品级冠词**：品级词（凡/灵/玄/地/天）只作名称冠词，不进描述正文
- **名字一致性**：CSV `name` 列与 config 同 id 条目的 `name` 字段 MUST 一致；不一致即 FAIL 并输出两处名字
- **首尾空白（换行所有权）**：`copy_variants.csv` 的 `text` 单元格 MUST NOT 自带首尾空白或换行——面板/消息的分隔换行归代码或面板模板所有（见 `narrative-text-config` 契约「叙事文案换行所有权」）。校验 MUST 在未脱 `{var}` 槽、未 strip 的**原稿**上进行：脱槽会把 `{name} 起手` 这类正常稿子变成前导空白（误报），先 strip 则永远看不出违规（漏报）

同步导入器（`scripts/sync_copy_variants_to_config.py`）在写入 `text` 前 SHALL 剔除稿子首尾空白；剔除实际发生时 MUST 逐条打印 WARN，指出 `domain.scene#variant_no`、被剔除的边缘字符与契约位置，并 MUST NOT 因该情形中止导入（闸门语义不变）。

#### Scenario: 禁词拒绝入库

- **WHEN** 某 draft 心法描述含"被动技能加成 +10%"字样
- **THEN** lint 输出该行的位置与违例词并以非零码退出；同步脚本中止，config 文件不被修改

#### Scenario: 名字不一致拒绝

- **WHEN** `weapons.csv` 中 `sword_006` 的 name 为"青云天剑"而 config 同名 id 条目 name 为"裂空神剑"
- **THEN** lint 报告两处名字差异并以非零码退出，同步不写盘

#### Scenario: legacy 行不阻塞

- **WHEN** CSV 中 status=legacy 的参照行存在 lint 违例
- **THEN** lint 以 WARN 报告该行但不计入 FAIL，不阻塞同步

#### Scenario: 稿子自带首尾换行被指出

- **WHEN** `copy_variants.csv` 某行 `text` 以 `\n\n` 起头或以空格结尾
- **THEN** lint 以 FAIL（定稿行）/ WARN（draft/占位行）指出该行 `text 首尾带空白/换行` 并说明换行归代码或面板模板；以 `{name}` 开头的正常稿子 MUST NOT 因脱槽而被误报

#### Scenario: 导入时剔除并告警

- **WHEN** 同步脚本导入一条首尾带空白的稿子
- **THEN** 脚本打印 WARN 指出 `domain.scene#variant_no` 与边缘字符，写入 config 的 `text` 为剔除后的正文，导入继续
