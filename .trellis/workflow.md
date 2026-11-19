# Development Workflow

---

## Core Principles

1. **Plan before code** — figure out what to do before you start
2. **Specs injected, not remembered** — guidelines are injected via hook/skill, not recalled from memory
3. **Persist everything** — research, decisions, and lessons all go to files; conversations get compacted, files don't
4. **Incremental development** — one task at a time
5. **Capture learnings** — after each task, review and write new knowledge back to spec

---

## Trellis System

### Developer Identity

On first use, initialize your identity:

```bash
python3 ./.trellis/scripts/init_developer.py <your-name>
```

Creates `.trellis/.developer` (gitignored) + `.trellis/workspace/<your-name>/`.

### Spec System

`.trellis/spec/` holds coding guidelines organized by package and layer.

- `.trellis/spec/<package>/<layer>/index.md` — entry point with **Pre-Development Checklist** + **Quality Check**. Actual guidelines live in the `.md` files it points to.
- `.trellis/spec/guides/index.md` — cross-package thinking guides.

```bash
python3 ./.trellis/scripts/get_context.py --mode packages   # list packages / layers
```

**When to update spec**: new pattern/convention found · bug-fix prevention to codify · new technical decision.

### Task System

Every task has its own directory under `.trellis/tasks/{MM-DD-name}/` holding `task.json`, `prd.md`, optional `design.md`, optional `implement.md`, optional `research/`, and context manifests (`implement.jsonl`, `check.jsonl`) for sub-agent-capable platforms.

```bash
# Task lifecycle
python3 ./.trellis/scripts/task.py create "<title>" --description "<what it delivers>" [--slug <name>] [--parent <dir>]
python3 ./.trellis/scripts/task.py start <name>          # set active task (session-scoped when available)
python3 ./.trellis/scripts/task.py current --source      # show active task and source
python3 ./.trellis/scripts/task.py finish                # clear active task (triggers after_finish hooks)
python3 ./.trellis/scripts/task.py archive <name>        # move to archive/{year-month}/
python3 ./.trellis/scripts/task.py list [--mine] [--status <s>]
python3 ./.trellis/scripts/task.py list-archive

# Code-spec context (injected into implement/check agents via JSONL).
# `implement.jsonl` / `check.jsonl` are seeded (empty) on `task create` for sub-agent-capable
# platforms; the AI registers context pointers (spec / tickets / research paths from the Matt
# `to-spec` → `to-tickets` flow) during planning. `validate` fails
# and `start` refuses while a seeded manifest is still empty — sub-agents would run with
# zero spec context. Pass `start --allow-empty-context` when that is intentional.
python3 ./.trellis/scripts/task.py add-context <name> <action> <file> <reason>
python3 ./.trellis/scripts/task.py list-context <name> [action]
python3 ./.trellis/scripts/task.py validate <name>

# Task metadata
python3 ./.trellis/scripts/task.py set-branch <name> <branch>
python3 ./.trellis/scripts/task.py set-base-branch <name> <branch>    # PR target
python3 ./.trellis/scripts/task.py set-scope <name> <scope>

# Hierarchy (parent/child)
python3 ./.trellis/scripts/task.py add-subtask <parent> <child>
python3 ./.trellis/scripts/task.py remove-subtask <parent> <child>

# PR creation
python3 ./.trellis/scripts/task.py create-pr [name] [--dry-run]
```

> Run `python3 ./.trellis/scripts/task.py --help` to see the authoritative, up-to-date list.

**Current-task mechanism**: `task.py create` creates the task directory and (when session identity is available) auto-sets the per-session active-task pointer so the planning breadcrumb fires immediately. `task.py start` writes the same pointer (idempotent if already set) and flips `task.json.status` from `planning` to `in_progress`. State is stored under `.trellis/.runtime/sessions/`. If no context key is available from hook input, `TRELLIS_CONTEXT_ID`, or a platform-native session environment variable, there is no active task; `task.py start` then runs in degraded mode (status flips, pointer is not persisted). Kimi Code exports no session id to Bash, so prefix every `task.py` call with `TRELLIS_CONTEXT_ID=<id>` there (the optional Kimi UserPromptSubmit hook prints the id). `task.py finish` deletes the current session file (status unchanged). `task.py archive <task>` writes `status=completed`, moves the directory to `archive/`, and deletes any runtime session files that still point at the archived task.

### Workspace System

Records every AI session for cross-session tracking under `.trellis/workspace/<developer>/`.

- `journal-N.md` — session log. **Max 2000 lines per file**; a new `journal-(N+1).md` is auto-created when exceeded.
- `index.md` — personal index (total sessions, last active).

```bash
python3 ./.trellis/scripts/add_session.py --title "Title" --commit "hash" --summary "Summary"
```

### Context Script

```bash
python3 ./.trellis/scripts/get_context.py                            # full session runtime
python3 ./.trellis/scripts/get_context.py --mode packages            # available packages + spec layers
python3 ./.trellis/scripts/get_context.py --mode phase --step <X.Y>  # detailed guide for a workflow step
```

---

<!--
  WORKFLOW-STATE BREADCRUMB CONTRACT (read this before editing the tag blocks below)

  The [workflow-state:STATUS] blocks embedded in the ## Phase Index section
  below are the SINGLE source of truth for the per-turn `<workflow-state>`
  breadcrumb that every supported AI platform's UserPromptSubmit hook
  reads. inject-workflow-state.py (Python platforms) and
  inject-workflow-state.js (OpenCode plugin) only parse them — there is no
  fallback dict baked into the scripts after v0.5.0-rc.0.

  STATUS charset: [A-Za-z0-9_-]+. When the hook can't find a tag, it
  degrades to a generic "Refer to workflow.md for current step." line —
  intentionally visible so users notice and fix a broken workflow.md.

  INVARIANT (test/regression.test.ts):
    Every workflow-walkthrough step marked `[required · once]` must have a
    matching enforcement line in its phase's [workflow-state:*] block. The
    breadcrumb is the only per-turn channel; if a mandatory step isn't
    mentioned there, the AI silently skips it (Phase 1 planning gate
    skip and Phase 3.4 commit skip both manifested via this gap).

  TAG ↔ PHASE scoping:
    [workflow-state:no_task]      → no active task; before Phase 1
    [workflow-state:task_error]   → active task record is unreadable; repair it before continuing
    [workflow-state:planning]     → all of Phase 1 (status='planning')
    [workflow-state:planning-inline] → Codex inline variant of Phase 1
    [workflow-state:in_progress]  → Phase 2 + Phase 3.2-3.4
                                    (status stays 'in_progress' from
                                    task.py start until task.py archive)
    [workflow-state:in_progress-inline] → Codex inline variant of Phase 2/3
    [workflow-state:completed]    → currently DEAD: cmd_archive flips
                                    status and moves the dir in the same
                                    call, so the resolver loses the
                                    pointer (block kept for a future
                                    explicit in_progress→completed
                                    transition)

  Editing checklist:
    - When you change a [workflow-state:STATUS] block, also check the
      matching phase's `[required · once]` walkthrough steps for sync
    - Run `trellis update` after editing to push the new bodies to
      downstream user projects (block-level managed replacement)
    - Full runtime contract:
      .trellis/spec/cli/backend/workflow-state-contract.md
-->

## Phase Index

```
Phase 1: Plan    → classify, get task-creation consent, then write planning artifacts
Phase 2: Execute → implement only after task status is in_progress
Phase 3: Finish  → verify, update spec, commit, and wrap up
```

### Request Triage

- Inline task (read-only Q&A, code explanation, local config or copy tweak, single-file or root-cause-clear fix): handle directly with minimal verification — do not ask to create a Trellis task. Inline work never gets a task card (host global rule: only durable / multi-decision work enters the board).
- Simple conversation or small task (not clearly inline): ask only whether this turn should create a Trellis task. If the user says no, skip Trellis for this session.
- Complex task: ask whether you may create a Trellis task and enter planning. If the user says no, do not do broad inline implementation; explain, clarify scope, or suggest a smaller split.
- User approval to create a task is not approval to start implementation. Planning still happens first — and planning is **Matt-owned**: load `grill-with-docs` (installed at `~/.agents/skills/`; it drives the `grilling` interview primitive and leaves a `GLOSSARY.md` / ADR paper trail) and interrogate the user until requirements, scope, acceptance criteria, and key decisions are agreed before any planning artifact is written.
- Incoming bug report or external issue (a raw report you did not create) -> load `triage`; the project's issue tracker stays bd, so triage classifies and the Trellis task carries the work.
- Skill routing is not memory: when the right Matt skill is not obvious, load `ask-matt` and route from its map. Some skills it names are not installed here — map a missing one to its installed fallback (`/retro` → `trellis-update-spec`, `/pr` → skip) instead of inventing a step.

### Planning Artifacts

- `prd.md` — requirements, constraints, and acceptance criteria. Do not put technical design or execution checklists here.
- `design.md` — technical design for complex tasks: boundaries, contracts, data flow, tradeoffs, compatibility, rollout / rollback shape.
- `implement.md` — execution plan for complex tasks: ordered checklist, validation commands, review gates, and rollback points.
- `implement.jsonl` / `check.jsonl` — spec and research manifests for sub-agent context. They do not replace `implement.md`.
- Lightweight tasks may be PRD-only. Complex tasks must have `prd.md`, `design.md`, and `implement.md` before `task.py start`.

**Single-source rule (every planning artifact, every task-tree level)**

- **One fact, one home.** A fact — a formula, threshold, config key, schema field, contract, or decision — is written in full in exactly one artifact. Every other place references it by path and section (`see <path> §<n>`) instead of restating it.
- **Task trees split the ownership.** The parent owns the cross-child invariants and the source requirement set; each child owns its own contracts. Keep the map in the parent's `design.md` as `| fact | owner | referrers |`.
- **Acceptance criteria may restate a literal.** An AC needs the value to be testable, so a threshold or key name may appear again there. Prose may not: no second full statement of the same fact outside an AC.
- **Evidence is not a fact.** `file:line` references, grep output, and code listings belong in `{TASK_DIR}/research/` or in a check script; artifacts carry stable anchors instead (symbol, config key, command name). Line numbers rot, and a stale anchor is worse than none.
- **One tracker.** The task directory is the tracker for this flow: `prd.md` is the spec, child tasks are the tickets. Do not publish a second copy to bd or an issue tracker.

### Parent / Child Task Trees

Use a parent task when one user request contains several independently verifiable deliverables. The parent task owns the source requirement set, the task map, cross-child acceptance criteria, and final integration review; it normally should not be the implementation target unless it also has direct work.

Use child tasks for deliverables that can be planned, implemented, checked, and archived independently. Parent/child structure is not a dependency system: if one child must wait for another, write that ordering in the child `prd.md` / `implement.md` and keep each child's acceptance criteria testable.

Create new children with `task.py create "<title>" --description "<ticket body>" --slug <name> --parent <parent-dir>`. Link existing tasks with `task.py add-subtask <parent> <child>`, and unlink mistakes with `task.py remove-subtask <parent> <child>`.

<!-- Per-turn breadcrumb: shown when there is no active task (before Phase 1) -->

[workflow-state:no_task]
No active task. First classify the current turn and ask for task-creation consent before creating any Trellis task.
Simple conversation / small task: ask only whether this turn should create a Trellis task. If the user says no, skip Trellis for this session.
Complex task: ask the user if you can create a Trellis task and enter the planning phase. If the user says no, explain, clarify scope, or suggest a smaller split. Once consent is yes, grill until requirements, scope, and key decisions are agreed (1.1), then create the task in 1.0.
[/workflow-state:no_task]

<!-- Per-turn breadcrumb: shown when the active task record cannot be read. -->

[workflow-state:task_error]
The active task record could not be read. Do not create or activate another task.
Inspect the task directory named above and repair its task.json. It must be a valid JSON object with a non-empty status.
Preserve existing task fields and artifacts. If the correct status cannot be determined safely, ask the user before reconstructing the record.
[/workflow-state:task_error]

### Phase 1: Plan
- 1.0 Create task `[required · once]` (only after task-creation consent *and* the 1.1 grill agreement)
- 1.1 Requirement exploration `[required · repeatable]` (Matt-owned: `grill-with-docs` → `to-spec` → `to-tickets`; `prd.md`; complex tasks also need `design.md` + `implement.md`)
- 1.2 Research `[optional · repeatable]`
- 1.3 Configure context `[required · once]` — Claude Code, Cursor, OpenCode, Codex, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, Pi, Oh My Pi, ZCode, Snow, Reasonix, Grok, Kimi Code (sub-agent-dispatch platforms only; inline platforms skip)
- 1.4 Activate task `[required · once]` (review gate, then `task.py start`; status → in_progress)
- 1.5 Completion criteria

<!-- Per-turn breadcrumb: shown throughout Phase 1 (status='planning') -->

[workflow-state:planning]
Load `grill-with-docs` (Matt; stateful in a repo) and grill until details, scope, and key decisions are agreed; then `to-spec` writes `prd.md` / `design.md` and `to-tickets` yields child tasks. Stay in planning.
Lightweight: `prd.md` can be enough. Complex: finish `prd.md`, `design.md`, and `implement.md`; ask for review before `task.py start`.
Multi-deliverable scope: consider a parent task plus independently verifiable child tasks; dependencies must be written in child artifacts, not implied by tree position.
Sub-agent mode: `to-spec` wrote the spec and `to-tickets` split it into child tasks with blocking edges; register spec/research paths as context pointers in `implement.jsonl` / `check.jsonl` before start.
[/workflow-state:planning]

<!-- Per-turn breadcrumb: shown throughout Phase 1 when codex.dispatch_mode=inline.
     Codex-only opt-in alternate to [workflow-state:planning]. The main agent
     edits code directly in Phase 2, so jsonl curation is skipped —
     the inline workflow loads `trellis-before-dev` instead of injecting JSONL
     into a sub-agent. -->

[workflow-state:planning-inline]
Load `grill-with-docs` (Matt; stateful in a repo) and grill until details, scope, and key decisions are agreed; then `to-spec` writes `prd.md` / `design.md` and `to-tickets` yields child tasks. Stay in planning.
Lightweight: `prd.md` can be enough. Complex: finish `prd.md`, `design.md`, and `implement.md`; ask for review before `task.py start`.
Multi-deliverable scope: consider a parent task plus independently verifiable child tasks; dependencies must be written in child artifacts, not implied by tree position.
Inline mode: skip jsonl curation; `to-spec` / `to-tickets` still run and child tasks carry the ticket graph; Phase 2 reads artifacts/specs via `trellis-before-dev` and Matt skills.
[/workflow-state:planning-inline]

### Phase 2: Execute
- 2.1 Implement `[required · repeatable]`
- 2.2 Quality check `[required · repeatable]`
- 2.3 Rollback `[on demand]`

<!-- Per-turn breadcrumb: shown while status='in_progress'.
     Scope: all of Phase 2 + Phase 3.2-3.4 (status stays 'in_progress' from
     task.py start until task.py archive; only archive flips it). The body
     therefore must cover every required step from implementation through
     commit, including Phase 3.3 spec update and Phase 3.4 commit. -->

Sub-agent dispatch protocol applies to all platforms and all Trellis-dispatched sub-agents (`trellis-implement` / `trellis-check` / `trellis-research`), including native Codex `SubagentStart` context injection with child-side pull fallback, class-2 Gemini/Qoder/Copilot/Reasonix/Trae/Grok/Kimi Code, and hook-backed ZCode/Snow: every dispatch prompt starts with `Active task: <task path from task.py current>` before role-specific instructions. Matt skills that dispatch their own internal sub-agents (e.g. `implement-spec`) are out of scope — they use context pointers, not `Active task:`. On Grok Build, use `spawn_subagent` with `subagent_type` set to the Trellis agent name (e.g. `trellis-implement`). On Kimi Code, dispatch the project custom agents `trellis-implement` / `trellis-check` / `trellis-research` (installed by `trellis init --kimi` under `.kimi-code/agents/`); the built-in `coder` / `explore` are fallbacks only, and `explore` is read-only so it cannot persist research. `AgentSwarm` runs only after the user enables swarm mode and shares the working tree — no worktree isolation — so serialize implementers unless the tickets touch disjoint files. On Pi / Oh My Pi there is no concurrent sub-agent: `trellis_subagent` queues tasks that execute **one at a time** in FIFO order, so a dispatch is a serial turn, not a parallel worker.

[workflow-state:in_progress]
Tools: `trellis-research` is a sub-agent type; `trellis-update-spec` is a skill. Implementation and review are Matt skills (`implement` / `implement-spec` + `tdd` / `code-review`) loaded from the skill catalog, or Trellis agents (`trellis-implement` / `trellis-check`) on platforms that dispatch them.
Flow: implement (`implement` / `implement-spec` + `tdd`, or `trellis-implement`) -> review (`code-review`, or `trellis-check`) -> `trellis-update-spec` -> commit (Phase 3.4) -> `/trellis:finish-work`.
Parallel dispatch is allowed (the host rule exempts `implement-spec`); pick frontier-ready tickets and dispatch implementers concurrently. Sub-agent self-exemption: a spawned implementer must not spawn further implement/review agents — dispatch is main-session only.
Dispatch prompt starts with `Active task: <task path from task.py current>`. Read context: jsonl pointer entries -> `prd.md` -> `design.md if present` -> `implement.md if present` -> the parent task's `design.md` / `prd.md` when `task.json` declares a `parent` (shared contracts are stated there once).
[/workflow-state:in_progress]

<!-- Per-turn breadcrumb: shown while status='in_progress' when
     codex.dispatch_mode=inline. Codex-only opt-in alternate to
     [workflow-state:in_progress]. The main session edits code directly
     instead of dispatching sub-agents. -->

[workflow-state:in_progress-inline]
Flow: `trellis-before-dev` -> Matt implement (`implement` / `implement-spec` + `tdd`) -> `code-review` -> validation -> `trellis-update-spec` -> commit (Phase 3.4) -> `/trellis:finish-work`.
Do not dispatch implement/check sub-agents in inline mode (parallel `implement-spec` still allowed under the host exemption).
Read context: `prd.md` -> `design.md if present` -> `implement.md if present` -> the parent task's `design.md` / `prd.md` when `task.json` declares a `parent`, plus relevant spec/research loaded by skills.
[/workflow-state:in_progress-inline]

### Phase 3: Finish
- 3.2 Debug retrospective `[on demand]`
- 3.3 Spec update `[required · once]`
- 3.4 Commit changes `[required · once]`
- 3.5 Wrap-up reminder

> Note: step 3.1 was folded into 2.2 (last-iteration full-scope check) and 3.4 (commit preamble). Numbering kept stable to avoid breaking external references.

<!-- Per-turn breadcrumb: shown while status='completed'.
     Currently DEAD in normal flow: cmd_archive writes status='completed' in
     the same call that moves the task dir to archive/, so the active-task
     resolver loses the pointer and the hook never fires on archived tasks.
     Block preserved for a future status-transition redesign (e.g. an
     explicit in_progress→completed command). Edit through the same spec
     channel as the live blocks. -->

[workflow-state:completed]
Code committed. Run `/trellis:finish-work`; if dirty, return to Phase 3.4 first.
[/workflow-state:completed]

### Rules

1. Identify which Phase you're in, then continue from the next step there
2. Run steps in order inside each Phase; `[required]` steps can't be skipped
3. Phases can roll back (e.g., Execute reveals a prd defect → return to Plan to fix, then re-enter Execute)
4. Steps tagged `[once]` are skipped if the output already exists; don't re-run
5. Artifact presence informs the next step; missing `design.md` / `implement.md` is valid for lightweight tasks and incomplete planning for complex tasks.

### Skill Routing (Matt)

The Matt catalog is large and half of it is not installed here, so route from this table instead of guessing, and load `ask-matt` only when none of these rows fits. This table is the workflow's own contract: it names only skills this flow actually uses.

| Intent | Skill |
| --- | --- |
| Requirements unclear / new feature | `grill-with-docs` (repo working dir; drives the `grilling` primitive) |
| Turn the agreed conversation into a spec | `to-spec` (tracker override: persist as `{TASK_DIR}/prd.md`) |
| Split the spec into tickets | `to-tickets` (tracker override: materialize as child tasks) |
| Module / interface shape question | `codebase-design` |
| Domain vocabulary or an irreversible decision | `domain-modeling` |
| Reading legwork, third-party API facts | `research` -> `{TASK_DIR}/research/` |
| A bug that resists a first look | `diagnosing-bugs` |
| Incoming bug report / external issue | `triage` |
| Write production code | `implement` (one ticket) / `implement-spec` (whole graph, frontier-parallel) |
| Per-slice red-green | `tdd` |
| Review a diff | `code-review` |
| None of the above fits | `ask-matt`, then map any skill it names but does not install here to an installed fallback |

`implement` vs `implement-spec`: use `implement` for one ticket (or a couple) worked in the current context; use `implement-spec` when the ticket graph has several frontier-ready tickets and you want them built in parallel on one integration branch. On Pi / Oh My Pi `implement-spec` degrades to serial: one ticket at a time, mainline gating each result.

### Active Task Routing

When a user request matches one of these intents inside an active task, route first, then load the detailed phase step if needed.

[Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]

- Planning or unclear requirements -> Matt `grill-with-docs` → `to-spec` → `to-tickets` (grill until the plan's details, scope, and key decisions are agreed before any task is created).
- `in_progress` implementation/check -> Matt: `implement` / `implement-spec` (ticket frontier) + `tdd`; review via `code-review`.
- Repeated debugging -> `trellis-break-loop`; spec updates -> `trellis-update-spec`.
- Engineering execution details -> mattpocock skills as needed (`tdd`, `diagnosing-bugs`, `code-review`, `prototype`, `research`, `grilling`, ...; installed at `~/.agents/skills/`).

[/Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]
[Pi, Oh My Pi]

- Planning or unclear requirements -> Matt `grill-with-docs` → `to-spec` → `to-tickets` (same flow; the skills are pi-local copies under `~/.pi/agent/skills/`).
- `in_progress` implementation/check -> Trellis `trellis-implement` with Matt `tdd` discipline, executed through the pi task queue: **one task at a time**, mainline gates each result.
- Repeated debugging -> `trellis-break-loop`; spec updates -> `trellis-update-spec`.
- Engineering execution details -> mattpocock skills as needed (`tdd`, `diagnosing-bugs`, `code-review`, `prototype`, `research`, `grilling`, ...; pi-local copies at `~/.pi/agent/skills/`).

[/Pi, Oh My Pi]

[Kimi Code]

- Planning or unclear requirements -> Matt `grill-with-docs` → `to-spec` → `to-tickets` (Kimi-local copies under `~/.kimi-code/skills/`; shared install under `~/.agents/skills/`).
- `in_progress` implementation/check -> dispatch the project custom agents `trellis-implement` (with Matt `tdd` discipline) and `trellis-check` from `.kimi-code/agents/`; the stock agents read `implement.jsonl` / `check.jsonl` themselves. Subagents must not commit; the mainline commits at Phase 3.4. If `.kimi-code/agents/` is missing (a project initialized only with `--dsh`), run `trellis init --kimi` in the project root to add the Kimi entry points.
- Research -> `trellis-research` custom agent (writes to `{TASK_DIR}/research/`). The built-in `explore` agent is read-only and cannot persist a report; use it only for throwaway lookups.
- Repeated debugging -> `trellis-break-loop`; spec updates -> `trellis-update-spec`.
- Engineering execution details -> mattpocock skills as needed (`tdd`, `diagnosing-bugs`, `code-review`, `prototype`, `research`, `grilling`, ...; available at `~/.agents/skills/` (shared) or `~/.kimi-code/skills/` (Kimi-local copies)).
- Session identity -> Kimi exports no session id to Bash. Prefix `task.py` with `TRELLIS_CONTEXT_ID=<id>` (the optional UserPromptSubmit hook prints one); otherwise `task.py start` runs degraded and `task.py current` returns nothing.

[/Kimi Code]


[codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

- Planning or unclear requirements -> Matt `grill-with-docs` → `to-spec` → `to-tickets` (grill until the plan's details, scope, and key decisions are agreed before any task is created).
- Before editing -> `trellis-before-dev`; implement via Matt (`implement` / `implement-spec` + `tdd`); after editing -> `code-review`.
- Repeated debugging -> `trellis-break-loop`; spec updates -> `trellis-update-spec`.
- Engineering execution details -> mattpocock skills as needed (`tdd`, `diagnosing-bugs`, `code-review`, `prototype`, `research`, `grilling`, ...; available to DeepSeek Harness at `~/.agents/skills/`).
- Host task board: cards with host-managed lifecycle (prompt/description/resume/archive) stay under host control; a Trellis task provides the engineering method for the same work. Do not duplicate card bookkeeping into `.trellis/tasks/` and do not fight the host card state.

[/codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

### Guardrails

- Task creation approval is not implementation approval; implementation waits for `task.py start` after artifact review.
- PRD-only is valid for lightweight tasks; complex tasks need `design.md` + `implement.md`.
- Planning must be persisted to task artifacts; checks must run before reporting completion.
- One owner per stage; only durable / multi-decision work gets a task (host global rule).
- Commits need user confirmation — Phase 3.4's one-shot plan already matches the host rule (local commit only on explicit user request; never push without explicit request). Trellis tooling's own auto-commits (journal / task archive) are toolchain behavior, not a substitute for that confirmation.

### Loading Step Detail

At each step, run this to fetch detailed guidance:

```bash
python3 ./.trellis/scripts/get_context.py --mode phase --step <step>
# e.g. python3 ./.trellis/scripts/get_context.py --mode phase --step 1.1
```

---

## Phase 1: Plan

Goal: classify the request, get task-creation consent when a task is needed, and produce the planning artifacts required before implementation.

#### 1.0 Create task `[required · once]`

**Prerequisite — grill first.** The host global plan gate (`~/.dsh/AGENTS.md` on DSH, `~/.kimi-code/AGENTS.md` on Kimi Code) forbids creating a task or writing a plan document before `grill-with-docs` (or the `grilling` / `grill-me` primitive it drives) has settled requirements, scope, and key decisions with the user. So the order is: task-creation consent → 1.1 grill → agreement → this step. If requirements are not agreed yet, run 1.1's Grill step now and come back here; the task directory is bookkeeping for the agreed plan, not the place where planning starts.

Create the task directory only after task-creation consent *and* that agreement. The command sets status to `planning`, writes `task.json`, creates a default `prd.md`, and auto-targets the new task when session identity is available:

```bash
python3 ./.trellis/scripts/task.py create "<task title>" --description "<what this task delivers>" --slug <name>
```

`--description` is required (a task with an empty description is refused at archive). `--slug` is the human-readable name only. Do **not** include the `MM-DD-` date prefix; `task.py create` adds that prefix automatically.

For task trees, create the parent task first and then create each child with `--parent <parent-dir>` and its own `--description`. Do not start the parent just because children exist; start the child that owns the next independently verifiable deliverable.

After this command succeeds, the per-turn breadcrumb auto-switches to `[workflow-state:planning]`, telling the AI to stay in planning. On Kimi Code there is no per-turn hook and no session id in Bash: pass `TRELLIS_CONTEXT_ID=<id>` on the command (or accept degraded mode) and keep the planning state in the conversation yourself.

Run only `create` here — do not also run `start`. `start` flips status to `in_progress`, which switches the breadcrumb to the implementation phase before planning artifacts are reviewed. Save `start` for step 1.4.

Skip when `python3 ./.trellis/scripts/task.py current --source` already points to a task.

#### 1.1 Requirement exploration `[required · repeatable]`

Planning is **Matt-owned**; Trellis owns the task lifecycle and the artifact paths. Run the Matt flow in this order and persist its output into the artifacts:

1. **Grill** — load `grill-with-docs` (installed at `~/.agents/skills/`). It runs the `grilling` interview primitive in rounds — every question whose prerequisites are settled, numbered, each with a recommended answer — and keeps a paper trail (`GLOSSARY.md`, ADRs), which is why it beats the stateless `grill-me` inside a repo. Never persist `prd.md` from assumptions; update the artifacts after each confirmed answer. If the task does not exist yet, run this grill *before* 1.0 creates it — 1.0 is blocked on the agreement, not the other way round — and re-run it whenever requirements change.
2. **Research** — step 1.2. Prefer reading the codebase over asking the user.
3. **Spec** — load `to-spec`; it synthesizes the agreed conversation without re-interviewing. **Tracker override:** the Trellis task directory is the tracker — persist the spec as `{TASK_DIR}/prd.md`, and for complex tasks turn the spec's Implementation Decisions / Testing Decisions / contract sections into `{TASK_DIR}/design.md`. Do not publish a second copy elsewhere. Keep `to-spec`'s section skeleton and add the **Acceptance Criteria** section it lacks.
4. **Tickets** — load `to-tickets`; it splits the spec into tracer-bullet tickets with declared blocking edges. **Materialize each ticket as a child task** (`task.py create --description "<ticket body>" --parent`) instead of `.scratch/` files: the child's `prd.md` carries the ticket body plus its blocking edges. Tickets are the task graph — implement in frontier order; a ticket whose blockers are all done is ready. Apply the single-source rule from "Planning Artifacts": a child that shares a fact with a sibling points at the owner instead of restating it.
5. **Design depth (optional)** — `codebase-design` for interface/module-shape questions (module, interface, depth, seam); `domain-modeling` for domain vocabulary and irreversible decisions (ADR).
6. **Router** — when the right skill is not obvious, load `ask-matt` and route from its map; map any skill it names that is not installed to an installed fallback.

`trellis-brainstorm` is **retired from routing**: its artifact rules, convergence gate, and quality bar now live in this workflow (1.1, "Planning Artifacts", 1.4). Its skill file stays on disk untouched.

When considering a parent/child split:
- Use a parent task when one request contains several independently verifiable deliverables.
- Parent tasks own source requirements, child-task mapping, cross-child acceptance criteria, and final integration review.
- Child tasks own actual deliverables that can be planned, implemented, checked, and archived independently.
- Parent/child structure is not a dependency system. If child B depends on child A, put a pointer in child B (`upstream contract: .trellis/tasks/<child-A>/design.md §<n>`) and write the ordering in `implement.md`; do not copy A's facts into B.
- Shared facts live in the parent. A child artifact that needs one writes a path pointer, never a second full statement — the implementer reads parent artifacts before the child's own.
- Start the child task that owns the next deliverable. Do not start the parent unless the parent itself has direct implementation work.

Return to this step whenever requirements change and revise the relevant artifact.

#### 1.2 Research `[optional · repeatable]`

Research can happen at any time during requirement exploration. It isn't limited to local code — you can use any available tool (MCP servers, skills, web search, etc.) to look up external information, including third-party library docs, industry practices, API references, etc.

**Method**: load the Matt `research` skill — it delegates the reading to a background agent and writes one cited Markdown file. Point that file at `{TASK_DIR}/research/`; a finding that stays only in the chat is lost at the next compaction.

[Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]

Spawn the research sub-agent:

- **Agent type**: `trellis-research`
- **Task description**: Research <specific question>
- **Key requirement**: Research output MUST be persisted to `{TASK_DIR}/research/`

[/Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]
[Pi, Oh My Pi]

Queue a research task with `trellis_subagent` (agent `trellis-research`, single mode, self-contained prompt — a fresh task does not see this conversation). It runs **serially**, one task at a time, persists findings to `{TASK_DIR}/research/`, and reports the file paths next turn. Cheap lookups (read/grep/fetch) are faster inline; queue only the reading legwork that would otherwise flood the context.

[/Pi, Oh My Pi]

[Kimi Code]

Dispatch the project custom agent `trellis-research` (`subagent_type: trellis-research`, installed by `trellis init --kimi`); its prompt starts with `Active task: <task path>` and it persists the report to `{TASK_DIR}/research/`. Do not use the built-in `explore` agent for this — it is read-only and cannot write the report. The Matt `research` skill is the fallback when you want its cited-Markdown format.

[/Kimi Code]


[codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

Override the general Method: do the research in the main session directly and write findings into `{TASK_DIR}/research/`. (The Matt `research` skill delegates to a background agent; on this pull-based platform, keep the work in the main session.)

[/codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

**Research artifact conventions**:
- One file per research topic (e.g. `research/auth-library-comparison.md`)
- Record third-party library usage examples, API references, version constraints in files
- Note relevant spec file paths you discovered for later reference

Brainstorm and research can interleave freely — pause to research a technical question, then return to talk with the user.

**Key principle**: Research output must be written to files, not left only in the chat. Conversations get compacted; files don't.

#### 1.3 Configure context `[required · once]`

[Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]

Curate `implement.jsonl` and `check.jsonl` so the Phase 2 implementers get the right spec/tickets/research context — these entries are exactly the Matt context-pointer list. These files were seeded on `task create` with a single self-describing `_example` line; register real entries produced by the `to-spec` / `to-tickets` flow (spec files, ticket child tasks, research notes).

**Location**: `{TASK_DIR}/implement.jsonl` and `{TASK_DIR}/check.jsonl` (already exist).

**Format**: one JSON object per line — `{"file": "<path>", "reason": "<why>"}`. Paths are repo-root relative.

**What to put in**:
- **Spec files** — `.trellis/spec/<package>/<layer>/index.md` and any specific guideline files (`error-handling.md`, `conventions.md`, etc.) relevant to this task
- **Ticket graph** — the child-task list from `to-tickets` (paths + blocking edges), so implementers see which tickets are frontier-ready
- **Research files** — `{TASK_DIR}/research/*.md` that the sub-agent will need to consult

**What NOT to put in**:
- Code files (`src/**`, `packages/**/*.ts`, etc.) — those are read by the sub-agent during implementation, not pre-registered here
- Files you're about to modify — same reason

**Split between the two files**:
- `implement.jsonl` → specs + research the implement sub-agent needs to write code correctly
- `check.jsonl` → specs for the check sub-agent (quality guidelines, check conventions, same research if needed)

These manifests do not replace `implement.md`. `implement.md` is the human-readable execution plan for a complex task; jsonl files only list context files to inject or load.

**How to discover relevant specs**:

```bash
python3 ./.trellis/scripts/get_context.py --mode packages
```

Lists every package + its spec layers with paths. Pick the entries that match this task's domain.

**How to append entries**:

Either edit the jsonl file directly in your editor, or use:

```bash
python3 ./.trellis/scripts/task.py add-context "$TASK_DIR" implement "<path>" "<reason>"
python3 ./.trellis/scripts/task.py add-context "$TASK_DIR" check "<path>" "<reason>"
```

Delete the seed `_example` line once real entries exist (optional — it's skipped automatically by consumers).

Ready gate: both `implement.jsonl` and `check.jsonl` must contain at least one real `{"file": "...", "reason": "..."}` entry before `task.py start`. The seed `_example` row alone is not ready.

Skip this step only when both files already have real curated entries.

[/Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]
[Pi, Oh My Pi]

Curate `implement.jsonl` and `check.jsonl` exactly as above — a queued pi task reads them from disk, so they are the only context it gets besides its prompt.

[/Pi, Oh My Pi]

[Kimi Code]

Curate `implement.jsonl` and `check.jsonl` exactly as above — the stock `trellis-implement` / `trellis-check` custom agents read them from disk. The dispatch prompt still starts with `Active task: <path>`; the jsonl is context, not a substitute for that line.

[/Kimi Code]


[codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

Skip this step. Context is loaded directly by the `trellis-before-dev` skill in Phase 2.

[/codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

#### 1.4 Activate task `[required · once]`

After artifact review, flip the task status to `in_progress`:

```bash
python3 ./.trellis/scripts/task.py start <task-dir>
```

For lightweight tasks, `prd.md` can be enough. For complex tasks, `prd.md`, `design.md`, and `implement.md` must exist and be reviewed before start. On sub-agent-dispatch platforms, `implement.jsonl` and `check.jsonl` must both have real curated entries before start. Runtime consumers tolerate missing or seed-only manifests for compatibility, but that tolerance is not a planning-ready state.

**Convergence gate (all artifacts)**: before `start`, read `prd.md` -> `design.md` -> `implement.md` once, top to bottom, and fix what the single-source rule forbids:
- the same fact stated twice outside an acceptance criterion;
- a child artifact restating a fact owned by the parent or a sibling instead of pointing at it;
- a `file:line` reference, grep output, or code listing left in an artifact (move it to `research/` or the check script);
- a resolved open question or temporary brainstorm section still standing.

After this command succeeds, the breadcrumb auto-switches to `[workflow-state:in_progress]`, and the rest of Phase 2 / 3 follows.

If `task.py start` reports "Session identity not available" and runs in degraded mode (no context key from hook input, `TRELLIS_CONTEXT_ID`, or a platform-native session env), set `TRELLIS_CONTEXT_ID` before retrying if the platform supports an explicit id. On Kimi Code the optional UserPromptSubmit hook prints the per-session id; DSH and Claude Code export their own session variables.

#### 1.5 Completion criteria

| Condition | Required |
|------|:---:|
| `prd.md` exists | ✅ |
| User confirms task should enter implementation | ✅ |
| `task.py start` has been run (status = in_progress) | ✅ |
| `research/` has artifacts (complex tasks) | recommended |
| `design.md` exists (complex tasks) | ✅ |
| `implement.md` exists (complex tasks) | ✅ |

[Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]

| `implement.jsonl` and `check.jsonl` each contain at least one real curated entry (seed row does not count) | ✅ |

[/Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]
[Pi, Oh My Pi]

| `implement.jsonl` and `check.jsonl` each contain at least one real curated entry (seed row does not count) | ✅ |

[/Pi, Oh My Pi]

[Kimi Code]

| `implement.jsonl` and `check.jsonl` each contain at least one real curated entry (seed row does not count) | ✅ |

[/Kimi Code]


---

## Phase 2: Execute

Goal: turn reviewed planning artifacts into code that passes quality checks.

#### 2.1 Implement `[required · repeatable]`

[Claude Code, Cursor, OpenCode, codex-sub-agent, CodeBuddy, Droid, ZCode, Snow]

Spawn the implement sub-agent:

- **Method**: Matt — `implement-spec` (whole ticket graph, frontier-parallel implementers, one integration branch) or `implement` per ticket; each implementer drives `tdd` red-green per slice
- **Agent type**: `trellis-implement`
- **Task description**: Implement the reviewed task artifacts, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check
- **Dispatch prompt guard**: The prompt MUST start with `Active task: <task path>`, then tell the spawned agent it is already the `trellis-implement` sub-agent and must implement directly, not spawn another `trellis-implement` / `trellis-check`.

The platform hook/plugin auto-handles:
- Reads `implement.jsonl` and injects referenced spec/research files into the agent prompt
- Injects `prd.md`, `design.md` if present, and `implement.md` if present
- For Codex, `SubagentStart` supplies native context injection; the agent profile keeps child-side loading as the fallback

[/Claude Code, Cursor, OpenCode, codex-sub-agent, CodeBuddy, Droid, ZCode, Snow]
[Pi, Oh My Pi]

The main session orchestrates; the pi extension queues the work.

- **Method**: Trellis `trellis-implement` agent with Matt `tdd` discipline (red-green per slice), driven through `trellis_subagent` (prompt starts with `Active task: <task path>`). **One task at a time**: queue it, wait for the result, verify it, then queue the next — do not commit between tasks; Phase 3.4 owns the commit gate. `implement-spec`'s frontier-parallelism does not exist here — N tickets cost N serial turns, so choose the frontier order deliberately and never queue several implement tasks in one reply expecting concurrent work.
- **Shared-tree hazard**: queued tasks share the working tree, and the previous task's changes stay in it. The agent cannot commit (`trellis-implement` forbids it), so every implement prompt must say "leave the tree dirty; do not commit, do not revert". The mainline verifies each result and queues the next task on the same dirty tree; Phase 3.4 commits the accumulated work in one batched plan.
- **Task description**: implement the reviewed artifacts, drive `tdd` red-green per slice, consult `{TASK_DIR}/research/`, run project lint and type-check, report files touched and verification results.
- **Recursion guard**: a queued task must not queue further tasks — dispatch is mainline-only.

[/Pi, Oh My Pi]

[Kimi Code]

Dispatch the project custom agent (installed by `trellis init --kimi`):

- **Method**: `trellis-implement` with Matt `tdd` discipline (red-green per slice). For a whole ticket graph, `implement-spec` is a main-session skill — load it in the main session instead of dispatching this agent.
- **Agent type**: `trellis-implement` (`subagent_type: trellis-implement`, definition at `.kimi-code/agents/trellis-implement.md`). The built-in `coder` is a fallback only when the project has no custom agent; if used, pass the `.kimi-code/skills/trellis-implement/SKILL.md` instructions and the same guards.
- **Dispatch prompt guard**: the prompt MUST start with `Active task: <task path>` and state: implement directly, do not spawn another implement/review agent, do not `git commit` / `git push`, leave the tree dirty.
- **Task description**: implement the reviewed artifacts, drive `tdd` red-green per slice, consult `{TASK_DIR}/research/`, finish by running project lint and type-check.
- **Concurrency**: `Agent` / `AgentSwarm` share the session's working tree; Kimi exposes no worktree option (only `prompt` / `description` / `subagent_type` / `model`), and `AgentSwarm` requires the user to enable swarm mode. Serialize implementers by default. Only swarm tickets that touch disjoint files, and still let the mainline verify each result. Do not let a coder commit — Phase 3.4 owns the commit gate. `Tower` is a separate experimental mode with mission worktrees; do not mix it into this flow.

[/Kimi Code]


[Gemini, Qoder, Copilot, Reasonix, Trae, Grok]

Spawn the implement sub-agent:

- **Method**: Matt — `implement-spec` (whole ticket graph, frontier-parallel implementers, one integration branch) or `implement` per ticket; each implementer drives `tdd` red-green per slice
- **Agent type**: `trellis-implement`
- **Task description**: Implement the reviewed task artifacts, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check
- **Dispatch prompt guard**: The prompt MUST start with `Active task: <task path>`, then explicitly say the spawned agent is already `trellis-implement` and must implement directly without spawning another `trellis-implement` / `trellis-check`.

The pull-based sub-agent definition auto-handles the context load requirement:
- Resolves the active task with `task.py current --source`, then reads `prd.md`, `design.md` if present, and `implement.md` if present
- Reads `implement.jsonl` and requires the agent to load each referenced spec/research file before coding

[/Gemini, Qoder, Copilot, Reasonix, Trae, Grok]

[Kiro]

Spawn the implement sub-agent:

- **Method**: Matt — `implement-spec` (whole ticket graph, frontier-parallel implementers, one integration branch) or `implement` per ticket; each implementer drives `tdd` red-green per slice
- **Agent type**: `trellis-implement`
- **Task description**: Implement the reviewed task artifacts, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check
- **Dispatch prompt guard**: Tell the spawned agent it is already the `trellis-implement` sub-agent and must implement directly, not spawn another `trellis-implement` / `trellis-check`.

The platform prelude auto-handles the context load requirement:
- Reads `implement.jsonl` and injects referenced spec/research files into the agent prompt
- Injects `prd.md`, `design.md` if present, and `implement.md` if present

[/Kiro]

[codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

1. Load the `trellis-before-dev` skill to read project guidelines
2. Load the Matt flow: `implement-spec` (whole ticket graph: frontier-parallel implementers, one integration branch) or `implement` per ticket; drive `tdd` red-green per slice
3. Read `{TASK_DIR}/prd.md`, then `design.md` if present, then `implement.md` if present, plus materials under `{TASK_DIR}/research/`; if `task.json` declares a `parent`, read the parent's `design.md` first — shared contracts are stated there once and only pointed at here
4. Parallel implementers are allowed: the host global rule treats choosing `implement-spec` as explicit opt-in for sub-agents — no extra confirmation needed
5. Implement the code per reviewed artifacts, then run project lint and type-check
6. Do not commit in this step — 3.4 owns the commit gate. If the Matt skill's final step says to commit, skip it and leave the tree dirty. Exception: `implement-spec` commits on its integration branch by design; if you use it, treat those commits as the work commits and skip 3.4's plan (go to 3.5 after verifying the tree is clean).

[/codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

#### 2.2 Quality check `[required · repeatable]`

[Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]

Spawn the review sub-agent:

- **Method**: Matt `code-review` — two axes: Standards (project specs) + Spec (does the change match `prd.md` / `design.md` / tickets)
- **Agent type**: `trellis-check`
- **Task description**: Review all code changes against specs and task artifacts; fix any findings directly; ensure lint and type-check pass
- **Dispatch prompt guard**: The prompt MUST start with `Active task: <task path>`, then tell the spawned agent it reviews/fixes directly, not spawn another review or implement agent.
- **Host review protocol**: give the reviewer detailed file paths, ask it to write temporary verification scripts, and pass the pragmatic principle (only real-world problems, no theoretical edge cases).

The check agent's job:
- Review code changes against specs
- Review code changes against `prd.md`, `design.md` if present, and `implement.md` if present, plus the parent task's `design.md` / `prd.md` when `task.json` declares a `parent` (shared contracts live there, not in the child)
- Auto-fix issues it finds
- Run lint and typecheck to verify

[/Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, ZCode, Snow, Reasonix, Trae, Grok]
[Pi, Oh My Pi]

Queue one review task (`trellis_subagent`, agent `trellis-check`) after the implement result lands. Phase 2.1 leaves the tree dirty, so the agent reviews the working-tree diff itself (`git add -N .` first so new files appear, then `git diff HEAD`); give it the base commit if it needs a range. The agent reads `check.jsonl`, reviews against specs and task artifacts, fixes findings directly, and runs lint/type-check; re-check until green. Commit only at Phase 3.4 — do not commit just to give the reviewer a range. (`code-review` is the main-session alternative when you want a report without fixes.)

[/Pi, Oh My Pi]

[Kimi Code]

Spawn the project custom agent `trellis-check` (`subagent_type: trellis-check`, definition at `.kimi-code/agents/trellis-check.md`). Phase 2.1 leaves the tree dirty, so pass the working-tree diff (`git add -N .` first so new files appear, then `git diff HEAD`); if the work was already committed, use `git diff <base>...HEAD` instead. The agent reads `check.jsonl`, reviews against specs and task artifacts, fixes findings directly, and runs lint/type-check; re-check until green. The mainline commits only at Phase 3.4 — do not commit just to give the reviewer a diff. (`code-review` is the main-session alternative when you want a report without fixes.)

[/Kimi Code]


[codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

Load the `code-review` skill and review the diff on both axes (Standards + Spec). The fixed point is the branch point before 2.1: if 2.1 left the tree dirty (the default), pass `git diff HEAD` (working tree; run `git add -N .` first so new files appear); if 2.1 committed (`implement-spec`), use `git diff <branch-point>...HEAD`.
- Spec compliance (`prd.md` / `design.md` / tickets, plus the parent task's contracts when `task.json` declares a `parent`)
- lint / type-check / tests
- Cross-layer consistency (when changes span layers)

If issues are found → fix → re-check, until green. On this platform `trellis-check` is retired; legacy references may be treated as an alias for `code-review`. (Kimi Code is different: there `trellis-check` is a live custom agent.)

[/codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

**Final pass (before Phase 3.4 commit)**: the last 2.2 of a task must run full-scope, not just on the latest implement chunk. List all affected packages with `python3 ./.trellis/scripts/get_context.py --mode packages`, then load each package's spec index Quality Check section. This catches cross-layer / multi-package issues a mid-iteration local 2.2 cannot.

#### 2.3 Rollback `[on demand]`

- `check` reveals a prd defect → return to Phase 1, fix `prd.md`, then redo 2.1
- Implementation went wrong → revert code, redo 2.1
- Need more research → research (same as Phase 1.2), write findings into `research/`

---

## Phase 3: Finish

Goal: ensure code quality, capture lessons, record the work.

#### 3.2 Debug retrospective `[on demand]`

If this task involved repeated debugging (the same issue was fixed multiple times), load the `trellis-break-loop` skill to:
- Classify the root cause
- Explain why earlier fixes failed
- Propose prevention

The goal is to capture debugging lessons so the same class of issue doesn't recur.

#### 3.3 Spec update `[required · once]`

Two passes, in this order:

1. **`retro`** — look back over the session for what the *environment* should have caught: a check that should exist, a standard that should be written, a pointer that should be in place. It proposes changes to the agent's environment, not to the code.
2. **`trellis-update-spec`** — turn the lasting part into `.trellis/spec/` knowledge: newly discovered patterns or conventions, pitfalls you hit, new technical decisions.

Update the docs under `.trellis/spec/` accordingly. Even if the conclusion is "nothing to update", walk through the judgment.

#### 3.4 Commit changes `[required · once]`

**Spec-sync preamble**: before drafting commits, ask: did this task fix a bug or surface non-obvious knowledge that should land in `.trellis/spec/` so future-you (or future-AI) doesn't repeat the mistake? If yes, return to Phase 3.3 first — spec writes belong in the same task's commit batch, not as a forgotten follow-up.

The AI drives a batched commit of this task's code changes so `/finish-work` can run cleanly afterwards. Goal: produce work commits FIRST, then bookkeeping (archive + journal) commits land after — never interleaved.

**Step-by-step**:

1. **Inspect dirty state**:
   ```bash
   git status --porcelain
   ```
   Snapshot every dirty path. If the working tree is clean, skip to 3.5.

2. **Learn commit style** from recent history (so drafted messages blend in):
   ```bash
   git log --oneline -5
   ```
   Note the prefix convention (`feat:` / `fix:` / `chore:` / `docs:` ...), language (中文/English), and length style.

3. **Classify dirty files into two groups**:
   - **AI-edited this session** — files you wrote/edited via Edit/Write/Bash tool calls in this session. You know what changed and why.
   - **Unrecognized** — dirty files you did NOT touch this session (could be the user's manual edits, leftover WIP from a previous session, or unrelated work). Do NOT silently include these.

4. **Draft a commit plan**. Group AI-edited files into logical commits (1 commit per coherent change unit, not 1 commit per file). Each entry: `<commit message>` + file list. List unrecognized files separately at the bottom.

5. **Present the plan once, ask for one-shot confirmation**. Format:
   ```
   Proposed commits (in order):
     1. <message>
        - <file>
        - <file>
     2. <message>
        - <file>

   Unrecognized dirty files (NOT in any commit — confirm include/exclude):
     - <file>
     - <file>

   Reply 'ok' / '行' to execute. Reply with edits, or '我自己来' / 'manual' to abort.
   ```

6. **On confirmation**: run `git add <files>` + `git commit -m "<msg>"` for each batch in order. Do not amend. Do not push.

7. **On rejection** (user replies "不行" / "我自己来" / "manual" / any pushback on the plan): stop. Do not attempt a second plan. The user will commit by hand; you skip ahead to 3.5 once they confirm.

**Rules**:
- No `git commit --amend` anywhere — three-stage three-commit flow (work commits → archive commit → journal commit).
- Never push to remote in this step.
- If the user wants different message wording but accepts the file grouping, edit the message and re-confirm once — but if they reject the grouping, exit to manual mode.
- The batched plan is one prompt; do not prompt per commit.

#### 3.5 Wrap-up reminder

After the above, remind the user they can run `/finish-work` to wrap up (archive the task, record the session).

---

## Customizing Trellis (for forks)

This section is for developers who want to modify the Trellis workflow itself. All customization is done by editing this file; the scripts are parsers only.

### Changing what a step means

Edit the corresponding step's walkthrough body in the Phase 1 / 2 / 3 sections above. Critical invariants:
- No active task must triage first and ask for task-creation consent before creating a Trellis task.
- Planning must distinguish lightweight PRD-only tasks from complex tasks that require `prd.md`, `design.md`, and `implement.md` before start.
- Every required execution path must keep the Phase 3.4 commit reminder reachable before `/trellis:finish-work`.

All tag blocks live in the `## Phase Index` section above, immediately after each phase summary:

| Scope | Corresponding tag |
|---|---|
| No active task (before Phase 1) | `[workflow-state:no_task]` (after the Phase Index ASCII art) |
| Active task record unreadable | `[workflow-state:task_error]` (repair the existing task before continuing) |
| All of Phase 1 (task created → ready for implementation) | `[workflow-state:planning]` (after Phase 1 summary) |
| Codex inline Phase 1 | `[workflow-state:planning-inline]` |
| Phase 2 + Phase 3.2–3.4 (implementation + check + wrap-up) | `[workflow-state:in_progress]` (after Phase 2 summary) |
| Codex inline Phase 2 + Phase 3.2–3.4 | `[workflow-state:in_progress-inline]` |
| After Phase 3.5 (archived) | `[workflow-state:completed]` (after Phase 3 summary; **currently DEAD**) |

### Changing the per-turn prompt text

Directly edit the body of the corresponding `[workflow-state:STATUS]` block. After editing, run `trellis update` (if you're a template maintainer) or restart your AI session (if you're customizing your own project) — no script changes required.

### Adding a custom status

Add a new block:

```
[workflow-state:my-status]
your per-turn prompt text
[/workflow-state:my-status]
```

Constraints:
- STATUS charset: `[A-Za-z0-9_-]+` (underscores and hyphens allowed, e.g. `in-review`, `blocked-by-team`)
- A lifecycle hook must write `task.json.status` to your custom value, otherwise the tag is never read
- Lifecycle hooks live in `task.json.hooks.after_*` and bind to one of `after_create / after_start / after_finish / after_archive`

### Adding a lifecycle hook

Add a `hooks` field to your `task.json`:

```json
{
  "hooks": {
    "after_finish": [
      "your-script-or-command-here"
    ]
  }
}
```

Supported events: `after_create / after_start / after_finish / after_archive`. Note that `after_finish` ≠ a status change (it only clears the active-task pointer); use `after_archive` for "task is done" notifications.

### Full contract

For the workflow state machine's runtime contract, the locations of all status writers, pseudo-statuses (`no_task` / `stale_<source_type>`), the hook reachability matrix, and other deep details, see:

- `.trellis/spec/cli/backend/workflow-state-contract.md` — runtime contract + writer table + test invariants
- `.trellis/scripts/inject-workflow-state.py` — actual parser (reads workflow.md only, no embedded text)
