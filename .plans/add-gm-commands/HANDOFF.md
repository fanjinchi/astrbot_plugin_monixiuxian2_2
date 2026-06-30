实现修仙插件 GM 命令系统。依据 OpenSpec change `add-gm-commands` 的 artifacts（proposal.md / design.md / specs/gm-commands/spec.md / tasks.md）。

核心目标：
- 新增统一 GM 命令入口 `修仙GM <子命令>` 和 `修仙GM帮助`。
- 新增独立配置 `GM_ADMINS`。
- 支持修改角色属性（境界、修为、灵石、气血、真元、攻击、精神力）、发放装备/物品进储物戒、卸下装备、清除 CD、强制历练/秘境结算、生成 Boss。
- 目标玩家解析：@mention → 数字 user_id → 发送者自己。
- 破坏性操作需 `确认` 二次确认。
- 审计日志写入插件数据目录 `gm_operations.log`，500MB 轮转。
- 在普通 `修仙帮助` 中列出 `修仙GM帮助`（GM-only 标记）。

质量门：
- `uv run ruff format . && uv run ruff check .` 通过
- `uv run python -m pytest tests/ -v` 通过
- 更新 `metadata.yaml` 版本和 `README.md` 变更日志