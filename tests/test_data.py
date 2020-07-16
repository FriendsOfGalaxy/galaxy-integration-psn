from galaxy.api.consts import LicenseType
from galaxy.api.types import Achievement, UserInfo, Game, LicenseInfo, SubscriptionGame
from cache import Cache, CacheEntry

COMMUNICATION_ID = "NPWR11556_00"

DEFAULT_LICENSE = LicenseInfo(LicenseType.SinglePurchase, None)

GAMES = [
    Game("CUSA07917_00", "Tooth and Tail", [], DEFAULT_LICENSE),
    Game("CUSA02000_00", "Batman: Return to Arkham - Arkham City", [], DEFAULT_LICENSE),
    Game("CUSA05603_00", "Batman", [], DEFAULT_LICENSE),
    Game("CUSA01427_00", "Game of Thrones", [], DEFAULT_LICENSE),
    Game("CUSA01858_00", "Grim Fandango Remastered", [], DEFAULT_LICENSE),
    Game("CUSA04607_00", "Batman: Return to Arkham - Arkham Asylum", [], DEFAULT_LICENSE),
    Game("CUSA00860_00", "Tales from the Borderlands", [], DEFAULT_LICENSE),
    Game("CUSA07320_00", "Horizon Zero Dawnâ„¢", [], DEFAULT_LICENSE),
    Game("CUSA07140_00", "Dreamfall Chapters", [], DEFAULT_LICENSE),
    Game("CUSA08487_00", "Life is Strange: Before the Storm", [], DEFAULT_LICENSE)
]

DLCS = [
    Game("CUSA07719_00", "Dreamfall Chapters (Original Soundtrack)", [], DEFAULT_LICENSE)
]

TITLES = GAMES + DLCS

BACKEND_GAME_TITLES_WITHOUT_DLC = {
    "start": 0,
    "size": 10,
    "totalResults": 10,
    "titles": [
        {"titleId": "CUSA07917_00", "name": "Tooth and Tail"},
        {"titleId": "CUSA02000_00", "name": "Batman: Return to Arkham - Arkham City"},
        {"titleId": "CUSA05603_00", "name": "Batman"},
        {"titleId": "CUSA01427_00", "name": "Game of Thrones"},
        {"titleId": "CUSA01858_00", "name": "Grim Fandango Remastered"},
        {"titleId": "CUSA04607_00", "name": "Batman: Return to Arkham - Arkham Asylum"},
        {"titleId": "CUSA00860_00", "name": "Tales from the Borderlands"},
        {"titleId": "CUSA07320_00", "name": "Horizon Zero Dawnâ„¢"},
        {"titleId": "CUSA07140_00", "name": "Dreamfall Chapters"},
        {"titleId": "CUSA08487_00", "name": "Life is Strange: Before the Storm"}
    ]
}

BACKEND_GAME_TITLES_WITH_DLC = {
    "start": 0,
    "size": 11,
    "totalResults": 11,
    "titles": [
        {"titleId": "CUSA07917_00", "name": "Tooth and Tail"},
        {"titleId": "CUSA02000_00", "name": "Batman: Return to Arkham - Arkham City"},
        {"titleId": "CUSA05603_00", "name": "Batman"},
        {"titleId": "CUSA01427_00", "name": "Game of Thrones"},
        {"titleId": "CUSA01858_00", "name": "Grim Fandango Remastered"},
        {"titleId": "CUSA04607_00", "name": "Batman: Return to Arkham - Arkham Asylum"},
        {"titleId": "CUSA00860_00", "name": "Tales from the Borderlands"},
        {"titleId": "CUSA07320_00", "name": "Horizon Zero Dawnâ„¢"},
        {"titleId": "CUSA07719_00", "name": "Dreamfall Chapters (Original Soundtrack)"},
        {"titleId": "CUSA07140_00", "name": "Dreamfall Chapters"},
        {"titleId": "CUSA08487_00", "name": "Life is Strange: Before the Storm"}
    ]
}

TITLE_TO_COMMUNICATION_ID = {
    "CUSA07917_00": ["NPWR12784_00"],
    "CUSA02000_00": ["NPWR10584_00"],
    "CUSA05603_00": ["NPWR11243_00"],
    "CUSA01427_00": ["NPWR07882_00"],
    "CUSA01858_00": ["NPWR07722_00"],
    "CUSA04607_00": ["NPWR10793_00"],
    "CUSA00860_00": ["NPWR07228_00"],
    "CUSA07320_00": ["NPWR11556_00"],
    "CUSA07719_00": [],
    "CUSA07140_00": ["NPWR12456_00"],
    "CUSA08487_00": ["NPWR13354_00"]
}

BACKEND_TROPHIES = {
    "trophies": [
        {
            "trophyId": 0,
            "fromUser": {"onlineId": "user-id", "earned": False},
            "trophyName": "achievement 0",
            "groupId": "default"
        },
        {
            "trophyId": 1,
            "fromUser": {"onlineId": "user-id", "earned": True, "earnedDate": "1987-01-22T09:01:33Z"},
            "trophyName": "achievement 1",
            "groupId": "default"
        },
        {
            "trophyId": 2,
            "fromUser": {"onlineId": "user-id", "earned": True, "earnedDate": "2011-10-16T16:33:18Z"},
            "trophyName": "achievement 2",
            "groupId": "default"
        },
        {
            "trophyId": 3,
            "fromUser": {"onlineId": "user-id", "earned": False, "earnedDate": "2013-12-29T09:18:33Z"},
            "trophyName": "achievement 3",
            "groupId": "001"
        },
        {
            "trophyId": 4,
            "fromUser": {"onlineId": "user-id", "earned": False},
            "trophyName": "achievement 4",
            "groupId": "001"
        },
        {
            "trophyId": 5,
            "fromUser": {"onlineId": "user-id", "earned": False, "earnedDate": "1987-02-07T10:14:42Z"},
            "trophyName": "achievement 5",
            "groupId": "022"
        },
    ]
}

UNLOCKED_ACHIEVEMENTS = [
    Achievement(achievement_id="NPWR11556_00_1", achievement_name="achievement 1", unlock_time=538304493.0,),
    Achievement(achievement_id="NPWR11556_00_2", achievement_name="achievement 2", unlock_time=1318782798.0)
]

TROPHIES_CACHE = Cache()
TROPHIES_CACHE._entries ={"NPWR11556_00": CacheEntry(value=UNLOCKED_ACHIEVEMENTS, timestamp=1490374318.0)}


BACKEND_USER_PROFILES = {
    "start": 0,
    "size": 7,
    "totalResults": 7,
    "profiles": [{
        "accountId": 1,
        "onlineId": "veryopenperson",
        "avatarUrls": [{"avatarUrl": "http://playstation.net/avatar/DefaultAvatar_m.png"}],
        "primaryOnlineStatus": "online",
        "presences": [{
            "onlineStatus": "online",
            "platform": "PS4"
        }],
        "friendRelation": "friend"
    }, {
        "accountId": 2,
        "onlineId": "ImTestingSth1",
        "avatarUrls": [{"avatarUrl": "http://playstation.net/avatar/DefaultAvatar_m.png"}],
        "primaryOnlineStatus": "offline",
        "presences": [{
            "onlineStatus": "offline",
            "lastOnlineDate": "2019-03-04T09:15:19Z"
        }],
        "friendRelation": "friend",
    }, {
        "accountId": 3,
        "onlineId": "venom6683",
        "avatarUrls": [{"avatarUrl": "http://playstation.net/avatar/WWS_E/E0007_m.png"}],
        "primaryOnlineStatus": "online",
        "presences": [{
            "onlineStatus": "online",
            "platform": "PS4"
        }],
        "friendRelation": "friend"
    }, {
        "accountId": 4,
        "onlineId": "l_Touwa_l",
        "avatarUrls": [{"avatarUrl": "http://playstation.net/avatar/DefaultAvatar_m.png"}],
        "primaryOnlineStatus": "offline",
        "presences": [{
            "onlineStatus": "offline",
            "lastOnlineDate": "2018-03-22T18:50:58Z"
        }],
        "friendRelation": "friend"
    }, {
        "accountId": 5,
        "onlineId": "Resilb",
        "avatarUrls": [{"avatarUrl": "http://playstation.net/avatar/DefaultAvatar_m.png"}],
        "primaryOnlineStatus": "offline",
        "presences": [{
            "onlineStatus": "offline",
            "lastOnlineDate": "2019-02-22T23:31:16Z"
        }],
        "friendRelation": "friend"
    }, {
        "accountId": 6,
        "onlineId": "Di_PL",
        "avatarUrls": [{"avatarUrl": "http://playstation.net/avatar/DefaultAvatar_m.png"}],
        "primaryOnlineStatus": "offline",
        "presences": [{
            "onlineStatus": "offline"
        }],
        "friendRelation": "friend"
    }, {
        "accountId": 7,
        "onlineId": "nyash",
        "avatarUrls": [{"avatarUrl": "http://playstation.net/avatar/3RD/E9A0BB8BC40BBF9B_M.png"}],
        "primaryOnlineStatus": "offline",
        "presences": [{
            "onlineStatus": "offline",
            "lastOnlineDate": "2019-02-25T01:52:44Z"
        }],
        "friendRelation": "friend"
    }]
}

FRIEND_INFO_LIST = [
    UserInfo(user_id="1", user_name="veryopenperson", avatar_url="http://playstation.net/avatar/DefaultAvatar_m.png", profile_url="https://my.playstation.com/profile/veryopenperson"),
    UserInfo(user_id="2", user_name="ImTestingSth1", avatar_url="http://playstation.net/avatar/DefaultAvatar_m.png", profile_url="https://my.playstation.com/profile/ImTestingSth1"),
    UserInfo(user_id="3", user_name="venom6683", avatar_url="http://playstation.net/avatar/WWS_E/E0007_m.png", profile_url="https://my.playstation.com/profile/venom6683"),
    UserInfo(user_id="4", user_name="l_Touwa_l", avatar_url="http://playstation.net/avatar/DefaultAvatar_m.png", profile_url="https://my.playstation.com/profile/l_Touwa_l"),
    UserInfo(user_id="5", user_name="Resilb", avatar_url="http://playstation.net/avatar/DefaultAvatar_m.png", profile_url="https://my.playstation.com/profile/Resilb"),
    UserInfo(user_id="6", user_name="Di_PL", avatar_url="http://playstation.net/avatar/DefaultAvatar_m.png", profile_url="https://my.playstation.com/profile/Di_PL"),
    UserInfo(user_id="7", user_name="nyash", avatar_url="http://playstation.net/avatar/3RD/E9A0BB8BC40BBF9B_M.png", profile_url="https://my.playstation.com/profile/nyash")
]

CONTEXT = {'NPWR16617_00': 1569108306.0, 'NPWR11453_00': 1567944392.0, 'NPWR16532_00': 1567545710.0, 'NPWR10526_00': 1566592417.0, 'NPWR15355_00': 1554141081.0, 'NPWR16687_00': 1553463882.0, 'NPWR13157_00': 1552250990.0, 'NPWR09412_00': 1549056652.0, 'NPWR12518_00': 1546473026.0, 'NPWR14695_00': 1546127236.0, 'NPWR07028_00': 1546030925.0, 'NPWR14376_00': 1545849865.0, 'NPWR13320_00': 1544914476.0, 'NPWR11631_00': 1544911126.0, 'NPWR06302_00': 1544888234.0, 'NPWR06685_00': 1544881604.0, 'NPWR13650_00': 1544828007.0, 'NPWR12662_00': 1544733951.0, 'NPWR15453_00': 1544646241.0, 'NPWR08260_00': 1544561891.0, 'NPWR13648_00': 1544555969.0, 'NPWR14065_00': 1543755146.0, 'NPWR07897_00': 1528635032.0, 'NPWR11469_00': 1528580350.0, 'NPWR08899_00': 1528349310.0, 'NPWR14963_00': 1528225627.0, 'NPWR11704_00': 1528053359.0, 'NPWR10261_00': 1526112707.0, 'NPWR14513_00': 1525182963.0, 'NPWR13970_00': 1524598278.0, 'NPWR05424_00': 1523813120.0, 'NPWR11920_00': 1523381863.0, 'NPWR07942_00': 1523299564.0, 'NPWR09187_00': 1523137528.0, 'NPWR14858_00': 1522962802.0, 'NPWR08864_00': 1522791973.0, 'NPWR09600_00': 1520813610.0, 'NPWR13161_00': 1519857527.0, 'NPWR09694_00': 1518818903.0, 'NPWR10810_00': 1518302892.0, 'NPWR09071_00': 1516049483.0, 'NPWR11866_00': 1514765179.0, 'NPWR08840_00': 1514647655.0, 'NPWR09304_00': 1514640325.0, 'NPWR08844_00': 1514401356.0, 'NPWR13263_00': 1514250188.0, 'NPWR06221_00': 1513543300.0, 'NPWR11659_00': 1510523951.0, 'NPWR10569_00': 1509043324.0, 'NPWR13412_00': 1508862631.0, 'NPWR04915_00': 1505244423.0, 'NPWR12845_00': 1504894257.0, 'NPWR12042_00': 1504214093.0, 'NPWR08935_00': 1502561238.0, 'NPWR06040_00': 1500916492.0, 'NPWR10876_00': 1500591963.0, 'NPWR08268_00': 1499886156.0, 'NPWR09350_00': 1499705028.0, 'NPWR08661_00': 1498935916.0, 'NPWR05818_00': 1494083469.0, 'NPWR08983_00': 1490903238.0, 'NPWR11556_00': 1490374318.0, 'NPWR04914_00': 1489329259.0}


USER_ACCOUNTS_DATA = {
    'language': 'en_US',
    'legalCountry': 'US',
    'dateOfBirth': '2003-02-12',
    'region': 'SCEA'
}


PSPLUS_GAMES = [
    SubscriptionGame(game_title='BioShock: The Collection', game_id='CUSA03979_00'),
    SubscriptionGame(game_title='The Sims™ 4', game_id='CUSA09209_00'),
    SubscriptionGame(game_title='Firewall Zero Hour™', game_id='CUSA09831_00')
]

PSNOW_GAMES = [
    SubscriptionGame(game_title='ABZÛ', game_id='CUSA03349_00'),
    SubscriptionGame(game_title='ADR1FT', game_id='CUSA02572_00'),
    SubscriptionGame(game_title='Back to Bed', game_id='CUSA02537_00'),
    SubscriptionGame(game_title='Watch Dogs 2', game_id='CUSA04459_00')
]

BACKEND_PSNOW_GAMES = {
	"id": "STORE-MSF192018-APOLLOROOT",
	"timestamp": 1594137933000,
	"revision": 1072,
	"categories": [{
		"id": "STORE-MSF192018-APOLLOTOP20",
		"timestamp": 1594137934000,
		"revision": 321,
		"name": "What's Hot",
		"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/STORE-MSF192018-APOLLOTOP20/1594137934?start=0&size=300&gkb=1&gkb2=1",
		"games": [{
			"id": "UP2002-CUSA01163_00-ROCKETLEAGUENA01",
			"timestamp": 1594600184000,
			"revision": 110,
			"name": "Rocket League®",
			"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/UP2002-CUSA01163_00-ROCKETLEAGUENA01/1594600184"
		}, {
			"id": "UP0001-CUSA01800_00-RAINBOWSIXSIEGE0",
			"timestamp": 1594407661000,
			"revision": 54,
			"name": "TOM CLANCY’S RAINBOW SIX® SIEGE",
			"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/UP0001-CUSA01800_00-RAINBOWSIXSIEGE0/1594407661"
		}]
	}, {
		"id": "STORE-MSF192018-APOLLOA",
		"timestamp": 1591117167000,
		"revision": 154,
		"name": "A",
		"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/STORE-MSF192018-APOLLOA/1591117167?start=0&size=300&gkb=1&gkb2=1",
		"games": [{
			"id": "UP4040-CUSA03349_00-ABZUGAME00000000",
			"timestamp": 1594282917000,
			"revision": 17,
			"name": "ABZÛ",
			"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/UP4040-CUSA03349_00-ABZUGAME00000000/1594282917"
		}, {
			"id": "UP4040-CUSA02572_00-ADR1FTGAME000001",
			"timestamp": 1594282914000,
			"revision": 13,
			"name": "ADR1FT",
			"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/UP4040-CUSA02572_00-ADR1FTGAME000001/1594282914"
		}]
	}, {
		"id": "STORE-MSF192018-APOLLOB",
		"timestamp": 1591241188000,
		"revision": 163,
		"name": "B",
		"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/STORE-MSF192018-APOLLOB/1591241188?start=0&size=300&gkb=1&gkb2=1",
		"games": [{
			"id": "UP2135-CUSA02537_00-BACKTOBEDLOOTPS4",
			"timestamp": 1594138014000,
			"revision": 5,
			"name": "Back to Bed",
			"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/UP2135-CUSA02537_00-BACKTOBEDLOOTPS4/1594138014"
		}]
	}, {
		"id": "STORE-MSF192018-APOLLOW",
		"timestamp": 1594137934000,
		"revision": 121,
		"name": "W - Z",
		"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/STORE-MSF192018-APOLLOW/1594137934?start=0&size=300&gkb=1&gkb2=1",
		"games": [{
			"id": "UP0001-CUSA04459_00-WD2FULLGAME00000",
			"timestamp": 1594601462000,
			"revision": 37,
			"name": "Watch Dogs 2",
			"url": "https://commerce1.api.np.km.playstation.net/store/api/ps4now/00_09_000/container/US/en/999/UP0001-CUSA04459_00-WD2FULLGAME00000/1594601462"
		}]
    }]
}

BACKEND_STORE_FREEPSPLUS_CONTAINER = {
    "data": {
        "attributes": {
            "attributes": {},
            "id": "STORE-MSF77008-PSPLUSFREEGAMES",
            "type": "container",
            "relationships": {
                "children": {
                    "data": [
                        {
                            "id": "UP1001-CUSA03979_00-BIOSHOCKCOLLECTN",
                            "type": "game"
                        },
                        {
                            "id": "UP0006-CUSA09209_00-THESIMS400000000",
                            "type": "game"
                        },
                        {
                            "id": "UP9000-CUSA09831_00-FIREWALL00000000",
                            "type": "game-related"
                        }
                    ]
                },
            }
        },
    },
    "included": [
        {
            "attributes": {
                "name": "BioShock: The Collection",
                "platforms": ["PS4"]
            },
            "id": "UP1001-CUSA03979_00-BIOSHOCKCOLLECTN",
            "type": "game"
        },
        {
            "attributes": {
                "name": "Full Game",
                "platforms": [0, 10, 13],
            },
            "id": "UP0006-CUSA09209_00-THESIMS400000000-U002",
            "type": "legacy-skus"
        },
        {
            "attributes": {
                "name": "The Sims™ 4",
                "platforms": ["PS4"]
            },
            "id": "UP0006-CUSA09209_00-THESIMS400000000",
            "type": "game"
        },
        {
            "attributes": {
                "name": "Firewall Zero Hour™",
                "platforms": ["PS4"],
                "ps-vr-compatibility": "required",
            },
            "id": "UP9000-CUSA09831_00-FIREWALL00000000-U002",
            "type": "game-related"
        },
    ]
}
