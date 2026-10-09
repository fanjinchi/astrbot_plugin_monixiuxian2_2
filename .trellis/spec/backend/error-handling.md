# Error Handling（错误处理与消息规范）

> 插件错误处理实际规范（AGENTS.md §8 浓缩）。总原则：**良好的错误处理，不让插件因
> 单个错误崩溃**；用户可见输出全部中文。

---

## 崩溃隔离（第一原则）

- 任何用户输入路径（指令处理、事件钩子）都不允许未捕获异常导致插件进程崩溃
- 业务异常在服务层捕获并转为带状态符的中文提示消息返回，不向上抛
- 定时任务必须包含指数退避重试（参考 `_schedule_boss_spawn`）

## 消息状态符规范（§8，易错重点）

- ❌/✅/⚠️/🎯 等消息状态符**一律由 manager/core 服务层自带完整文案**，handler 裸渲染
  `msg`、禁止再包 ✅/❌ 前缀：同一服务方法常被多个入口（全局指令/宗门子命令）消费，
  只有服务层自带 emoji 才能保证各入口输出一致；handler 仅对自身的参数/入口校验文案负责
  （参考实现 bounty/bank/储物戒/装备/丹药 域）
- 服务层消息嵌入自己的包装头（如「❌ 结算失败：{msg}」「✅ 已卸下…：{msg}」）时，
  内嵌 msg 须先 `removeprefix('❌ ')` / `removeprefix('✅ ')` 去重，保证整条消息以单一
  状态符开头
- 例外：返回 `\n` / `\n\n` 开头、供调用方拼接到主消息尾部的片段（如 📜 进度提示、
  `f"\n{unequipped_item_name} 已自动存入储物戒"`）自带内容符号，由调用方原样拼接、
  不再加状态头

## 消息发送陷阱

- 群聊广播：`self.context.send_message(umo, message_chain)`，`umo` 格式
  `{platform}:GroupMessage:{group_id}`
- aiocqhttp：`plain` 消息发送自动 `strip()` 首尾空白；需保留空白时在消息前后加零宽
  空格 `\u200b`
- 事件钩子（`on_llm_request`、`on_decorating_result` 等）中不能 `yield` 发送消息，
  必须用 `event.send()`；`event.stop_event()` 可阻止后续插件和 LLM 请求

## 配置缺失兜底

- 静态配置：`config/*.json` 缺失时，`config_manager.py` 自动从
  `data/default_configs.py` 创建默认值；解析失败应有可读日志，不让加载流程崩溃