# hygiene-cleanup-batch

## Why

三个相互独立、各自高确定性的架构卫生项，合批以降低流程开销：

- **10c 死代码**：`utils/image_generator.py`（189 行）的 `ImageGenerator` 全仓零调用（grep 仅命中定义文件本身），且其唯一外部依赖 Pillow 亦仅被它使用（`requirements.txt` 唯一条目）。架构评审 exploration 曾声称「AGENTS.md §架构速览将其列为活跃组件」——**复核不成立**：实际 AGENTS.md、README、design_docs 均无 image_generator 字样，故无需文档修正，纯删文件 + 摘依赖。
- **10g 迁移入口命名**：`data/migration.py` 的 `MigrationManager.migrate()`（:537-638）对外呈现为常规增量升级入口（MIGRATION_TASKS 注册表 + `@migration` 装饰器，:25-53），但其第三路径对版本低于 `TASK_CHAIN_MIN_VERSION`（32）的数据库执行 `_drop_all_tables()` + 重建（:605-628，日志「旧数据将被清空」）——**全部玩家数据被静默清空**，且无任何备份。 destructive 分支藏在 routine-looking 接口后，是命名与接缝问题；修复使其不可误读（改名 + 重置前备份），不改变任何迁移策略。
- **10e 丹药查找双实现**：丹药配置查找存在两份 drift 的实现——`managers/alchemy_manager.py:95-119` `_get_pill_config_by_name`（顺序 exp_pills→utility_pills→pills→items，带 `hasattr` 守卫）与 `core/pill_manager.py:35-58` `get_pill_by_name`（顺序 pills→exp_pills→utility_pills，**无** items 兜底）。调用面：alchemy 自调用 :51；pill_manager 内部 :105、:688；`handlers/pill_handler.py:140`。两表顺序不同 + 兜底有无不同 = 同一药名在两处可能解析到不同配置字典（实测唯一交叠名「血煞丹」两实现同表命中，行为暂未分岔，但结构随时会）。`hasattr` 守卫是测试 fake 的妥协泄漏进生产代码。

## What Changes

- **10c**：删除 `utils/image_generator.py`（含 `__pycache__` 编译产物）；`requirements.txt` 删除 `Pillow>=9.0.0`（实施前再跑一次全仓 PIL 使用 grep 确认）；AGENTS.md 无任何 image_generator 表述（已复核），无需文档改动。
- **10g**：`MigrationManager.migrate()` 改名为 `migrate_or_reset()`，docstring 明示三条路径中第三路径重置数据；重置分支（`_drop_all_tables` 之前）新增备份钩子：将 db 文件复制为 `<db_path>.v<current_version>.pre-reset.bak`（连接已 OPEN 时复制文件需先 `VACUUM INTO` 或于连接打开前拷贝——见 design D2）；调用点同步改名：`main.py:455` 与 9 个测试文件（`test_sect_manager.py:81`、`test_gm_manager.py:897`、`test_impart_manager.py:145`、`test_sect_handlers.py:106`、`test_sect_content_link.py:102`、`test_sect_growth.py:188`、`test_sect_master.py:145`、`test_transaction_atomicity.py:80`、及 `tests/` 下其他 `.migrate()` 调用——实施时 grep 全量）。
- **10e**：`ConfigManager` 新增唯一权威方法 `get_pill_config(name) -> dict | None`（落点紧邻既有 `is_pill` :485 / `get_all_pill_names` :500，三份 pill 表名域实测互不相交，唯一 items 交叠「血煞丹」在任何 pill→items 顺序下均解析到 pill 表条目——故权威顺序定为 pills→exp_pills→utility_pills→items 兜底，对全部现存药名与两旧实现**逐位等价**）；`alchemy_manager._get_pill_config_by_name` 与 `pill_manager.get_pill_by_name` 均改为单行委托并删除（`get_pill_by_name` 同步删除或保留为带 DeprecationWarning 的薄包装由 design D3 定）；`hasattr` 守卫随委托消失。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 三项均为非行为变更：10c 删零调用代码；10g 改名 + 新增备份副作用（重置路径数据可恢复性提升，非需求级行为）；10e 为纯合并重构，现存全部药名解析结果逐位等价，无需求契约描述丹药查找顺序。故 `.openspec.yaml` 设 `skip_specs: true`。）

## Impact

- **代码**：`utils/image_generator.py`（-189 行，删除）、`requirements.txt`（-1 行）、`data/migration.py`（改名 + 备份钩子约 +20 行）、`config_manager.py`（+`get_pill_config` 约 15 行）、`managers/alchemy_manager.py`（-25 行）、`core/pill_manager.py`（方法体收缩）、`main.py:455` + 测试文件若干（机械改名）。
- **依赖**：Pillow 从插件依赖移除（AstrBot 插件加载器不再自动安装；宿主若另有 Pillow 使用者不受影响）。
- **测试**：10e 补 `get_pill_config` 单测（三表 + items 兜底 + 未命中 None）；10g 补备份钩子测试（重置路径产生 `.bak` 文件、内容含重置前数据）；既有 `.migrate()` 调用点机械改名后全量回归。
- **无**数据库 schema 变更、无玩法数值变化、无 config 变更。
