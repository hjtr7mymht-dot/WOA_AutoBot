# -*- coding: utf-8 -*-
"""
WOA AutoBot - 全局常量 (消除在 4 个文件中重复定义的魔法值)
"""

from core.platform import IS_WINDOWS, IS_MAC

# ─── 版本与仓库 ──────────────────────────────────────────
LOCAL_VERSION = "1.2.8"
OFFICIAL_REPO_URL = "https://github.com/hjtr7mymht-dot/WOA_AutoBot"
OFFICIAL_REPO_NAME = "hjtr7mymht-dot/WOA_AutoBot"
ONLINE_VERSION_PATH = "version.json"
ARPA_REPO_URL = "https://github.com/hjtr7mymht-dot/ARPA-FOR-WOA"
ARPA_REPO_NAME = "hjtr7mymht-dot/ARPA-FOR-WOA"

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
