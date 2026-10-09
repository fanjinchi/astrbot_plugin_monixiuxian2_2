# Directory Structure（目录结构与接入点）

> 本插件实际目录组织与"新指令/新子系统"标准接入点（AGENTS.md §1、§13 浓缩）。

---

## Directory Layout

```
astrbot_plugin_monixiuxian2_2/
├── main.py                  # 插件入口：命令路由 + 定时任务初始化 + _wire_core_services() 装配
├── metadata.yaml            # 插件元数据（display_name / support_platforms / astrbot_version / version）
├── _conf_schema.json        # WebUI 可视化配置 Schema（动态配置经 AstrBotConfig 注入）
├── config_manager.py        # 配置加载器（自动从 data/default_configs.py 补默认值）
├── config/                  # JSON 静态配置（境界、物品、武器、丹药、配方、敌人等）
├── handlers/                # 指令处理器（按系统分类），__init__.py 导出 Handler 类
├── managers/                # 业务逻辑（战斗、宗门、Boss、悬赏等）
├── core/                    # 通用工具（修炼、丹药、装备、储物戒、BusyState 等单例服务）
├── data/                    # 数据库封装（data_manager.py）+ 迁移（migration.py）
├── models.py / models_extended.py   # Player 数据模型 / UserStatus 扩展模型
├── utils/                   # 跨层工具
├── design_docs/             # 设计事实层（内容设计先行，§14/§15）
├── tests/                   # pytest 用例（tests/helpers.py load_module 加载）
└── openspec/specs/          # 只读历史契约（16 篇，不再新增 change）
```

## 新指令的接入点（新增指令必守）

1. `main.py` 定义 `CMD_XXX` 常量 + `@filter.command(CMD_XXX)` 方法；方法必须加
   `@require_whitelist`（已在 main.py 定义）；装饰器顺序：`@filter.command` 在外层、
   `@require_whitelist` 在内层
2. 业务逻辑优先写 `handlers/xxx_handler.py`，复杂逻辑委托 `managers/` 或 `core/`；
   处理器在 `handlers/__init__.py` 导出，并在 main.py 顶部 import
3. 指令名不能带空格（AstrBot 将空格后内容解析为参数）；本项目用纯中文指令（如"闭关"）
4. 路由方法 docstring 固定格式：
   `"""Command 「指令名」- 描述; routes to xxx_handler.handle_yyy."""`

## 新子系统的接入点（§13 六步模板）

1. `core/xxx_manager.py` — 核心逻辑（单例服务）
2. `managers/xxx_manager.py` — 业务封装（如需）
3. `handlers/xxx_handlers.py` — 指令处理
4. `handlers/__init__.py` — 导出 Handler
5. `main.py` — 在 `_wire_core_services()` 装配段实例化并注入 Handler、注册命令
6. 如有数据库表 → `data/migration.py` 添加迁移

## Naming Conventions

- Python 文件名/标识符 snake_case；类名 PascalCase；指令常量 `CMD_XXX`
- 数据库表/列名与 `UserStatus` 枚举值对应 `user_cd` 表的 `type` 列
- 用户可见输出一律中文；消息状态符（❌/✅/⚠️/🎯 等）由 manager/core 服务层自带完整文案

## 禁止模式

- ❌ 在 handler/manager 内自构造 core 单例服务（必须由装配段注入）
- ❌ 在插件自身目录存放用户数据/运行时状态（一律走 AstrBot plugin_data 路径）
- ❌ 指令名含空格；Handler 不定义在插件类中；文件名不是 main.py