# 后端开发规范（Backend Guidelines）

> AstrBot 文字修仙插件的实际编码规范（2026-10-09 bootstrap 任务从 AGENTS.md 提炼）。

---

## 项目形态

Python 插件（无独立构建系统），作为宿主 AstrBot 的子目录运行，依赖 AstrBot 提供的
运行时与 API。**权威规范源是插件根 `AGENTS.md`，本目录是其浓缩抽取，两者冲突时以
AGENTS.md 为准**。

- 入口：`main.py`（文件名必须为 main.py，`Star` 子类）；core 服务由 `_wire_core_services()`
  装配段统一注入，**禁止在 handler/manager 内自构造核心服务**
- 分层链路：`handlers/`（指令处理）→ `managers/`（业务逻辑）→ `core/`（通用工具/单例
  服务）→ `data/`（数据库封装 + 迁移）；`config/`（JSON 静态配置）、`config_manager.py`
  （配置加载器）、`models.py` / `models_extended.py`（Player / UserStatus 模型）
- 运行时热重载：改代码后须在 AstrBot WebUI 插件管理 → 重载插件才生效；无独立解释器，
  一律用 AstrBot 根目录的 `uv run python` / `uv run ruff ...`

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | 目录组织、新指令/新子系统接入点 | ✅ 已填充（2026-10-09） |
| [Database Guidelines](./database-guidelines.md) | aiosqlite、事务 CM、迁移、数据存储路径 | ✅ 已填充（2026-10-09） |
| [Error Handling](./error-handling.md) | 崩溃隔离、中文用户消息、消息状态符规范 | ✅ 已填充（2026-10-09） |
| [Quality Guidelines](./quality-guidelines.md) | 质量门、docstring/注释、版本与文档同步 | ✅ 已填充（2026-10-09） |
| [Logging Guidelines](./logging-guidelines.md) | AstrBot logger、后台任务重试日志 | ✅ 已填充（2026-10-09） |

## 使用方式

trellis-implement / trellis-check 子代理开工前，由任务 manifest（implement.jsonl /
check.jsonl）列出应注入的 spec 文件；按任务实际涉及的层选择注入对应篇目。guides/
（跨层思维指南）适配一切跨层改动。