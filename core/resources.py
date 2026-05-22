# -*- coding: utf-8 -*-
"""
WOA AutoBot - 资源路径工具 (消除 gui_launcher 与 main_adb 中重复定义)
统一资源路径获取逻辑，兼容 PyInstaller / Nuitka / 源码运行。
"""

import os
import sys

# 缓存（可选，由调用方决定是否启用 cachetools）
try:
    from cachetools import cached, TTLCache
    _HAS_CACHE = True
except ImportError:
    _HAS_CACHE = False

ICON_DIR = "icon"


def get_resource_path(relative_path):
    """获取资源路径，兼容 PyInstaller、Nuitka 与源码运行"""
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(sys.executable)
        return os.path.join(base, relative_path)

    # 源码模式：尝试多个可能位置
    try:
        base_path = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.dirname(base_path)  # core/ -> 项目根
    except NameError:
        base_path = os.getcwd()

    candidates = [
        os.path.join(base_path, relative_path),
        os.path.join(os.getcwd(), relative_path),
    ]
    if hasattr(sys, "executable"):
        candidates.append(os.path.join(os.path.dirname(sys.executable), relative_path))

    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def get_bundled_resource_path(relative_path):
    """获取打包后资源路径（兼容 PyInstaller _MEIPASS 和 Nuitka）"""
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(sys.executable)
        return os.path.join(base, relative_path)
    else:
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            base = os.path.dirname(base)  # core/ -> 项目根
        except NameError:
            base = os.getcwd()
        return os.path.join(base, relative_path)


def get_icon_dir():
    return os.path.join(get_resource_path(ICON_DIR), "")


# 可选缓存
if _HAS_CACHE:
    get_resource_path = cached(cache=TTLCache(maxsize=128, ttl=300))(get_resource_path)
    get_bundled_resource_path = cached(cache=TTLCache(maxsize=128, ttl=300))(get_bundled_resource_path)
