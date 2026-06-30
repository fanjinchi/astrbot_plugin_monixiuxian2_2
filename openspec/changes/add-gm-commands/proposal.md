## Why

修仙插件目前缺乏一套统一的游戏管理员（GM）工具。管理员需要频繁调试、补偿玩家或举办活动，但现有命令仅限普通玩家流程，无法直接修改角色属性、发放装备或强制触发探索/历练结算。新增 GM 命令入口可以大幅降低运营和测试成本。

## What Changes

- 新增统一的 GM 命令入口 `修仙GM <子命令> [目标玩家] [参数]`。
- 新增独立的 GM 管理员权限配置 `GM_ADMINS`，与现有 `BOSS_ADMINS` 解耦。
- 新增 `core/gm_manager.py` 作为 GM 业务逻辑核心，负责权限校验、目标玩家解析、子命令分发和审计日志。
- 新增 GM 日志文件 `gm_operations.log`，写入插件数据目录，不新增数据库表。
- 新增 `handlers/gm_handler.py` 处理命令入口，并在 `main.py` 注册。
- 新增 `修仙GM帮助` 命令，列出所有 GM 子命令。
- 支持子命令：
  - 角色属性：设置境界、设置修为、设置灵石、设置气血、设置真元、设置攻击、设置精神力、清除 CD
  - 装备物品：给予装备（进储物戒）、给予物品（进储物戒）、卸下装备
  - 触发结算：触发历练结算、触发秘境结算
  - 系统：生成 Boss、GM 帮助

## Capabilities

### New Capabilities

- `gm-commands`: 统一的 GM 命令入口，提供角色属性修改、装备发放、探索/历练结算触发及审计日志能力。

### Modified Capabilities

- 无现有 spec 需要修改。

## Impact

- `main.py`: 新增 `CMD_GM` 常量、GM handler 初始化、权限检查方法、命令注册。
- `core/`: 新增 `gm_manager.py`。
- `handlers/`: 新增 `gm_handler.py`，更新 `__init__.py`。
- `_conf_schema.json`: 新增 `GM_ADMINS` 配置项。
- 插件数据目录：新增 `gm_operations.log` 日志文件。
- 无数据库 schema 变更。
