# Issue tracker: bd (beads)

本仓库的 issue 追踪走 **bd (beads)** —— 本地 JSONL 文件数据库（`.beads/`），由 `bd` CLI
操作。项目硬约束（AGENTS.md）：**一律用 bd，禁止 markdown TODO 与外部 issue 追踪器**
（GitHub Issues 等）——因此本仓库不接 `gh` / `glab`。

## Conventions

- 程序化/脚本调用一律加 `--json`
- 类型与优先级：`bd create "<title>" --description="<details>" -t bug|feature|task -p 0-4 --json`
- 依赖关系用 `discovered-from`（`bd link <id> <dep-id>`）
- 状态流转：`bd update <id> --claim --json`（认领）、`bd close <id> --reason "<原因>" --json`（关闭）、`bd reopen <id>`（重开）
- 快速捕获：`bd q "<标题>"` 只输出 ID
- 查询：`bd list` / `bd show <id> --json` / `bd search "<文本>"` / `bd query "<表达式>"` / `bd count`
- 其余能力：`bd label` / `bd tag` / `bd set-state` / `bd note` / `bd comment` / `bd priority`

## When a skill says "publish to the issue tracker"

运行 `bd create "<title>" --description="<details>" -t <type> -p <priority> --json`，
用返回的 `issue_id` 作为唯一引用；需要依赖时用 `bd link` 声明。

## When a skill says "fetch the relevant ticket"

运行 `bd show <id> --json`（按 ID）或 `bd search` / `bd query`（定位后 show）。

## Triage 状态落地的近似表达

bd 无原生 label 机制；triage 五角色用 `bd set-state` / `bd tag`（或用 `bd label` 管理的
词表）近似表达，语义映射见 `triage-labels.md`。