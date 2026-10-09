# Logging Guidelines（日志规范）

> 插件日志实际规范（AGENTS.md §10 浓缩）。

---

## 日志方式

- 使用 AstrBot 运行时提供的 logger：插件类内用 `self.logger`（Star 子类持有），
  模块级辅助代码用项目既有 logger 模式（参考 main.py / core/ 内实际用法），
  不自行 `logging.basicConfig` 或重复造 logger
- 日志内容用中文描述性文本（与项目一致），关键错误带堆栈（`logger.exception` 或
  `exc_info=True`）

## 日志级别

| 级别 | 何时使用 |
|------|----------|
| debug | 高频内部状态（尽量少用，避免刷屏） |
| info | 命令入口、定时任务执行、配置加载等关键节点 |
| warning | 可恢复的异常（单次任务失败、外部重试中、配置降级） |
| error | 不可恢复的错误（插件部件加载失败、数据库异常等），必须可定位 |

## 后台任务（关键）

- 所有定时任务必须包含指数退避重试（参考 `_schedule_boss_spawn`）：失败记 warning +
  退避计划，连续失败到阈值记 error，但不让整个插件崩溃

## 禁止记录

- 不记录用户 token / 密钥 / 明文敏感信息；数据库连接串不含密码
- 不记录完整玩家个人数据（user_id 可保留用于定位，聊天内容尽量截断）