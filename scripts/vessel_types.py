"""
船舶類型定義與過濾
參考：data-collectors/collectors/ship_ais.py
"""

# 船舶類型代碼對照表
VESSEL_TYPE_NAMES = {
    0: "未指定",
    20: "地效翼船",
    30: "漁船",
    31: "拖船",
    32: "拖船（長度>200m或寬度>25m）",
    33: "疏浚船",
    34: "潛水作業船",
    35: "軍艦",
    36: "帆船",
    37: "遊艇",
    40: "高速船",
    50: "引水船",
    51: "搜救船",
    52: "港口小艇",
    53: "防污船",
    55: "執法船",
    # 60-69: 客輪
    60: "客輪",
    61: "客輪-危險貨物A",
    62: "客輪-危險貨物B",
    63: "客輪-危險貨物C",
    64: "客輪-危險貨物D",
    69: "客輪-無額外資訊",
    # 70-79: 貨船
    70: "貨船",
    71: "貨船-危險貨物A",
    72: "貨船-危險貨物B",
    73: "貨船-危險貨物C",
    74: "貨船-危險貨物D",
    79: "貨船-無額外資訊",
    # 80-89: 油輪
    80: "油輪",
    81: "油輪-危險貨物A",
    82: "油輪-危險貨物B",
    83: "油輪-危險貨物C",
    84: "油輪-危險貨物D",
    89: "油輪-無額外資訊",
    90: "其他"
}

# 船舶類型分類群組
VESSEL_CATEGORIES = {
    "fishing": [30],                          # 漁船
    "cargo": list(range(70, 80)),             # 貨船 70-79
    "tanker": list(range(80, 90)),            # 油輪 80-89
    "passenger": list(range(60, 70)),         # 客輪 60-69
    "tug": [31, 32],                          # 拖船
    "military": [35],                         # 軍艦
    "sailing": [36, 37],                      # 帆船/遊艇
    "service": [50, 51, 52, 53, 55, 33, 34],  # 服務船舶
    "highspeed": [40],                        # 高速船
    "other": [0, 20, 90]                      # 其他
}

# 航行狀態代碼對照表
NAV_STATUS_NAMES = {
    0: "航行中",
    1: "錨泊中",
    2: "失去控制",
    3: "操縱受限",
    4: "受吃水限制",
    5: "繫泊中",
    6: "擱淺",
    7: "從事捕魚",
    8: "帆船航行",
    11: "拖曳中",
    12: "推頂中",
    14: "AIS-SART",
    15: "未定義"
}


def get_vessel_type_name(type_code: int) -> str:
    """取得船舶類型名稱"""
    return VESSEL_TYPE_NAMES.get(type_code, f"未知類型({type_code})")


def get_nav_status_name(status_code: int) -> str:
    """取得航行狀態名稱"""
    return NAV_STATUS_NAMES.get(status_code, f"未知狀態({status_code})")


def filter_by_category(ships: list, category: str) -> list:
    """
    依據類別過濾船舶

    Args:
        ships: 船舶資料列表，每筆需有 'vesselType' 欄位
        category: 類別名稱 (fishing, cargo, tanker, passenger, tug, military, sailing, service, highspeed, other)
                  或 'all' 表示不過濾

    Returns:
        過濾後的船舶列表
    """
    if category == "all":
        return ships

    if category not in VESSEL_CATEGORIES:
        raise ValueError(f"未知類別: {category}，可用類別: {list(VESSEL_CATEGORIES.keys())}")

    valid_types = set(VESSEL_CATEGORIES[category])
    return [ship for ship in ships if ship.get("vessel_type", 0) in valid_types]


def get_category_name(category: str) -> str:
    """取得類別的中文名稱"""
    names = {
        "all": "所有船舶",
        "fishing": "漁船",
        "cargo": "貨船",
        "tanker": "油輪",
        "passenger": "客輪",
        "tug": "拖船",
        "military": "軍艦",
        "sailing": "帆船/遊艇",
        "service": "服務船舶",
        "highspeed": "高速船",
        "other": "其他"
    }
    return names.get(category, category)
