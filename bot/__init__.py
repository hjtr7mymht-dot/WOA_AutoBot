# -*- coding: utf-8 -*-
"""
WOA AutoBot - Bot 引擎包

⚠️ 归档说明 (2026-06):
  ConfigMixin / TowerMixin 已从 WoaBot 继承链中移除。
  WoaBot (main_adb.py) 完整覆盖了所有方法，Mixin 实为死代码。
  保留源文件仅作像素阈值等历史参考，不再参与运行时继承。
"""

# 保留导入供外部参考（如有脚本单独引用）
# 使用 try/except 防止缺少 cv2 等依赖导致包导入崩溃
try:
    from bot.config import ConfigMixin  # noqa: F401
except ImportError:
    ConfigMixin = None  # type: ignore

try:
    from bot.tower import TowerMixin  # noqa: F401
except ImportError:
    TowerMixin = None  # type: ignore

__all__ = ["ConfigMixin", "TowerMixin"]
