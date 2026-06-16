# -*- coding: utf-8 -*-
"""
WOA AutoBot - 全局常量 (消除在 4 个文件中重复定义的魔法值)
"""

from core.platform import IS_WINDOWS, IS_MAC

# ─── 版本与仓库 ──────────────────────────────────────────
LOCAL_VERSION = "1.4.0"
OFFICIAL_REPO_URL = "https://github.com/hjtr7mymht-dot/WOA_AutoBot"
OFFICIAL_REPO_NAME = "hjtr7mymht-dot/WOA_AutoBot"
ONLINE_VERSION_PATH = "version.json"
ARPA_REPO_URL = "https://github.com/hjtr7mymht-dot/ARPA-FOR-WOA"
ARPA_REPO_NAME = "hjtr7mymht-dot/ARPA-FOR-WOA"

# ─── 右侧类别栏按钮（图像识别 + 坐标回退） ─────────────
# 所有坐标以 1600×900 归一化分辨率为基准（REF_WIDTH × REF_HEIGHT）
# 运行时根据设备实际分辨率自动缩放
REF_WIDTH = 1600
REF_HEIGHT = 900

# 搜索区域：游戏右侧竖排类别按钮区域 (x, y, w, h) — 归一化空间
SIDEBAR_SEARCH_ROI = (1520, 400, 90, 680)

SIDEBAR_CATEGORIES = [
    # icon_off: 未选中图标（亮灰圆底）  icon_on: 选中图标（深灰圆底）
    # verify_pos: 像素验证坐标 (x, y)，用于判断按钮是否高亮选中
    # 选中时该位置像素为浅色(light)，未选中时为深色(dark)
    # 所有坐标均为 1600×900 归一化空间参考值
    {"key": "favorites", "label": "❤️ 喜爱/合约",   "icon_off": "love_off.png",           "icon_on": "love_on.png",
     "fallback_pos": (1537, 400), "verify_pos": (1537, 400)},
    # 第2个按钮是"待处理全部"（不需要处理，跳过）
    {"key": "fleet",     "label": "⚠️ 机队",       "icon_off": "myairbase_off.png",      "icon_on": "myairbase_on.png",
     "fallback_pos": (1537, 546), "verify_pos": (1537, 546)},
    {"key": "players",   "label": "🟢 其他玩家",   "icon_off": "otherairbase_off.png",   "icon_on": "otherairbase_on.png",
     "fallback_pos": (1537, 619), "verify_pos": (1537, 619)},
    {"key": "event",     "label": "🔵 活动飞机",   "icon_off": "spairbase_off.png",      "icon_on": "spairbase_on.png",
     "fallback_pos": (1537, 689), "verify_pos": (1537, 689)},
    {"key": "passenger", "label": "✈️ 客机",       "icon_off": "keji_off.png",           "icon_on": "keji_on.png",
     "fallback_pos": (1537, 759), "verify_pos": (1537, 759)},
    {"key": "cargo",     "label": "📦 货机",       "icon_off": "huoji_off.png",          "icon_on": "huoji_on.png",
     "fallback_pos": (1537, 829), "verify_pos": (1537, 829)},
]

CATEGORY_CYCLE_INTERVAL = 15.0

# ─── 功能完整性守卫标记 ──────────────────────────────────
FEATURE_GUARD_TOKEN = "WOA_DONATE_GUARD_V1"

# ─── 实例与资源 ──────────────────────────────────────────
MAX_INSTANCES = 3
DEFAULT_APP_DATA_DIR = "WOA_AutoBot"

# ─── MuMu 常用 ADB 端口 ──────────────────────────────────
MUMU_PORTS = {16384, 16385, 16416, 16448, 7555, 5555}

# ─── 守卫模块列表 ────────────────────────────────────────
REQUIRED_GUARD_MODULES = (
    "adb_controller",
    "main_adb",
    "simple_ocr",
    "emulator_discovery",
)

# ─── 跨平台默认字体 ──────────────────────────────────────
if IS_MAC:
    DEFAULT_FONT = "SF Pro"
    MONO_FONT = "Menlo"
elif IS_WINDOWS:
    DEFAULT_FONT = "Microsoft YaHei UI"
    MONO_FONT = "Consolas"
else:
    DEFAULT_FONT = "Sans"
    MONO_FONT = "Monospace"
