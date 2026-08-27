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

#### Scenario: 出处不可查证拒绝

- **WHEN** 某行 `canon_origin` 填了"云州·落星湖"而 bible 地理章无"落星湖"
- **THEN** lint 以 FAIL 报告"出处未在 bible 登记"，提示要么先在 bible 补设定、要么改用已登记出处

#### Scenario: 占位状态可入库但标记

- **WHEN** 某行数值 status=draft 且 narrative_status=占位
- **THEN** lint 对该行描述按"占位文案"规则放宽检查（允许平实功能描述），但仍 MUST 检查禁用词与名字一致性，并以 WARN 提示该行叙事待写

## MODIFIED Requirements

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
