## Purpose

Defines how the project extracts concrete content material (sect storylines, artifacts, techniques, breakthrough events) from original xianxia novel texts, organized by the game's gameplay dimensions, so the extracted material can directly feed game content settings and display text.

## ADDED Requirements

### Requirement: Obtain free readable/downloadable novel full text
The extraction workflow SHALL obtain the full original text of each target novel from a free, accessible source (public reading sites, GitHub text repositories, or downloadable e-book archives). The source MUST be verified accessible before extraction starts; if a source fails, the workflow SHALL switch to an alternative source or substitute the novel.

#### Scenario: Source accessible
- **WHEN** the workflow attempts to fetch/download a novel's full text from a chosen source
- **THEN** it successfully obtains the text (or a confirmed readable portion) and records the source URL and access date in the extraction record

#### Scenario: Source unavailable
- **WHEN** the chosen source is inaccessible (site down, paywalled, region-blocked, or text missing)
- **THEN** the workflow switches to an alternative free source, or if none exists, replaces the novel with another from the approved list and notes the substitution

### Requirement: Extract concrete content by gameplay dimensions
The workflow SHALL read the novel text chapter by chapter and extract concrete items (not general overviews) for each of the following dimensions, aligned with this project's gameplay systems:
1. **境界与突破情节**: concrete breakthrough events, tribulation descriptions, realm-specific progression stories (maps to 闭关/突破/渡劫 systems)
2. **宗门与故事情节**: specific sects, their storylines, sect politics, inheritance/trials, sect wars (maps to 宗门/传承 systems)
3. **道具法宝**: named artifacts, weapons, treasures, storage items, their effects and lore (maps to 装备/百宝阁/储物戒 systems)
4. **功法神通技能**: named techniques, skills, spells with effect descriptions (maps to 功法/技能/修习 systems)
5. **丹药灵药**: named pills, herbs, recipes, effects, costs (maps to 丹药/炼丹/灵田/丹阁 systems)
6. **地名与势力**: named locations, realms, forces, their characteristics (maps to 秘境/历练/洞天 systems)
7. **事件与奇遇模板**: adventure events, encounters, trials, rewards (maps to 秘境探索/历练/悬赏 systems)
8. **战斗描写**: fight scene descriptions usable as display text (maps to 战报/决斗/Boss systems)
9. **人物与关系**: named characters, archetypes, relationships (maps to 双修/宗门成员/传承 roles)

Each extracted item MUST record: name (verbatim), source chapter, a 1-3 sentence summary of the storyline/effect, and the mapped gameplay system.

#### Scenario: Extraction covers all dimensions
- **WHEN** the extraction of one novel is complete
- **THEN** the record contains at least one item for each of the 9 dimensions, each with name, chapter reference, and gameplay-system mapping

#### Scenario: Item granularity
- **WHEN** the workflow encounters a concrete named artifact/technique/pill/place/event in the text
- **THEN** it is recorded as an individual item with its verbatim name and effect/plot summary, rather than merged into a general setting overview

### Requirement: Record format and location
The workflow SHALL write each novel's extraction record as a Markdown file at `design_docs/novel-research/extract-<novel-slug>.md` following a fixed template: header (novel, author, source URL, access date, chapters read), one section per gameplay dimension, per-item entries with name/chapter/summary/mapping, and a final section listing unread chapters or gaps. The workflow SHALL register each new file in the `design_docs/README.md` 资料清单 table.

#### Scenario: Record written and registered
- **WHEN** a novel's extraction is finished
- **THEN** `design_docs/novel-research/extract-<novel-slug>.md` exists with all template sections filled and `design_docs/README.md` lists the file

#### Scenario: Incomplete reading (partial-coverage novels)
- **WHEN** a novel is only partially read by design (the 7 partial novels)
- **THEN** the record marks which chapters were read and which dimensions are additionally covered by web-search summaries

### Requirement: Novel coverage
Three novels SHALL be read **in full, continuously** (凡人修仙传, 仙逆, 遮天): reading proceeds in batches, each batch's findings are appended to the extraction record, and reading continues across sessions until the novel is finished (the record SHALL have no unread chapters at completion). The other seven novels (诛仙, 一念永恒, 我师兄实在太稳健了, 大奉打更人, 诡秘之主, 道诡异仙, 佛本是道) SHALL be covered by partial close reading of selected chapters PLUS web searches that summarize each setting dimension; their records SHALL mark which parts come from reading vs. from web research. Each record SHALL include verbatim quotes from the text for at least the named artifacts, techniques, and breakthrough events.

#### Scenario: Full-read novels completed
- **WHEN** a full-read novel's extraction is declared complete
- **THEN** its record covers all chapters read through the end of the novel, with no remaining unread-chapter gap marked

#### Scenario: Partial novels combine reading and web research
- **WHEN** the workflow finishes a partial-coverage novel
- **THEN** its record contains items from chapter reading and setting summaries from web research, each entry labeled with its source (原文章节 vs 网络调研)

#### Scenario: Quote requirement
- **WHEN** an item is recorded as a named artifact, technique, or breakthrough event
- **THEN** its entry includes a short verbatim quote from the original text (or exact name + chapter if the surrounding text is too long to quote)

### Requirement: Progress persistence across sessions
For the three full-read novels, the workflow SHALL persist reading progress in the extraction record file itself: a header field "已读至第 X 章 / 共 Y 章" updated after every reading batch. A later session SHALL be able to resume reading from that marker without re-reading earlier chapters.

#### Scenario: Resume after session break
- **WHEN** a new session continues a full-read novel whose record already exists
- **THEN** it reads the record header to find the current chapter marker and continues from the next unread chapter

#### Scenario: Batch increment
- **WHEN** a reading batch is finished
- **THEN** the record header's chapter marker and the dimension sections are updated with the batch's findings before the batch's raw text is compressed
