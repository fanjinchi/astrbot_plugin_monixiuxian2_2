# Tasks — hygiene-cleanup-batch

## 1. 10c · 删除 utils/image_generator.py

- [ ] 1.1 删除前终检：全仓 grep `ImageGenerator|image_generator|PIL|ImageDraw|ImageFont`（含 tests/、scripts/、main.py、handlers/），确认除 `utils/image_generator.py` 自身与 `requirements.txt` 外零命中；确认 AstrBot 本体（`~/code/AstrBot/requirements.txt` 或 pyproject）独立声明 Pillow（本体依赖则摘依赖对宿主零影响，记于 PR 描述）
- [ ] 1.2 删除 `utils/image_generator.py` 与 `utils/__pycache__/image_generator.*.pyc`；`requirements.txt` 删除 `Pillow>=9.0.0`（若文件因此为空则删除文件并在 metadata/AGENTS 核对依赖声明处无残留）
- [ ] 1.3 复核 docs：AGENTS.md/README/design_docs 确无 image_generator 表述（exploration 报告曾误称 AGENTS.md 列其为活跃组件——实际无，任务即「核对通过」）；若发现任何残留引用一并清除

## 2. 10g · migrate() → migrate_or_reset() + 重置前备份

- [ ] 2.1 `data/migration.py:537` `migrate()` 改名 `migrate_or_reset()`：docstring 首句明示「三条路径中第三路径（版本低于任务链下限）会**重置全部数据**，重置前自动备份至 `.pre-reset.bak`」；方法体三条路径逻辑零改动
- [ ] 2.2 `data/migration.py` 重置分支（`_drop_all_tables` 调用之前，`PRAGMA foreign_keys = OFF` 之后）插入备份钩子 `_backup_before_reset(current_version)`：`VACUUM INTO '<db_path>.v<version>.pre-reset.bak'`（从活连接取一致性快照）；整段 try/except，失败降级 ERROR 日志「备份失败，未备份即重置」并继续（不劣化现状）；备份成功 INFO 日志含备份路径
- [ ] 2.3 调用点机械改名：生产 `main.py:455`；测试全仓 grep `\.migrate()` 逐一改 `.migrate_or_reset()`（已知 9 处：`test_sect_manager.py:81`、`test_gm_manager.py:897`、`test_impart_manager.py:145`、`test_sect_handlers.py:106`、`test_sect_content_link.py:102`、`test_sect_growth.py:188`、`test_sect_master.py:145`、`test_transaction_atomicity.py:80`，实施时以 grep 为准补全）；检查是否有 `Mock(spec=MigrationManager)` 按名字断言处需同步
- [ ] 2.4 新增测试 `tests/test_migration_reset_backup.py`（或并入既有 migration 测试文件）：构造 v31 旧库（向 db_info 写入 31）→ `migrate_or_reset()` → 断言（a）重置后 version = LATEST_DB_VERSION；（b）`<db>.v31.pre-reset.bak` 存在且为合法 sqlite（可 OPEN 并查到重置前的玩家行）；（c）全新安装路径不产生 .bak；测试用临时目录 db 文件，不复用生产路径

## 3. 10e · ConfigManager.get_pill_config 合并丹药查找

- [ ] 3.1 `config_manager.py`（紧邻 `is_pill` :485 之后）新增 `get_pill_config(name) -> dict | None`：顺序 `pills_data`→`exp_pills_data`→`utility_pills_data`→`items_data`（`type=="丹药"` 兜底）→ `None`；英文 Google 风格 docstring 注明「三表名域声明为互不相交（导入管线保证），重名时先命中者胜」
- [ ] 3.2 `managers/alchemy_manager.py`：`:51` 调用点改 `self.config_manager.get_pill_config(name)`；删除 `_get_pill_config_by_name`（:95-119）整方法与全部 `hasattr` 守卫
- [ ] 3.3 `core/pill_manager.py`：删除 `get_pill_by_name`（:35-58）；内部调用点 `:105`、`:688` 改 `self.config_manager.get_pill_config(...)`；`handlers/pill_handler.py:140` 同步改调（经其持有的 config_manager）
- [ ] 3.4 测试 fixture 收敛：grep 两旧方法名的全部测试引用并改调 `get_pill_config`；为 fake config_manager 补 `get_pill_config` 方法（聚合其已有的三表字典 + items 兜底）
- [ ] 3.5 新增 `tests/` 单测（可并入 `tests/test_config_manager*.py` 或新建）：`get_pill_config` 四来源各命中一例、未命中返回 None、**三表名域互不相交断言**（对 config/*.json 实测，防 sync_content_to_config.py 未来灌入重名条目静默改变解析）

## 4. 质量门与收尾

- [ ] 4.1 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过
- [ ] 4.2 按 AGENTS.md §7 版本 checklist 评估：10c 摘依赖建议至少补丁版本号 + README changelog 一行（依赖变化对部署可见）；10g/10e 无玩法变化
- [ ] 4.3 用 `bd` 登记跟进 issue：10g D3 备份轮转策略（若未来出现连续跨版本重置场景）
- [ ] 4.4 `openspec validate --change hygiene-cleanup-batch` 通过；本地分三个 conventional commit（`chore: remove dead image_generator…`、`refactor(db): rename migrate to migrate_or_reset with pre-reset backup…`、`refactor(config): merge pill lookup into ConfigManager.get_pill_config…`），不 push
