# data/default_configs.py

# 叙事文案默认值按域拆分在 data/narrative_defaults/ 包中（避免单文件冲突），
# 在此汇编导出，保持「默认值统一从 default_configs 引用」的单源约定。
from .narrative_defaults import DEFAULT_NARRATIVE_CONFIG, NARRATIVE_SCENE_VARS

__all__ = [
    "ADVENTURE_CONFIG",
    "BOUNTY_CONFIG",
    "DEFAULT_NARRATIVE_CONFIG",
    "ENEMY_CONFIG",
    "NARRATIVE_SCENE_VARS",
    "SECT_CONFIG",
    "SECT_FACTIONS",
    "SECT_TASKS",
    "BOSS_CONFIG",
    "RIFT_CONFIG",
    "ALCHEMY_CONFIG",
    "IMPART_CONFIG",
]

SECT_CONFIG = {
    "create_cost": 10000,
    "create_level_required": 3,  # 筑基
    # positions 为职位体系唯一事实源（见 design_docs/sect-system-design.md §3.8）：
    # promotion 为晋升到该职位的双门槛（贡献+境界，null 表示无晋升通道），
    # benefits 为该职位的福利（每日灵石/商店折扣/传承解锁资格）。
    "positions": {
        "0": {
            "name": "宗主",
            "permission": 10,
            "promotion": None,
            "benefits": {"daily_stones": 2000, "shop_discount": 0.8, "unlocks": []},
        },
        "1": {
            "name": "长老",
            "permission": 8,
            "promotion": {"contribution": 30000, "level_index": 9},
            "benefits": {"daily_stones": 800, "shop_discount": 0.85, "unlocks": []},
        },
        "2": {
            "name": "亲传弟子",
            "permission": 5,
            "promotion": {"contribution": 8000, "level_index": 6},
            "benefits": {
                "daily_stones": 300,
                "shop_discount": 0.9,
                "unlocks": ["wpn_qy_001"],
            },
        },
        "3": {
            "name": "内门弟子",
            "permission": 2,
            "promotion": {"contribution": 2000, "level_index": 4},
            "benefits": {
                "daily_stones": 100,
                "shop_discount": 0.95,
                "unlocks": ["heart_qy_001"],
            },
        },
        "4": {
            "name": "外门弟子",
            "permission": 1,
            "promotion": {"contribution": 500, "level_index": 2},
            "benefits": {"daily_stones": 0, "shop_discount": 1.0, "unlocks": []},
        },
    },
    "scale_ratio": 10,  # 1灵石 = 10建设度
    # buildings 为玩家宗门的全局默认建筑配置（默认宗门读各自 faction 的 buildings，
    # 结构一致）。upgrade_cost[i] = 从 i 级升到 i+1 级所需宗门资材。
    "buildings": {
        "fairyland": {
            "max_level": 5,
            "exp_bonus_per_level": 0.02,
            "upgrade_cost": [200, 400, 800, 1600, 3200],
        },
        "elixir_room": {
            "max_level": 5,
            "unlock_pills_per_level": [
                "炼气丹",
                "聚灵丹",
                "凝气丹",
                "培元丹",
                "玄灵丹",
            ],
            "upgrade_cost": [200, 400, 800, 1600, 3200],
        },
    },
}

BOSS_CONFIG = {
    "spawn_interval": 3600,
    "levels": [
        {
            "name": "练气",
            "level_index": 0,
            "hp_mult": 1.0,
            "atk_mult": 1.0,
            "reward_mult": 1.0,
        },
        {
            "name": "筑基",
            "level_index": 3,
            "hp_mult": 1.5,
            "atk_mult": 1.2,
            "reward_mult": 1.5,
        },
        {
            "name": "金丹",
            "level_index": 6,
            "hp_mult": 2.0,
            "atk_mult": 1.5,
            "reward_mult": 2.0,
        },
        {
            "name": "元婴",
            "level_index": 9,
            "hp_mult": 2.5,
            "atk_mult": 1.8,
            "reward_mult": 2.5,
        },
        {
            "name": "化神",
            "level_index": 12,
            "hp_mult": 3.0,
            "atk_mult": 2.0,
            "reward_mult": 3.0,
        },
        {
            "name": "炼虚",
            "level_index": 15,
            "hp_mult": 4.0,
            "atk_mult": 2.5,
            "reward_mult": 4.0,
        },
        {
            "name": "合体",
            "level_index": 18,
            "hp_mult": 5.0,
            "atk_mult": 3.0,
            "reward_mult": 5.0,
        },
        {
            "name": "大乘",
            "level_index": 21,
            "hp_mult": 6.0,
            "atk_mult": 3.5,
            "reward_mult": 6.0,
        },
    ],
}

RIFT_CONFIG = {
    "default_duration": 1800,  # 30分钟
    "legacy_chance": 0.10,  # 探索完成触发秘境传承机缘的概率（0 关闭）
    # 遭遇机制（add-rift-encounters design D4/D6）：结算后独立判定谜题/妖兽遭遇；
    # 秘境条目 encounter_rate 存在时覆盖 puzzle_rate/beast_rate 两者。
    # 存量 rift_config.json 不会被自动合并新键，读取处按 explore_events 先例
    # 回落到本默认值（见 managers/rift_manager.py）
    "puzzle_rate": 0.3,  # 结算后触发古阵谜题遭遇的概率
    "beast_rate": 0.5,  # 结算后触发妖兽拦路遭遇的概率（沿用旧 rift low 难度 50% 量级）
    "encounter_ttl_seconds": 600,  # pending 遭遇惰性过期时限（秒，design D1）
    "puzzle_attempts": 2,  # 谜题作答机会次数（design D6）
    # 探索事件变体池（外移自 rift_manager 原硬编码，文案逐字保留）；
    # 旧版 rift_config.json 缺该键时运行时回落到本默认池
    "explore_events": [
        {"desc": "你发现了一处灵泉，修为大增！", "item_chance": 70},
        {"desc": "你在秘境中击败了一只妖兽！", "item_chance": 80},
        {"desc": "你找到了一个隐藏的宝箱！", "item_chance": 100},
        {"desc": "你领悟了一些修炼心得。", "item_chance": 40},
        {"desc": "你在秘境中遇到了前辈留下的传承！", "item_chance": 90},
    ],
    "rifts": [
        # id 1-5 的内容以 rifts 表 DB 种子为准（migration v15），此处仅保留
        # 与 DB 一致的基础信息 + 宗门准入字段（sect_id/access），避免双写漂移。
        # description/settlement_desc 为叙事占位（config-only，不落 DB），
        # 内容由 design_docs 管线后续填充；空串时 UI/结算行为与旧版一致
        {
            "id": 1,
            "name": "青云秘境",
            "level": 0,
            "exp_range": [500, 1500],
            "gold_range": [200, 800],
            "description": "",
            "settlement_desc": "",
        },
        {
            "id": 2,
            "name": "落日峡谷",
            "level": 3,
            "exp_range": [1500, 4000],
            "gold_range": [500, 2000],
            "description": "",
            "settlement_desc": "",
        },
        {
            "id": 3,
            "name": "万妖洞",
            "level": 6,
            "exp_range": [3000, 8000],
            "gold_range": [1000, 5000],
            "description": "",
            "settlement_desc": "",
        },
        {
            "id": 4,
            "name": "玄冰地宫",
            "level": 10,
            "exp_range": [5000, 15000],
            "gold_range": [2000, 10000],
            "description": "",
            "settlement_desc": "",
        },
        {
            "id": 5,
            "name": "上古遗迹",
            "level": 15,
            "exp_range": [10000, 30000],
            "gold_range": [5000, 20000],
            "description": "",
            "settlement_desc": "",
        },
        {
            "id": 6,
            "name": "青云剑冢",
            "level": 3,
            "exp_range": [300, 900],
            "gold_range": [100, 400],
            "sect_id": "qingyun",  # 宗门专属秘境
            "access": "sect_member",  # 仅本宗成员可探索（7.2 接线准入校验）
            "description": "",
            "settlement_desc": "",
        },
        {
            # add-rift-encounters 临时测试秘境（验证后拆除）：enemy_group 指向
            # enemies.json 的 rift_test 定向组；encounter_rate 1.0 必触发保证测试确定性
            "id": 7,
            "name": "试炼古境",
            "level": 0,
            "exp_range": [100, 200],
            "gold_range": [50, 100],
            "description": "云雾深处的一座残破古境，唯有石傀儡徘徊其中。（测试秘境）",
            "settlement_desc": "你离开了试炼古境，身后傀儡重归沉寂。（测试秘境）",
            "legacy_type": "rift",
            "enemy_group": "rift_test",
            "encounter_rate": 1.0,
        },
    ],
}

# 传承系统等阶奖励默认配置（impart_config.json 缺失时兜底）
# types 按传承类型分组；首版四类共享 20/40/60/80/100 阈值。
_IMPART_TIERS = [
    {
        "tier": 1,
        "impart_value_required": 20,
        "rewards": [{"type": "heart_method", "id": "传承心法·吐纳"}],
    },
    {
        "tier": 2,
        "impart_value_required": 40,
        "rewards": [{"type": "heart_method", "id": "传承心法·归元"}],
    },
    {
        "tier": 3,
        "impart_value_required": 60,
        "rewards": [{"type": "technique", "id": "impart_skill_001"}],
    },
    {
        "tier": 4,
        "impart_value_required": 80,
        "rewards": [{"type": "technique", "id": "impart_skill_002"}],
    },
    {
        "tier": 5,
        "impart_value_required": 100,
        "rewards": [{"type": "level_up", "amount": 1}],
    },
]
IMPART_CONFIG = {
    "cultivation_points_every_minutes": 15,
    "guardian": {"enemy_group": "legacy_guardian"},
    "types": {
        "common": {"name": "通用传承", "tiers": _IMPART_TIERS},
        "sect": {"name": "宗门传承", "tiers": _IMPART_TIERS},
        "adventure": {"name": "历练传承", "tiers": _IMPART_TIERS},
        "rift": {"name": "秘境传承", "tiers": _IMPART_TIERS},
    },
}

ALCHEMY_CONFIG = {
    "recipes": {
        "1": {
            "name": "聚气丹",
            "level_required": 0,
            "materials": {"灵草": 3, "灵石": 100},
            "success_rate": 80,
            "effect": {"type": "exp", "value": 1000},
            "desc": "增加1000修为",
        },
        "2": {
            "name": "筑基丹",
            "level_required": 2,
            "materials": {"灵草": 5, "灵石": 500},
            "success_rate": 60,
            "effect": {"type": "exp", "value": 5000},
            "desc": "增加5000修为",
        },
        "3": {
            "name": "金丹",
            "level_required": 5,
            "materials": {"灵草": 10, "灵石": 2000},
            "success_rate": 40,
            "effect": {"type": "exp", "value": 20000},
            "desc": "增加20000修为",
        },
        "4": {
            "name": "回春丹",
            "level_required": 1,
            "materials": {"灵草": 2, "灵石": 200},
            "success_rate": 70,
            "effect": {"type": "hp_restore", "value": 50},
            "desc": "恢复50%气血",
        },
        "5": {
            "name": "聚灵丹",
            "level_required": 1,
            "materials": {"灵草": 2, "灵石": 200},
            "success_rate": 70,
            "effect": {"type": "mp_restore", "value": 50},
            "desc": "恢复50%真元",
        },
    }
}


# 默认宗门定义（sect_factions.json 的播种默认值，结构见 design_docs/sect-system-design.md §3.1）
# destruction 结构一期仅定型不消费（二期毁灭重建玩法使用）。
_SECT_DESTRUCTION_DEFAULT = {
    "enabled": True,
    "default_loss_profile": "medium",
    "loss_profiles": {
        "light": {
            "scale": 0.2,
            "materials": 0.2,
            "stones": 0.2,
            "skills": 0.1,
            "treasures": 0.0,
        },
        "medium": {
            "scale": 0.5,
            "materials": 0.5,
            "stones": 0.5,
            "skills": 0.3,
            "treasures": 0.2,
        },
        "heavy": {
            "scale": 0.8,
            "materials": 0.8,
            "stones": 0.8,
            "skills": 0.6,
            "treasures": 0.5,
        },
        "ruined": {
            "scale": 1.0,
            "materials": 1.0,
            "stones": 1.0,
            "skills": 0.9,
            "treasures": 0.8,
        },
    },
}

SECT_FACTIONS = {
    "factions": [
        {
            "id": "qingyun",
            "name": "青云门",
            "alignment": "正",
            "description": (
                "青云门立派于青云山巅，开派祖师青云子以一卷《青云心典》创下千年基业。"
                "门中崇尚循序渐进的学院式修行：外门演武、内门讲道、亲传授业，层层递进。"
                "当代掌门云游在外，门务由传功长老玄诚子代为主持，广收天下有志于道的少年修士。"
            ),
            "join_level_range": [0, 5],
            "skill_pool": "sect_qingyun",
            "mainbuff": ["qy_001"],
            "heart_methods": ["heart_qy_001"],
            "treasures": [{"type": "weapon", "id": "wpn_qy_001", "min_position": 2}],
            # 宗门商店：贡献点结算；min_position 缺省 4（全员可购），数值越小门槛越高
            "shop": [
                {"id": "sword_006", "price": 1500, "min_position": 3},
                {"id": "heart_201", "price": 1000},
            ],
            "buildings": {
                "fairyland": {
                    "max_level": 5,
                    "exp_bonus_per_level": 0.02,
                    "upgrade_cost": [200, 400, 800, 1600, 3200],
                },
                "elixir_room": {
                    "max_level": 5,
                    "unlock_pills_per_level": ["炼气丹", "聚灵丹", "凝气丹"],
                    "upgrade_cost": [200, 400, 800, 1600, 3200],
                },
            },
            "elders": [
                {"name": "玄诚子", "title": "传功长老"},
                {"name": "清微道长", "title": "执事长老"},
            ],
            "destruction": _SECT_DESTRUCTION_DEFAULT,
        },
        {
            "id": "huanxi",
            "name": "合欢宗",
            "alignment": "魔",
            "description": (
                "合欢宗没有山门，只有一座随季候迁徙的销金窟。三百年前一群被名门正派逐出门墙的散修"
                "在此立誓：道法不问出处，强弱只论生死。宗内不讲辈分，只讲投名状；不传心诀，只传杀术。"
                "护法长老厉无欢坐镇总坛，凡带艺投宗者，须先见血，再入门墙。"
            ),
            "join_level_range": [2, 6],
            "skill_pool": "sect_huanxi",
            "mainbuff": ["hx_001"],
            "heart_methods": [],
            "treasures": [],
            "shop": [
                {"id": "dagger_005", "price": 1500, "min_position": 3},
                {"id": "heart_301", "price": 1000},
            ],
            "buildings": {
                "fairyland": {
                    "max_level": 5,
                    "exp_bonus_per_level": 0.02,
                    "upgrade_cost": [200, 400, 800, 1600, 3200],
                },
                "elixir_room": {
                    "max_level": 5,
                    "unlock_pills_per_level": ["聚灵丹", "凝气丹", "培元丹"],
                    "upgrade_cost": [200, 400, 800, 1600, 3200],
                },
            },
            "elders": [
                {"name": "厉无欢", "title": "护法长老"},
                {"name": "花妩娘", "title": "传功长老"},
            ],
            "destruction": _SECT_DESTRUCTION_DEFAULT,
        },
    ]
}

# 宗门任务池定义（sect_tasks.json 的播种默认值，结构见 design_docs/sect-system-design.md §3.9）
SECT_TASKS = {
    "construction_tasks": [
        {
            "id": "build_001",
            "name": "修缮山门",
            "type": "donate_materials",
            "cost": {"materials": 50},
            "reward": {"contribution": 30},
            "cooldown": 3600,
        },
        {
            "id": "build_002",
            "name": "输财助宗",
            "type": "donate_stones",
            "cost": {"stones": 500},
            "reward": {"contribution": 40},
            "cooldown": 3600,
        },
        {
            "id": "build_003",
            "name": "加固护山大阵",
            "type": "donate_materials",
            "cost": {"materials": 200},
            "reward": {"contribution": 120},
            "cooldown": 7200,
        },
    ],
    "master_task_chains": [
        {
            "id": "chain_qy_01",
            "sect_id": "qingyun",
            "level_range": [0, 2],
            "stages": [
                {
                    "name": "入门演武",
                    "type": "win_pve",
                    "count": 3,
                    "reward": {"contribution": 50, "exp": 200},
                    "text": "玄诚子：新入门弟子，先去后山演武场活动筋骨，胜三场妖兽来见我。",
                },
                {
                    "name": "采药历练",
                    "type": "adventure_complete",
                    "count": 1,
                    "reward": {
                        "contribution": 80,
                        "skill_learn_chance": "sect_qingyun",
                    },
                    "text": "玄诚子：丹房缺几味常见灵草，你去历练一趟，顺便把采药的规矩学了。",
                },
                {
                    "name": "破境之礼",
                    "type": "breakthrough",
                    "count": 1,
                    "reward": {"contribution": 150, "exp": 1000},
                    "text": "清微道长：破境乃修行第一关，成之后来执事堂登记，门中自有嘉奖。",
                },
            ],
        },
        {
            "id": "chain_hx_01",
            "sect_id": "huanxi",
            "level_range": [2, 4],
            "stages": [
                {
                    "name": "投名状",
                    "type": "donate",
                    "count": 1000,
                    "reward": {"contribution": 80, "exp": 500},
                    "text": "花妩娘：入我合欢宗，先纳一千灵石做投名状，宗门不养闲人。",
                },
                {
                    "name": "见血",
                    "type": "win_pve",
                    "count": 5,
                    "reward": {
                        "contribution": 120,
                        "skill_learn_chance": "sect_huanxi",
                    },
                    "text": "厉无欢：去杀五个不开眼的东西，提着他们的兵刃回来，才算自己人。",
                },
            ],
        },
    ],
}


# --- 三 manager 的 fallback 默认值（externalize-narrative-texts D4 收敛） ---
# adventure/bounty/enemy 三 manager 原各自内嵌一份 DEFAULT_CONFIG 副本，
# 与 config/*.json 漂移后成为漏检源；现统一迁移到此单源，manager 改为引用。

ADVENTURE_CONFIG = {
    "routes": [
        {
            "key": "scout",
            "name": "巡山问道",
            "aliases": ["短途", "巡山"],
            "description": "巡视宗门周边，风险较低，适合积累经验。",
            "risk": "低",
            "duration": 1800,
            "min_level": 0,
            "fatigue_cooldown": 300,
            "base_exp_per_min": 45,
            "base_gold_per_min": 10,
            "level_bonus_exp": 12,
            "level_bonus_gold": 3,
            "completion_bonus": {"exp": 300, "gold": 120},
            "event_weights": {"safe": 60, "standard": 30, "risky": 10},
            "drop_tier": "low",
            "bounty_tag": "adventure_scout",
            "bounty_progress": 1,
        }
    ],
    "event_groups": {
        "safe": [
            {
                "key": "steady_path",
                "name": "平稳推进",
                "desc": "历练过程顺风顺水，按部就班地完成目标。",
                "exp_mult": 1.1,
                "gold_mult": 1.1,
                "item_chance": 60,
                "bonus_progress": 0,
            }
        ],
        "standard": [
            {
                "key": "minor_skirmish",
                "name": "遭遇小型冲突",
                "desc": "击退拦路妖兽，实战经验有所增长。",
                "exp_mult": 1.2,
                "gold_mult": 1.2,
                "item_chance": 50,
                "bonus_progress": 1,
            }
        ],
        "risky": [
            {
                "key": "ambush",
                "name": "埋伏受创",
                "desc": "遭遇伏击，受了点伤但仍坚持完成任务。",
                "exp_mult": 0.7,
                "gold_mult": 0.7,
                "item_chance": 15,
                "bonus_progress": 0,
                "injury": True,
            }
        ],
    },
    "drop_tables": {
        "low": [
            {"name": "灵草", "weight": 50, "min": 1, "max": 3},
            {"name": "精铁", "weight": 30, "min": 1, "max": 2},
            {"name": "灵石碎片", "weight": 20, "min": 2, "max": 5},
        ]
    },
}

BOUNTY_CONFIG = {
    "difficulties": {
        "easy": {
            "name": "F级",
            "stone_scale": 1.0,
            "exp_scale": 1.0,
            "min_level": 0,
        }
    },
    "templates": [
        {
            "id": 1,
            "name": "击退妖兽",
            "difficulty": "easy",
            "category": "巡山",
            "progress_tags": ["adventure_scout"],
            "min_target": 3,
            "max_target": 5,
            "time_limit": 3600,
            "reward": {"stone": 300, "exp": 2500},
            "item_table": "hunt",
            "description": "驱逐骚扰山门的妖兽。",
        }
    ],
    "item_tables": {
        "hunt": [
            {"name": "灵兽毛皮", "weight": 40, "min": 1, "max": 3},
            {"name": "妖兽精血", "weight": 30, "min": 1, "max": 2},
            {"name": "玄铁", "weight": 30, "min": 1, "max": 2},
        ]
    },
}

ENEMY_CONFIG = {
    "enemy_groups": [
        {
            "key": "default",
            "name": "默认妖域",
            "level_range": [0, 100],
            "templates": [
                {
                    "key": "default_monster",
                    "name": "未知妖兽",
                    "elite_prefixes": ["强大的"],
                    "boss_names": ["妖王"],
                    "hp_mult": 1.0,
                    "atk_mult": 1.0,
                    "defense": 0,
                    "crit_rate": 0,
                }
            ],
            "elite": {
                "hp_mult": 1.0,
                "atk_mult": 1.0,
                "defense_bonus": 0,
                "crit_rate_bonus": 0,
            },
            "boss": {
                "hp_mult": 1.2,
                "atk_mult": 1.2,
                "defense_bonus": 0,
                "crit_rate_bonus": 0,
            },
            "drop_tier": "low",
        },
        {
            "key": "legacy_guardian",
            "name": "传承之地守护",
            "description": "传承获取前置挑战的守护 NPC 组；不带 level_range，只能经 spawn_enemy_from_group 定向触达。",
            "templates": [
                {
                    "key": "guardian_low",
                    "name": "守门石像",
                    "max_level_index": 30,
                    "hp_mult": 1.0,
                    "atk_mult": 0.9,
                    "defense": 5,
                    "crit_rate": 0.05,
                },
                {
                    "key": "guardian_mid",
                    "name": "镇府灵将",
                    "max_level_index": 60,
                    "hp_mult": 1.1,
                    "atk_mult": 1.0,
                    "defense": 10,
                    "crit_rate": 0.08,
                },
                {
                    "key": "guardian_high",
                    "name": "传承守护神",
                    "max_level_index": 999,
                    "hp_mult": 1.2,
                    "atk_mult": 1.1,
                    "defense": 20,
                    "crit_rate": 0.1,
                },
            ],
        },
        {
            # add-rift-encounters 临时测试组（验证后拆除）：与 enemies.json 的
            # rift_test 组保持一致；不带 level_range，只能定向触达
            "key": "rift_test",
            "name": "试炼古境傀儡",
            "description": "试炼古境中沉睡的傀儡造物，强度极低，仅供遭遇机制测试（验证后拆除）",
            "templates": [
                {
                    "key": "stone_golem",
                    "name": "石傀儡",
                    "description": "古境碎石拼合而成的傀儡，行动迟缓，力道涣散",
                    "elite_prefixes": ["历战的", "坚固的", "龟裂的"],
                    "boss_names": ["古境石灵", "镇境石尊"],
                    "hp_mult": 0.5,
                    "atk_mult": 0.5,
                    "defense": 2,
                    "crit_rate": 3,
                }
            ],
        },
    ],
    "difficulty_coefficients": {
        "normal": 0.85,
        "elite": 1.0,
        "boss": 1.2,
    },
    "naming": {
        "normal": "{name}",
        "elite": "{prefix}{name}",
        "boss": "{boss_name}",
    },
}
