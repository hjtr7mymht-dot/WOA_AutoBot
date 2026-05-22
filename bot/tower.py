# -*- coding: utf-8 -*-
"""
WOA AutoBot - 塔台管理 Mixin
从 main_adb.py 提取的塔台延时、菜单操作、倒计时读取逻辑。
"""

import time
import cv2


class TowerMixin:
    """塔台延时/监控逻辑，与 WoaBot 主类通过多重继承合并。"""

    # ─── 像素辅助 ──────────────────────────────────────
    def _color_diff(self, a, b):
        return sum(abs(int(a[i]) - int(b[i])) for i in range(3))

    def _is_pixel_light(self, screen, x, y):
        try:
            b, g, r = screen[y, x]
        except (IndexError, TypeError):
            return False
        return self._color_diff((b, g, r), self.COLOR_LIGHT) < 45

    def _is_pixel_dark(self, screen, x, y):
        try:
            b, g, r = screen[y, x]
        except (IndexError, TypeError):
            return False
        return self._color_diff((b, g, r), self.COLOR_DARK) < 40

    def _is_point_red(self, b, g, r):
        return self._color_diff((b, g, r), self.TOWER_RED_BGR) < 55

    # ─── 塔台状态检测 ──────────────────────────────────
    def _is_tower_off(self, screen):
        """通过检查 4 个采样点是否都是塔台灰色来判断塔台是否关闭"""
        for x, y in self.TOWER_CHECK_POINTS:
            if not self._is_pixel_dark(screen, x, y):
                return False
            try:
                b, g, r = screen[y, x]
                if self._color_diff((b, g, r), self.TOWER_OFF_COLOR) > 50:
                    return False
            except (IndexError, TypeError):
                return False
        return True

    def _is_tower_all_open_by_pixels(self, screen):
        """通过 4 个采样点的颜色快速判断塔台是否四个控制器全开（均为红色）"""
        for i, (x, y) in enumerate(self.TOWER_CHECK_POINTS):
            try:
                b, g, r = screen[y, x]
            except (IndexError, TypeError):
                return False
            if not self._is_point_red(b, g, r):
                return False
        return True

    def _is_tower_icon_visible(self):
        """检测塔台图标 tower.png 是否在画面中可见"""
        screen = self.adb.get_screenshot()
        if screen is None:
            return False
        result = self._locate_on_screen('tower.png', screen, confidence=0.7)
        return result is not None

    # ─── 塔台菜单操作 ──────────────────────────────────
    def _open_tower_menu(self, fast=False, budget_start=None, budget_sec=None):
        """点击(646,822)打开塔台菜单，通过 ROI 检测 tower_1.png 校验是否成功。"""
        def _budget_exhausted(guard=0.0):
            if budget_start is None or budget_sec is None:
                return False
            return (time.time() - budget_start) >= max(0.0, budget_sec - guard)

        max_attempts = 1 if fast else 2
        click_wait = 0.18 if fast else 0.45
        retry_wait = 0.12 if fast else 0.5
        for attempt in range(max_attempts):
            if _budget_exhausted(guard=0.2):
                break
            self.adb.click(646, 822)
            self.sleep(click_wait)
            screen = self.adb.get_screenshot()
            if screen is not None:
                roi = screen[271:327, 32:90]
                tpl_path = self.icon_path + 'tower_1.png'
                tpl = self.adb._template_cache.get(tpl_path)
                if tpl is None:
                    tpl = self.adb._read_image_safe(tpl_path)
                    if tpl is not None:
                        self.adb._template_cache[tpl_path] = tpl
                if tpl is not None:
                    result = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, _ = cv2.minMaxLoc(result)
                    if max_val >= 0.8:
                        return True
            if attempt < max_attempts - 1:
                self.log(f"🗼 [塔台] 菜单未打开，{attempt+1}/2 次重试...")
                self.sleep(retry_wait)
        self.log("🗼 [塔台] ⚠️ 菜单打开失败，2次尝试均未检测到 tower_1.png")
        return False

    def _close_tower_menu(self, fast=False):
        """关闭塔台菜单"""
        timeout = 0.45 if fast else 1.4
        click_wait = 0.08 if fast else 0.25
        self.log("🗼 [塔台] 关闭塔台菜单...")
        if not self.wait_and_click('back.png', timeout=timeout, click_wait=click_wait, random_offset=2):
            self.log("🗼 [塔台] 未找到返回按钮，使用 close_window 关闭")
            self.close_window()

    # ─── 倒计时读取 ────────────────────────────────────
    def _read_tower_times(self, open_menu=True, fast=False, budget_start=None, budget_sec=None):
        """OCR 读取四个控制器的倒计时，返回 [秒数, ...] 列表"""
        def _budget_exhausted(guard=0.0):
            if budget_start is None or budget_sec is None:
                return False
            return (time.time() - budget_start) >= max(0.0, budget_sec - guard)

        if open_menu:
            if not fast:
                if self._is_tower_icon_visible():
                    self.log("🗼 [塔台] 塔台图标可见，直接打开菜单...")
                else:
                    self.log("🗼 [塔台] 塔台图标不可见，先关闭窗口...")
                    self.close_window()
                    self.sleep(0.25)
            if not self._open_tower_menu(fast=fast, budget_start=budget_start, budget_sec=budget_sec):
                return [None, None, None, None]
        else:
            if not fast:
                self.log("🗼 [塔台] 菜单已打开，直接读取...")

        times = [None, None, None, None]
        raw_by_slot = [set() for _ in range(4)]
        passes = 1 if fast else 2
        for _ in range(passes):
            if _budget_exhausted(guard=0.2):
                break
            screen = self.adb.get_screenshot()
            if screen is None:
                self.log("🗼 [塔台] ⚠️ 截图失败，无法读取控制器时间")
                continue
            for i, region in enumerate(self.TOWER_TIME_REGIONS):
                best_secs = times[i]
                candidates = list(self._iter_region_fallbacks(region, pad_x=(8 if fast else 12), pad_y=4))
                if fast:
                    candidates = candidates[:2]
                for candidate in candidates:
                    if _budget_exhausted(guard=0.15):
                        break
                    text = self.ocr.recognize_number(candidate, mode='task', screen_image=screen)
                    if text:
                        raw_by_slot[i].add(text)
                    secs = self.ocr.parse_tower_time(text)
                    if secs is None:
                        continue
                    if best_secs is None or secs > best_secs:
                        best_secs = secs
                times[i] = best_secs
            if all(v is not None for v in times):
                break
            if not fast:
                self.sleep(0.12)
            else:
                self.sleep(0.03)

        if not fast:
            for i in range(4):
                if times[i] is not None:
                    self.log(f"   塔台控制器 {i+1}: {times[i]}s")
                else:
                    raw_preview = ", ".join(sorted(raw_by_slot[i])) if raw_by_slot[i] else "无"
                    self.log(f"   塔台控制器 {i+1}: 无有效数字 (raw={raw_preview})")
        return times

    def _handle_server_error_popup(self, force=False):
        """处理游戏内部错误弹窗，检测 error_ok.png 时自动点击"好的"。"""
        now = time.time()
        if not force and now - self._last_error_popup_check_ts < self._error_popup_check_interval:
            return False
        self._last_error_popup_check_ts = now
        screen = self.adb.get_screenshot()
        ok_pos = self._locate_on_screen('error_ok.png', screen, confidence=0.75)
        if not ok_pos:
            return False
        self.log("⚠️ [异常弹窗] 检测到服务器错误弹窗，正在点击'好的'关闭...")
        for _ in range(3):
            self.adb.click(ok_pos[0], ok_pos[1], random_offset=4)
            self.sleep(0.35)
            next_screen = self.adb.get_screenshot()
            next_ok = self._locate_on_screen('error_ok.png', next_screen, confidence=0.75)
            if not next_ok:
                self.log("✅ [异常弹窗] 错误弹窗已关闭")
                return True
            ok_pos = next_ok
        self.log("⚠️ [异常弹窗] 尝试关闭失败，将在后续循环继续处理")
        return True
