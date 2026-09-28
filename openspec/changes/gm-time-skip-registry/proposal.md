# gm-time-skip-registry

## Why

「时间快进」的字段覆盖清单是 `core/gm_manager.py:68-122` 的手工 `_TIME_SKIP_RULES` 元组（10 条 SQL），AGENTS.md §2（:77）将其固化为**永久性人工义务**：「新增等待类冷却域时必须同步补充本清单与 GM 帮助文本——否则新冷却不被快进覆盖，冷却类功能测试会隐性失败」。义务的履行没有任何机制保证——忘了改清单 = 冷却类测试静默失效（测试平台等待超时才会以难以归因的方式暴露）；GM 帮助文本（`cmd_help` :384-440，时间快进行 :431-432）是另一份手工维护的摘要，与清单的语义已经漂移（帮助从未逐项枚举域清单，清单注释 :62-67 自认「首版不覆盖的已知域见 design D2」）。知识的所有权也在错误的一侧：字段是各玩法 manager 的，清单却长在 gm_manager 里——每新增一个冷却域，gm_manager 这个 1356 行的分发器就要被不相关地编辑一次。

## What Changes

- 新增 `core/time_skip_registry.py` 的 `TimeSkipRegistry`：**声明式注册表**，装配时从「字段属主模块各自声明的 `TIME_SKIP_ENTRIES` 常量」汇总（provider 列表一次声明、只存模块名字符串、惰性 import，逐域常量与字段知识同文件）；删 `_TIME_SKIP_RULES` 元组，11 条 SQL 原样迁移到属主模块（Boss/灵眼单条双键拆为两条、各归写点属主，同 label 按聚合计数——回复行数与计数锚点不变，见 design D2a）。
- `cmd_time_skip`（:1179-1222）消费注册表：循环语义、逐域计数回复、事务全有或全无语义**逐行不变**（`add-transaction-unit-of-work` 已把原手写 `BEGIN IMMEDIATE` 收编为 :1208 的 `db.transaction()` CM，本 change 直接落在 CM 形态上；仍为多 `?` 参数以前移秒数填充）。
- `cmd_help` 时间快进条目**自动列出覆盖域**（域标签从注册表生成）；既有代码持有的警示文案（不可逆/不唤醒睡眠定时任务/贷款逾期警告，:431-432）保持代码所有、逐字不变——帮助文本不再手抄清单。
- 新增不变量测试：注册表覆盖 = `openspec/specs/gm-commands`「GM 时间快进」需求枚举的最小域清单（spec 保留枚举作为保证）；帮助文本含各域标签 + 时间快进用法行。
- AGENTS.md §2（:77）人工义务措辞改写为「在属主模块声明 `TIME_SKIP_ENTRIES` + 登记 provider」——登记后自动被快进覆盖与帮助列出；三层防漏：既有域清单由 registry 最小清单测试 fail fast 钉住、声明了常量但漏登记 provider 由静态扫描测试钉住（全新域未声明仍靠 review）。
- **范围外**：GMManager 28 个 `cmd_*` 方法按域拆分（原架构发现 #6 的另一半）不在本 change，已登记 bd 跟进（`astrbot_plugin_monixiuxian2_2-5vt`）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- **gm-commands ·「GM 时间快进」**：需求正文「将数据库中**明确枚举**的未来到期类时间戳统一前移」描述了人工枚举机制，本 change 将其改为「字段属主声明 + 注册表装配」的声明式覆盖，同时把原枚举清单降级为**保证**（注册表 MUST 覆盖该清单，测试钉住）；玩法可观察行为（覆盖域、逐域计数回复、确认约定、正常路径零影响）逐字不变。delta 见 `specs/gm-commands/spec.md`。
- 「GM 测试命令安全边界」的「帮助文本列出测试命令」场景不受实质影响（帮助仍列出时间快进用法），不修改。

## Impact

- **代码**：新增 `core/time_skip_registry.py`；`core/gm_manager.py`（删 :62-122 清单与 :1209 循环数据源，改消费注册表；`cmd_help` :431-432 追加生成域列表）；~8 个属主模块各增 `TIME_SKIP_ENTRIES` 模块常量（SQL 原样迁移）。
- **Spec**：`openspec/specs/gm-commands/spec.md`「GM 时间快进」需求经本 change 的 delta 更新（`skip_specs` 不设——需求正文内嵌了被替换的机制描述）。
- **文档**：AGENTS.md §2（:77）改写；`design_docs/api-overview.md:107` 的「按 `_TIME_SKIP_RULES` 枚举」表述改指注册表；`scripts/test_suite_ctl.py:1255` 注释提及 `_TIME_SKIP_RULES` 处核对（描述快进幽灵数据语义，改不改名以注释是否失真为准）。
- **软依赖已兑现**：`add-transaction-unit-of-work`（2026-09-19 已归档）的 tasks 3.3 已把 `core/gm_manager.py:1208` 的 `BEGIN IMMEDIATE` 改为事务 CM（同一循环块）——本 change 直接落在 CM 形态上实施即可。
- **同文件并发**：`busy-state-owner` 触碰 gm_manager 的清除路径（`:915-919` / `:1255-1260`），与本 change 区域（:62-122 / :384-440 / :1179-1222）不相交；实施前各自重新锚定行号。
- **无**数据库迁移、无配置变更、无 GM 命令行为变化（覆盖域、回复格式、帮助既有文案逐字保持）。
