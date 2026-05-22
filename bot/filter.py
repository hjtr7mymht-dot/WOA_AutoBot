# -*- coding: utf-8 -*-
"""
WOA AutoBot - 筛选管理 Mixin
从 main_adb.py 提取的筛选模式检测与切换逻辑。
"""

import time


class FilterMixin:
    """筛选模式管理（模式1=仅待处理，模式2=仅停机位，模式3=不起飞轮切）"""

    # ─── 筛选模式匹配 ──────────────────────────────────
    def _matches_filter_mode(self, screen, points_config):
        """检测当前筛选状态是否匹配给定配置"""
        for (x, y), want_light in points_config:
            is_light = self._is_pixel_light(screen, x, y)
            if (want_light and not is_light) or (not want_light and is_light):
                return False
        return True

    def _matches_filter_mode3(self, screen):
        """不起飞模式：菜单深 (1542,474)深 (1533,331)(1537,403)浅 A/B 仅一个深"""
        mx, my = self.FILTER_MENU_BTN
        if not self._is_pixel_dark(screen, mx, my):
            return False
        if not self._is_pixel_dark(screen, 1542, 474):
            return False
        if not self._is_pixel_light(screen, 1533, 331):
            return False
        if not self._is_pixel_light(screen, 1537, 403):
            return False
        a_dark = self._is_pixel_dark(screen, self.FILTER_POINT_A[0], self.FILTER_POINT_A[1])
        b_dark = self._is_pixel_dark(screen, self.FILTER_POINT_B[0], self.FILTER_POINT_B[1])
        return (a_dark and not b_dark) or (not a_dark and b_dark)

    def _get_mode3_side(self, screen):
        a_dark = self._is_pixel_dark(screen, self.FILTER_POINT_A[0], self.FILTER_POINT_A[1])
        b_dark = self._is_pixel_dark(screen, self.FILTER_POINT_B[0], self.FILTER_POINT_B[1])
        if a_dark and not b_dark:
            return 'landing'
        if b_dark and not a_dark:
            return 'stand'
        return None

    # ─── 不起飞模式调度 ────────────────────────────────
    def _schedule_no_takeoff_auto_logout(self):
        self._no_takeoff_auto_logout_next_time = time.time() + self._no_takeoff_auto_logout_interval * 60.0

    def _schedule_standalone_logout(self):
        self._standalone_logout_next_time = time.time() + self._standalone_logout_interval * 60.0

    def _toggle_no_takeoff_cycle_side(self, reason="定时切换"):
        self._no_takeoff_cycle_side = 'stand' if self._no_takeoff_cycle_side == 'landing' else 'landing'
        self._no_takeoff_cycle_next_switch_time = time.time() + self._no_takeoff_switch_interval
        self.log(f"📋 [不起飞模式] {reason}，切换到{'待降落' if self._no_takeoff_cycle_side == 'landing' else '停机坪'}")

    def _get_no_takeoff_strategy(self):
        if all(self._tower_active_slots):
            return 'stand_only'
        if self._tower_active_slots == [False, False, False, True]:
            return 'landing_stand_cycle'
        return 'stand_only'

    # ─── 小退 ──────────────────────────────────────────
    def _do_no_takeoff_small_logout(self):
        """不起飞模式小退：主界面 → 换机场 → first_start_2 → 等待主界面"""
        self._check_running()
        loc = self.safe_locate('main_interface.png', region=self.REGION_MAIN_ANCHOR, confidence=0.8)
        if not loc:
            self.log("📋 [小退] 未找到主界面按钮，跳过本次小退")
            return
        self.adb.click(loc[0], loc[1], random_offset=5)
        self.sleep(0.5)
        if not self.find_and_click('change_airport.png', confidence=0.75, wait=0):
            self.log("📋 [小退] 未找到更改机场按钮，跳过")
            return
        self.sleep(4.0)
        t0 = time.time()
        found_fs2 = False
        while time.time() - t0 < 30.0:
            self._check_running()
            if self.find_and_click('first_start_2.png', wait=0.5):
                found_fs2 = True
                break
            self.sleep(0.5)
        if not found_fs2:
            self.log("📋 [小退] 30s 内未找到开始按钮，继续等待主界面")
        self.sleep(10.0)
        wait_main = time.time()
        while time.time() - wait_main < 90.0:
            self._check_running()
            if self.safe_locate('main_interface.png', region=self.REGION_MAIN_ANCHOR, confidence=0.8):
                self.log("📋 [小退] 已返回主界面，恢复处理")
                self.sleep(0.5)
                try:
                    self._init_tower_countdown()
                except Exception as e:
                    self.log(f"🗼 [塔台] ⚠️ 小退后重检测塔台失败: {e}")
                self._periodic_15s_check(force_initial_filter_check=True)
                return
            self.sleep(1.0)
        self.log("📋 [小退] 90s 内未检测到主界面，交由后续流程处理")

    # ─── 筛选模式强制切换 ──────────────────────────────
    def _force_switch_filter_mode1(self):
        """强制切回模式1（仅待处理），仅在主界面下执行"""
        if not self.safe_locate('main_interface.png', region=self.REGION_MAIN_ANCHOR, confidence=0.8):
            return
        screen = self.adb.get_screenshot()
        if screen is None:
            return
        mx, my = self.FILTER_MENU_BTN
        if self._is_pixel_light(screen, mx, my):
            self._click_filter_point(mx, my)
            self.sleep(0.5)
            for _ in range(5):
                screen = self.adb.get_screenshot()
                if screen is None:
                    break
                if self._is_pixel_dark(screen, mx, my):
                    break
                self._click_filter_point(mx, my)
                self.sleep(0.3)
            screen = self.adb.get_screenshot()
            if screen is None:
                return
        if self._matches_filter_mode(screen, self.FILTER_CHECK_POINTS_MODE1):
            return
        self.log("📋 [筛选] 关闭不起飞模式，强制切换至模式1(仅待处理)...")
        for (x, y), want_light in self.FILTER_CHECK_POINTS_MODE1:
            screen = self.adb.get_screenshot()
            if screen is None:
                break
            is_light = self._is_pixel_light(screen, x, y)
            if (want_light and not is_light) or (not want_light and is_light):
                self._click_filter_point(x, y)
                self.sleep(0.2)

    def _click_filter_point(self, x, y):
        self.adb.click(x, y, random_offset=5)
