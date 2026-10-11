# Database Guidelines（数据库规范）

> 本项目数据库实际规范（AGENTS.md §3、§4 浓缩）。核心原则：全异步 aiosqlite +
> unit-of-work 事务上下文管理器（CM），业务模块不自管事务。

---

## 驱动与访问方式

- 使用 **aiosqlite**，所有数据库操作均为 async
- 多语句事务（unit-of-work）统一使用 `async with db.transaction() as txn:`
  （`DataBase.transaction()`，seam 在 data/data_manager.py 返回 `_TransactionCM`）；
  BEGIN/COMMIT/ROLLBACK 由 CM 管理，业务模块不自管事务
- 单语句写操作可直接 `await db.execute(...)`——叶子 helper 按 `conn._txn_depth` 门控
  自动提交

## 事务并发语义（设计 D1.2）

- **同任务嵌套** = no-op join：内层 CM 不重复提交，仅归属（owner）提交
- **跨任务互斥**：事务归属 `conn._txn_owner_task`，后到者等待串行，禁止静默共享事务
- 任何手工提交点未来包进 CM 时，必须删除块内裸 `conn.commit()`（残留 = 提前提交 bug）；
  CM 不得进入 raw `BEGIN IMMEDIATE` 块内部

## 忙碌状态读写（BusyState 双层，勿手动同步）

- `player.state`（字符串："空闲"/"修炼中"）——内存镜像，仅展示/快进选择器用
- `user_cd` 表（`type` 对应 `UserStatus` 枚举）——唯一真相，busy 判定一律以此为准
- 读写一律由 `core/busy_state.py` 的 `BusyState` 承接：`set_busy(player, status,
  scheduled_time, extra_data=...)` / `clear(player)`，双写包在调用方同一
  `async with db.transaction():` 内
- 处理器默认用 `@player_required` 装饰器（handlers/utils.py）；自定义守卫用
  `BusyState.assert_idle(user_id, template=...)`，禁止手写 user_cd/state 判断
- 例外：GM force-settle（core/gm_manager.py 的 `update_user_cd` 直写）保留直连
- 新增**等待类冷却域**（任何参与到期/冷却判定的时间戳字段）必须登记 GM「时间快进」
  字段覆盖清单（`core/time_skip_registry.py` 注册表）——否则新冷却不被快进覆盖、
  冷却类测试会隐性失败

## 定时任务与连接

- 定时任务中先 `await db.ensure_connection()` 再操作

## Migrations（迁移）

- 新增表/字段在 `data/migration.py` 写迁移脚本；`migrate()` 自动按版本号执行
- 数据库路径由 `StarTools.get_data_dir("astrbot_plugin_monixiuxian2_2")` 决定，不写死

## 数据存储路径（AstrBot 官方要求）

- 简单 KV：`self.put_kv_data()` / `get_kv_data()` / `delete_kv_data()`
- 大文件/自定义数据：必须存 `data/plugin_data/astrbot_plugin_monixiuxian2_2/`
  （经 `get_astrbot_data_path()` 拼出）
- **严禁**在插件自身目录存放用户数据或运行时状态

## 常见错误（Common Mistakes）

- ❌ 在 CM 块内残留裸 `conn.commit()`（提前提交 bug）
- ❌ 手写 `player.state` / `user_cd` 判断绕过 BusyState（双层漂移、快进失效）
- ❌ 新增冷却域不登记 time_skip_registry（快进测试隐性失败）
- ❌ 硬编码数据库路径或把数据文件写进插件目录
- ❌ 领域服务直写某列、通用 `update_player` 又按 dataclass 全字段落库 —— 调用方内存
  里的陈旧字段会在下一次 `update_player` 把领域服务写入的值静默刷回（气血基座 P0：
  settle 推进的 health_recovered_at 锚点被战斗后 update_player 回刷，恢复窗口复活）。
  修法二选一（可叠加）：把该列登记进 `data/data_manager.py` 的 `_DOMAIN_OWNED_FIELDS`
  （UPDATE 排除、INSERT 保留），让领域服务成为唯一写入方；和/或领域服务写库后同步
  回写内存对象（参考 BusyState 钩子 settle 后回写 `player.current_hp`）。新增"领域
  服务直写 + 调用方缓存 player 再 update_player"模式的列时，必须过一遍这个检查。