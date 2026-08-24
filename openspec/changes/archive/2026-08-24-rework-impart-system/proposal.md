## Why

当前传承系统的传承值仅通过「传承 PK」胜利随机累积（+1~5），与设计意图不符：PK 应当只负责**夺取传承相关内容**，传承值累积应由**修炼**驱动。此外，`impart_config.json` 奖励引用的心法/功法 id（传承心法·吐纳/归元、impart_skill_001/002）在 `heart_methods.json`/`skills.json` 中不存在，奖励发放实际空转。

## What Changes

- **传承值改由修炼累积**：出关结算时，玩家持有的每条传承按有效修炼时间累积传承值（**每 15 分钟 1 点**），达到所属类型等阶阈值自动发放奖励。
- **PK 改为夺取制（BREAKING）**：「传承挑战」胜者**整体夺取**对方一条传承（传承值清零、已领取等阶清零，需重新修炼解锁）；被挑战者胜利则无事发生；挑战者失败后 **5 天内不得再向同一人发起挑战**。传承值本身不参与 PK 战力计算（维持现状语义）。
- **传承不唯一**：一人可持有多条传承实例。新增 `legacy_instances` 表（`id/owner_id/legacy_type/impart_value/claimed_tiers/sect_id/acquired_at`）；旧 `impart_info` 数据迁移为 `common` 类型实例后删除旧表。新增 `impart_pk_cooldown` 表记录挑战失败冷却。
- **配置按类型分表**：`impart_config.json` 重构为 `types`（`common`/`sect`/`adventure`/`rift`）各自 `tiers`/`rewards`（首版复用同一套默认阈值 20/40/60/80/100，结构支持独立配置）。
- **获取途径（均需先挑战「传承之地守护 NPC」，复用 CombatEngine PvE，胜利才获得）**：
  - 宗门奖励：type=`sect`，**不可被 PK 夺走**，离宗/被踢时由宗门收回（与既有宗门宝物规则一致）；
  - 历练结算概率触发（先做概率，事件化留后续）；
  - 秘境结算概率触发（特定秘境专属传承留后续）。
  - 获取概率接入对应模块配置（`adventure_config.json`/`rift_config.json` 加 `legacy_chance`，宗门传承入 `sect_factions.json` 宝库 `kind="legacy"`）；守护 NPC 入 `enemies.json`（`legacy_guardian` 组）。
- **修复奖励空转**：在 `design_docs/content-design/heart_methods.csv`、`skills.csv` 补齐传承奖励条目并经 `sync_content_to_config.py` 同步。
- **版本与文档**：`metadata.yaml` v3.10.0 → v3.11.0；README、/修仙帮助、`design_docs/current-design-report.md`、`project-architecture.md`、`api-overview.md`、`sect-system-design.md` 同步更新。
- **GM 传承测试支持**：新增「给予传承」「清除传承」GM 子命令（仅限 GM_ADMINS 白名单），用于功能测试预置/清理传承实例，支撑夺取/冷却/保护路径的端到端用例。

## Capabilities

### New Capabilities

- `impart-system`: 传承系统核心行为——传承实例的获取（宗门/历练/秘境 + 守护 NPC 挑战）、修炼累积传承值、等阶奖励解锁、PK 夺取与失败冷却、传承信息/排行展示。

### Modified Capabilities

- `sect-system`: 宗门宝库扩展承载宗门传承（`kind="legacy"`，领取需先通过守护 NPC 挑战，成功后创建绑定宗门的传承实例）；离宗/被踢时回收玩家持有的宗门传承实例。
- `gm-commands`: 新增「给予传承」「清除传承」子命令，用于功能测试预置/清理传承实例。

## Impact

- **代码**：`managers/impart_manager.py`（重构：实例生命周期/累积/转移/冷却）、`managers/impart_pk_manager.py`（夺取制）、`managers/adventure_manager.py`、`managers/rift_manager.py`、`managers/sect_manager.py`（宝库 kind=legacy + 离宗回收）、`managers/pve_combat_manager.py`（守护 NPC 挑战）、`handlers/impart_handlers.py`、`handlers/impart_pk_handlers.py`、`handlers/player_handler.py`（出关累积）、`data/migration.py`（v32）、`data/database_extended.py`、`data/data_manager.py`、`models_extended.py`、`core/gm_manager.py`（传承预置/清除子命令）、`main.py`、`handlers/misc_handler.py`。
- **配置**：`config/impart_config.json`（重构）、`config/adventure_config.json`、`config/rift_config.json`（加 `legacy_chance`）、`config/sect_factions.json`（宝库 kind=legacy）、`config/enemies.json`（legacy_guardian）、`config/heart_methods.json`/`config/skills.json`（经 sync 管道补齐奖励 id）。
- **数据**：新表 `legacy_instances`、`impart_pk_cooldown`、`impart_snatch_protection`；**迁移重构**：v3.11.0 起不再向前兼容——移除全部历史逐版本迁移（不再有 `impart_info` 拷贝保真），统一 `_create_all_tables()` 直接生成 v32 最新 schema，旧库重建（数据重置）；保留 `MIGRATION_TASKS` 注册机制供后续版本增量升级。
- **测试**：`tests/test_impart_manager.py` 重写、`tests/test_migration.py` 增补 v32、`tests/test_sect_manager.py`（若存在）扩展；`functional_tests` 新增传承域用例。
- **文档**：`design_docs/current-design-report.md`（4.17 节重写、ImpartInfo→LegacyInstance、迁移里程碑）、`design_docs/project-architecture.md`、`design_docs/api-overview.md`、`design_docs/sect-system-design.md`、`README.md`、`handlers/misc_handler.py` 帮助文本。
