# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

## 本仓库（bd）的落地说明

本仓库词表与默认完全一致，**未在远程创建任何标签**（tracker 是本地 bd，非 GitHub/GitLab）。
bd 落地时近似表达式见 `docs/agents/issue-tracker.md` 的「Triage 状态落地的近似表达」节：
`bd set-state` / `bd tag` / `bd label`；triage 语义 → bd 类型优先用
`bd create -t bug|feature|task`。