# Design — hygiene-cleanup-batch

三项任务相互独立（10c 纯删除、10g data 层命名/副作用、10e config 层方法合并），无共享改动面，可分开 review、分开回滚，合批仅为流程效率。以下分节给出各自 Context/Decision/Risk。

## 10c · 删除 utils/image_generator.py

**Context**：`ImageGenerator`（:22-189）生成玩家信息卡片图片，硬编码坐标布局（:125 `sect_y_header = 1442  # 原版硬编码`）。全仓 grep（`ImageGenerator|image_generator|info_card|IMG_PATH`）仅命中定义文件本身——零生产调用、零测试覆盖、零文档引用（exploration 报告中的「AGENTS.md 列其为活跃组件」经复核为误报：仓库实际 AGENTS.md 无该字样）。渲染现状由 AstrBot 内建 `text_to_image`/`html_render`（AGENTS.md §12）承担。Pillow 使用 grep 全仓仅 `image_generator.py` 命中 → `requirements.txt` 唯一条目可一并摘除。

**Decision · 直接删除，不标记 deprecated。** 零调用者意味着 deprecation 周期无受众；git 历史保留完整实现，未来若恢复信息卡片功能可直接 revert 取回（届时应按 AGENTS.md §12 优先评估 `html_render` 模板路线，PIL 硬编码坐标方案的 189 行大概率不值得复活）。

**Risk**：摘除 Pillow 后宿主环境若依赖插件加载器自动安装 Pillow 的**其他**旁路（无证据）会缺失——实施前再跑一次全仓 PIL grep + 检查 AstrBot 本体 requirements 是否独立声明 Pillow（其为本体依赖则零影响）。

## 10g · migrate() → migrate_or_reset() + 重置前备份

**Context**：`MigrationManager.migrate()`（`data/migration.py:537`）三条路径：全新安装（建表）、增量任务链（v32+ 且 pending 非空）、**重建**（版本低于任务链下限或无 pending 任务且 version < LATEST：:605-628 `PRAGMA foreign_keys = OFF` → `_drop_all_tables` → `_create_all_tables` → 数据全清）。注册表接缝（`MIGRATION_TASKS` + `@migration`）只挂了一个任务（v34），增量路径几乎不触发，第三路径才是绝大多数旧库的真实命运——但入口名 `migrate()` 不传达这一点。调用点：生产仅 `main.py:455`；测试 9 处。

**Decisions**：
- **D1 · 改名 `migrate_or_reset()`，不留兼容别名。** 调用点共 10 处全部在仓内（生产 1 + 测试 9），一次性机械改名成本低于永久维护别名的语义模糊。docstring 首句即写明「三条路径之一会重置数据，重置前自动备份」。
- **D2 · 备份实现选 `VACUUM INTO`，不拷文件。** 进入 `migrate()` 时连接已 OPEN（`main.py` 先 `db.connect()` 后 migrate），直接 `shutil.copy(db_path)` 会复制到不一致快照（WAL/未落页）；SQLite 3.27+ `VACUUM INTO '<path>'` 从活连接产出一致备份。备份路径 `<db_path>.v<current_version>.pre-reset.bak`（version 取自重置前的 current_version）；失败策略：备份失败**不阻断**重置（否则旧库永远无法启动），但 ERROR 日志明示「未备份即重置」（现状本就无备份，不劣化）。备份仅第三路径执行；新建/增量路径零开销。
- **D3 · 备份目录不轮转。** 每次重置覆盖同名 `.bak`（旧库重置是低频一次性事件；多次重置间插件版本已变，旧备份价值衰减）。登记 bd 跟进项：若未来出现「连续跨版本重置」场景再评估保留多份。

**Risk**：`VACUUM INTO` 要求 SQLite ≥3.27（Python 3.12 自带 sqlite3 远高于此，aiosqlite 透传，无环境风险）；备份写失败（磁盘满）→ 按 D2 降级为 ERROR 日志后继续，语义不劣于现状；测试 fake 连接（`MagicMock` conn，如 `test_gm_manager.py:897`）需让备份钩子在 conn 为 mock 时可跳过或 mock 掉——实施时以 `try/except` 包裹整段备份并以 `logger.warning` 降级，测试零改动。

## 10e · 丹药查找合并为 ConfigManager.get_pill_config

**Context**：两份实现见 proposal。关键事实（实测）：`pills.json`/`exp_pills.json`/`utility_pills.json` 三表名域**互不相交**；`items.json` 中 `type=丹药` 且与三表交叠者唯一「血煞丹」。因此任意「三表优先于 items」的合并顺序对全部现存药名与两旧实现解析结果逐位等价；两旧实现间的顺序差异（alchemy 把 exp/utility 置于 pills 前）在不相交名域下也是无差别。`hasattr` 守卫（alchemy :98-116）为测试 fake config_manager 而生——合并后 fake 只需提供 `get_pill_config`（测试 fixture 一并收敛）。

**Decisions**：
- **D1 · 落点 `ConfigManager.get_pill_config`，顺序 pills→exp_pills→utility_pills→items 兜底。** 紧邻既有 `is_pill`(:485)/`get_all_pill_names`(:500)——丹药判定与丹药取值的权威已在 ConfigManager，查找并入同一 locality；pill_manager/alchemy_manager 退化为消费方。顺序取 pill_manager 版（三表首）+ alchemy 版独有的 items 兜底，两版行为的并集。
- **D2 · `get_pill_by_name` 删除不留包装。** 仓内调用面仅 4 处（pill_manager 内部 2、pill_handler 1、alchemy 经自身方法 1），均随合并改调 `config_manager.get_pill_config`；删除测试防新增调用点。`_get_pill_config_by_name` 同样整方法删除。
- **D3 · `hasattr` 守卫随委托消失。** 测试 fake（`FakeConfigManager` 等）在各自测试文件中补 `get_pill_config` 方法（多数 fake 已聚合 pills/exp/utility 三表字典，补一个 5 行方法）；这反而是收益——fake 与生产接口的偏差被强制对齐。

**Risk**：「逐位等价」依赖三表不相交这一**数据事实**而非结构保证——tasks 中要求 `get_pill_config` 单测断言三表互不相交（加载时 warning 或测试断言），未来内容管线（`sync_content_to_config.py`）灌入重名条目时能被立即发现而非静默改变解析。

## Migration Plan

无部署/迁移步骤。10c 摘 Pillow 由 AstrBot 插件加载器在下次重载生效（仅不再安装，不卸载已装包）；10g/10e 随插件重载生效。回滚 = revert 单个 commit（三项建议分三个 commit 合批提交）。

## Open Questions

无（三项设计点——删除/不删、改名/别名、备份实现、合并落点/顺序/旧方法处置——均按 settled direction 结合代码事实收敛；唯一 exploration 修正：10c 无需文档改动）。
