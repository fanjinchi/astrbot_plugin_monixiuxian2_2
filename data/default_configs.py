# data/default_configs.py

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
    "rifts": [
        # id 1-5 的内容以 rifts 表 DB 种子为准（migration v15），此处仅保留
        # 与 DB 一致的基础信息 + 宗门准入字段（sect_id/access），避免双写漂移
        {
            "id": 1,
            "name": "青云秘境",
            "level": 0,
            "exp_range": [500, 1500],
            "gold_range": [200, 800],
        },
        {
            "id": 2,
            "name": "落日峡谷",
            "level": 3,
            "exp_range": [1500, 4000],
            "gold_range": [500, 2000],
        },
        {
            "id": 3,
            "name": "万妖洞",
            "level": 6,
            "exp_range": [3000, 8000],
            "gold_range": [1000, 5000],
        },
        {
            "id": 4,
            "name": "玄冰地宫",
            "level": 10,
            "exp_range": [5000, 15000],
            "gold_range": [2000, 10000],
        },
        {
            "id": 5,
            "name": "上古遗迹",
            "level": 15,
            "exp_range": [10000, 30000],
            "gold_range": [5000, 20000],
        },
        {
            "id": 6,
            "name": "青云剑冢",
            "level": 3,
            "exp_range": [300, 900],
            "gold_range": [100, 400],
            "sect_id": "qingyun",  # 宗门专属秘境
            "access": "sect_member",  # 仅本宗成员可探索（7.2 接线准入校验）
        },
    ],
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
