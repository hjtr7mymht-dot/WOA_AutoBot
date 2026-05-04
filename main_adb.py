import cv2
import numpy as np
import time
import random
import threading
import sys
import os
import gc
import traceback
from adb_controller import AdbController, woa_debug_set_runtime_started, save_image_safe, read_image_safe
from simple_ocr import StopSignal, SimpleOCR

# 资助功能完整性守卫标记（由 gui_launcher 在严格模式下联动校验）
WOA_FEATURE_GUARD_TOKEN = "WOA_DONATE_GUARD_V1"


def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(sys.executable)
        return os.path.join(base, relative_path)
    base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class WoaBot:
    def _check_running(self):
        if not self.running:
            raise StopSignal()

    def __init__(self, log_callback=None, config_callback=None, instance_id=1):
        self.instance_id = instance_id
        self.last_staff_log_time = 0
        self.config_callback = config_callback
        self.adb = None
        self.target_device = None
        self.running = False
        self._worker_thread = None
        self.log_callback = log_callback
        self.icon_path = get_resource_path('icon') + os.sep
        self.last_staff_shortage_time = 0
        self.CLOSE_X = 1153
        self.CLOSE_Y = 181
        self.ocr = None
        self.stand_skip_index = 0
        self.in_staff_shortage_mode = False
        self._next_staff_recovery_probe_time = 0.0
        self._staff_recovery_probe_interval = 8.0
        self.enable_bonus_staff = False
        self.last_bonus_staff_time = 0
        self.BONUS_COOLDOWN = 2 * 60 * 60
        self.REGION_GLOBAL_STAFF = (573, 92, 640 - 573, 112 - 92)
        self.REGION_TASK_COST = (270, 670, 330 - 270, 695 - 670)
        self.REGION_GREEN_DOT = (405, 517, 201, 109)
        self.next_bonus_retry_time = 0
        self.doing_task_forbidden_until = 0
        self.next_list_refresh_time = 0
        self.enable_vehicle_buy = False
        self.enable_speed_mode = False
        self.enable_skip_staff = False
        self.enable_delay_bribe = False
        self.enable_random_task = False
        self.control_method = "adb"
        self.screenshot_method = "nemu_ipc"
        self.mumu_path = ""
        self.module_flags = {
            'lifecycle': True,
            'scanner': True,
            'idle_recovery': True,
            'task_doing': True,
            'task_approach': True,
            'task_taxiing': True,
            'task_takeoff': True,
            'task_stand': True,
            'task_ice': True,
            'task_repair': True,
        }
        self.branch_definitions = {
            'full': list(self.module_flags.keys()),
            'safe': ['lifecycle', 'scanner', 'idle_recovery', 'task_doing', 'task_approach', 'task_taxiing',
                     'task_takeoff', 'task_stand'],
            'ground_only': ['lifecycle', 'scanner', 'idle_recovery', 'task_doing', 'task_stand',
                            'task_ice', 'task_repair'],
            'air_only': ['lifecycle', 'scanner', 'idle_recovery', 'task_approach', 'task_taxiing', 'task_takeoff'],
        }
        self.active_branch = 'full'

        self.slide_min_duration = 250
        self.slide_max_duration = 500
        self.REGION_MAIN_ANCHOR = (30, 30, 55, 45)
        self.REGION_REWARD_RECOVERY = (308, 428, 1007, 311)
        self.REWARD_FLOW_BUTTONS = ['get_award_1.png', 'get_award_2.png', 'get_award_3.png', 'get_award_4.png',
                                    'push_back.png', 'taxi_to_runway.png', 'start_general.png']
        self.last_seen_main_interface_time = time.time()
        self.STUCK_TIMEOUT = 28.0
        self._interface_check_interval = 0.35
        self._next_interface_check_time = 0.0
        self.auto_delay_count = 0
        self.TOWER_CHECK_POINTS = [(656, 809), (634, 831), (634, 809), (656, 830)]
        # BGR: 红(需延时) 绿(无需延时) 灰(塔台关闭)
        self.TOWER_RED_BGR = (110, 112, 251)
        self.TOWER_GREEN_BGR = (153, 219, 94)
        self.TOWER_OFF_COLOR = (128, 111, 94)
        # 塔台菜单中四个控制器的倒计时 OCR 区域 (x, y, w, h)，右上角顶点分别为 (320,387) (320,491) (320,595) (320,699)
        self.TOWER_TIME_REGIONS = [
            (320 - 110, 387, 110, 18),
            (320 - 110, 491, 110, 18),
            (320 - 110, 595, 110, 18),
            (320 - 110, 699, 110, 18),
        ]
        # 塔台倒计时定时器：到期时间戳（0 表示未设置）
        self._tower_delay_deadline = 0.0
        # 四个延时按钮坐标（对应控制器1-4）
        self.TOWER_DELAY_BUTTONS = [(362, 376), (362, 479), (362, 583), (362, 688)]
        # 全部延时按钮
        self.TOWER_DELAY_ALL_BTN = (362, 785)
        # 记录哪些控制器是活跃的（启动时确定）
        self._tower_active_slots = [False, False, False, False]
        # 塔台是否已确认关闭（全部未开启）
        self._tower_disabled = False
        # 塔台图标 ROI 区域 (x, y, w, h)
        self.TOWER_ICON_ROI = (549, 794, 53, 55)
        # 塔台是否曾经开启过（用于"塔台关闭筛选全部"功能）
        self._tower_was_active = False
        # 塔台关闭后强制模式1（仅在塔台从开启变为关闭时触发）
        self._tower_off_force_mode1 = False
        # 塔台监测硬预算：从触发监测到得出结果，目标压到 2s 内。
        self.TOWER_MONITOR_MAX_SEC = 2.0
        self.COLOR_LIGHT = (203, 191, 179)
        self.COLOR_DARK = (101, 85, 70)
        self.FILTER_MENU_BTN = (1537, 37)
        self.FILTER_CHECK_POINTS_MODE1 = [
            ((1542, 190), True), ((1535, 118), True), ((1540, 261), True),
            ((1533, 331), True), ((1537, 403), True), ((1542, 474), False)
        ]
        self.FILTER_CHECK_POINTS_MODE2 = [
            ((1542, 190), False), ((1535, 118), True), ((1540, 261), True),
            ((1533, 331), True), ((1537, 403), True), ((1542, 474), False)
        ]
        self.enable_no_takeoff_mode = False
        self.enable_standalone_logout = False
        self.enable_cancel_stand_filter = False
        self.enable_filter_stand_only_when_tower_open = False
        self.FILTER_POINT_A = (1535, 118)
        self.FILTER_POINT_B = (1542, 190)
        self._no_takeoff_cycle_side = 'landing'
        self._no_takeoff_cycle_next_switch_time = 0.0
        self._no_takeoff_switch_interval = 15.0
        self._request_switch_mode1 = False
        self._no_takeoff_auto_logout_interval = 30.0
        self._no_takeoff_auto_logout_next_time = 0.0
        self._standalone_logout_interval = 30.0
        self._standalone_logout_next_time = 0.0
        self._stat_approach = 0
        self._stat_depart = 0
        self._stat_stand_count = 0
        self._stat_stand_staff = 0
        self._stat_session_approach = 0
        self._stat_session_depart = 0
        self._stat_session_stand_count = 0
        self._stat_session_stand_staff = 0
        self._stat_date = None
        self._stat_last_required_cost = None
        self.REGION_STATUS_TITLE = (20, 320, 190, 250)
        self.LIST_ROI_X = 1312
        self.LIST_ROI_W = 60
        self.LIST_ROI_H = 900
        self.REGION_BOTTOM_ROI = (20, 750, 340, 130)
        self.REGION_VACANT_ROI = (390, 690, 730, 150)

        # 防卡死相关
        self.enable_anti_stuck = True
        self.consecutive_timeout_count = 0
        self.last_recovery_time = 0  # 冷却时间
        self.last_window_close_time = time.time()
        self._anti_stuck_warn_threshold = 6
        self._anti_stuck_trigger_count = 0
        self._anti_stuck_stop_threshold = 6
        self._anti_stuck_hard_stop_threshold = 12
        self._anti_stuck_stop_requested = False

        self.last_checked_avail_staff = -1
        self.last_read_success = False
        self.thinking_mode = 0
        self.thinking_range = (0, 0)
        self._task_fail_cooldown = {}
        self._task_fail_cooldown_sec = 5.0
        self._no_operable_count = 0
        self._no_operable_threshold = 3
        self._last_error_popup_check_ts = 0.0
        self._error_popup_check_interval = 1.2

        self.ICON_ROIS = {
            'cross_runway.png': self.REGION_BOTTOM_ROI,
            'get_award_1.png': self.REGION_BOTTOM_ROI,
            'get_award_2.png': self.REGION_REWARD_RECOVERY,
            'get_award_3.png': self.REGION_REWARD_RECOVERY,
            'get_award_4.png': self.REGION_REWARD_RECOVERY,
            'landing_permitted.png': self.REGION_BOTTOM_ROI,
            'landing_prohibited.png': self.REGION_BOTTOM_ROI,
            'push_back.png': self.REGION_BOTTOM_ROI,
            'stand_confirm.png': self.REGION_BOTTOM_ROI,
            'start_ground_support.png': self.REGION_BOTTOM_ROI,
            'start_ice.png': self.REGION_BOTTOM_ROI,
            'takeoff.png': self.REGION_BOTTOM_ROI,
            'takeoff_by_gliding.png': self.REGION_BOTTOM_ROI,
            'taxi_to_runway.png': self.REGION_BOTTOM_ROI,
            'start_general.png': self.REGION_BOTTOM_ROI,
            'wait.png': self.REGION_BOTTOM_ROI,
            'go_repair.png': self.REGION_BOTTOM_ROI,
            'start_repair.png': self.REGION_BOTTOM_ROI,
            'ground_support_done.png': self.REGION_BOTTOM_ROI,
            'stand_vacant.png': self.REGION_VACANT_ROI,
            'green_dot.png': self.REGION_GREEN_DOT
        }

        self.task_templates = {}
        task_files = [
            'pending_ice.png', 'pending_repair.png', 'pending_doing.png',
            'pending_approach.png', 'pending_taxiing.png', 'pending_takeoff.png',
            'pending_stand.png'
        ]
        for tf in task_files:
            p = self.icon_path + tf
            if os.path.exists(p):
                self.task_templates[tf] = read_image_safe(p)

    def set_random_task_mode(self, enabled, log_change=True):
        if self.enable_random_task == enabled:
            return
        self.enable_random_task = enabled
        if log_change:
            self.log(f">>> [配置] 随机任务选择: {'已开启' if enabled else '已关闭'}")

    def set_no_takeoff_mode(self, enabled):
        if self.enable_no_takeoff_mode == enabled:
            return
        self.enable_no_takeoff_mode = enabled
        self.log(f">>> [配置] 不起飞模式: {'已开启' if enabled else '已关闭'}")
        if enabled:
            self._no_takeoff_cycle_side = 'landing'
            self._no_takeoff_cycle_next_switch_time = time.time() + self._no_takeoff_switch_interval
            self._schedule_no_takeoff_auto_logout()
        else:
            self._no_takeoff_auto_logout_next_time = 0.0
            self._request_switch_mode1 = True

    def set_no_takeoff_switch_interval(self, seconds):
        try:
            interval = float(seconds)
        except (TypeError, ValueError):
            interval = 15.0
        interval = max(3.0, min(300.0, interval))
        if self._no_takeoff_switch_interval == interval:
            return
        self._no_takeoff_switch_interval = interval
        self.log(f">>> [配置] 不起飞模式切换间隔: {interval:g} 秒")
        if self.enable_no_takeoff_mode:
            self._no_takeoff_cycle_next_switch_time = time.time() + self._no_takeoff_switch_interval

    def set_no_takeoff_auto_logout_interval(self, minutes):
        try:
            interval = float(minutes)
        except (TypeError, ValueError):
            interval = 30.0
        interval = max(1.0, min(120.0, interval))
        if self._no_takeoff_auto_logout_interval == interval:
            return
        self._no_takeoff_auto_logout_interval = interval
        self.log(f">>> [配置] 不起飞模式自动小退间隔: {interval:g} 分钟")
        if self.enable_no_takeoff_mode:
            self._schedule_no_takeoff_auto_logout()

    def set_standalone_logout_enabled(self, enabled):
        if self.enable_standalone_logout == enabled:
            return
        self.enable_standalone_logout = enabled
        self.log(f">>> [配置] 独立小退: {'已开启' if enabled else '已关闭'}")
        if enabled:
            self._schedule_standalone_logout()
        else:
            self._standalone_logout_next_time = 0.0

    def set_standalone_logout_interval(self, minutes):
        try:
            interval = float(minutes)
        except (TypeError, ValueError):
            interval = 30.0
        interval = max(1.0, min(120.0, interval))
        if self._standalone_logout_interval == interval:
            return
        self._standalone_logout_interval = interval
        self.log(f">>> [配置] 独立小退间隔: {interval:g} 分钟")
        if self.enable_standalone_logout:
            self._schedule_standalone_logout()

    def set_cancel_stand_filter_when_tower_off(self, enabled):
        if self.enable_cancel_stand_filter == enabled:
            return
        self.enable_cancel_stand_filter = enabled
        self.log(f">>> [配置] 塔台关闭时取消停机位筛选: {'已开启' if enabled else '已关闭'}")

    def set_filter_stand_only_when_tower_open(self, enabled):
        if self.enable_filter_stand_only_when_tower_open == enabled:
            return
        self.enable_filter_stand_only_when_tower_open = enabled
        if not enabled and not self.enable_no_takeoff_mode:
            self._request_switch_mode1 = True
        self.log(f">>> [配置] 塔台全开时仅停机位待处理: {'已开启' if enabled else '已关闭'}")

    def _color_diff(self, a, b):
        return sum(abs(int(a[i]) - int(b[i])) for i in range(3))

    def _is_pixel_light(self, screen, x, y):
        try:
            b, g, r = screen[y, x]
            return self._color_diff((b, g, r), self.COLOR_LIGHT) < 80
        except Exception:
            return False

    def _is_pixel_dark(self, screen, x, y):
        try:
            b, g, r = screen[y, x]
            return self._color_diff((b, g, r), self.COLOR_DARK) < 80
        except Exception:
            return False

    def _is_tower_off(self, screen):
        """四个检测点全部为灰色才表示塔台关闭"""
        tb, tg, tr = self.TOWER_OFF_COLOR
        for (x, y) in self.TOWER_CHECK_POINTS:
            try:
                b, g, r = screen[y, x]
                if self._color_diff((b, g, r), (tb, tg, tr)) > 70:
                    return False
            except Exception:
                return False
        return True

    def _is_tower_all_open_by_pixels(self, screen):
        """像素兜底判断塔台四个控制器是否都处于开启状态。
        增加稳定性确认：连续多次检测到全开才返回True，防止偶发误判导致筛选模式跳变。"""
        tb, tg, tr = self.TOWER_OFF_COLOR
        current_all_open = True
        for (x, y) in self.TOWER_CHECK_POINTS:
            try:
                b, g, r = screen[y, x]
                # 与关闭灰色差异足够大，则视为该点已开启（红/绿均可）
                if self._color_diff((b, g, r), (tb, tg, tr)) <= 70:
                    current_all_open = False
            except Exception:
                return False
        # 稳定性确认：状态需要连续保持才认可
        if current_all_open:
            self._tower_all_open_stable_count += 1
        else:
            self._tower_all_open_stable_count = 0
        # 连续多次确认才认为是稳定状态
        if self._tower_all_open_stable_count >= self.TOWER_STABLE_CONFIRM_COUNT:
            self._last_tower_all_open_state = True
            return True
        # 如果之前状态是不全开，立即恢复
        if self._tower_all_open_stable_count == 0:
            self._last_tower_all_open_state = False
        return False

    def _is_tower_icon_visible(self):
        """检测塔台图标是否可见（ROI 内匹配 tower.png）"""
        return self.safe_locate('tower.png', confidence=0.8, region=self.TOWER_ICON_ROI) is not None

    def _is_point_red(self, b, g, r):
        """检测点是否为红色（需延时）：R 主导，与绿/灰区分"""
        rb, rg, rr = self.TOWER_RED_BGR
        diff_red = self._color_diff((b, g, r), (rb, rg, rr))
        diff_green = self._color_diff((b, g, r), self.TOWER_GREEN_BGR)
        diff_gray = self._color_diff((b, g, r), self.TOWER_OFF_COLOR)
        return diff_red < 90 and diff_red <= diff_green and diff_red <= diff_gray

    def _matches_filter_mode(self, screen, points_config):
        for (x, y), want_light in points_config:
            if want_light:
                if not self._is_pixel_light(screen, x, y):
                    return False
            else:
                if not self._is_pixel_dark(screen, x, y):
                    return False
        return True

    def _matches_filter_mode3(self, screen):
        """不起飞模式：菜单深色、(1542,474)深色，(1535,118)与(1542,190)有且仅有一个为深色，(1533,331)(1537,403)为浅色"""
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

    def _do_no_takeoff_small_logout(self):
        """不起飞模式小退：点击主界面 -> 等待0.5s -> 点击换机场 -> 等待4s -> 点击 first_start_2(30s内) -> 等待10s -> 等待主界面(90s内)"""
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
                return
            self.sleep(1.0)
        self.log("📋 [小退] 90s 内未检测到主界面，交由后续流程处理")

    def _force_switch_filter_mode1(self):
        """在主循环中强制将筛选状态切回模式1（仅待处理）"""
        # 仅在主界面下尝试
        if not self.safe_locate('main_interface.png', region=self.REGION_MAIN_ANCHOR, confidence=0.8):
            return
        screen = self.adb.get_screenshot()
        if screen is None:
            return
        mx, my = self.FILTER_MENU_BTN
        # 确保筛选菜单已展开
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
        # 若已是模式1则不动，否则按模式1配置逐项修正
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

    def _periodic_15s_check(self, force_initial_filter_check=False):
        if not hasattr(self, 'last_periodic_check_time'):
            self.last_periodic_check_time = 0
        now = time.time()
        if not force_initial_filter_check and now - self.last_periodic_check_time < 15.0:
            return
        self.last_periodic_check_time = now

        # 1. 检测主界面
        if self.safe_locate('main_interface.png', region=self.REGION_MAIN_ANCHOR, confidence=0.8):
            self.last_seen_main_interface_time = time.time()

        # 2. 中间领奖区防卡死：不论是否在主界面，均遍历寻找领奖按钮并点击直至恢复正常
        rx, ry, rw, rh = self.REGION_REWARD_RECOVERY
        for _ in range(10):
            screen = self.adb.get_screenshot()
            if screen is None:
                break
            roi = screen[ry:ry + rh, rx:rx + rw]
            clicked = False
            for btn in self.REWARD_FLOW_BUTTONS:
                res = self.adb.locate_image(self.icon_path + btn, confidence=0.65, screen_image=roi)
                if res:
                    self.log(f"🚨 [15s周期检测] 在领奖区域内发现 {btn}，点击恢复...")
                    self.adb.click(res[0] + rx, res[1] + ry, random_offset=3)
                    self.sleep(1.0)
                    clicked = True
                    break
            if not clicked:
                break

        # 3. 筛选状态检查 (仅在确认在主界面时执行)
        if not self.safe_locate('main_interface.png', region=self.REGION_MAIN_ANCHOR, confidence=0.8):
            return
        screen = self.adb.get_screenshot()
        if screen is None:
            return

        mx, my = self.FILTER_MENU_BTN
        if self._is_pixel_light(screen, mx, my):
            self.log("📋 [筛选] 展开筛选菜单...")
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

        is_mode1 = self._matches_filter_mode(screen, self.FILTER_CHECK_POINTS_MODE1)
        is_mode2 = self._matches_filter_mode(screen, self.FILTER_CHECK_POINTS_MODE2)
        is_mode3 = self.enable_no_takeoff_mode and self._matches_filter_mode3(screen)

        def apply_mode(points_config):
            for (x, y), want_light in points_config:
                screen = self.adb.get_screenshot()
                if screen is None:
                    break
                is_light = self._is_pixel_light(screen, x, y)
                if (want_light and not is_light) or (not want_light and is_light):
                    self._click_filter_point(x, y)
                    self.sleep(0.2)

        def apply_mode3(target_side):
            """确保菜单深、(1542,474)深，(1533,331)(1537,403)浅，再根据目标侧设置待降落/停机坪。"""
            for _ in range(8):
                screen = self.adb.get_screenshot()
                if screen is None:
                    return
                if self._is_pixel_light(screen, mx, my):
                    self._click_filter_point(mx, my)
                    self.sleep(0.3)
                    continue
                if not self._is_pixel_dark(screen, 1542, 474):
                    self._click_filter_point(1542, 474)
                    self.sleep(0.2)
                    continue
                if not self._is_pixel_light(screen, 1533, 331):
                    self._click_filter_point(1533, 331)
                    self.sleep(0.2)
                    continue
                if not self._is_pixel_light(screen, 1537, 403):
                    self._click_filter_point(1537, 403)
                    self.sleep(0.2)
                    continue
                ax, ay = self.FILTER_POINT_A[0], self.FILTER_POINT_A[1]
                bx, by = self.FILTER_POINT_B[0], self.FILTER_POINT_B[1]
                a_dark = self._is_pixel_dark(screen, ax, ay)
                b_dark = self._is_pixel_dark(screen, bx, by)
                want_a_dark = target_side == 'landing'
                if want_a_dark and not a_dark:
                    self._click_filter_point(ax, ay)
                    self.sleep(0.2)
                elif not want_a_dark and not b_dark:
                    self._click_filter_point(bx, by)
                    self.sleep(0.2)
                else:
                    break

        if self.enable_no_takeoff_mode:
            strategy = self._get_no_takeoff_strategy()
            # OCR 读取偶发抖动时，用像素状态兜底：全开塔台强制按仅停机位处理。
            if strategy == 'landing_stand_cycle' and self._is_tower_all_open_by_pixels(screen):
                strategy = 'stand_only'
                self._tower_active_slots = [True, True, True, True]
            if strategy == 'landing_stand_cycle':
                current_side = self._get_mode3_side(screen) if is_mode3 else None
                if current_side != self._no_takeoff_cycle_side:
                    self.log(f"📋 [不起飞模式] 应用{'待降落' if self._no_takeoff_cycle_side == 'landing' else '停机坪'}筛选...")
                    apply_mode3(self._no_takeoff_cycle_side)
            else:
                if not is_mode2:
                    self.log("📋 [不起飞模式] 塔台全开或非4号单开，强制切换至停机坪待处理...")
                    apply_mode(self.FILTER_CHECK_POINTS_MODE2)
            return

        if self.enable_filter_stand_only_when_tower_open and all(self._tower_active_slots):
            if not is_mode2:
                self.log("📋 [筛选] 塔台全开，强制切换至模式2(仅停机位)...")
                apply_mode(self.FILTER_CHECK_POINTS_MODE2)
            return

        if (not self.enable_filter_stand_only_when_tower_open) and all(self._tower_active_slots) and is_mode2:
            self.log("📋 [筛选] 已关闭塔台全开仅停机位，恢复模式1(仅待处理)...")
            apply_mode(self.FILTER_CHECK_POINTS_MODE1)
            return

        need_mode1_only = self._tower_off_force_mode1
        if need_mode1_only and not is_mode1:
            self.log("📋 [筛选] 切换至仅待处理... (塔台已关闭)")
            apply_mode(self.FILTER_CHECK_POINTS_MODE1)
            return

        if is_mode1 or is_mode2:
            return
        self.log("📋 [筛选] 状态异常，默认切换至仅待处理...")
        apply_mode(self.FILTER_CHECK_POINTS_MODE1)

    def _nemu_ipc_debug_save_mismatch(self, nemu_img, adb_img):
        """nemu_ipc 与 ADB 截图不匹配时保存对比图，便于排查"""
        try:
            import datetime
            debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nemu_ipc_debug")
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            p_n = os.path.join(debug_dir, f"mismatch_nemu_{ts}.png")
            p_a = os.path.join(debug_dir, f"mismatch_adb_{ts}.png")
            save_image_safe(p_n, nemu_img)
            save_image_safe(p_a, adb_img)
            self.log(f"📋 [调试] 已保存对比图: {p_n} / {p_a}")
        except Exception as e:
            self.log(f"📋 [调试] 保存对比图失败: {e}")

    def _droidcast_raw_debug_save_mismatch(self, droidcast_img, adb_img):
        """DroidCast_raw 与 ADB 截图不匹配时保存对比图，便于排查"""
        try:
            import datetime
            debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "droidcast_raw_debug")
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            p_d = os.path.join(debug_dir, f"mismatch_droidcast_{ts}.png")
            p_a = os.path.join(debug_dir, f"mismatch_adb_{ts}.png")
            save_image_safe(p_d, droidcast_img)
            save_image_safe(p_a, adb_img)
            self.log(f"📋 [调试] 已保存对比图: {p_d} / {p_a}")
        except Exception as e:
            self.log(f"📋 [调试] 保存对比图失败: {e}")

    def _save_list_roi_debug(self, full_screen, list_roi_img, lx, ly, lw, lh):
        """任务列表检测为 0 时保存调试图（WOA_DEBUG=1 或 LIST_DETECT_DEBUG=1）"""
        try:
            base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
            debug_dir = os.path.join(base, "list_detect_debug")
            os.makedirs(debug_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            p_full = os.path.join(debug_dir, f"list_debug_full_{ts}.png")
            p_roi = os.path.join(debug_dir, f"list_debug_roi_{ts}.png")
            # 兼容中文路径的保存方式
            save_image_safe(p_full, full_screen)
            save_image_safe(p_roi, list_roi_img)
            self.log(f"📋 [调试] 任务列表调试图已保存至: {debug_dir}")
        except Exception as e:
            self.log(f"📋 [调试] 保存 list_detect 截图失败: {e}")

    def _run_pending_detection(self, list_roi_img):
        """按行识别：每行只保留该行内置信度最高的类型，避免跨行竞争导致相似图标误判。"""
        base_defs = [
            ('pending_ice.png', self.handle_ice_task, 0.8, 'ice', 'task_ice'),
            ('pending_repair.png', self.handle_repair_task, 0.8, 'repair', 'task_repair'),
            ('pending_doing.png', self.handle_vehicle_check_task, 0.85, 'doing', 'task_doing'),
            ('pending_approach.png', self.handle_approach_task, 0.8, 'approach', 'task_approach'),
            ('pending_taxiing.png', self.handle_taxiing_task, 0.8, 'taxiing', 'task_taxiing'),
            ('pending_takeoff.png', self.handle_takeoff_task, 0.8, 'takeoff', 'task_takeoff'),
            ('pending_stand.png', self.handle_stand_task, 0.8, 'stand', 'task_stand')
        ]
        try:
            conf_override = float(os.environ.get("LIST_DETECT_CONF", "0"))
        except ValueError:
            conf_override = 0
        task_defs = [
            (n, h, conf_override if conf_override > 0 else c, t)
            for n, h, c, t, module_name in base_defs
            if self._is_module_enabled(module_name)
        ]
        ROW_HEIGHT = 24

        all_matches = []
        for img_name, handler, conf, t_type in task_defs:
            found = self._fast_locate_all(list_roi_img, img_name, confidence=conf)
            for item in found:
                rel_cx, rel_cy = item['center']
                abs_cx = rel_cx + self.LIST_ROI_X
                abs_cy = rel_cy
                type_for_logic = 'stand' if t_type == 'stand' else ('doing' if t_type == 'doing' else 'other')
                all_matches.append({
                    'y': rel_cy, 'center': (abs_cx, abs_cy), 'handler': handler, 'name': img_name,
                    'score': item['score'], 'type': type_for_logic, 'raw_type': t_type
                })

        if not all_matches:
            return [], []

        # 按 y 先排序，再线性分组，避免 used+全表扫描导致的 O(n^2) 开销。
        all_matches.sort(key=lambda d: d['y'])
        final_tasks = []
        i = 0
        n = len(all_matches)
        while i < n:
            row = [all_matches[i]]
            row_anchor = all_matches[i]['y']
            j = i + 1
            while j < n and abs(all_matches[j]['y'] - row_anchor) <= ROW_HEIGHT:
                row.append(all_matches[j])
                j += 1
            best = max(row, key=lambda x: x['score'])
            final_tasks.append(best)
            i = j

        return all_matches, final_tasks

    def _fast_locate_all(self, screen_roi, template_name, confidence=0.8):
        if template_name not in self.task_templates:
            return []

        template = self.task_templates[template_name]
        if template is None: return []

        try:
            res = cv2.matchTemplate(screen_roi, template, cv2.TM_CCOEFF_NORMED)
        except Exception:
            return []

        h, w = template.shape[:2]
        ys, xs = np.where(res >= confidence)
        if len(xs) == 0:
            return []

        # 用 10px 网格桶聚合重复命中，保留每个桶内最高分，避免逐项 O(n^2) 去重。
        bucket_size = 10
        best_by_bucket = {}
        for x, y in zip(xs, ys):
            key = (int(x) // bucket_size, int(y) // bucket_size)
            score = float(res[y, x])
            old = best_by_bucket.get(key)
            if old is None or score > old['score']:
                best_by_bucket[key] = {
                    'box': (int(x), int(y), w, h),
                    'center': (int(x) + w // 2, int(y) + h // 2),
                    'score': score,
                }
        return list(best_by_bucket.values())

    def _locate_on_screen(self, image_name, screen, confidence=0.8, region=None):
        if screen is None:
            return None
        if region is None:
            return self.adb.locate_image(self.icon_path + image_name, confidence=confidence, screen_image=screen)
        x, y, w, h = region
        x = max(0, int(x))
        y = max(0, int(y))
        roi = screen[y:y + h, x:x + w]
        result = self.adb.locate_image(self.icon_path + image_name, confidence=confidence, screen_image=roi)
        if result:
            return result[0] + x, result[1] + y
        return None

    def _batch_locate_on_screen(self, screen, specs):
        """在同一帧内做多图匹配，降低重复截图与重复匹配开销。"""
        if screen is None:
            return {key: None for key, _, _, _ in specs}
        results = {}
        for key, image_name, confidence, region in specs:
            results[key] = self._locate_on_screen(image_name, screen, confidence=confidence, region=region)
        return results

    def set_thinking_time_mode(self, mode_index, log_change=True):
        mode_index = int(mode_index)
        if hasattr(self, 'thinking_mode') and self.thinking_mode == mode_index:
            return
        self.thinking_mode = mode_index
        if self.thinking_mode == 1:
            self.thinking_range = (0.1, 0.4)
            desc = "短 (0.1s-0.4s)"
        elif self.thinking_mode == 2:
            self.thinking_range = (0.3, 1.0)
            desc = "中 (0.3s-1.0s)"
        elif self.thinking_mode == 3:
            self.thinking_range = (0.8, 2.0)
            desc = "长 (0.8s-2.0s)"
        else:
            self.thinking_range = (0, 0)
            desc = "关闭"
        prev = getattr(self, '_last_thinking_desc', None)
        if prev == desc:
            if self.adb:
                self.adb.set_thinking_strategy(*self.thinking_range)
            return
        self._last_thinking_desc = desc
        if self.adb:
            self.adb.set_thinking_strategy(*self.thinking_range)
        if log_change:
            self.log(f">>> [配置] 思考时间: {desc}")

    def set_bonus_staff_feature(self, enabled):
        if self.enable_bonus_staff == enabled: return
        self.enable_bonus_staff = enabled
        self.log(f">>> [配置] 自动领取地勤: {'已开启' if enabled else '已关闭'}")

    def set_vehicle_buy_feature(self, enabled):
        if self.enable_vehicle_buy == enabled: return
        self.enable_vehicle_buy = enabled
        self.log(f">>> [配置] 自动购买车辆: {'已开启' if enabled else '已关闭'}")

    def set_speed_mode(self, enabled):
        if self.enable_speed_mode == enabled: return
        self.enable_speed_mode = enabled
        self.log(f">>> [配置] 跳过二次校验: {'已开启' if enabled else '已关闭'}")

    def set_skip_staff_verify(self, enabled):
        if self.enable_skip_staff == enabled: return
        self.enable_skip_staff = enabled
        self.log(f">>> [配置] 跳过地勤验证: {'已开启' if enabled else '已关闭'}")

    def set_auto_delay(self, count):
        count = int(count)
        old_count = self.auto_delay_count
        self.auto_delay_count = count
        # 如果从禁用变为启用，重新初始化塔台状态
        if old_count <= 0 and count > 0:
            self.log(f">>> [配置] 自动延时塔台已启用 ({count} 次)，重新初始化塔台状态")
            self._tower_disabled = False
            self._tower_delay_deadline = 0.0  # 触发重新检查
        elif old_count > 0 and count <= 0:
            self.log(f">>> [配置] 自动延时塔台已关闭")
            self._tower_delay_deadline = 0.0

    def set_delay_bribe(self, enabled):
        if self.enable_delay_bribe == enabled: return
        self.enable_delay_bribe = enabled
        self.log(f">>> [配置] 延误飞机贿赂: {'已开启' if enabled else '已关闭'}")

    def set_anti_stuck_config(self, enabled, threshold=None, log_change=True):
        enabled = bool(enabled)
        changed = (self.enable_anti_stuck != enabled)
        self.enable_anti_stuck = enabled

        if threshold is not None:
            try:
                val = int(threshold)
            except (TypeError, ValueError):
                val = self._anti_stuck_warn_threshold
            val = max(3, min(20, val))
            if self._anti_stuck_warn_threshold != val:
                self._anti_stuck_warn_threshold = val
                changed = True
            stop_val = max(self._anti_stuck_warn_threshold, val)
            if self._anti_stuck_stop_threshold != stop_val:
                self._anti_stuck_stop_threshold = stop_val
                changed = True
            hard_val = max(self._anti_stuck_stop_threshold + 2, val * 2)
            if self._anti_stuck_hard_stop_threshold != hard_val:
                self._anti_stuck_hard_stop_threshold = hard_val
                changed = True

        if not self.enable_anti_stuck:
            self._anti_stuck_trigger_count = 0
            self._anti_stuck_stop_requested = False
            self.consecutive_timeout_count = 0

        if log_change and changed:
            state = "已开启" if self.enable_anti_stuck else "已关闭"
            self.log(
                f">>> [配置] 防卡死: {state}，阈值={self._anti_stuck_warn_threshold}，自动停机阈值={self._anti_stuck_hard_stop_threshold}"
            )

    def set_slide_duration_range(self, min_d, max_d, log_change=True):
        min_d = int(min_d)
        max_d = int(max_d)
        if hasattr(self, 'slide_min_duration') and hasattr(self, 'slide_max_duration'):
            if self.slide_min_duration == min_d and self.slide_max_duration == max_d:
                return
        self.slide_min_duration = min_d
        self.slide_max_duration = max_d
        if log_change:
            self.log(f">>> [配置] 滑块随机耗时: {self.slide_min_duration}ms - {self.slide_max_duration}ms")

    def set_device(self, device_serial):
        self.target_device = device_serial

    def set_control_method(self, method):
        m = (method or "adb").lower()
        valid = ("adb", "uiautomator2")
        if m not in valid:
            m = "adb"
        if self.control_method != m:
            self.control_method = m

    def set_screenshot_method(self, method):
        m = (method or "adb").lower()
        if m not in ("adb", "nemu_ipc", "uiautomator2", "droidcast_raw"):
            m = "adb"
        if self.screenshot_method != m:
            self.screenshot_method = m

    def set_mumu_path(self, path):
        self.mumu_path = (path or "").strip()
        if self.adb:
            self.adb.set_mumu_path(self.mumu_path)

    def _is_module_enabled(self, module_name):
        if not self.module_flags.get(module_name, True):
            return False
        branch_modules = self.branch_definitions.get(self.active_branch, self.branch_definitions['full'])
        return module_name in branch_modules

    def set_module_enabled(self, module_name, enabled, log_change=True):
        if module_name not in self.module_flags:
            return
        enabled = bool(enabled)
        if self.module_flags[module_name] == enabled:
            return
        self.module_flags[module_name] = enabled
        if log_change:
            self.log(f">>> [模块] {module_name}: {'启用' if enabled else '禁用'}")

    def set_module_flags(self, flags, log_change=True):
        if not isinstance(flags, dict):
            return
        for name, enabled in flags.items():
            self.set_module_enabled(str(name), bool(enabled), log_change=log_change)

    def set_active_branch(self, branch_name, log_change=True):
        branch = (branch_name or 'full').strip().lower()
        if branch not in self.branch_definitions:
            branch = 'full'
        if self.active_branch == branch:
            return
        self.active_branch = branch
        if log_change:
            self.log(f">>> [分支] 当前执行分支: {self.active_branch}")

    def log(self, message):
        if not message or not str(message).strip():
            return
        try:
            print(message)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            pass
        if self.log_callback:
            try:
                self.log_callback(message)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass

        if not self.enable_anti_stuck:
            return

        # 【核心修正】智能防卡死逻辑
        # 1. 过滤掉恢复日志本身，防止递归触发
        if "防卡死" in message: return

        # 2. 统计警告次数
        if "⚠️" in message or "超时" in message:
            self.consecutive_timeout_count += 1
        elif "✅" in message or "成功" in message:
            self.consecutive_timeout_count = 0

        # 3. 触发条件：连续告警超过阈值 + 冷却时间已过
        if self.consecutive_timeout_count >= self._anti_stuck_warn_threshold:
            if time.time() - self.last_recovery_time > 16:
                self._record_anti_stuck_trigger("检测到连续多次卡顿，尝试紧急寻找领奖图标")
                self.consecutive_timeout_count = 0
                self.last_recovery_time = time.time()
                self._attempt_emergency_reward_recovery()
            else:
                self.consecutive_timeout_count = 0  # 冷却中，暂时重置

    def _record_anti_stuck_trigger(self, reason):
        if not self.enable_anti_stuck:
            return
        self._anti_stuck_trigger_count += 1
        self.log(f"🚨 [防卡死] {reason}，累计 {self._anti_stuck_trigger_count}/{self._anti_stuck_stop_threshold} 次")
        if self._anti_stuck_trigger_count < self._anti_stuck_stop_threshold:
            return
        self.log("🛠️ [防卡死] 已达到自修复阈值，开始执行恢复流程...")
        if self._attempt_self_heal_and_resume():
            self._anti_stuck_trigger_count = 0
            self._anti_stuck_stop_requested = False
            self.consecutive_timeout_count = 0
            self.last_seen_main_interface_time = time.time()
            self.log("✅ [防卡死] 界面恢复正常，脚本已自动继续运行")
            return

        self.log("⚠️ [防卡死] 本轮自修复未完全恢复，将继续监控并重试")
        if self._anti_stuck_trigger_count < self._anti_stuck_hard_stop_threshold:
            return

        if self._anti_stuck_stop_requested:
            return
        self._anti_stuck_stop_requested = True
        self.log("🛑 [防卡死] 长时间无法恢复，脚本已停止，请检查模拟器界面或当前机场状态")
        self.running = False
        if self.config_callback:
            try:
                self.config_callback("bot_stopped", "防卡死多次触发且自修复失败，已自动停止")
            except Exception:
                pass

    def _attempt_self_heal_and_resume(self):
        if self._is_main_interface_ready(retries=2, interval=0.3):
            return True

        for _ in range(3):
            self._attempt_emergency_reward_recovery(max_rounds=4)
            if self._is_main_interface_ready(retries=2, interval=0.4):
                return True

            if self.wait_and_click('back.png', timeout=1.2, click_wait=0.4, random_offset=2):
                self.log("   -> [自修复] 点击 Back")
            if self.wait_and_click('cancel.png', timeout=1.2, click_wait=0.4):
                self.log("   -> [自修复] 点击 Cancel")
            if self._is_main_interface_ready(retries=2, interval=0.4):
                return True

            self.log("   -> [自修复] 执行盲点关闭尝试")
            self.close_window()
            self.sleep(0.8)
            if self._is_main_interface_ready(retries=2, interval=0.5):
                return True

        return False

    def _is_main_interface_ready(self, retries=1, interval=0.0):
        retries = max(1, int(retries))
        for i in range(retries):
            if self.safe_locate('main_interface.png', region=self.REGION_MAIN_ANCHOR, confidence=0.8):
                return True
            if interval > 0 and i < retries - 1:
                self.sleep(interval)
        return False

    def _attempt_emergency_reward_recovery(self, max_rounds=3):
        # 全屏搜索领奖图标
        targets = ['get_award_1.png', 'get_award_2.png', 'get_award_3.png', 'get_award_4.png']
        max_rounds = max(1, int(max_rounds))
        # 尝试循环检测，确保如果点到第1步能接着点第2步
        for _ in range(max_rounds):
            clicked = False
            for t in targets:
                # 使用 region=None 进行全屏搜索，降低一点阈值以防图标变灰或变暗
                res = self.safe_locate(t, confidence=0.65, region=None)
                if res:
                    self.log(f"   -> 🚨 紧急恢复：点击 {t}")
                    self.adb.click(res[0], res[1])
                    self.sleep(1.5)  # 点击后多等一会儿
                    clicked = True
                    break
            if not clicked:
                break

    def wait_and_click(self, image_name, timeout=3.0, click_wait=0.2, confidence=0.8, random_offset=5):
        self._check_running()
        start_time = time.time()
        use_roi = False
        roi_x, roi_y, roi_w, roi_h = 0, 0, 0, 0
        if image_name in self.ICON_ROIS:
            use_roi = True
            roi_x, roi_y, roi_w, roi_h = self.ICON_ROIS[image_name]

        while time.time() - start_time < timeout:
            self._check_running()
            screen = self.adb.get_screenshot()
            if screen is None:
                time.sleep(0.1)
                continue
            if use_roi:
                search_img = screen[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
                offset_x, offset_y = roi_x, roi_y
            else:
                search_img = screen
                offset_x, offset_y = 0, 0

            result = self.adb.locate_image(self.icon_path + image_name, confidence=confidence, screen_image=search_img)
            if result:
                self._check_running()
                real_x = result[0] + offset_x
                real_y = result[1] + offset_y
                self.adb.click(real_x, real_y, random_offset=random_offset)
                if click_wait > 0: self.sleep(click_wait)
                return True
            time.sleep(0.1)
        return False

    def start(self):
        if self.running: return
        self.stand_skip_index = 0
        self.in_staff_shortage_mode = False
        self._next_staff_recovery_probe_time = 0.0
        self.last_checked_avail_staff = -1
        self.last_window_close_time = time.time()
        # 初始化计数器
        self.consecutive_timeout_count = 0
        self.consecutive_errors = 0
        self.last_recovery_time = 0
        self._next_interface_check_time = 0.0
        self._anti_stuck_warn_threshold = max(3, int(self._anti_stuck_warn_threshold))
        self._anti_stuck_stop_threshold = max(self._anti_stuck_warn_threshold, int(self._anti_stuck_stop_threshold))
        self._anti_stuck_hard_stop_threshold = max(self._anti_stuck_stop_threshold + 2, int(self._anti_stuck_hard_stop_threshold))
        self._anti_stuck_trigger_count = 0
        self._anti_stuck_stop_requested = False
        self._no_operable_count = 0
        # 重置塔台状态
        self._tower_disabled = False
        self._tower_was_active = False
        self._tower_off_force_mode1 = False
        self._tower_delay_deadline = 0.0
        self._tower_active_slots = [False, False, False, False]

        if not self.target_device:
            self.log("❌ 未选择设备！")
            return
        self.running = True
        self.log(f">>> 连接设备: {self.target_device} ...")
        try:
            self.adb = AdbController(
                target_device=self.target_device,
                control_method=self.control_method,
                screenshot_method=self.screenshot_method,
                instance_id=self.instance_id,
            )
            self.adb.set_mumu_path(self.mumu_path)
            method_probe = self.adb.ensure_methods_usable()
            if self.config_callback:
                self.adb.set_nemu_folder_callback(
                    lambda folder: self.config_callback("mumu_path", folder)
                )
            self.adb.set_thinking_strategy(*self.thinking_range)
            self.ocr = SimpleOCR(self.adb, self.icon_path)
            self.log("✅ OCR 模块已加载")
            test_img = self.adb.get_screenshot()
            if test_img is None:
                self.log("❌ 连接成功但无法获取画面！")
                self.running = False
                try:
                    if self.adb:
                        self.adb.close()
                except Exception:
                    pass
                return
            h, w = test_img.shape[:2]
            res_info = self.adb.get_resolution_info() if hasattr(self.adb, 'get_resolution_info') else None
            if res_info:
                raw_w, raw_h = res_info.get('raw', (w, h))
                self.log(f"✅ 画面正常，脚本启动 (设备分辨率: {raw_w}x{raw_h} -> 逻辑分辨率: {w}x{h})")
            else:
                self.log(f"✅ 画面正常，脚本启动 (逻辑分辨率: {w}x{h})")
            ctrl_map = {"adb": "ADB", "uiautomator2": "uiautomator2"}
            ctrl = ctrl_map.get(self.adb.control_method, "ADB")
            shot = self.adb.screenshot_method if self.adb.screenshot_method != "adb" else "ADB"
            self.log(f">>> [模式] 触控: {ctrl}, 截图: {shot}")
            if method_probe.get("repaired"):
                self.log(">>> [模式] 已自动修复不可用方案，当前使用稳定回退组合")
            if os.environ.get("WOA_DEBUG", "").strip().lower() in ("1", "true", "yes"):
                try:
                    debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "woa_debug") if not getattr(sys, "frozen", False) else os.path.join(os.path.dirname(sys.executable), "woa_debug")
                    self.log(f">>> [WOA_DEBUG] 已开启，仅在启动时执行方案测试，结果保存至: {debug_dir}")
                except Exception:
                    self.log(">>> [WOA_DEBUG] 已开启，仅在启动时执行方案测试")
                self.log(">>> [WOA_DEBUG] 正在进行截图与触控方案测试...")
                self.adb.run_all_method_tests()
                woa_debug_set_runtime_started()
                self.log(">>> [WOA_DEBUG] 方案测试完成，开始主循环")
                os.environ.pop("WOA_DEBUG", None)
            thread = threading.Thread(target=self._main_loop)
            thread.daemon = True
            self._worker_thread = thread
            thread.start()
        except Exception as e:
            self.log(f"❌ 启动失败: {e}")
            self.running = False
            try:
                if hasattr(self, 'adb') and self.adb:
                    self.adb.close()
            except Exception:
                pass

    def stop(self):
        self.running = False
        self.log(">>> 正在停止脚本...")
        self._print_session_stats()
        self._save_stats_to_csv()
        self.next_bonus_retry_time = 0
        adb_ref = getattr(self, 'adb', None)
        if adb_ref:
            threading.Thread(target=self._async_close_adb, args=(adb_ref,), daemon=True).start()

    def _print_session_stats(self):
        start = getattr(self, "_run_start_time", None)
        if start is not None:
            secs = max(0, int(time.time() - start))
            h, rest = divmod(secs, 3600)
            m, s = divmod(rest, 60)
            if h > 0:
                dur = f"{h}小时{m}分{s}秒"
            else:
                dur = f"{m}分{s}秒"
            self.log(f"[统计] 本次运行时长: {dur}")
        a = getattr(self, "_stat_session_approach", self._stat_approach)
        d = getattr(self, "_stat_session_depart", self._stat_depart)
        sc = getattr(self, "_stat_session_stand_count", self._stat_stand_count)
        ss = getattr(self, "_stat_session_stand_staff", self._stat_stand_staff)
        if a + d + sc == 0:
            return
        self.log(f"[统计] ═══════════════════════════════════")
        self.log(f"[统计]  ✈ 进场飞机:  {a} 架次")
        self.log(f"[统计]  ✈ 离场飞机:  {d} 架次")
        self.log(f"[统计]  ✈ 分配地勤:  {sc} 架次 / {ss} 人次")
        self.log(f"[统计] ═══════════════════════════════════")

    def _add_stats_to_csv_date(self, target_date, a, d, sc, ss):
        """将 (a,d,sc,ss) 累加到 CSV 中 target_date 所在行。若 a+d+sc==0 则不写。
        所有实例共用同一个 woa_stats.csv，使用文件锁防止并发写入冲突。"""
        import csv
        if a + d + sc == 0:
            return
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__)) if not getattr(sys, "frozen", False) else os.path.dirname(sys.executable)
            csv_path = os.path.join(base_dir, "woa_stats.csv")
            lock_path = csv_path + ".lock"
            header = ["date", "approach", "depart", "stand_count", "stand_staff"]
            # 使用文件锁保证多实例安全
            import msvcrt
            with open(lock_path, "w") as lf:
                lf.write("1")
                lf.flush()
                msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    rows = []
                    if os.path.isfile(csv_path):
                        with open(csv_path, "r", encoding="utf-8-sig") as f:
                            reader = csv.reader(f)
                            for i, row in enumerate(reader):
                                if i == 0 and row and row[0].strip().lower() == "date":
                                    continue
                                if len(row) >= 5:
                                    rows.append(row)
                    found = False
                    for row in rows:
                        if row[0] == target_date:
                            row[1] = str(int(row[1]) + a)
                            row[2] = str(int(row[2]) + d)
                            row[3] = str(int(row[3]) + sc)
                            row[4] = str(int(row[4]) + ss)
                            found = True
                            break
                    if not found:
                        rows.append([target_date, str(a), str(d), str(sc), str(ss)])
                    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow(header)
                        writer.writerows(rows)
                finally:
                    msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception as e:
            self.log(f"⚠️ 保存统计数据失败: {e}")

    def _save_stats_to_csv(self):
        """停止时将当日累计写入 CSV（本次运行 0 点后的部分）"""
        a, d, sc, ss = self._stat_approach, self._stat_depart, self._stat_stand_count, self._stat_stand_staff
        today = time.strftime("%Y-%m-%d")
        self._add_stats_to_csv_date(today, a, d, sc, ss)

    @staticmethod
    def _async_close_adb(adb):
        try:
            adb.close()
        except Exception:
            pass

    def _main_loop(self):
        try:
            self._do_main_loop()
        except StopSignal:
            pass
        except BaseException:
            self._write_thread_crash_report()
            traceback.print_exc()

    def _write_thread_crash_report(self):
        """从工作线程安全地写入崩溃报告（不碰 tkinter）"""
        try:
            from gui_launcher import _write_crash_report
            exc_type, exc_value, exc_tb = sys.exc_info()
            if exc_type:
                path = _write_crash_report(exc_type, exc_value, exc_tb)
                if path:
                    self.log(f"🛑 [严重错误] 脚本异常退出，日志已保存至: {path}")
        except Exception:
            traceback.print_exc()

    def _do_main_loop(self):
        self._run_start_time = time.time()
        self._stat_date = time.strftime("%Y-%m-%d")
        self.log("[DEBUG] 主循环线程已启动")
        self.sleep(1.0)
        self.last_periodic_check_time = 0
        if self.enable_no_takeoff_mode:
            self._no_takeoff_cycle_side = 'landing'
            self._no_takeoff_cycle_next_switch_time = time.time() + self._no_takeoff_switch_interval
        self._periodic_15s_check(force_initial_filter_check=True)
        if self.enable_no_takeoff_mode:
            self._schedule_no_takeoff_auto_logout()
        if self.enable_standalone_logout:
            self._schedule_standalone_logout()
        # 启动时读取塔台倒计时
        try:
            self._init_tower_countdown()
        except StopSignal:
            raise
        except Exception as e:
            self.log(f"🗼 [塔台] ⚠️ 初始化塔台失败: {e}，跳过")
            self._tower_disabled = True
        idle_count = 0
        gc_counter = 0
        while self.running:
            try:
                if self._handle_server_error_popup():
                    idle_count = 0
                    continue
                now_date = time.strftime("%Y-%m-%d")
                if self._stat_date and now_date != self._stat_date:
                    a, d, sc, ss = self._stat_approach, self._stat_depart, self._stat_stand_count, self._stat_stand_staff
                    self._add_stats_to_csv_date(self._stat_date, a, d, sc, ss)
                    if a + d + sc > 0:
                        self.log(f"[统计] 已跨 0 点，将 {self._stat_date} 的统计写入 CSV（进场 {a} / 离场 {d} / 地勤 {sc} 架 {ss} 人次）")
                    self._stat_approach = 0
                    self._stat_depart = 0
                    self._stat_stand_count = 0
                    self._stat_stand_staff = 0
                    self._stat_date = now_date
                if self._is_module_enabled('lifecycle'):
                    if getattr(self, '_request_switch_mode1', False):
                        self._request_switch_mode1 = False
                        self._force_switch_filter_mode1()
                    now_ts = time.time()
                    if self.enable_no_takeoff_mode and self._get_no_takeoff_strategy() == 'landing_stand_cycle' and now_ts >= self._no_takeoff_cycle_next_switch_time:
                        self._toggle_no_takeoff_cycle_side(reason="到达切换间隔")
                        self._periodic_15s_check(force_initial_filter_check=True)
                    if self.enable_no_takeoff_mode and self._no_takeoff_auto_logout_next_time > 0 and now_ts >= self._no_takeoff_auto_logout_next_time:
                        self.log("📋 [不起飞模式] 到达自动小退间隔，执行小退...")
                        self._do_no_takeoff_small_logout()
                        self._schedule_no_takeoff_auto_logout()
                    if self.enable_standalone_logout and self._standalone_logout_next_time > 0 and now_ts >= self._standalone_logout_next_time:
                        self.log("📋 [独立小退] 到达小退间隔，执行小退...")
                        self._do_no_takeoff_small_logout()
                        self._schedule_standalone_logout()
                    # 检查塔台倒计时是否到期
                    if self._check_tower_countdown():
                        idle_count = 0
                        continue
                did_work = self.scan_and_process() if self._is_module_enabled('scanner') else False
                if did_work:
                    self.sleep(0.05)
                    idle_count = 0
                else:
                    if self._is_module_enabled('idle_recovery'):
                        self.sleep(0.5)
                        idle_count += 1
                        if idle_count == 10:
                            self.close_window()
                    else:
                        self.sleep(0.2)
                        idle_count = 0
                gc_counter += 1
                if gc_counter > 50:
                    gc.collect()
                    gc_counter = 0
            except StopSignal:
                self.log(">>> [系统] 停止指令，终止...")
                break
            except (KeyboardInterrupt, SystemExit):
                break
            except Exception as e:
                # 出现异常，打印堆栈
                traceback.print_exc()
                error_msg = f"❌ 运行出错: {e}"
                self.log(error_msg)
                
                # 如果连续出错，主动触发系统的异常处理逻辑（生成报告并重启或停止）
                if not hasattr(self, 'consecutive_errors'):
                    self.consecutive_errors = 0
                self.consecutive_errors += 1
                
                if self.consecutive_errors >= 6:
                    self.log("🛑 检测到持续报错，脚本将终止运行以防止僵死状态")
                    self._write_thread_crash_report()
                    self.running = False
                    break
                
                try:
                    self.sleep(3.0)
                except (StopSignal, KeyboardInterrupt, SystemExit):
                    break
                except Exception:
                    break
            else:
                # 如果成功运行一轮，重置连续错误计数
                self.consecutive_errors = 0
        self.log(">>> 脚本已完全停止")
        try:
            if hasattr(self, 'adb') and self.adb:
                self.adb.close()
        except Exception:
            pass

    def random_sleep(self, min_s, max_s):
        self._check_running()
        self.sleep(random.uniform(min_s, max_s))
        self._check_running()

    def sleep(self, seconds):
        end_time = time.time() + seconds
        while time.time() < end_time:
            self._check_running()
            remaining = end_time - time.time()
            sleep_time = min(0.1, remaining)
            if sleep_time > 0: time.sleep(sleep_time)

    def close_window(self):
        self.adb.double_click(self.CLOSE_X, self.CLOSE_Y, random_offset=30)
        self.last_window_close_time = time.time()
        self.sleep(0.1)

    def find_and_click(self, image_name, confidence=0.8, wait=0.5, random_offset=5):
        self._check_running()
        screen = self.adb.get_screenshot()
        if screen is None: return False
        search_img = screen
        offset_x, offset_y = 0, 0
        if image_name in self.ICON_ROIS:
            roi = self.ICON_ROIS[image_name]
            x, y, w, h = roi
            search_img = screen[y:y + h, x:x + w]
            offset_x, offset_y = x, y
        result = self.adb.locate_image(self.icon_path + image_name, confidence=confidence, screen_image=search_img)
        if result:
            self._check_running()
            real_x = result[0] + offset_x
            real_y = result[1] + offset_y
            self.adb.click(real_x, real_y, random_offset=random_offset)
            self.sleep(wait)
            return True
        return False

    def safe_locate(self, image_name, confidence=0.8, region=None):
        self._check_running()
        if region is None:
            return self.adb.locate_image(self.icon_path + image_name, confidence=confidence)
        screen = self.adb.get_screenshot()
        if screen is None: return None
        x, y, w, h = region
        x = max(0, int(x));
        y = max(0, int(y))
        search_img = screen[y:y + h, x:x + w]
        result = self.adb.locate_image(self.icon_path + image_name, confidence=confidence, screen_image=search_img)
        if result:
            return (result[0] + x, result[1] + y)
        return None

    def _iter_region_fallbacks(self, region, pad_x=0, pad_y=0):
        x, y, w, h = region
        candidates = [region]
        if pad_x > 0 or pad_y > 0:
            candidates.extend([
                (x - pad_x, y - pad_y, w + pad_x * 2, h + pad_y * 2),
                (x - pad_x, y, w + pad_x * 2, h),
                (x, y - pad_y, w, h + pad_y * 2),
                (x + pad_x // 2, y, w, h),
                (x - pad_x // 2, y, w, h),
            ])
        unique = []
        for candidate in candidates:
            if candidate not in unique:
                unique.append(candidate)
        return unique

    def check_global_staff(self, screen_image=None):
        for region in self._iter_region_fallbacks(self.REGION_GLOBAL_STAFF, pad_x=14, pad_y=6):
            text = self.ocr.recognize_number(region, mode='global', screen_image=screen_image)
            if not text:
                continue
            result = self.ocr.parse_staff_count(text)
            if result:
                return result[2]
        return None

    def _verify_and_redirect(self, expected_status_img):
        if self.enable_speed_mode: return True
        status_map = [
            ('status_stand.png', self.handle_stand_task),
            ('status_takeoff.png', self.handle_takeoff_task),
            ('status_taxiing.png', self.handle_taxiing_task),
            ('status_approach.png', self.handle_approach_task),
            ('status_ice.png', self.handle_ice_task),
            ('status_doing.png', self.handle_vehicle_check_task)
        ]

        x, y, w, h = self.REGION_STATUS_TITLE

        def _scan_statuses(full_screen):
            specs = [(img, img, 0.7, (x, y, w, h)) for img, _ in status_map]
            return self._batch_locate_on_screen(full_screen, specs)

        for attempt in range(2):
            full_screen = self.adb.get_screenshot()
            if full_screen is None: continue
            status_hits = _scan_statuses(full_screen)
            if status_hits.get(expected_status_img):
                return True
            if attempt == 0:
                self.sleep(0.15)

        self.log(f"   -> 状态校验不匹配 ({expected_status_img})，尝试纠错...")
        full_screen = self.adb.get_screenshot()
        if full_screen is None: return False
        status_hits = _scan_statuses(full_screen)
        found = next((img for img, _ in status_map if status_hits.get(img)), None)
        if found:
            for img, handler in status_map:
                if img == found:
                    if img == 'status_doing.png' and time.time() <= self.doing_task_forbidden_until:
                        self.log("   -> ⏳ Doing 任务尚在6秒冷却中，关闭窗口")
                        self.close_window()
                        return False
                    self.log(f"   -> ↪️ 自动跳转至: {img}")
                    try:
                        handler()
                    except TypeError:
                        handler(None)
                    return False
        self.sleep(0.2)
        full_screen = self.adb.get_screenshot()
        if full_screen is not None:
            status_hits = _scan_statuses(full_screen)
            if status_hits.get(expected_status_img):
                return True
            found = next((img for img, _ in status_map if status_hits.get(img)), None)
            if found:
                for img, handler in status_map:
                    if img == found:
                        if img == 'status_doing.png' and time.time() <= self.doing_task_forbidden_until:
                            self.log("   -> ⏳ Doing 任务尚在6秒冷却中，关闭窗口")
                            self.close_window()
                            return False
                        self.log(f"   -> ↪️ 自动跳转至: {img}")
                        try:
                            handler()
                        except TypeError:
                            handler(None)
                        return False
        self.log("   -> 未知状态，退出")
        self.close_window()
        return False

    def _update_staff_tracker(self, val):
        if val is None:
            if self.last_read_success:
                self.log(f"⚠️ [状态监测] 可用地勤读取失败")
                self.last_read_success = False
            return
        if not self.last_read_success:
            self.log(f"📊 [状态监测] 读取恢复: {val}")
            self.last_read_success = True
            self.last_checked_avail_staff = val
        elif val != self.last_checked_avail_staff:
            if self.last_checked_avail_staff == -1:
                self.log(f"📊 [状态监测] 当前可用地勤: {val}")
            else:
                self.log(f"📊 [状态监测] 可用地勤: {self.last_checked_avail_staff} -> {val}")
            self.last_checked_avail_staff = val

    def _read_tower_times(self, open_menu=True, fast=False, budget_start=None, budget_sec=None):
        """OCR 读取四个控制器的倒计时，返回 [秒数, ...] 列表（读取失败的为 None）
        open_menu=True 时智能判断是否需要关窗再打开塔台菜单；False 时假设菜单已打开。
        注意：此方法不关闭菜单，由调用方负责。"""
        def _budget_exhausted(guard=0.0):
            if budget_start is None or budget_sec is None:
                return False
            return (time.time() - budget_start) >= max(0.0, budget_sec - guard)

        if open_menu:
            # 快速模式下尽量避免关窗，优先直接尝试打开塔台菜单。
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
                    # 取更大值可减少 OCR 漏位把 8m35s 误读成 35s 的情况。
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
        """处理游戏内部错误弹窗，检测到 `error_ok.png` 时自动点击“好的”。"""
        now = time.time()
        if not force and now - self._last_error_popup_check_ts < self._error_popup_check_interval:
            return False
        self._last_error_popup_check_ts = now

        screen = self.adb.get_screenshot()
        ok_pos = self._locate_on_screen('error_ok.png', screen, confidence=0.75)
        if not ok_pos:
            return False

        self.log("⚠️ [异常弹窗] 检测到服务器错误弹窗，正在点击“好的”关闭...")
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

    def _open_tower_menu(self, fast=False, budget_start=None, budget_sec=None):
        """点击(646,822)打开塔台菜单，并通过 ROI 内检测 tower_1.png 校验是否成功。
        最多重试2次（间隔2s），返回 True/False。"""
        import cv2
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
                # ROI: (32,271) 到 (90,327)
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

    def _init_tower_countdown(self):
        """启动时读取塔台倒计时，判断哪些控制器活跃，设置定时器。
        先通过 tower.png 可见性 + 像素灰度判断塔台是否关闭，避免不必要的菜单操作。"""
        self.log("🗼 [塔台] 启动初始化：检测塔台图标...")
        # 第一步：检测 ROI 内是否有 tower.png
        icon_visible = self._is_tower_icon_visible()
        if not icon_visible:
            # 图标不可见，可能被窗口遮挡，先关窗再检测
            self.log("🗼 [塔台] 塔台图标不可见，尝试关闭窗口后重新检测...")
            self.close_window()
            self.sleep(0.5)
            icon_visible = self._is_tower_icon_visible()
        if not icon_visible:
            # 关窗后仍不可见，无法确认塔台状态，跳过
            self.log("🗼 [塔台] 关窗后塔台图标仍不可见，无法确认塔台状态，跳过初始化")
            return
        # 第二步：图标可见，用像素检测判断塔台是否全灰（关闭）
        screen = self.adb.get_screenshot()
        if screen is not None and self._is_tower_off(screen):
            self._tower_disabled = True
            self._tower_delay_deadline = 0.0
            self._tower_active_slots = [False, False, False, False]
            self.log("🗼 [塔台] 塔台图标全灰，判定塔台已关闭，不打开菜单")
            if self.enable_no_takeoff_mode:
                self.log("⚠️ [塔台] 不起飞模式已开启但塔台未开启，建议打开塔台控制器4以处理推出")
            return
        if not self._is_main_interface_ready(retries=2, interval=0.15):
            self._tower_delay_deadline = time.time() + 12.0
            self.log("🗼 [塔台] 当前非主界面，初始化延后 12s 再检测")
            return
        # 第三步：塔台非灰色，打开菜单读取时间
        self.log("🗼 [塔台] 塔台图标可见且非灰色，打开菜单读取控制器状态...")
        if not self._open_tower_menu():
            self.log("🗼 [塔台] ⚠️ 菜单打开失败，跳过初始化")
            self._close_tower_menu()
            return
        times = self._read_tower_times(open_menu=False)
        # 判断活跃状态
        active = [t is not None and t > 0 for t in times]
        active_count = sum(active)
        self.log(f"🗼 [塔台] OCR 结果: {times}，活跃数: {active_count}/4")
        if active_count == 0:
            self._tower_disabled = True
            self._tower_delay_deadline = 0.0
            self._tower_active_slots = [False, False, False, False]
            self.log("🗼 [塔台] 四个控制器均未开启，塔台已关闭，以后不再打开菜单")
            if self.enable_no_takeoff_mode:
                self.log("⚠️ [塔台] 不起飞模式已开启但塔台未开启，建议打开塔台控制器4以获得最佳效果")
            self._close_tower_menu()
            return
        self._tower_active_slots = active
        self._tower_disabled = False
        self._tower_was_active = True
        slots_str = ",".join([str(i+1) for i, a in enumerate(active) if a])
        valid_times = [t for t, a in zip(times, active) if a]
        min_time = min(valid_times)
        max_time = max(valid_times)
        if self.auto_delay_count > 0:
            # 检查是否有控制器已经 < 3分钟，需要立即延时
            needs_delay_now = [False, False, False, False]
            urgent = False
            for i in range(4):
                if active[i] and times[i] is not None and times[i] < 180:
                    needs_delay_now[i] = True
                    urgent = True
            if urgent:
                urgent_slots = [i+1 for i in range(4) if needs_delay_now[i]]
                self.log(f"🗼 [塔台] ⚠️ 控制器 {urgent_slots} 剩余不足3分钟，立即执行延时！")
                self._perform_tower_delay(needs_delay_now, menu_already_open=True)
                return
            # 自动延时已开启：提前3分钟触发
            trigger_in = max(0, min_time - 180)
            self._tower_delay_deadline = time.time() + trigger_in
            mins, secs = divmod(int(min_time), 60)
            self.log(f"🗼 [塔台] 自动延时已开启(剩余{self.auto_delay_count}次)，活跃控制器: [{slots_str}]")
            self.log(f"🗼 [塔台] 最短剩余 {mins}m{secs}s，将在 {int(trigger_in)}s 后触发延时检查")
        else:
            # 自动延时未开启：在最长时间到期后+10s 再打开菜单确认状态
            trigger_in = max_time + 10
            self._tower_delay_deadline = time.time() + trigger_in
            mins, secs = divmod(int(max_time), 60)
            self.log(f"🗼 [塔台] 自动延时未开启，活跃控制器: [{slots_str}]")
            self.log(f"🗼 [塔台] 最长剩余 {mins}m{secs}s，将在 {int(trigger_in)}s 后重新确认塔台状态")
        self._close_tower_menu()

    def _check_tower_countdown(self):
        """检查塔台倒计时是否到期。
        - 自动延时开启时：到期则打开菜单重新读取，延时 <10min 的控制器
        - 自动延时未开启时：到期则打开菜单确认塔台状态（监控模式）"""
        monitor_start = time.time()
        monitor_budget = self.TOWER_MONITOR_MAX_SEC

        if self._tower_delay_deadline <= 0:
            if self.auto_delay_count > 0:
                try:
                    self._init_tower_countdown()
                except Exception as e:
                    self.log(f"🗼 [塔台] ⚠️ 重新初始化塔台状态失败: {e}")
            if self._tower_delay_deadline <= 0 or self._tower_disabled:
                return False
        if time.time() < self._tower_delay_deadline:
            return False
        if not self._is_main_interface_ready(retries=1, interval=0.08):
            self._tower_delay_deadline = time.time() + 8.0
            self.log("🗼 [塔台] 当前不在主界面，延后 8s 再检查")
            return False
        if not self._is_tower_icon_visible():
            self._tower_delay_deadline = time.time() + 5.0
            self.log("🗼 [塔台] 暂未检测到塔台图标，延后 5s 再检查")
            return False
        self._tower_delay_deadline = 0.0

        if self.auto_delay_count <= 0:
            # 监控模式：自动延时未开启，只是确认塔台状态
            self.log("🗼 [塔台] 监控到期，打开菜单确认塔台状态...")
            times = self._read_tower_times(open_menu=True, fast=True, budget_start=monitor_start, budget_sec=monitor_budget)
            active = [t is not None and t > 0 for t in times]
            active_count = sum(active)
            self.log(f"🗼 [塔台] OCR 结果: {times}，活跃数: {active_count}/4")
            if active_count == 0:
                if any(t is None for t in times) and any(self._tower_active_slots):
                    self.log("🗼 [塔台] OCR 读取不完整，暂不判定塔台关闭，稍后重试")
                    self._tower_delay_deadline = time.time() + 8.0
                    self._close_tower_menu(fast=True)
                    elapsed = time.time() - monitor_start
                    if elapsed > monitor_budget:
                        self.log(f"🗼 [塔台] ⚠️ 监测预算超时: {elapsed:.2f}s > {monitor_budget:.2f}s")
                    return True
                self._tower_disabled = True
                self._tower_active_slots = [False, False, False, False]
                self.log("🗼 [塔台] 四个控制器均已关闭，以后不再打开菜单")
                if self._tower_was_active and self.enable_cancel_stand_filter:
                    self._tower_off_force_mode1 = True
                    self.log("🗼 [塔台] 塔台从开启变为关闭，启用强制筛选模式1")
            else:
                self._tower_active_slots = active
                valid_times = [t for t, a in zip(times, active) if a]
                max_time = max(valid_times)
                trigger_in = max_time + 10
                self._tower_delay_deadline = time.time() + trigger_in
                mins, secs = divmod(int(max_time), 60)
                slots_str = ",".join([str(i+1) for i, a in enumerate(active) if a])
                self.log(f"🗼 [塔台] 活跃控制器: [{slots_str}]，最长剩余 {mins}m{secs}s")
                self.log(f"🗼 [塔台] 将在 {int(trigger_in)}s 后再次确认塔台状态")
            self._close_tower_menu(fast=True)
            elapsed = time.time() - monitor_start
            if elapsed > monitor_budget:
                self.log(f"🗼 [塔台] ⚠️ 监测预算超时: {elapsed:.2f}s > {monitor_budget:.2f}s")
            return True

        # 延时模式：自动延时已开启
        self.log("🗼 [塔台] 延时倒计时到期，打开菜单检查剩余时间...")
        times = self._read_tower_times(open_menu=True, fast=True, budget_start=monitor_start, budget_sec=monitor_budget)
        self.log(f"🗼 [塔台] OCR 结果: {times}")
        # 先检查是否全部关闭（全 None）
        active = [t is not None and t > 0 for t in times]
        if sum(active) == 0:
            if any(t is None for t in times) and any(self._tower_active_slots):
                self.log("🗼 [塔台] OCR 读取不完整，暂不判定塔台关闭，稍后重试")
                self._tower_delay_deadline = time.time() + 8.0
                self._close_tower_menu(fast=True)
                elapsed = time.time() - monitor_start
                if elapsed > monitor_budget:
                    self.log(f"🗼 [塔台] ⚠️ 监测预算超时: {elapsed:.2f}s > {monitor_budget:.2f}s")
                return True
            self._tower_disabled = True
            self._tower_active_slots = [False, False, False, False]
            self.log("🗼 [塔台] 四个控制器均已关闭，塔台已关闭")
            if self._tower_was_active and self.enable_cancel_stand_filter:
                self._tower_off_force_mode1 = True
                self.log("🗼 [塔台] 塔台从开启变为关闭，启用强制筛选模式1")
            self._close_tower_menu(fast=True)
            elapsed = time.time() - monitor_start
            if elapsed > monitor_budget:
                self.log(f"🗼 [塔台] ⚠️ 监测预算超时: {elapsed:.2f}s > {monitor_budget:.2f}s")
            return True
        # 自动延时模式下也要持续刷新活跃槽位，避免沿用旧状态导致筛选策略误判。
        self._tower_active_slots = active
        # 判断哪些活跃控制器需要延时（< 10分钟）
        needs_delay = [False, False, False, False]
        any_need = False
        for i in range(4):
            if active[i] and times[i] is not None and times[i] < 60:
                needs_delay[i] = True
                any_need = True
                self.log(f"🗼 [塔台] 控制器 {i+1} 剩余 {int(times[i])}s < 60s，需要延时")
        if not any_need:
            # 没有需要延时的，重新设置下次 deadline
            self.log("🗼 [塔台] 所有活跃控制器均 >= 10分钟，暂不延时")
            valid_times = [t for t, a in zip(times, active) if a and t is not None and t > 0]
            if valid_times:
                min_time = min(valid_times)
                trigger_in = max(0, min_time - 180)
                self._tower_delay_deadline = time.time() + trigger_in
                self.log(f"🗼 [塔台] 将在 {int(trigger_in)}s 后再次检查")
            self._close_tower_menu(fast=True)
            elapsed = time.time() - monitor_start
            if elapsed > monitor_budget:
                self.log(f"🗼 [塔台] ⚠️ 监测预算超时: {elapsed:.2f}s > {monitor_budget:.2f}s")
            return True
        # 菜单已打开，直接执行延时（不关菜单）
        if time.time() - monitor_start >= monitor_budget - 0.25:
            # 监测预算即将耗尽：优先在 2s 内返回结果，延时动作延后到下一轮。
            self._tower_delay_deadline = time.time() + 0.4
            self.log("🗼 [塔台] 监测预算即将耗尽，延时动作顺延至下一轮")
            self._close_tower_menu(fast=True)
            return True
        self.log(f"🗼 [塔台] 需要延时的控制器: {[i+1 for i in range(4) if needs_delay[i]]}")
        self._perform_tower_delay(needs_delay, menu_already_open=True)
        elapsed = time.time() - monitor_start
        if elapsed > monitor_budget:
            self.log(f"🗼 [塔台] ⚠️ 监测预算超时: {elapsed:.2f}s > {monitor_budget:.2f}s")
        return True

    def _try_delay_clicks(self, needs_delay, all_active, all_need):
        """尝试点击延时按钮并确认，返回 True/False"""
        def _confirm_delay_dialog_any():
            # 兼容不同塔台续费弹窗：全延时/单控制器延时可能出现不同确认按钮。
            for _ in range(4):
                acted = False
                if self.wait_and_click('delay.png', timeout=0.7, click_wait=0.25, random_offset=2):
                    acted = True
                elif self.wait_and_click('delay_1.png', timeout=0.7, click_wait=0.25, random_offset=2):
                    acted = True
                elif self.wait_and_click('yes.png', timeout=0.9, click_wait=0.25, random_offset=2):
                    acted = True

                screen = self.adb.get_screenshot()
                has_delay = self._locate_on_screen('delay.png', screen, confidence=0.78)
                has_delay_1 = self._locate_on_screen('delay_1.png', screen, confidence=0.78)
                has_yes = self._locate_on_screen('yes.png', screen, confidence=0.78)
                if not (has_delay or has_delay_1 or has_yes):
                    return True

                if not acted:
                    self.sleep(0.15)
            return False

        if all_active and all_need:
            self.log("   -> 点击全部延时按钮")
            self.adb.click(*self.TOWER_DELAY_ALL_BTN)
            self.sleep(0.35)
            ok = _confirm_delay_dialog_any()
            if not ok:
                self.log("   -> 全部延时确认失败")
            return ok
        else:
            any_ok = False
            for i in range(4):
                if not needs_delay[i]:
                    continue
                self.log(f"   -> 点击控制器 {i+1} 延时按钮")
                self.adb.click(*self.TOWER_DELAY_BUTTONS[i])
                self.sleep(0.35)
                if _confirm_delay_dialog_any():
                    self.log(f"   -> 控制器 {i+1} 延时确认成功")
                    any_ok = True
                else:
                    self.log(f"   -> 控制器 {i+1} 延时确认失败")
            return any_ok

    def _check_delay_by_ocr(self, pre_times):
        """通过 OCR 对比延时前后的时间，若任意活跃控制器时间变长则视为延时成功。
        pre_times: 延时前的 [秒数, ...] 列表。返回 True/False。"""
        self.sleep(0.6)
        post_times = self._read_tower_times(open_menu=False)
        for i in range(4):
            if not self._tower_active_slots[i]:
                continue
            before = pre_times[i]
            after = post_times[i]
            if before is not None and after is not None and after > before:
                self.log(f"   -> 🗼 OCR 检测：控制器 {i+1} 时间 {before}s -> {after}s，判定延时成功")
                return True
        return False

    def _perform_tower_delay(self, needs_delay, menu_already_open=False):
        """执行塔台延时操作。needs_delay: [bool]*4 表示哪些控制器需要延时。
        menu_already_open=True 时假设菜单已打开。
        失败时重试：关窗重点按钮(最多2次) → 关窗+back退回主界面+重开菜单(1次)
        每次尝试后通过 OCR 对比时间变化，防止误判导致重复延时。"""
        delay_slots = [i+1 for i in range(4) if needs_delay[i]]
        self.log(f"🗼 [塔台] 开始延时操作，目标控制器: {delay_slots}，菜单已打开: {menu_already_open}")
        if not menu_already_open:
            self.close_window()
            self.sleep(0.3)
            if not self._open_tower_menu():
                self.log("🗼 [塔台] ⚠️ 菜单打开失败，30s 后再次尝试")
                self._tower_delay_deadline = time.time() + 30
                return True
        # 记录延时前的 OCR 时间，用于后续对比
        pre_times = self._read_tower_times(open_menu=False)
        self.log(f"🗼 [塔台] 延时前 OCR 时间: {pre_times}")
        all_active = all(self._tower_active_slots)
        all_need = all(n for n, a in zip(needs_delay, self._tower_active_slots) if a)
        confirm_success = self._try_delay_clicks(needs_delay, all_active, all_need)
        # UI 未确认时，用 OCR 对比判断是否实际已延时
        if not confirm_success:
            if self._check_delay_by_ocr(pre_times):
                confirm_success = True
        # 重试阶段1：关窗后重新点击按钮（最多2次）
        if not confirm_success:
            for retry in range(2):
                self.log(f"   -> ⚠️ 延时未确认，关窗重试 ({retry+1}/2)...")
                self.close_window()
                self.sleep(0.5)
                confirm_success = self._try_delay_clicks(needs_delay, all_active, all_need)
                if not confirm_success:
                    if self._check_delay_by_ocr(pre_times):
                        confirm_success = True
                if confirm_success:
                    break
        # 重试阶段2：退回主界面，重新打开菜单（1次）
        if not confirm_success:
            self.log("   -> ⚠️ 关窗重试仍失败，退回主界面后重新打开菜单...")
            self.close_window()
            self.sleep(0.3)
            if not self.wait_and_click('back.png', timeout=3.0, click_wait=0.5, random_offset=2):
                self.close_window()
            self.sleep(0.5)
            if not self._open_tower_menu():
                self.log("🗼 [塔台] ⚠️ 重开菜单失败")
            else:
                confirm_success = self._try_delay_clicks(needs_delay, all_active, all_need)
                if not confirm_success:
                    if self._check_delay_by_ocr(pre_times):
                        confirm_success = True
        if confirm_success:
            self.log(f"   -> ✅ 延时操作完成，剩余延时次数: {self.auto_delay_count - 1}")
            self.auto_delay_count -= 1
            if self.config_callback:
                self.config_callback("auto_delay_count", self.auto_delay_count)
            # 延时确认后等待1s，此时仍在塔台页面，直接读取时间
            self.sleep(1.0)
            self.log("🗼 [塔台] 延时确认后，直接读取当前倒计时...")
            times = self._read_tower_times(open_menu=False)
            valid_times = [t for t, a in zip(times, self._tower_active_slots) if a and t is not None and t > 0]
            if valid_times:
                if self.auto_delay_count > 0:
                    # 还有延时次数，按延时模式：最短时间 - 3分钟
                    min_time = min(valid_times)
                    trigger_in = max(0, min_time - 180)
                    self._tower_delay_deadline = time.time() + trigger_in
                    mins, secs = divmod(int(min_time), 60)
                    self.log(f"🗼 [塔台] 最短剩余 {mins}m{secs}s，{int(trigger_in)}s 后执行下次延时")
                else:
                    # 延时次数已用完，切换为监控模式：最长时间 + 10s
                    max_time = max(valid_times)
                    trigger_in = max_time + 10
                    self._tower_delay_deadline = time.time() + trigger_in
                    mins, secs = divmod(int(max_time), 60)
                    self.log(f"🗼 [塔台] 延时次数已用完，切换为监控模式，最长剩余 {mins}m{secs}s，{int(trigger_in)}s 后确认塔台状态")
            else:
                self._tower_delay_deadline = 0.0
                self.log("🗼 [塔台] ⚠️ 延时后未能读取到有效时间")
            self._close_tower_menu()
        else:
            self.log("   -> ⚠️ 所有重试均失败，30s 后再次尝试")
            self._tower_delay_deadline = time.time() + 30
            self._close_tower_menu()
        return True

    def _check_and_perform_auto_delay(self, screen=None):
        if self.auto_delay_count <= 0 or self._tower_disabled: return False

        if time.time() < self.doing_task_forbidden_until:
            return False

        # 先检查塔台图标是否可见，确保当前在主界面
        if not self._is_tower_icon_visible():
            return False

        if screen is None:
            screen = self.adb.get_screenshot()
        if screen is None: return False
        is_triggered = False
        for (x, y) in self.TOWER_CHECK_POINTS:
            try:
                b, g, r = screen[y, x]
                if self._is_point_red(int(b), int(g), int(r)):
                    is_triggered = True
                    break
            except Exception:
                pass
        if is_triggered:
            self.log(f"🚨 [最高优] 监测到自动塔台红灯...")
            # 打开塔台菜单，读取时间
            self.close_window()
            self.sleep(0.3)
            if not self._open_tower_menu():
                self.log("🗼 [塔台] ⚠️ 红灯触发但菜单打开失败，跳过本次")
                return True
            times = self._read_tower_times(open_menu=False)
            self.log(f"🗼 [塔台] 红灯触发 OCR 结果: {times}")
            # 判断哪些活跃控制器需要延时（< 2分钟，紧急）
            needs_delay = [False, False, False, False]
            for i in range(4):
                if self._tower_active_slots[i] and times[i] is not None and times[i] < 120:
                    needs_delay[i] = True
                    self.log(f"🗼 [塔台] 控制器 {i+1} 剩余 {int(times[i])}s < 120s，紧急延时")
            if any(needs_delay):
                # 菜单已打开，直接延时
                self.log(f"🗼 [塔台] 紧急延时控制器: {[i+1 for i in range(4) if needs_delay[i]]}")
                self._perform_tower_delay(needs_delay, menu_already_open=True)
            else:
                # 全部活跃的都延时（红灯说明至少有一个快到期了）
                needs_all = [a for a in self._tower_active_slots]
                self.log(f"🗼 [塔台] 无 <2min 控制器，对所有活跃控制器执行延时")
                self._perform_tower_delay(needs_all, menu_already_open=True)
            return True
        return False

    def _exit_vehicle_buy_scene(self, max_rounds=4):
        """尝试从车辆购买界面安全退回，避免在购买页卡死。"""
        max_rounds = max(1, int(max_rounds))
        for _ in range(max_rounds):
            self._check_running()
            screen = self.adb.get_screenshot()
            if screen is None:
                self.sleep(0.15)
                continue

            has_buy = self._locate_on_screen('buy_vehicle.png', screen, confidence=0.78)
            has_confirm = self._locate_on_screen('buy_vehicle_confirm.png', screen, confidence=0.78)
            if not has_buy and not has_confirm:
                return True

            # 依次尝试返回、取消和右上角关闭，尽量兼容不同弹窗层级。
            if self.wait_and_click('back.png', timeout=0.9, click_wait=0.3, random_offset=2):
                continue
            if self.wait_and_click('cancel.png', timeout=0.9, click_wait=0.3):
                continue
            self.close_window()
            self.sleep(0.25)

        verify_screen = self.adb.get_screenshot()
        if verify_screen is None:
            return False
        still_buy = self._locate_on_screen('buy_vehicle.png', verify_screen, confidence=0.78)
        still_confirm = self._locate_on_screen('buy_vehicle_confirm.png', verify_screen, confidence=0.78)
        return not (still_buy or still_confirm)

    def handle_vehicle_check_task(self, target_pos=None):
        self.sleep(0.2)
        self.log(">>> [任务] 检查 Doing 状态...")
        screen = self.adb.get_screenshot()
        batch_hits = self._batch_locate_on_screen(screen, [
            ('red_warning', 'red_warning.png', 0.75, None),
            ('ground_done', 'ground_support_done.png', 0.8, self.REGION_BOTTOM_ROI),
        ])
        red_warn = batch_hits.get('red_warning')
        if red_warn:
            self._no_operable_count = 0
            if self.enable_vehicle_buy:
                self.log("   -> 🚨 发现车辆不足，准备购买")
                self.adb.click(red_warn[0], red_warn[1], random_offset=1)
                self.sleep(0.5)
                if self.wait_and_click('buy_vehicle.png', timeout=2.0, click_wait=1.0):
                    if self.wait_and_click('buy_vehicle_confirm.png', timeout=3.0, click_wait=0.5):
                        self.log("   -> ✅ 购买确认成功")
                    elif self.wait_and_click('back.png', timeout=3.0, click_wait=0.5, random_offset=2):
                        self.log("   -> 🛑 金钱不足，取消购买")
                        self.enable_vehicle_buy = False
                        if self.config_callback: self.config_callback("vehicle_buy", False)
                else:
                    self.log("   -> 未找到购买按钮")
            else:
                self.log("   -> 🚨 发现车辆不足，忽略")
            if not self._exit_vehicle_buy_scene():
                self.log("⚠️ [Doing] 购买界面未能正常退出，触发临时冷却避免循环卡死")
                self.doing_task_forbidden_until = time.time() + 8.0
                return False
            self.close_window()
            return True
        if screen is not None:
            res_done = batch_hits.get('ground_done')
            if res_done:
                self._no_operable_count = 0
                self.log("   -> 🕒 发现延误/完成飞机")
                if self.enable_delay_bribe:
                    agent_loc = self._locate_on_screen('stand_agent_false.png', screen)
                    if agent_loc:
                        self.log("   -> [贿赂] 点击服务代理...")
                        self.adb.click(agent_loc[0], agent_loc[1])
                        self.sleep(0.25)
                        bribe_ok = False
                        verify_start = time.time()
                        while time.time() - verify_start < 2.0:
                            self._check_running()
                            verify_screen = self.adb.get_screenshot()
                            if self._locate_on_screen('stand_agent_true.png', verify_screen, confidence=0.8):
                                bribe_ok = True
                                break
                            self.sleep(0.1)
                        if bribe_ok:
                            self.log("   -> [贿赂] 代理已激活")
                        else:
                            self.log("   -> [贿赂] 激活未确认，跳过结束服务避免误推出")
                            self.close_window()
                            return False
                self.adb.click(res_done[0], res_done[1])
                self.log("   -> ✅ 点击结束服务")
                self.sleep(0.5)
                return True
        self._no_operable_count += 1
        self.log(f"   -> 未发现可操作项目 ({self._no_operable_count}/{self._no_operable_threshold})")
        self.close_window()
        if self._no_operable_count >= self._no_operable_threshold:
            self.log("📋 [调度] 未发现可操作项目达到阈值，切换下个任务")
            self._no_operable_count = 0
            return False
        return True

    def handle_approach_task(self, target_pos=None):
        self.sleep(0.2)
        if not self._verify_and_redirect('status_approach.png'): return True
        self.log(">>> [任务] 处理进场...")
        start_time = time.time()
        approach_timeout = 1.0 if getattr(self.adb, 'screenshot_method', 'adb') in ('nemu_ipc', 'uiautomator2') else 2.0
        while time.time() - start_time < approach_timeout:
            self._check_running()
            if self.find_and_click('landing_permitted.png', wait=0):
                self._stat_approach += 1
                self._stat_session_approach += 1
                self.sleep(0.05)
                return True
            screen = self.adb.get_screenshot()
            if screen is None: continue
            vx, vy, vw, vh = self.REGION_VACANT_ROI
            vacant_roi = screen[vy:vy + vh, vx:vx + vw]
            res_vacant = self.adb.locate_image(self.icon_path + 'stand_vacant.png', confidence=0.8,
                                               screen_image=vacant_roi)
            if res_vacant:
                self.log("   -> 分配机位")
                self.adb.click(res_vacant[0] + vx, res_vacant[1] + vy)
                self.sleep(0.1)
                stand_confirm_t = 1.0 if getattr(self.adb, 'screenshot_method', 'adb') in ('nemu_ipc', 'uiautomator2') else 1.5
                if self.wait_and_click('stand_confirm.png', timeout=stand_confirm_t, click_wait=0):
                    w_start = time.time()
                    while time.time() - w_start < 2.5:
                        self._check_running()
                        if self.find_and_click('landing_permitted.png', wait=0):
                            self._stat_approach += 1
                            self._stat_session_approach += 1
                            self.sleep(0.05)
                            return True

                        check_screen = self.adb.get_screenshot()
                        if check_screen is not None:
                            bx, by, bw, bh = self.REGION_BOTTOM_ROI
                            bottom_roi = check_screen[by:by + bh, bx:bx + bw]
                            if self.adb.locate_image(self.icon_path + 'landing_prohibited.png', confidence=0.8,
                                                     screen_image=bottom_roi):
                                self.sleep(0.05)
                                return True

                        time.sleep(0.1)
                    self.sleep(0.05)
                    return True
                else:
                    self.log("❌ 找不到确认按钮")
                    self.close_window()
                    return False
            time.sleep(0.1)
        self.log("⚠️ 进场超时")
        self.close_window()
        self.sleep(1.0)
        return False

    def handle_taxiing_task(self, target_pos=None):
        self.sleep(0.2)
        if not self._verify_and_redirect('status_taxiing.png'): return True
        self.log(">>> [任务] 处理跑道穿越...")
        taxi_timeout = 1.0 if getattr(self.adb, 'screenshot_method', 'adb') in ('nemu_ipc', 'uiautomator2') else 3.0
        if self.wait_and_click('cross_runway.png', timeout=taxi_timeout, click_wait=0): return True
        self.log("⚠️ 未找到按钮")
        self.close_window()
        return False

    def handle_takeoff_task(self, target_pos=None):
        self.sleep(0.2)
        if not self._verify_and_redirect('status_takeoff.png'): return True
        self.log(">>> [任务] 处理离场...")
        start_time = time.time()
        action_buttons = ['push_back.png', 'taxi_to_runway.png', 'wait.png', 'takeoff_by_gliding.png', 'takeoff.png',
                          'get_award_1.png', 'get_award_4.png', 'start_general.png']
        sm = getattr(self.adb, 'screenshot_method', 'adb')
        scan_timeout = 1.0 if sm in ('nemu_ipc', 'uiautomator2') else 5.0
        while time.time() - start_time < scan_timeout:
            self._check_running()
            screen = self.adb.get_screenshot()
            if screen is None: continue
            bx, by, bw, bh = self.REGION_BOTTOM_ROI
            roi_img = screen[by:by + bh, bx:bx + bw]
            for btn in action_buttons:
                res = self.adb.locate_image(self.icon_path + btn, confidence=0.8, screen_image=roi_img)
                if res:
                    x = res[0] + bx
                    y = res[1] + by
                    if btn == 'get_award_1.png' or btn == 'get_award_4.png':
                        self.log("   -> 🎁 发现领奖图标，进入流程")
                        self.adb.click(x, y)
                        self.sleep(0.4)  # 等待弹窗完全出现，避免 nemu_ipc 等高速截图下未就绪
                        got_step2 = False
                        t2_start = time.time()
                        # 领奖第二步按钮：降低置信度、减小点击偏移，提高点击成功率
                        def _reward_step2_click(name):
                            return self.find_and_click(name, confidence=0.72, wait=0.6, random_offset=3)
                        while time.time() - t2_start < 15.0:
                            self._check_running()
                            if _reward_step2_click('get_award_2.png') or \
                                    _reward_step2_click('get_award_3.png') or \
                                    _reward_step2_click('get_award_4.png'):
                                got_step2 = True
                                break
                            time.sleep(0.1)
                        if not got_step2:
                            self.log("🛑 领奖流程卡死")
                            return False
                        self.log("   -> 领奖确认，等待开始检测下一步...")
                        self.sleep(1.4)
                        t3_timeout = 1.0 if sm in ('nemu_ipc', 'uiautomator2') else 2.0
                        t3_start = time.time()
                        while time.time() - t3_start < t3_timeout:
                            self._check_running()
                            s3_screen = self.adb.get_screenshot()
                            if s3_screen is None:
                                time.sleep(0.1)
                                continue
                            s3_roi = s3_screen[by:by + bh, bx:bx + bw]
                            for final_btn in ['push_back.png', 'taxi_to_runway.png', 'start_general.png']:
                                res_final = self.adb.locate_image(self.icon_path + final_btn, confidence=0.7,
                                                                  screen_image=s3_roi)
                                if res_final:
                                    if final_btn in ('push_back.png', 'taxi_to_runway.png'):
                                        self._stat_depart += 1
                                        self._stat_session_depart += 1
                                    self.adb.click(res_final[0] + bx, res_final[1] + by)
                                    self.log("   -> ✅ 离场动作执行完毕")
                                    return True
                            time.sleep(0.1)
                        if self.safe_locate('green_dot.png', region=self.REGION_GREEN_DOT):
                            self.log("   -> ⚠️ 检测到绿点，跳转至地勤分配...")
                            self.sleep(0.5)
                            return self.handle_stand_task()
                        self.log("   -> ℹ️ 未检测到绿点，判定为塔台已接管")
                        return True
                    if btn in ('push_back.png', 'taxi_to_runway.png'):
                        self._stat_depart += 1
                        self._stat_session_depart += 1
                    self.adb.click(x, y)
                    self.sleep(0.5)          
                    return True
            time.sleep(0.1)
        self.log("⚠️ 离场任务扫描超时")
        self.close_window()
        return False

    def handle_stand_task(self, target_pos=None):
        self.sleep(0.1)
        if not self._verify_and_redirect('status_stand.png'): return True
        self.log(">>> [任务] 处理停机位队列...")
        _stand_deadline = time.time() + 30.0
        while time.time() < _stand_deadline:
            self._check_running()
            avail_staff = None
            is_read_success = False
            for _ in range(3):
                val = self.check_global_staff()
                if val is not None and val < 900:
                    avail_staff = val
                    is_read_success = True
                    self._update_staff_tracker(val)
                    break
                self.sleep(0.2)
            if avail_staff is None:
                self.log("⚠️ 无法读取地勤人数，尝试盲做")
                self._update_staff_tracker(None)
                avail_staff = 999
                is_read_success = False
            required_cost = None
            for region in self._iter_region_fallbacks(self.REGION_TASK_COST, pad_x=12, pad_y=6):
                cost_text = self.ocr.recognize_number(region, mode='task')
                required_cost = self.ocr.parse_cost(cost_text)
                if required_cost is not None:
                    break
            self._stat_last_required_cost = required_cost
            if required_cost is None:
                self.log(f"⚠️ 读取花费失败，盲做")
                if self._perform_stand_action_sequence(force_verify=not is_read_success):
                    self.log("   -> 盲做成功")
                    self.stand_skip_index = 0
                    self.doing_task_forbidden_until = time.time() + 6.0
                    self.next_list_refresh_time = time.time() + 6.0
                    return True
                else:
                    if self.in_staff_shortage_mode:
                        self.log("🛑 盲做触发人员不足")
                        self.close_window()
                        if self._try_get_bonus_staff():
                            self.stand_skip_index = 0
                            return True
                    self.stand_skip_index += 1
                    return False
            self.log(f"   -> 需求: {required_cost}+1 | 可用: {avail_staff}")

            if avail_staff >= (required_cost + 1):
                self.in_staff_shortage_mode = False
                self._next_staff_recovery_probe_time = 0.0
                green_screen = self.adb.get_screenshot()
                if self._locate_on_screen('green_dot.png', green_screen, region=self.REGION_GREEN_DOT):
                    self.log("   -> ✅ 地勤人员充足，开始分配")
                    if self._perform_stand_action_sequence(force_verify=not is_read_success):
                        self.log("   -> 地勤保障开始成功")
                        self.stand_skip_index = 0
                        self.doing_task_forbidden_until = time.time() + 6.0
                        self.next_list_refresh_time = time.time() + 6.0
                        return True
                    else:
                        if not self.in_staff_shortage_mode:
                            self.log("   -> 操作未成功，跳过本架")
                            self.stand_skip_index += 1
                            return False
                else:
                    self.log("   -> ⚠️ 人员充足但未检测到绿点，跳过")
                    self.close_window()
                    return False

            self.log(f"🛑 人力不足 (缺 {required_cost + 1 - avail_staff})")
            self.close_window()
            if self._try_get_bonus_staff():
                self.log("   -> 领取成功，重试")
                self.stand_skip_index = 0
                return True
            self.stand_skip_index += 1
            self.in_staff_shortage_mode = True
            self._next_staff_recovery_probe_time = time.time() + self._staff_recovery_probe_interval
            self.last_known_available_staff = avail_staff
            return False

    def handle_ice_task(self, target_pos=None):
        self.sleep(0.2)
        if not self._verify_and_redirect('status_ice.png'): return True
        self.log(">>> [任务] 处理除冰...")
        ice_timeout = 1.0 if getattr(self.adb, 'screenshot_method', 'adb') in ('nemu_ipc', 'uiautomator2') else 3.0
        if self.wait_and_click('start_ice.png', timeout=ice_timeout, click_wait=0.5):
            self.log("   -> 除冰开始")
            return True
        self.log("⚠️ 未找到除冰按钮")
        self.close_window()
        return False

    def handle_repair_task(self, target_pos=None):
        self.sleep(0.2)
        self.log(">>> [任务] 处理维修/维护...")
        action_buttons = ['go_repair.png', 'start_repair.png', 'start_general.png']
        start_time = time.time()
        repair_timeout = 1.0 if getattr(self.adb, 'screenshot_method', 'adb') in ('nemu_ipc', 'uiautomator2') else 3.0
        while time.time() - start_time < repair_timeout:
            self._check_running()
            screen = self.adb.get_screenshot()
            if screen is None: continue
            bx, by, bw, bh = self.REGION_BOTTOM_ROI
            roi_img = screen[by:by + bh, bx:bx + bw]
            for btn in action_buttons:
                res = self.adb.locate_image(self.icon_path + btn, confidence=0.8, screen_image=roi_img)
                if res:
                    abs_x = res[0] + bx
                    abs_y = res[1] + by
                    self.adb.click(abs_x, abs_y)
                    self.log(f"   -> ✅ 维护开始 ({btn})")
                    self.sleep(0.5)
                    if btn == 'start_repair.png':
                        self._check_running()
                        s2 = self.adb.get_screenshot()
                        if s2 is not None:
                            roi2 = s2[by:by + bh, bx:bx + bw]
                            res2 = self.adb.locate_image(self.icon_path + 'go_repair.png', confidence=0.8, screen_image=roi2)
                            if res2:
                                self.adb.click(res2[0] + bx, res2[1] + by)
                                self.log("   -> ✅ 点击 go_repair")
                                self.sleep(0.5)
                    return True
            time.sleep(0.1)
        self.log("⚠️ 未找到维修按钮")
        self.close_window()
        return False

    def _try_get_bonus_staff(self):
        if not self.enable_bonus_staff: return False
        now = time.time()
        if now < self.next_bonus_retry_time: return False
        self.log(">>> [福利] 开始领取流程...")
        if self.find_and_click('top_ground_staff.png', wait=0.8):
            self.adb.click(800, 580)
            self.sleep(2.0)
            if self.wait_and_click('get_staff.png', timeout=2.0, click_wait=1.0, confidence=0.7):
                self.log("   -> ✅ 领取成功！")
                self.sleep(2.0)
                self.next_bonus_retry_time = time.time() + (2 * 60 * 60)
                # back.png 偏移量减小
                self.find_and_click('back.png', wait=0.5, random_offset=2)
                self.sleep(3.0)
                return True
            else:
                self.log("   -> 未找到领取按钮")
                self.next_bonus_retry_time = time.time() + (15 * 60)
                # back.png 偏移量减小
                self.find_and_click('back.png', wait=0.5, random_offset=2)
                self.sleep(3.0)
                return True
        self.log("❌ 未找到顶部地勤图标")
        self.next_bonus_retry_time = time.time() + (15 * 60)
        return False

    def _perform_stand_action_sequence(self, force_verify=False):
        if self.slide_min_duration >= self.slide_max_duration:
            rand_duration = self.slide_min_duration
        else:
            rand_duration = random.randint(self.slide_min_duration, self.slide_max_duration)

        start_x = int(random.gauss(494, 5))
        start_y = int(random.gauss(574, 5))
        end_x = random.randint(800, 900)
        end_y = int(random.gauss(574, 5))

        self.log(f"   -> [动作] 拟人滑块: ({start_x},{start_y})->({end_x},{end_y}) 耗时:{rand_duration}ms")
        self.adb.swipe(start_x, start_y, end_x, end_y, duration_ms=rand_duration)

        self.sleep(0.1)
        agent_x = int(random.gauss(803, 5))
        agent_y = int(random.gauss(646, 5))
        self.adb.click(agent_x, agent_y)
        self.sleep(0.3)

        if self.safe_locate('insufficient_ground_staff.png', confidence=0.7):
            self.log("🛑 警告：人员不足 (盲操作后检测)")
            self.in_staff_shortage_mode = True
            self.last_known_available_staff = 0
            self.close_window()
            return False

        should_skip = self.enable_skip_staff and (not force_verify)
        if should_skip:
            self.log("   -> [极速] 跳过地勤验证")
        else:
            if self.enable_skip_staff and force_verify:
                self.log("   -> [安全] 地勤人数未知，强制执行验证")
            self.sleep(0.2)
            check_x, check_y = 63, 546
            b, g, r = self.adb.get_pixel_color(check_x, check_y)
            target_b, target_g, target_r = 153, 220, 96
            diff = abs(b - target_b) + abs(g - target_g) + abs(r - target_r)
            is_green = diff < 100

            if is_green:
                self.log("   -> [颜色检测] ✅ 通过")
            else:
                self.log(f"   -> [颜色检测] ❌ 失败 (diff={diff})")

            is_success_icon = self.safe_locate('stand_agent_true.png', confidence=0.85)
            if is_success_icon:
                self.log("   -> [图标检测] ✅ 通过")
            else:
                self.log("   -> [图标检测] ❌ 失败")
            if not (is_green and is_success_icon):
                self.log("🛑 验证失败：颜色或图标未通过")
                if self.safe_locate('insufficient_ground_staff.png', confidence=0.7):
                    self.log("   -> 原因：发现了人员不足警告")
                    self.in_staff_shortage_mode = True
                    self.last_known_available_staff = 0
                self.close_window()
                return False

        if self.wait_and_click('start_ground_support.png', timeout=2.0, click_wait=0):
            self._stat_stand_count += 1
            self._stat_session_stand_count += 1
            cost = self._stat_last_required_cost
            if cost is not None:
                add_staff = cost + 1
                self._stat_stand_staff += add_staff
                self._stat_session_stand_staff += add_staff
            self.sleep(0.5)
            return True
        else:
            if self.safe_locate('insufficient_ground_staff.png', confidence=0.7):
                self.log("🛑 警告：人员不足 (寻找开始按钮时)")
                self.in_staff_shortage_mode = True
                self.last_known_available_staff = 0
            self.close_window()
            return False

    def _check_and_recover_interface(self, current_screen=None):
        now_ts = time.time()
        if now_ts < self._next_interface_check_time:
            return
        self._next_interface_check_time = now_ts + self._interface_check_interval

        main_hit = self._locate_on_screen('main_interface.png', current_screen, confidence=0.8, region=self.REGION_MAIN_ANCHOR)
        if main_hit:
            self.last_seen_main_interface_time = now_ts
            return
        if current_screen is None and self.safe_locate('main_interface.png', region=self.REGION_MAIN_ANCHOR, confidence=0.8):
            self.last_seen_main_interface_time = now_ts
            return
        if not self.enable_anti_stuck:
            return
        elapsed = now_ts - self.last_seen_main_interface_time
        if elapsed > self.STUCK_TIMEOUT:
            self._record_anti_stuck_trigger(f"未检测到主界面已 {int(elapsed)} 秒，尝试强行返回")

            # First Start 恢复逻辑
            if self.find_and_click('first_start_1.png', wait=0.5):
                self.log("   -> 尝试 First Start 恢复流程...")
                fs_start = time.time()
                found_step2 = False
                while time.time() - fs_start < 5.0:
                    self._check_running()
                    if self.find_and_click('first_start_2.png', wait=0.5):
                        found_step2 = True
                        break
                    self.sleep(0.5)

                if found_step2:
                    self.log("   -> 正在等待返回主界面...")
                    wait_main = time.time()
                    while time.time() - wait_main < 20.0:
                        self._check_running()
                        if self.safe_locate('main_interface.png', region=self.REGION_MAIN_ANCHOR, confidence=0.8):
                            self.last_seen_main_interface_time = time.time()
                            self.log("   -> ✅ 恢复成功")
                            return
                        self.sleep(1.0)

            if self.wait_and_click('back.png', timeout=1.0, click_wait=0.5, random_offset=2):
                self.log("   -> 点击了 Back 按钮")
                self.last_seen_main_interface_time = time.time()
                return
            if self.wait_and_click('cancel.png', timeout=1.0, click_wait=0.5):
                self.log("   -> 点击了 Cancel 按钮")
                self.last_seen_main_interface_time = time.time()
                return
            self.log("   -> 尝试盲点关闭区域")
            self.close_window()
            self.last_seen_main_interface_time = time.time() - (self.STUCK_TIMEOUT - 5)

    def _task_key(self, task):
        center = task.get('center', (0, 0))
        return f"{task.get('name', '')}:{center[0]}:{center[1]}"

    def _is_task_on_cooldown(self, task):
        key = self._task_key(task)
        until = self._task_fail_cooldown.get(key, 0.0)
        return time.time() < until

    def _mark_task_failed(self, task):
        key = self._task_key(task)
        self._task_fail_cooldown[key] = time.time() + self._task_fail_cooldown_sec

    def _cleanup_task_cooldown(self):
        now = time.time()
        expired = [k for k, v in self._task_fail_cooldown.items() if v <= now]
        for k in expired:
            self._task_fail_cooldown.pop(k, None)

    def _execute_task(self, task):
        self.log(f"识别结果: {task['name']} (分数: {task['score']:.2f})")
        self.adb.click(task['center'][0] + 60, task['center'][1], random_offset=3)
        try:
            result = task['handler']()
        except (StopSignal, KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            result = task['handler'](None)

        if result:
            self._task_fail_cooldown.pop(self._task_key(task), None)
            return True

        self._mark_task_failed(task)
        self.log(f"📋 [调度] 当前任务未满足，自动切换下一任务: {task['name']}")
        return False

    def scan_and_process(self):
        current_screen = self.adb.get_screenshot()
        self._check_and_recover_interface(current_screen=current_screen)
        self._periodic_15s_check()
        self._cleanup_task_cooldown()

        if current_screen is None:
            if not hasattr(self, '_scan_screenshot_fails'):
                self._scan_screenshot_fails = 0
            self._scan_screenshot_fails += 1
            if self._scan_screenshot_fails >= 5:
                self.log(f"⚠️ [连接] 截图连续{self._scan_screenshot_fails}次失败，尝试重建 ADB 连接...")
                self._scan_screenshot_fails = 0
                try:
                    self.adb.connect()
                    self.adb._start_persistent_shell()
                except Exception as e:
                    self.log(f"⚠️ [连接] ADB 重连异常: {e}")
                self.sleep(1.0)
            return False
        self._scan_screenshot_fails = 0

        if not hasattr(self, 'last_staff_check_time'): self.last_staff_check_time = 0
        now = time.time()
        prev_staff = self.last_checked_avail_staff
        staff_this_round = None
        staff_check_interval = 1.0 if (self.in_staff_shortage_mode or self.stand_skip_index > 0) else 3.0
        if now - self.last_staff_check_time > staff_check_interval:
            staff_this_round = self.check_global_staff(screen_image=current_screen)
            self._update_staff_tracker(staff_this_round)
            self.last_staff_check_time = now

        if self.in_staff_shortage_mode or self.stand_skip_index > 0:
            current_avail = staff_this_round if staff_this_round is not None else self.check_global_staff(screen_image=current_screen)
            if current_avail is not None:
                is_blind_recovery = (prev_staff >= 900) and (current_avail < 900)
                is_changed = (prev_staff != -1) and (current_avail != prev_staff)
                is_zero_recovery = (prev_staff == 0) and (current_avail > 0)
                is_safe_amount = current_avail >= 15
                required_cost = self._stat_last_required_cost
                meets_required_cost = required_cost is not None and current_avail >= (required_cost + 1)
                if is_safe_amount or is_changed or is_blind_recovery or is_zero_recovery or meets_required_cost:
                    if meets_required_cost:
                        self.log(f"✅ 地勤已满足当前需求 ({current_avail} >= {required_cost + 1})，恢复执行")
                    elif is_changed:
                        self.log(f"✅ 地勤变化 ({prev_staff}->{current_avail})，恢复")
                    self.in_staff_shortage_mode = False
                    self.stand_skip_index = 0
                    self._next_staff_recovery_probe_time = 0.0
                self.last_checked_avail_staff = current_avail

        if self._check_and_perform_auto_delay(current_screen): return True
        lx, ly, lw, lh = self.LIST_ROI_X, 0, self.LIST_ROI_W, self.LIST_ROI_H
        list_roi_img = current_screen[ly:ly + lh, lx:lx + lw]
        _, final_tasks = self._run_pending_detection(list_roi_img)
        # 注意：运行过程中不再与 ADB 校验后自动回退，仅在启动时通过截图方案测试和回退链确定方案

        doing_tasks = [d for d in final_tasks if d['type'] == 'doing']
        if not self.enable_no_takeoff_mode:
            for det in doing_tasks:
                if time.time() <= self.doing_task_forbidden_until:
                    continue
                if self._is_task_on_cooldown(det):
                    continue
                self.log(f"⚡ [高优] 发现 Doing 任务 (分数: {det['score']:.2f})")
                if self._execute_task(det):
                    return True

        valid_candidates = []
        no_takeoff_strategy = self._get_no_takeoff_strategy() if self.enable_no_takeoff_mode else None
        skips_left = self.stand_skip_index
        for t in final_tasks:
            if t['type'] == 'doing' and not self.enable_no_takeoff_mode:
                continue
            if t['type'] == 'stand':
                if self.in_staff_shortage_mode:
                    if time.time() < self._next_staff_recovery_probe_time:
                        continue
                    self.log("📋 [调度] 地勤短缺恢复探测：尝试执行一个停机位任务")
                    self._next_staff_recovery_probe_time = time.time() + self._staff_recovery_probe_interval
                if skips_left > 0:
                    skips_left -= 1
                    continue
            if self._is_task_on_cooldown(t):
                continue
            valid_candidates.append(t)

        if not valid_candidates:
            if self.enable_no_takeoff_mode and no_takeoff_strategy == 'landing_stand_cycle':
                self._toggle_no_takeoff_cycle_side(reason="当前分组无任务")
                self._periodic_15s_check(force_initial_filter_check=True)
            if not getattr(self, '_no_candidate_closed', False):
                self._no_candidate_closed = True
                n_doing = len(doing_tasks)
                n_total = len(final_tasks)
                self.log(f"📋 [检测] 任务数={n_total}, Doing={n_doing}, 有效候选=0 -> 关闭窗口")
                self.close_window()
            return False

        self._no_candidate_closed = False
        ordered_tasks = []
        if self.enable_random_task and len(valid_candidates) > 1:
            top_k = 3
            if random.random() < 0.8:
                pool = valid_candidates[:top_k]
                first = random.choice(pool)
            else:
                pool = valid_candidates[top_k:]
                if not pool:
                    pool = valid_candidates[:top_k]
                first = random.choice(pool)
            ordered_tasks = [first] + [t for t in valid_candidates if t is not first]
        else:
            ordered_tasks = valid_candidates

        time_until_refresh = self.next_list_refresh_time - time.time()
        if 0 < time_until_refresh < 0.8:
            self.sleep(time_until_refresh + 0.5)
            return False

        for task in ordered_tasks:
            if self._execute_task(task):
                return True
        return False