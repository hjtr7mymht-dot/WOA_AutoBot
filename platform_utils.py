# -*- coding: utf-8 -*-
"""
向后兼容模块 — 所有实现已迁移至 core.platform
新代码请直接从 core 导入: from core import IS_WINDOWS, lock_file, ...
"""
from core.platform import (
    lock_file,
    unlock_file,
    try_lock_file,
    CREATE_NO_WINDOW,
    IS_WINDOWS,
    IS_MAC,
    IS_LINUX,
    IS_POSIX,
    ADB_EXE_NAME,
    get_app_data_dir,
    get_adb_bundled_path,
    safe_subprocess_run,
    safe_popen_wait,
)
