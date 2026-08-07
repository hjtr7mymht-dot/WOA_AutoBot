# -*- coding: utf-8 -*-
"""
向后兼容模块 — 所有实现已迁移至 core.debug
新代码请直接从 core 导入: from core import woa_debug_log, read_image_safe, ...
"""
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

# 向后兼容旧命名（下划线前缀版本）
_woa_debug_enabled = woa_debug_enabled
_woa_debug_log = woa_debug_log
_woa_debug_save_img = woa_debug_save_img
_woa_debug_save_screenshot = woa_debug_save_screenshot
_woa_debug_save_click_before = woa_debug_save_click_before
