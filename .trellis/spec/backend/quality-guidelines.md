# Quality Guidelines（质量规范）

> 项目质量门与代码风格实际规范（AGENTS.md 相关各节浓缩）。

---

## 质量门（提交/完成前必跑）

在插件目录执行（无独立解释器，一律用 AstrBot 的 uv 环境）：

```bash
uv run ruff format .
uv run ruff check .
uv run python -m pytest tests/ -v
```

- 因 `managers/__init__.py` 含相对导入，不能从 AstrBot 根目录直接跑 pytest；
  插件内测试用 `tests/helpers.py` 的 `load_module()` 绕过 `__init__.py` 链
- 功能变更配套测试；真实环境功能回归由用户手动发起（AI 不主动跑平台用例）

## 代码风格

- 所有用户可见输出与命令字符串用中文（如"闭关"、"突破"）
- 运行时代码非 dunder 函数/类均有 docstring：**新代码用英文 Google 风格**（存量中文
  保留，不强制改写）；main.py 路由方法 docstring 固定格式
  `"""Command 「指令名」- 描述; routes to xxx_handler.handle_yyy."""`
- 修改函数行为时同步更新 docstring（docstring 与实现不一致视为 bug）
- 行内注释解释"为什么"而非复述代码：数值公式/阈值必须注明出处（config 键或
  design_docs 引用）；平台/框架陷阱的 workaround 必须注释；改动涉及存量过时注释
  一并修正（过时注释与过时 docstring 同视为 bug）

## 版本更新 checklist（功能/修复后必做）

1. `metadata.yaml` 的 `version`
2. `README.md` 更新日志（末尾追加）
3. `handlers/misc_handler.py` 的 `/修仙帮助` 文本
4. 数据库变更 → `data/migration.py` 迁移版本
5. 影响玩法 → 同步 `design_docs/`（见下）

## 设计文档同步义务（玩法变更必做）

- 任何影响玩法的改动（数值、机制、战斗、技能、成长曲线、掉落/概率）都必须在
  `design_docs/` 记录或修正（内容设计 → content-design/；数值框架 → attribute-growth/
  、level-exp-curve/；整体 → current-design-report.md；新资料登记 → README.md 资料清单）
- **内容设计先行**：可配置的游戏内容（文案、数值、事件、悬赏、秘境、敌人等）一律先
  在 design_docs/ 完成设计并经用户确认，禁止直接改 `config/*.json`；导入走
  `scripts/sync_content_to_config.py`（预算 + 叙事 lint 双闸门）
- 未知项按"影响玩法"处理；纯 bug 修复（行为与设计意图不变）不要求
- 新变更提案流程：**Trellis 任务闭环**（trellis task create → PRD 于
  `.trellis/tasks/`）；`openspec/specs/`（16 篇）保留为只读历史契约，不再新增 change

## Issue 追踪

- 一律用 **bd（beads）**：`bd create "issue" --description=... -t bug|feature|task
  -p 0-4 --json`；禁止 markdown TODO 与外部 issue 追踪器；程序化使用加 `--json`

## 禁止模式（Forbidden）

- ❌ 绕过 BusyState 手写忙碌状态双层（见 database-guidelines）
- ❌ 绕过 CM 自管事务 / 块内残留裸 commit
- ❌ handler 再包状态符前缀（服务层已自带）
- ❌ 在 handler/manager 自构造 core 服务
- ❌ 用 `requests`（必须 aiohttp/httpx 等异步库）
- ❌ 直接改 `config/*.json` 填内容（必须先 design_docs + 用户确认）