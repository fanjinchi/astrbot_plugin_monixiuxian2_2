## ADDED Requirements

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

#### Scenario: 出处不可查证警告

- **WHEN** 某行 `canon_origin` 填了"云州·落星湖"而 bible 地理章无"落星湖"
- **THEN** lint 以 FAIL 报告"出处未在 bible 登记"，提示要么先在 bible 补设定、要么改用已登记出处

#### Scenario: 占位状态可入库但标记

- **WHEN** 某行数值 status=draft 且 narrative_status=占位
- **THEN** lint 对该行描述按"占位文案"规则放宽检查（允许平实功能描述），但仍 MUST 检查禁用词与名字一致性，并以 WARN 提示该行叙事待写
