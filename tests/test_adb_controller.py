"""ADB Controller 单元测试。"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from src.infrastructure.adb.controller import (
    ADBController, ADBError, ADBConnectionError, ADBCommandError,
    ScreenshotError, ADBDisconnectedError, FatalError,
)
from src.domain.models import NormalizedPoint


class TestADBErrors(unittest.TestCase):
    """异常类测试。"""

    def test_error_codes(self):
        self.assertEqual(ADBConnectionError("test").error_code, "ADB_001")
        self.assertEqual(ADBDisconnectedError("test").error_code, "ADB_002")
        self.assertEqual(ADBCommandError("cmd").error_code, "ADB_003")
        self.assertEqual(ScreenshotError("fail").error_code, "ADB_004")
        self.assertEqual(FatalError("fatal").error_code, "ADB_999")

    def test_error_inheritance(self):
        self.assertIsInstance(ADBConnectionError("t"), ADBError)
        self.assertIsInstance(ScreenshotError("t"), ADBError)


class TestNormalizedPointConversion(unittest.TestCase):
    """归一化坐标转换测试。"""

    def test_to_device(self):
        p = NormalizedPoint(0.5, 0.5)
        self.assertEqual(p.to_device(1600, 900), (800, 450))

    def test_edge_cases(self):
        p = NormalizedPoint(0.0, 0.0)
        self.assertEqual(p.to_device(1600, 900), (0, 0))
        p = NormalizedPoint(1.0, 1.0)
        self.assertEqual(p.to_device(1600, 900), (1600, 900))


class TestADBControllerInit(unittest.TestCase):
    """ADBController 初始化测试。"""

    def test_constructor(self):
        ctrl = ADBController("test_serial", adb_path="/fake/adb")
        self.assertEqual(ctrl.serial, "test_serial")
        self.assertFalse(ctrl.is_connected)
        self.assertEqual(ctrl.get_resolution(), (1600, 900))

    def test_resolution_cache(self):
        ctrl = ADBController("test")
        ctrl.update_resolution_cache(1920, 1080)
        self.assertEqual(ctrl.get_resolution(), (1920, 1080))


if __name__ == "__main__":
    unittest.main()
