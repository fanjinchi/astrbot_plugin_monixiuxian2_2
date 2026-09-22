# Tasks — gm-time-skip-registry

## 0. 前置检查

- [ ] 0.1 核实在飞变更状态并重新锚定行号：`add-transaction-unit-of-work`（其 tasks 3.3 改 `core/gm_manager.py:1199` 时间快进块为事务 CM——**建议其先合入**，本 change 直接落在 CM 形态上）、`busy-state-owner`（触碰 `:908-910`/`:1246-1252` 清除路径，与本 change 区域不相交）；确认 `_TIME_SKIP_RULES`（:68-122）、`cmd_help`（:381-437）、`cmd_time_skip`（:1170-1213）行号仍有效
- [ ] 0.2 grep 基线：`_TIME_SKIP_RULES` 全部引用（运行时代码/文档/脚本）与本 tasks 清单一致——已知三处文档：`AGENTS.md:77`、`design_docs/api-overview.md:107`、`scripts/test_suite_ctl.py:1255`（注释）

## 1. 注册表与迁移（core + 属主模块）

- [ ] 1.1 新增 `core/time_skip_registry.py`：`TimeSkipRegistry`（不可变元组包装，`from_providers(provider_modules)` 按模块顺序汇总各模块的 `TIME_SKIP_ENTRIES` 常量，`entries() -> tuple[tuple[str, str], ...]`）；英文 Google 风格 docstring 写明「声明即覆盖」不变量与 SQL 参数约定（`?` 以前移秒数按个数填充）
- [ ] 1.2 迁移 10 条 SQL（**文本原样**，顺序保持现状，**保持 10 条不变**——Boss/灵眼是单条双键 UPDATE，属主必须唯一）：`user_cd.scheduled_time` 与 `players.cultivation_start_time` 两条属主落 `core/cultivation_manager.py` 旁的新常量区（**不得落 `handlers/player_handler.py`**——registry → handlers → gm_handler → core.gm_manager 的 import 链会在 core 包半初始化时炸 ImportError，review Finding B）；`combat_cooldowns` → combat 域模块；`dual_cultivation` → `managers/dual_cultivation_manager.py`；`bounty_tasks` + `system_config bounty_abandon_cd_%` → `managers/bounty_manager.py`；`bank_loans` → `managers/bank_manager.py`；**`boss/spirit_eye 刷新键`（单条双键 UPDATE）→ 单一属主**（建议 `managers/boss_manager.py` 声明该组合条目，或新建 `system_config` 域 provider 常量区——不得拆成两条，否则回复行数 10→11 破坏任务 2.1"回复格式逐字不变"、任务 3.1"10 条逐项相等"与 spec 的逐域计数语义，review Finding A）；`impart_pk_cooldown`/`impart_snatch_protection` → impart 域（`managers/impart_pk_manager.py` 或新常量区）；每条注释保留原「只动到期判定时间戳」原则
- [ ] 1.3 删 `core/gm_manager.py` 的 `_TIME_SKIP_RULES`（:62-122 含注释）与 `:1200` 的循环数据源引用；`GMManager.__init__` 构造注册表（`from_providers([...])`，provider 列表集中声明于 `time_skip_registry.py` 顶部并注释「新增冷却域 = 属主模块加常量 + 此处登记模块」）

## 2. 消费方改造（语义逐行保持）

- [ ] 2.1 `cmd_time_skip`（:1170-1213）：循环改 `for label, sql in self._time_skip.entries():`；事务边界（现为 :1199 的 `db.transaction()` CM——`add-transaction-unit-of-work` 已收编原手写 `BEGIN IMMEDIATE`/commit/rollback，全有或全无语义不变）、`params = (seconds,) * sql.count("?")`、逐域 `rowcount`、回复格式（「✅ 时间已快进 N 秒（共前移 M 条记录）」+ 域计数明细 + 警示尾句）**逐字不变**
- [ ] 2.2 `cmd_help`（:381-437）：时间快进条目（:428-429）保持既有警示文案逐字不变，追加生成段「覆盖域：<标签 joined>」（来源注册表 `entries()`）；docstring 注明生成段与代码持有段的边界
- [ ] 2.3 收尾 grep：运行时代码 `_TIME_SKIP_RULES` 零命中；`time_skip_registry` 注册表为唯一覆盖清单来源

## 3. 测试

- [ ] 3.1 注册表装配测试：provider 汇总顺序 = 现状 10 条原序；每条 `(label, sql)` 与迁移前 `_TIME_SKIP_RULES` 逐项相等（把现状清单作为测试 fixture 数据内联，防迁移走样）
- [ ] 3.2 契约钉住测试：注册表覆盖 `openspec/specs/gm-commands`「GM 时间快进」需求枚举的最小域清单（按 SQL 的 table.column 特征断言 10 域各在，漏域即 fail fast——替代 AGENTS.md §2 的人工义务）
- [ ] 3.3 `cmd_time_skip` 行为测试：逐域计数与回复格式快照（与改造前一致）；`cmd_help` 含时间快进用法行 + 全部域标签；无确认/非法秒数分支不变
- [ ] 3.4 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过

## 4. Spec delta 与文档

- [ ] 4.1 本 change 的 `specs/gm-commands/spec.md` delta（## MODIFIED Requirements ·「GM 时间快进」）：机制句「明确枚举」改为「字段属主声明 `TIME_SKIP_ENTRIES`、注册表装配覆盖」；枚举清单保留并改写为「注册表 MUST 至少覆盖以下清单」（保证语义）；新增场景「新冷却域自动覆盖」；实施核对 `openspec validate` 与主 spec 的 apply 语义
- [ ] 4.2 `AGENTS.md:77` 改写：人工义务（「必须同步补充 _TIME_SKIP_RULES 与 GM 帮助文本」）改为「在字段属主模块声明 `TIME_SKIP_ENTRIES` 常量并登记 provider——登记即自动被时间快进覆盖与帮助列出；注册表最小清单测试会钉住漏登记」
- [ ] 4.3 `design_docs/api-overview.md:107`「按 `_TIME_SKIP_RULES` 枚举」改指注册表（`core/time_skip_registry.py`）；`scripts/test_suite_ctl.py:1255` 注释核对（名称改注册表或泛化，语义保持）

## 5. 验证与收尾

- [ ] 5.1 functional_tests：含时间快进的用例（GM 域/需要快进的冷却类用例）重跑，回复域计数与帮助文本锚点全过
- [ ] 5.2 按 AGENTS.md §7 版本 checklist 评估（纯工程重构无玩法变化，通常无需升版本号）
- [ ] 5.3 `openspec validate --changes gm-time-skip-registry` 通过；本地 conventional commit（不 push）
