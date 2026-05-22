# -*- coding: utf-8 -*-
"""
WOA AutoBot - 核心共享模块
提供跨平台工具、资源路径、调试日志、常量定义。
"""

from core.platform import (
    IS_WINDOWS,
    IS_MAC,
    IS_LINUX,
    IS_POSIX,
    ADB_EXE_NAME,
    CREATE_NO_WINDOW,
    lock_file,
    unlock_file,
    try_lock_file,
    get_app_data_dir,
    safe_subprocess_run,
    safe_popen_wait,
)
from core.debug import (
    woa_debug_enabled,
    woa_debug_set_runtime_started,
    woa_debug_log,
    get_woa_debug_dir,
    read_image_safe,
    save_image_safe,
    woa_debug_save_img,
    woa_debug_save_screenshot,
    woa_debug_save_click_before,
    woa_debug_save_roi,
)
from core.resources import (
    get_resource_path,
    get_bundled_resource_path,
    get_icon_dir,
    ICON_DIR,
)
from core.constants import (
    FEATURE_GUARD_TOKEN,
    LOCAL_VERSION,
    OFFICIAL_REPO_URL,
    OFFICIAL_REPO_NAME,
    ONLINE_VERSION_PATH,
    MAX_INSTANCES,
    DEFAULT_FONT,
    MONO_FONT,
    MUMU_PORTS,
    REQUIRED_GUARD_MODULES,
)

__all__ = [
    # platform
    "IS_WINDOWS", "IS_MAC", "IS_LINUX", "IS_POSIX",
    "ADB_EXE_NAME", "CREATE_NO_WINDOW",
    "lock_file", "unlock_file", "try_lock_file",
    "get_app_data_dir", "safe_subprocess_run", "safe_popen_wait",
    # debug
    "woa_debug_enabled", "woa_debug_set_runtime_started", "woa_debug_log",
    "get_woa_debug_dir", "read_image_safe", "save_image_safe",
    "woa_debug_save_img", "woa_debug_save_screenshot",
    "woa_debug_save_click_before", "woa_debug_save_roi",
    # resources
    "get_resource_path", "get_bundled_resource_path", "get_icon_dir", "ICON_DIR",
    # constants
    "FEATURE_GUARD_TOKEN", "LOCAL_VERSION",
    "OFFICIAL_REPO_URL", "OFFICIAL_REPO_NAME", "ONLINE_VERSION_PATH",
    "MAX_INSTANCES", "DEFAULT_FONT", "MONO_FONT",
    "MUMU_PORTS", "REQUIRED_GUARD_MODULES",
]
