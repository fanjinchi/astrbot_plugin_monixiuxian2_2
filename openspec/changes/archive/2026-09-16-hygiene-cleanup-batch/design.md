# Design — hygiene-cleanup-batch

三项任务相互独立（10c 纯删除、10g data 层命名/副作用、10e config 层方法合并），无共享改动面，可分开 review、分开回滚，合批仅为流程效率。以下分节给出各自 Context/Decision/Risk。

## 10c · 删除 utils/image_generator.py

**Context**：`ImageGenerator`（:22-189）生成玩家信息卡片图片，硬编码坐标布局（:125 `sect_y_header = 1442  # 原版硬编码`）。全仓 grep（`ImageGenerator|image_generator|info_card|IMG_PATH`）仅命中定义文件本身——零生产调用、零测试覆盖、零文档引用（exploration 报告中的「AGENTS.md 列其为活跃组件」经复核为误报：仓库实际 AGENTS.md 无该字样）。渲染现状由 AstrBot 内建 `text_to_image`/`html_render`（AGENTS.md §12）承担。Pillow 使用 grep 全仓仅 `image_generator.py` 命中 → `requirements.txt` 唯一条目可一并摘除。

**Decision · 直接删除，不标记 deprecated。** 零调用者意味着 deprecation 周期无受众；git 历史保留完整实现，未来若恢复信息卡片功能可直接 revert 取回（届时应按 AGENTS.md §12 优先评估 `html_render` 模板路线，PIL 硬编码坐标方案的 189 行大概率不值得复活）。

**Risk**：摘除 Pillow 后宿主环境若依赖插件加载器自动安装 Pillow 的**其他**旁路（无证据）会缺失——实施前再跑一次全仓 PIL grep + 检查 AstrBot 本体 requirements 是否独立声明 Pillow（其为本体依赖则零影响）。

## 10g · migrate() → migrate_or_reset() + 重置前备份

**Context**：`MigrationManager.migrate()`（`data/migration.py:537`）三条路径：全新安装（建表）、增量任务链（v32+ 且 pending 非空）、**重建**（版本低于任务链下限或无 pending 任务且 version < LATEST：:605-628 `PRAGMA foreign_keys = OFF` → `_drop_all_tables` → `_create_all_tables` → 数据全清）。注册表接缝（`MIGRATION_TASKS` + `@migration`）只挂了一个任务（v34），增量路径几乎不触发，第三路径才是绝大多数旧库的真实命运——但入口名 `migrate()` 不传达这一点。调用点：生产仅 `main.py:455`；测试 9 处。

**Decisions**：
- **D1 · 改名 `migrate_or_reset()`，不留兼容别名。** 调用点全部在仓内：生产 1 处（`main.py:455`）+ 测试 25 处 `.migrate()` 调用（`test_migration.py` 独占 17 处）+ 1 处按名 mock（`test_feature_switches.py:259` 的 `MagicMock(migrate=AsyncMock())`——grep `\.migrate\(` 抓不到，须显式同步）。一次性机械改名成本低于永久维护别名的语义模糊。docstring 首句即写明「三条路径之一会重置数据，重置前自动备份」。
- **D2 · 备份实现选 `VACUUM INTO`，不拷文件。** 进入 `migrate()` 时连接已 OPEN（`main.py` 先 `db.connect()` 后 migrate），直接 `shutil.copy(db_path)` 会复制到不一致快照（WAL/未落页）；SQLite 3.27+ `VACUUM INTO '<path>'` 从活连接产出一致备份。备份路径 `<db_path>.v<current_version>.pre-reset.bak`（version 取自重置前的 current_version）。**db_path 获取**：`MigrationManager` 构造只收 conn、不持路径——实施时经 `PRAGMA database_list` 取主库文件路径；**空路径（`:memory:` 连接）必须跳过备份并 warning**（实测 `VACUUM INTO` 对 `:memory:` 连接会成功执行，naive 路径拼接会在 pytest CWD 写出流浪 `.bak`——既有 `:memory:` 重置路径测试 `test_migration.py:245` 即中此场景）。**插入位置**：`PRAGMA foreign_keys = OFF`（:614）之后、`BEGIN`（:615）**之前**——VACUUM 禁止在事务内执行，放错位置会每次静默降级为「无备份」。失败策略：备份失败**不阻断**重置（否则旧库永远无法启动），但 ERROR 日志明示「未备份即重置」（现状本就无备份，不劣化）。备份仅第三路径执行；新建/增量路径零开销。
- **D3 · 备份目录不轮转。** 每次重置覆盖同名 `.bak`（旧库重置是低频一次性事件；多次重置间插件版本已变，旧备份价值衰减）。登记 bd 跟进项：若未来出现「连续跨版本重置」场景再评估保留多份。

**Risk**：`VACUUM INTO` 要求 SQLite ≥3.27（Python 3.12 自带 sqlite3 远高于此，aiosqlite 透传，无环境风险）；备份写失败（磁盘满）→ 按 D2 降级为 ERROR 日志后继续，语义不劣于现状。经复核，`test_gm_manager.py:897` 的 conn 是**真实 `:memory:` 连接**（仅 config_manager 是 MagicMock），且走全新安装路径不触备份钩子——「mock conn 崩备份」仅为理论风险，真实风险点是 `test_feature_switches.py:259` 的按名 mock（D1）与 `:memory:` 空路径（D2）。备份整段以 `try/except` 包裹降级，现有测试零改动预期。

## 10e · 丹药查找合并为 ConfigManager.get_pill_config

**Context**：两份实现见 proposal。关键事实（实测）：`pills.json`/`exp_pills.json`/`utility_pills.json` 三表名域**互不相交**（26/30/143 raw 条目，两两交集为空；**三轮补审修正**：utility_pills 去重后实为 142 名——「混元血容丹」表内重名一组，两个不同 tier 共名，dict 去重遮蔽其一（util_128 皇品被遮），见 bd `-czl`；去重后名域仍两两不相交）；`items.json` 中 `type=丹药` 的 33 个条目与三表名域的交叠仅 1 个：**「血煞丹」同时在 utility_pills 与 items 登记**（其余 32 个为 items 独有；**三轮补审修正**：初稿称「血煞丹实测在 utility_pills 表而非 items.json」失实——两表都有）。items 兜底对三表药名不触发、对 items 独有丹药名触发（补足旧 pill_manager 路径对这些名字返回未找到的缺陷，行为与旧 alchemy 一致）；血煞丹在两旧实现与新实现中均经 util 表解析，items 重复登记从不触发，无解析分叉。因此任意「三表优先于 items」的合并顺序对全部现存药名与两旧实现**逐位等价**（唯一放宽：pill_manager 旧路径对 32 个 items 独有丹药名返回未找到 → 新实现可解析，属修复方向）；两旧实现间的顺序差异（alchemy 把 exp/utility 置于 pills 前）在不相交名域下也是无差别。`hasattr` 守卫（alchemy :98-116）为测试 fake config_manager 而生——合并后 fake 只需提供 `get_pill_config`（测试 fixture 一并收敛）。

**Decisions**：
- **D1 · 落点 `ConfigManager.get_pill_config`，顺序 pills→exp_pills→utility_pills→items 兜底。** 紧邻既有 `is_pill`(:485)/`get_all_pill_names`(:500)——丹药判定与丹药取值的权威已在 ConfigManager，查找并入同一 locality；pill_manager/alchemy_manager 退化为消费方。顺序取 pill_manager 版（三表首）+ alchemy 版独有的 items 兜底，两版行为的并集。
- **D2 · `get_pill_by_name` 删除不留包装。** 仓内调用面仅 4 处（pill_manager 内部 2、pill_handler 1、alchemy 经自身方法 1），均随合并改调 `config_manager.get_pill_config`；删除测试防新增调用点。`_get_pill_config_by_name` 同样整方法删除。**显式排除（out of scope）**：`handlers/breakthrough_handler.py:177` 与 `core/breakthrough_manager.py:154` 的 `config_manager.pills_data.get(pill_name)` 是**故意的只查破境丹表**——破境丹语义要求未知药名报「未找到破境丹」，若并入带 exp/utility/items 兜底的 `get_pill_config`，传入修为丹/功能丹名将意外解析成功，行为回退。这两处保持原样，不随合并改动。
- **D3 · `hasattr` 守卫随委托消失。** 测试 fake 补 `get_pill_config` 方法——**实测收敛面很窄**：需补的只有 `tests/test_transaction_atomicity.py:58` 的 FakeConfigManager（`test_pill_manager.py` 用真实 ConfigManager；其余 fake 仅服务 MigrationManager 构造、不碰 pill 数据）；这反而是收益——fake 与生产接口的偏差被强制对齐。

**Risk**：「逐位等价」依赖三表不相交、items 与三表零交叠这两**数据事实**而非结构保证——tasks 中要求 `get_pill_config` 单测断言三表两两不相交、items 丹药条目与三表零交叠、**且每表 raw 条目数==去重名字数（表内无重名）**——只断前两条查不出表内重名（交集仍空、dict 静默覆盖），第三条才是防内容管线灌入重名的闸门（加载时 warning 或测试断言；已知 utility_pills 重名挂 bd `-czl`，闸门先于内容修复转红是预期行为），未来内容管线（`sync_content_to_config.py`）灌入重名条目时能被立即发现而非静默改变解析。

**追加批次修订注记（2026-09-16，commit d7c4167）**：10e 决策随追加批次修订——`get_pill_config` 由四来源（pills→exp_pills→utility_pills→items `type=="丹药"` 兜底）改为三来源（pills→exp_pills→utility_pills→None），「丹药 = 三表名域」由数据事实升格为**结构保证**：`items.json` 已删除全部 33 个 `type=丹药` 条目（32 个 items-only + 血煞丹 items 侧重复登记），旧九品体系退役说明见 `design_docs/content-design/pills-legacy-retirement.md`（tasks 5.4 登记）。原 D1/D2 四来源叙述保留为历史决策，不做改动；对应 tasks 第 5 节（5.1–5.6）全部完成。

## 文档同步（随实施一并落地）

- **10g 改名波及三处按名引用**：`design_docs/api-overview.md:29` 与 `:117` 的 `MigrationManager.migrate()` 同步改名（AGENTS.md 文档地图要求公开方法重命名必须更新 api-overview）；`openspec/specs/impart-system/spec.md:187-190` 场景 WHEN 的 `migrate()` 标识符做 **prose-only 同步**（行为不变、THEN 不动，`.openspec.yaml` 维持 `skip_specs: true`）。
- **10c 摘 Pillow 后五处依赖声明修正**（「仅 Pillow」表述全部失效）：`AGENTS.md:12`、`AGENTS.md:37`、`design_docs/current-design-report.md:21`、`design_docs/project-architecture.md:15`、`README.md:261`（安装步骤的 `pip install Pillow`）。

## Migration Plan

无部署/迁移步骤。10c 摘 Pillow 由 AstrBot 插件加载器在下次重载生效（仅不再安装，不卸载已装包）；10g/10e 随插件重载生效。回滚 = revert 单个 commit（三项建议分三个 commit 合批提交）。

## Open Questions

无（三项设计点——删除/不删、改名/别名、备份实现、合并落点/顺序/旧方法处置——均按 settled direction 结合代码事实收敛；唯一 exploration 修正：10c 无需文档改动）。
