# WOA 调试/日志工具模块
# 从 adb_controller.py 提取的独立调试功能

import os
import sys
import time


# 调试开关：WOA_DEBUG=1 时仅在启动阶段输出连接/方案测试的详细日志，运行中不再刷屏
def _woa_debug_enabled():
    return os.environ.get("WOA_DEBUG", "").strip().lower() in ("1", "true", "yes")

_woa_debug_runtime_started = False  # 主循环开始后为 True，此后不再输出运行时调试日志、不保存截/ROI

def woa_debug_set_runtime_started():
    global _woa_debug_runtime_started
    _woa_debug_runtime_started = True

def _woa_debug_log(msg):
    if not _woa_debug_enabled():
        return
    if _woa_debug_runtime_started:
        return  # 运行中不输出，仅启动阶段（连接、方案测试）输出
    print(f">>> [WOA_DEBUG] {msg}")

def get_woa_debug_dir():
    """返回 woa_debug 目录路径（兼容开发与打包）"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "woa_debug")

def read_image_safe(path):
    """支持中文路径的图片读取方式"""
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
    """支持中文路径的图片保存方式"""
    if img is None:
        return False
    try:
        import cv2
        is_success, buffer = cv2.imencode(".png", img)
        if is_success:
            with open(path, "wb") as f:
                f.write(buffer)
            return True
    except Exception:
        pass
    return False

def _woa_debug_save_img(img, subdir, prefix):
    """仅在方案测试阶段保存图片，运行中不再保存"""
    if not _woa_debug_enabled() or img is None or _woa_debug_runtime_started:
        return
    try:
        base = os.path.join(get_woa_debug_dir(), subdir)
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png")
        if save_image_safe(path, img):
            print(f">>> [WOA_DEBUG] 已保存: {path}")  # 方案测试阶段直接 print，不走 _woa_debug_log
    except Exception:
        pass

def _woa_debug_save_screenshot(img, method):
    """运行中不再保存截图，仅在方案测试时由 run_all_method_tests 保存"""
    if _woa_debug_runtime_started:
        return
    # 以下逻辑仅在启动阶段有效，方案测试会直接调用 _woa_debug_save_img
    if not _woa_debug_enabled() or img is None:
        return
    # 保留计数避免重复，但实际不再保存（run_all_method_tests 自己保存 method_test）
    pass

def _woa_debug_save_click_before(img, x, y, method):
    """运行中不再保存点击前截图"""
    if _woa_debug_runtime_started or not _woa_debug_enabled() or img is None:
        return
    pass

def woa_debug_save_roi(img, roi_name):
    """调试精简：不再保存 ROI 区域图"""
    return
