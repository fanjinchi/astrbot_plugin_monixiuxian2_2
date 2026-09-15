# Tasks — hygiene-cleanup-batch

## 1. 10c · 删除 utils/image_generator.py

- [x] 1.1 删除前终检：全仓 grep `ImageGenerator|image_generator|PIL|ImageDraw|ImageFont`（含 tests/、scripts/、main.py、handlers/），确认除 `utils/image_generator.py` 自身与 `requirements.txt` 外零命中；确认 AstrBot 本体（`~/code/AstrBot/requirements.txt` 或 pyproject）独立声明 Pillow（本体依赖则摘依赖对宿主零影响，记于 PR 描述）
- [x] 1.2 删除 `utils/image_generator.py` 与 `utils/__pycache__/image_generator.*.pyc`；`requirements.txt` 删除 `Pillow>=9.0.0`（若文件因此为空则删除文件并在 metadata/AGENTS 核对依赖声明处无残留）
- [x] 1.3 复核 docs：AGENTS.md/README/design_docs 确无 image_generator 表述（exploration 报告曾误称 AGENTS.md 列其为活跃组件——实际无，任务即「核对通过」）；若发现任何残留引用一并清除
- [x] 1.4 摘 Pillow 后同步五处「仅 Pillow」依赖声明（全部改为无额外依赖/移除该条）：`AGENTS.md:12`、`AGENTS.md:37`、`design_docs/current-design-report.md:21`、`design_docs/project-architecture.md:15`、`README.md:261`（安装步骤的 `pip install Pillow` 行删除或改写）

## 2. 10g · migrate() → migrate_or_reset() + 重置前备份

- [x] 2.1 `data/migration.py:537` `migrate()` 改名 `migrate_or_reset()`：docstring 明示「四条路径中第三路径（版本低于任务链下限）会**重置全部数据**，重置前自动备份至 `.pre-reset.bak`」——**四条路径都要写全**：新建（空库）/ 升级（逐版本任务）/ 重置+备份 / **第 4 条兜底（:631-636，current_version > LATEST 抛 RuntimeError 拒绝降级运行，现有 docstring 就漏了它，重写时补上，避免「三条路径」表述再次缺兜底）**；方法体逻辑零改动
- [x] 2.2 `data/migration.py` 重置分支插入备份钩子 `_backup_before_reset(current_version)`，位置在 `PRAGMA foreign_keys = OFF`（:614）之后、`BEGIN`（:615）**之前**（VACUUM 禁止事务内执行，放错位置将静默降级为永无备份）：db_path 经 `PRAGMA database_list` 取主库文件路径（MigrationManager 构造不持路径，**不得**新增构造参数）；**空路径（`:memory:` 连接）跳过备份并 `logger.warning`**（实测 `VACUUM INTO` 对 `:memory:` 会成功执行，naive 拼接会在 pytest CWD 写出流浪 `.bak`）；非空路径执行 `VACUUM INTO '<db_path>.v<version>.pre-reset.bak'` 从活连接取一致性快照；整段 try/except，失败降级 ERROR 日志「备份失败，未备份即重置」并继续（不劣化现状）；备份成功 INFO 日志含备份路径；实施时确认进入 migrate() 时连接上无残留隐式事务（VACUUM INTO 要求无活动事务——上层未 commit 的写会使备份失败并走降级路径；main.py 的 connect()→migrate() 顺序无未提交写，仅需确认无其他调用方）
- [x] 2.3 调用点机械改名：生产 `main.py:455`；测试仓内全部 `.migrate()` 调用实测 25 处，逐一改 `.migrate_or_reset()`——`test_migration.py` 17 处（:45、:70、:154、:178、:199、:206、:222、:233、:283、:355、:366、:383、:413、:423、:434、:472、:504），`test_sect_manager.py:81`、`test_gm_manager.py:897`、`test_impart_manager.py:145`、`test_sect_handlers.py:106`、`test_sect_content_link.py:102`、`test_sect_growth.py:188`、`test_sect_master.py:145`、`test_transaction_atomicity.py:80`（实施时仍以 grep `\.migrate()` 全量复核）；**显式改名 `tests/test_feature_switches.py:259` 的按名 mock** `MagicMock(migrate=AsyncMock())` → `MagicMock(migrate_or_reset=AsyncMock())`（`.migrate()` grep 抓不到此处；不改则 `await` 同步 MagicMock 抛 TypeError）；同步检查测试中 `Mock(spec=MigrationManager)` 按名断言处
- [x] 2.4 新增测试 `tests/test_migration_reset_backup.py`（或并入既有 migration 测试文件）：构造 v31 旧库（向 db_info 写入 31）→ `migrate_or_reset()` → 断言（a）重置后 version = LATEST_DB_VERSION；（b）`<db>.v31.pre-reset.bak` 存在且为合法 sqlite（可 OPEN 并查到重置前的玩家行）；（c）全新安装路径不产生 .bak；测试用临时目录 db 文件，不复用生产路径
- [x] 2.5 文档按名引用同步：`design_docs/api-overview.md:29` 与 `:117` 的 `MigrationManager.migrate()` 改名 `migrate_or_reset()`；`openspec/specs/impart-system/spec.md:187-190` 场景 WHEN 的 `migrate()` 标识符 prose-only 同步（行为不变，`.openspec.yaml` 维持 `skip_specs: true`）；**顺带修正同面过时数字**：`design_docs/api-overview.md:117` 的「新装直接建最新 schema（v30）」实为 v34 且漏第三路径（重建）——改名动到这行时一并改对（v34 + 三路径）；spec.md:190 THEN 的「重建为 v32」同步改 v34（LATEST_DB_VERSION=34，data/migration.py:19）

## 3. 10e · ConfigManager.get_pill_config 合并丹药查找

- [x] 3.1 `config_manager.py`（紧邻 `is_pill` :485 之后）新增 `get_pill_config(name) -> dict | None`：顺序 `pills_data`→`exp_pills_data`→`utility_pills_data`→`items_data`（`type=="丹药"` 兜底）→ `None`；英文 Google 风格 docstring 注明「三表名域声明为互不相交（导入管线保证），重名时先命中者胜」
- [x] 3.2 `managers/alchemy_manager.py`：`:51` 调用点改 `self.config_manager.get_pill_config(name)`；删除 `_get_pill_config_by_name`（:95-119）整方法与其**方法体内**的 4 个 `hasattr` 守卫（:100/:105/:110/:115）——**仅删方法体内的**；`:34` 的 `hasattr(config_manager, "alchemy_recipes")` 属配方加载逻辑（`_normalize_recipe` 之外），**必须保留**
- [x] 3.3 `core/pill_manager.py`：删除 `get_pill_by_name`（:35-58）；内部调用点 `:105`、`:688` 改 `self.config_manager.get_pill_config(...)`；`handlers/pill_handler.py:140` 同步改调（经其持有的 config_manager）；**显式排除**：`handlers/breakthrough_handler.py:177` 与 `core/breakthrough_manager.py:154` 的 `pills_data.get(pill_name)` 为故意的只查破境丹表（未知药名必须报「未找到破境丹」），**不**并入 `get_pill_config`、保持原样
- [x] 3.4 测试 fixture 收敛：grep 两旧方法名的全部测试引用并改调 `get_pill_config`；为 fake config_manager 补 `get_pill_config` 方法——**实测收敛面比预想的窄**：需补的只有 `tests/test_transaction_atomicity.py:58` 的 FakeConfigManager（`test_pill_manager.py` 用真实 ConfigManager；其余 FakeConfigManager 仅服务 MigrationManager 构造、migrate 不碰 pill 数据，无需补）；以测试通过为准
- [x] 3.5 新增 `tests/` 单测（可并入 `tests/test_config_manager*.py` 或新建）：`get_pill_config` 四来源各命中一例、未命中返回 None、**数据事实断言**（对 config/*.json 实测）：①三表名域两两不相交；②items.json 的 `type=丹药` 条目与三表名域的交叠 ⊆ 已知无害集合（当前实测 = {血煞丹}——util 与 items 重复登记，两旧实现与新实现均经 util 表解析，items 条目从不触发；断言写成 `交叠 ⊆ {"血煞丹"}`，内容管线新增交叠名即转红待人工评估）；③**每表 raw 条目数 == 去重后名字数（表内无重名）**——只断言①查不出表内重名（交集仍为空、dict 化静默覆盖），②只能拦新交叠，③才是防 sync_content_to_config.py 灌入重名的闸门。**已知失败项**：`utility_pills.json` 现有 1 组重名「混元血容丹」（raw 143 → unique 142；两个**不同 tier**——util_128 皇品+10000 气血 / util_142 混元先天+300000，dict 去重后 util_128 被整体遮蔽，皇品 tier 在游戏中不可获得）——属内容决策（改名走 design_docs 管线），已登记 **bd `-czl`（混元血容丹重名遮蔽）**，本 change 不修；任务 ③ 的断言作为闸门保留，bd 修复内容后转绿

## 4. 质量门与收尾

- [x] 4.1 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过
- [x] 4.2 按 AGENTS.md §7 版本 checklist 评估并执行：10c 摘依赖建议至少补丁版本号——**显式更新 `metadata.yaml` 的 `version`** + README changelog 一行（依赖变化对部署可见）；10g/10e 无玩法变化
- [x] 4.3 用 `bd` 登记跟进 issue：10g D3 备份轮转策略（若未来出现连续跨版本重置场景）
- [x] 4.4 `openspec validate --changes hygiene-cleanup-batch` 通过；本地分三个 conventional commit（`chore: remove dead image_generator…`、`refactor(db): rename migrate to migrate_or_reset with pre-reset backup…`、`refactor(config): merge pill lookup into ConfigManager.get_pill_config…`），不 push
