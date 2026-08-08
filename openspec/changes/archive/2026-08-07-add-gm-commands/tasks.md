## 1. Configuration and permission plumbing

- [x] 1.1 Add `GM_ADMINS` array to `_conf_schema.json` under access control
- [x] 1.2 Load `GM_ADMINS` in `XiuXianPlugin.__init__` and store as `self.gm_admins`
- [x] 1.3 Implement `_check_gm_admin(event)` method in `main.py`

## 2. GM core manager

- [x] 2.1 Create `core/gm_manager.py` with `GMManager` class
- [x] 2.2 Implement target player resolution (numeric ID, at-mention, sender fallback)
- [x] 2.3 Implement sub-command dispatcher mapping Chinese verbs to methods
- [x] 2.4 Implement realm-name to `level_index` resolution for both cultivation types
- [x] 2.5 Implement attribute modification methods (设置修为, 设置灵石, 设置气血, 设置真元, 设置攻击, 设置精神力)
- [x] 2.6 Implement `设置境界` with validation against `ConfigManager` level data
- [x] 2.7 Implement `给予装备` / `给予物品` via `StorageRingManager.store_item`
- [x] 2.8 Implement `卸下装备` via `EquipmentManager.unequip_item` with storage-ring fallback
- [x] 2.9 Implement `清除CD` by syncing `user_cd` and `player.state`; require `确认` argument
- [x] 2.10 Implement log rotation when `gm_operations.log` reaches 500 MB
- [x] 2.11 Implement `触发历练结算` by advancing `user_cd.scheduled_time` and calling `AdventureManager.finish_adventure`
- [x] 2.12 Implement `触发秘境结算` by advancing `user_cd.scheduled_time` and calling `RiftManager.finish_exploration`
- [x] 2.13 Implement `生成Boss` by delegating to `BossManager.auto_spawn_boss` or `handle_spawn_boss` logic
- [x] 2.14 Implement JSON-line audit logging to plugin data directory

## 3. GM command handler

- [x] 3.1 Create `handlers/gm_handler.py` with `GMHandler` class
- [x] 3.2 Implement `handle_gm(event, args)` method that checks GM permission, parses sub-command, and delegates to `GMManager`
- [x] 3.3 Implement `handle_gm_help(event)` method
- [x] 3.4 Export `GMHandler` from `handlers/__init__.py`

## 4. Command registration

- [x] 4.1 Add `CMD_GM = "修仙GM"` and `CMD_GM_HELP = "修仙GM帮助"` constants in `main.py`
- [x] 4.2 Initialize `gm_handler = GMHandler(...)` in `XiuXianPlugin.__init__`
- [x] 4.3 Register `@filter.command(CMD_GM)` handler method
- [x] 4.4 Register `@filter.command(CMD_GM_HELP)` handler method
- [x] 4.5 Include `修仙GM帮助` in the regular `修仙帮助` output with a GM-only marker

## 5. Testing and quality

- [x] 5.1 Add unit tests for target player resolution logic
- [x] 5.2 Add unit tests for realm-name to `level_index` resolution
- [x] 5.3 Add unit tests for audit log formatting
- [x] 5.4 Run `uv run ruff format . && uv run ruff check .`
- [x] 5.5 Run `uv run python -m pytest tests/ -v`
- [x] 5.6 Update `README.md` changelog
- [x] 5.7 Update `metadata.yaml` version
- [x] 5.8 Update `handlers/misc_handler.py` help text if GM help is exposed there
