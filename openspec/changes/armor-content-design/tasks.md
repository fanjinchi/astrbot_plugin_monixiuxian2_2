# Tasks: 防具内容设计框架

## 1. 前置依赖确认

- [x] 1.1 确认 separate-block-armor-source 已落地（格挡来源分离合入并通过测试）——本变更全部数值工作以其为前提

## 2. 设计文档修订

- [x] 2.1 修订 `design_docs/content-design/route-identity.md`：满级期望面板分离"天生护甲/装备护甲"两行，更新 §2 相关描述
- [x] 2.2 在 `design_docs/content-design/README.md` 登记 armors.csv 并更新 §6 缺口清单（防具项移除）

## 3. armors.csv 起草

- [x] 3.1 新建 `design_docs/content-design/armors.csv`，列结构对齐 weapons.csv 约定 + `armor_family`/`bonus_hp` 列
- [x] 3.2 按供给曲线（design.md D1）填重甲族 9 品级标杆件 armor_value，status=draft
- [x] 3.3 按对称 EHP 反解（design.md D2）填两族 bonus_hp 与法袍族 armor_value
- [x] 3.4 标 route_mult 向性（通用件 ≥10 件，向性件对称镜像），填命名/文案列（基调查 world-bible.md）
- [x] 3.5 移除 3 件占位防具（玄铁甲/月华袍/泰坦之铠）——用户已拍板（2026-09-06）直接删除不映射，由新标杆件体系重做；在 armors.csv 设计说明中留档删除决定

## 4. 机器校验与模拟验收

- [x] 4.1 `validate_budget.py` 新增防具校验：供给曲线带、对称 EHP ±5%、属性池纪律、通用件占比 ≥50%
- [x] 4.2 `sim_route_matchup.py` 扩展带装场景（同级同装镜像 TTK、满级跨路线带装胜率）
- [x] 4.3 跑 lint_narrative.py + validate_budget.py 自检，修正至全绿
- [x] 4.4 跑带装模拟验收：镜像 TTK ≥5 回合、跨路线胜率 50%±2，结果写入 route-matchup-report.md 附录；裸装复跑留档（2026-09-08 修正模拟器 level_index 桩后全绿：镜像 10/10 PASS、L40 带装 49.4% PASS、基线 8/8 PASS）

## 5. 收口

- [x] 5.1 更新 `design_docs/current-design-report.md` 防具节（占位 → 定稿框架，附供给曲线表与 M 序列推导；M 序列按验收结果定稿 v1 缓坡）
- [ ] 5.2 **用户确认设计稿**（AGENTS.md §15：未经用户确认不导入 config）
- [ ] 5.3 用户确认后经 `scripts/sync_content_to_config.py` 导入 config/items.json（导入前核对 bd bx8 宗门内容收编状态），复跑 `uv run python -m pytest tests/ -v` 与 ruff
- [ ] 5.4 检查 `functional_tests/cases/` 是否有商店/装备域用例需补充或更新（AGENTS.md 功能测试套件规范）
- [ ] 5.5 按 AGENTS.md §7 更新 `metadata.yaml` version 与 `README.md` 更新日志
