## Context

The plugin currently has two permission tiers:

- Normal players, gated by group whitelist (`WHITELIST_GROUPS`).
- Boss administrators (`BOSS_ADMINS`), who can spawn world bosses.

There is no general GM capability. Administrators who want to compensate a player, test a feature, or run an event must manually edit the SQLite database or rely on normal player commands.

## Goals / Non-Goals

**Goals:**

- Provide a single, discoverable GM command entry point.
- Support modifying core character attributes, giving items/equipment, clearing busy states, and forcing adventure/rift settlements.
- Support resolving a target player by mention, numeric user ID, or defaulting to the sender.
- Record every GM operation to a dedicated log file in the plugin data directory.
- Keep the change self-contained and avoid database schema migrations.

**Non-Goals:**

- A web-based admin panel.
- Fine-grained role-based access control (e.g., junior GM vs senior GM).
- Modifying sects, banks, bounties, spirit farms, or dual-cultivation states in the first iteration.
- Auto-equipping items given by GM; items go to storage ring only.
- Custom reward values for forced settlements; normal random rewards are used.

## Decisions

### 1. Unified command entry point with sub-command dispatcher

All GM commands go through `修仙GM <sub-command> [target] [args]` instead of registering a separate top-level command per GM action. This keeps the command namespace clean and makes it easy to add new GM capabilities later.

**Rationale:** The plugin already has dozens of top-level commands. A nested CLI reduces clutter and makes authorization simple (one command to guard).

**Alternative considered:** Separate commands like `修仙设置境界`, `修仙给装备`. Rejected because it pollutes the command space and requires duplicating permission checks.

### 2. Independent `GM_ADMINS` configuration

GM admins are configured separately from `BOSS_ADMINS`. A user can be a GM without being a boss admin, and vice versa.

**Rationale:** GM commands can modify player data, which is a broader and more dangerous capability than spawning bosses. Separation follows the principle of least privilege.

### 3. Target resolution order: mention → numeric ID → sender

The first positional argument after the sub-command is inspected. If it is an `At` segment, the target is the mentioned user. If it is numeric, it is treated as a user ID. Otherwise it is treated as part of the command arguments and the sender becomes the target.

**Rationale:** Matches the user's stated priority (user ID first, then at-mention as enhancement). Defaulting to the sender makes self-testing and self-compensation convenient.

**Risk:** Mention parsing depends on the platform adapter. The initial implementation will support at-mentions where AstrBot exposes them in `event.message_obj`, falling back to numeric IDs when not available.

### 4. High-level attribute commands instead of generic field setter

GM can use commands like `设置境界`, `设置灵石` rather than `设置 player.gold 9999`.

**Rationale:** Prevents accidental corruption of derived or internal fields (e.g., `level_index` must stay within valid range, `state` must be kept in sync with `user_cd`). It also makes commands more natural in Chinese.

### 5. Items go to storage ring, not auto-equipped

`给予装备` and `给予物品` both place the item into the target player's storage ring.

**Rationale:** Avoids bypassing equipment level requirements and lets the player choose when to equip. A separate `卸下装备` command handles removing already-equipped gear.

### 6. Forced settlements reuse existing manager logic

To force an adventure or rift settlement, the GM manager sets `user_cd.scheduled_time` to the current time (or slightly earlier) and then calls the existing `finish_adventure` / `finish_exploration` methods.

**Rationale:** Maximizes code reuse and ensures reward logic, state cleanup, and bounty progress updates remain consistent with normal play.

### 7. Audit log as JSON lines in plugin data directory

Each GM operation appends one JSON line to `gm_operations.log` under `StarTools.get_data_dir("astrbot_plugin_monixiuxian2")`. No database table is added.

**Rationale:** The user explicitly requested a file-based log. JSON lines are easy to parse later and do not require a migration. Logs are kept outside the plugin source tree, satisfying AstrBot's data persistence rules.

## Risks / Trade-offs

- **[Risk]** Mention parsing may behave differently across adapters (aiocqhttp, telegram, discord).
  - **Mitigation:** Initial release focuses on numeric user IDs. At-mention support is added as a thin adapter-specific layer with explicit fallback to numeric IDs.

- **[Risk]** GM commands bypass normal gameplay balance.
  - **Mitigation:** All operations are logged. Future iterations could add log viewer or command confirmation for destructive actions.

- **[Risk]** `finish_adventure` and `finish_exploration` may change in the future, breaking forced settlement behavior.
  - **Mitigation:** The GM manager delegates to these methods rather than duplicating logic, so changes propagate automatically. Tests should cover forced settlement paths.

- **[Risk]** Setting `level_index` to an invalid value could break display or combat calculations.
  - **Mitigation:** The `设置境界` command validates the realm name against `ConfigManager.level_data` / `body_level_data` and rejects unknown names.

## Migration Plan

No migration is required. The change is purely additive:

1. Add `GM_ADMINS` to `_conf_schema.json`.
2. Deploy the plugin update.
3. Configure GM admin user IDs via AstrBot's web UI or config file.
4. The `gm_operations.log` file is created automatically on first GM command.

## Open Questions

- Should `修仙GM帮助` be hidden from the regular `修仙帮助` output, or listed with a note that it requires GM privileges?
  - **Resolved:** List it in the regular `修仙帮助` output with a GM-only marker.
- Should destructive GM commands (e.g., `清除CD` while a player is mid-combat) require an explicit `确认` argument?
  - **Resolved:** Yes. Destructive commands require appending `确认` to the end of the command.
- Should the audit log rotate after reaching a certain size?
  - **Resolved:** Rotate when the log reaches 500 MB, renaming the old file with a timestamp suffix.
