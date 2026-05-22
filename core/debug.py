# -*- coding: utf-8 -*-
"""
WOA AutoBot 调试/日志模块 (重构自 woa_debug.py)
提供调试开关、日志目录、截图保存等工具函数。
"""

import os
import sys
import time


def woa_debug_enabled():
    """WOA_DEBUG=1 时启用调试模式"""
    return os.environ.get("WOA_DEBUG", "").strip().lower() in ("1", "true", "yes")


_runtime_started = False


def woa_debug_set_runtime_started():
    """标记主循环已启动，此后不再输出运行时调试日志"""
    global _runtime_started
    _runtime_started = True


def woa_debug_log(msg):
    """仅在启动阶段输出调试日志，运行中不输出"""
    if not woa_debug_enabled():
        return
    if _runtime_started:
        return
    print(f">>> [WOA_DEBUG] {msg}")


def get_woa_debug_dir():
    """返回 woa_debug 目录路径（开发模式：项目目录；打包后：Application Support）"""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            base = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "WOA_AutoBot")
        elif sys.platform == "win32":
            base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WOA_AutoBot")
        else:
            base = os.path.join(os.path.expanduser("~"), ".woa_autobot")
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        base = os.path.dirname(base)  # 从 core/ 向上到项目根目录
    return os.path.join(base, "woa_debug")


# ─── 图像读写（支持中文路径） ──────────────────────────────
def read_image_safe(path):
    """支持中文路径的图片读取"""
    import cv2
    import numpy as np

    if not os.path.exists(path):
        return None
    try:
        img_array = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except Exception:
        return None


def save_image_safe(path, img):
    """支持中文路径的图片保存"""
    if img is None:
        return False
    try:
        import cv2
        is_success, buffer = cv2.imencode(".png", img)
        if is_success:
            with open(path, "wb") as f:
                f.write(buffer)
            return True
        return False
    except Exception:
        return False


# ─── 调试截图保存 ─────────────────────────────────────────
def _make_debug_dir():
    d = os.path.join(get_woa_debug_dir(), "screenshots")
    os.makedirs(d, exist_ok=True)
    return d


def woa_debug_save_img(img, subdir, prefix):
    """保存调试截图（非运行阶段）"""
    if not woa_debug_enabled() or _runtime_started or img is None:
        return
    try:
        from core.platform import IS_WINDOWS
        d = os.path.join(_make_debug_dir(), subdir)
        os.makedirs(d, exist_ok=True)
        ts = time.time()
        # Windows 文件名不能包含冒号
        if IS_WINDOWS:
            ts_str = time.strftime("%H%M%S") + f"_{int((ts % 1) * 1000):03d}"
        else:
            ts_str = time.strftime("%H:%M:%S") + f".{int((ts % 1) * 1000):03d}"
        name = f"{prefix}_{ts_str}.png"
        save_image_safe(os.path.join(d, name), img)
    except Exception:
        pass


def woa_debug_save_screenshot(img, method):
    """保存截图调试文件"""
    woa_debug_save_img(img, "screenshots", f"sc_{method}")


def woa_debug_save_click_before(img, x, y, method):
    """保存点击前的调试截图"""
    woa_debug_save_img(img, "clicks", f"click_{int(x)}_{int(y)}_{method}")


def woa_debug_save_roi(img, roi_name):
    """保存 ROI 区域调试截图"""
    woa_debug_save_img(img, "roi", roi_name)
