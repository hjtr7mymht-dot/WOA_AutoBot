"""CV Matcher 单元测试。"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from src.infrastructure.cv.matcher import (
    MultiScaleTemplateMatcher, RingSampler, LRUTemplateCache,
    ResolutionAdapter, MatchMethod, LOW_CONTRAST_TEMPLATES,
    get_confidence_threshold,
)
from src.domain.models import NormalizedPoint


class TestLRUCache(unittest.TestCase):
    """LRU 缓存测试。"""

    def test_put_get(self):
        cache = LRUTemplateCache(max_size=3)
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        cache.put("a", img)
        self.assertIsNotNone(cache.get("a"))
        self.assertEqual(len(cache), 1)

    def test_eviction(self):
        cache = LRUTemplateCache(max_size=2)
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        cache.put("a", img.copy())
        cache.put("b", img.copy())
        cache.put("c", img.copy())  # 驱逐 "a"
        self.assertIsNone(cache.get("a"))
        self.assertIsNotNone(cache.get("b"))
        self.assertEqual(len(cache), 2)


class TestRingSampler(unittest.TestCase):
    """双环采样器测试。"""

    def test_uniform_background(self):
        rs = RingSampler()
        screen = np.ones((100, 200, 3), dtype=np.uint8) * 128
        result = rs.sample(screen, 100, 50)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.outer_brightness, 128, delta=5)
        self.assertFalse(result.is_reliable)  # 同质 → 不可靠

    def test_dark_center(self):
        rs = RingSampler()
        screen = np.ones((100, 200, 3), dtype=np.uint8) * 180  # 亮背景
        screen[45:55, 95:105] = [80, 80, 80]  # 深色中心
        result = rs.sample(screen, 100, 50)
        self.assertIsNotNone(result)
        self.assertTrue(result.outer_brightness > 160)


class TestResolutionAdapter(unittest.TestCase):
    """分辨率适配器测试。"""

    def test_16_9(self):
        ra = ResolutionAdapter(1600, 900)
        ra.update_device_resolution(1920, 1080)
        self.assertTrue(ra.is_16_9)

    def test_non_16_9_phone(self):
        ra = ResolutionAdapter(1600, 900)
        ra.update_device_resolution(1080, 2400)  # 手机全面屏
        self.assertFalse(ra.is_16_9)
        # 中心等比缩放应产生偏移
        self.assertTrue(ra._offset_y > 0 or ra._offset_x > 0)

    def test_normalize_screenshot(self):
        ra = ResolutionAdapter(1600, 900)
        ra.update_device_resolution(1920, 1080)
        screen = np.ones((1080, 1920, 3), dtype=np.uint8) * 128
        result = ra.normalize_screenshot(screen)
        self.assertEqual(result.shape, (900, 1600, 3))


class TestConfidenceThreshold(unittest.TestCase):
    """低对比度阈值测试。"""

    def test_low_contrast(self):
        self.assertEqual(get_confidence_threshold("2D_on.png"), 0.35)
        self.assertEqual(get_confidence_threshold("filter_pending_off.png"), 0.35)
        self.assertEqual(get_confidence_threshold("huoji_on.png"), 0.35)

    def test_normal_contrast(self):
        self.assertEqual(get_confidence_threshold("filter_arrival_on.png"), 0.42)
        self.assertEqual(get_confidence_threshold("unknown_template.png"), 0.42)


class TestMatchMethod(unittest.TestCase):
    """匹配方法测试。"""

    def test_is_best_score_higher(self):
        self.assertTrue(MatchMethod.is_best_score_higher(MatchMethod.CCOEFF))
        self.assertFalse(MatchMethod.is_best_score_higher(MatchMethod.SQDIFF))


if __name__ == "__main__":
    unittest.main()
