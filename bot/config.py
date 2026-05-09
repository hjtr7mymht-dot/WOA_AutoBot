# -*- coding: utf-8 -*-
"""
WOA AutoBot - 配置管理 Mixin
从 main_adb.py 提取的配置 Setter 方法。
"""

import time


class ConfigMixin:
    """配置项 Setter 集合，与 WoaBot 主类通过多重继承合并。"""

    # ─── 随机任务 ──────────────────────────────────────
    def set_random_task_mode(self, enabled, log_change=True):
        if self.enable_random_task == enabled:
            return
        self.enable_random_task = enabled
        if log_change:
            self.log(f">>> [配置] 随机任务选择: {'已开启' if enabled else '已关闭'}")

    # ─── 不起飞模式 ────────────────────────────────────
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
        if self._no_takeoff_switch_interval != interval:
            self._no_takeoff_switch_interval = interval
            self._no_takeoff_cycle_next_switch_time = time.time() + interval
            self.log(f">>> [配置] 不起飞轮切间隔已更新: {interval:.0f} 秒")

    def set_no_takeoff_auto_logout_interval(self, minutes):
        try:
            interval = float(minutes)
        except (TypeError, ValueError):
            interval = 30.0
        interval = max(1.0, min(120.0, interval))
        if self._no_takeoff_auto_logout_interval != interval:
            self._no_takeoff_auto_logout_interval = interval
            self._schedule_no_takeoff_auto_logout()
            self.log(f">>> [配置] 不起飞自动小退间隔已更新: {interval:.0f} 分钟")

    def set_standalone_logout_enabled(self, enabled):
        if self.enable_standalone_logout == enabled:
            return
        self.enable_standalone_logout = enabled
        self.log(f">>> [配置] 独立小退: {'已开启' if enabled else '已关闭'}")
        if enabled:
            self._schedule_standalone_logout()

    def set_standalone_logout_interval(self, minutes):
        try:
            interval = float(minutes)
        except (TypeError, ValueError):
            interval = 30.0
        interval = max(1.0, min(120.0, interval))
        if self._standalone_logout_interval != interval:
            self._standalone_logout_interval = interval
            self.log(f">>> [配置] 独立小退间隔已更新: {interval:.0f} 分钟")
        if self.enable_standalone_logout:
            self._schedule_standalone_logout()

    # ─── 筛选 / 塔台过滤 ────────────────────────────────
    def set_cancel_stand_filter_when_tower_off(self, enabled):
        if self.enable_cancel_stand_filter == enabled:
            return
        self.enable_cancel_stand_filter = enabled
        self.log(f">>> [配置] 塔台关闭时筛选全部飞机: {'已开启' if enabled else '已关闭'}")

    def set_filter_stand_only_when_tower_open(self, enabled):
        if self.enable_filter_stand_only_when_tower_open == enabled:
            return
        self.enable_filter_stand_only_when_tower_open = enabled
        if not enabled and not self.enable_no_takeoff_mode:
            self._request_switch_mode1 = True
        self.log(f">>> [配置] 塔台全开时仅停机位待处理: {'已开启' if enabled else '已关闭'}")

    # ─── 速度优化 ──────────────────────────────────────
    def set_bonus_staff_feature(self, enabled):
        self.enable_bonus_staff = enabled

    def set_vehicle_buy_feature(self, enabled):
        self.enable_vehicle_buy = enabled

    def set_speed_mode(self, enabled):
        self.enable_speed_mode = enabled

    def set_skip_staff_verify(self, enabled):
        self.enable_skip_staff = enabled

    def set_delay_bribe(self, enabled):
        self.enable_delay_bribe = enabled

    def set_auto_delay(self, count):
        if self.auto_delay_count != count:
            self.auto_delay_count = count
            if count > 0:
                self.log(f">>> [配置] 自动延时塔台: 已开启 (剩余 {count} 次)")
                try:
                    self._init_tower_countdown()
                except Exception as e:
                    self.log(f"🗼 [塔台] ⚠️ 重新初始化塔台状态失败: {e}")
            else:
                self.log(">>> [配置] 自动延时塔台: 已关闭")

    # ─── 防卡死 ────────────────────────────────────────
    def set_anti_stuck_config(self, enabled, threshold=None, log_change=True):
        self.enable_anti_stuck = enabled
        if threshold is not None:
            threshold = max(3, min(20, int(threshold)))
            if self._anti_stuck_stop_threshold != threshold:
                self._anti_stuck_stop_threshold = threshold
                if log_change:
                    self.log(f">>> [配置] 防卡死触发阈值: {threshold}")
        if log_change:
            self.log(f">>> [配置] 防卡死: {'已开启' if enabled else '已关闭'}")

    # ─── 滑动 / 思考时间 ────────────────────────────────
    def set_slide_duration_range(self, min_d, max_d, log_change=True):
        self.slide_min_duration = max(100, int(min_d))
        self.slide_max_duration = min(2000, max(self.slide_min_duration, int(max_d)))
        if log_change:
            self.log(f">>> [配置] 滑动耗时范围: {self.slide_min_duration}-{self.slide_max_duration}ms")

    def set_thinking_time_mode(self, mode_index, log_change=True):
        thinking_configs = {
            0: (0.0, 0.0),
            1: (0.1, 0.4),
            2: (0.3, 1.0),
            3: (0.8, 2.0),
        }
        self.thinking_mode = int(mode_index)
        self.thinking_range = thinking_configs.get(self.thinking_mode, (0, 0))
        if self.adb:
            self.adb.set_thinking_strategy(*self.thinking_range)
        if log_change:
            labels = {0: "关闭", 1: "短(0.1-0.4)", 2: "中(0.3-1.0)", 3: "长(0.8-2.0)"}
            self.log(f">>> [配置] 随机思考时间: {labels.get(self.thinking_mode, '未知')}")

    # ─── 设备/方法 ──────────────────────────────────────
    def set_device(self, device_serial):
        self.target_device = device_serial

    def set_control_method(self, method):
        self.control_method = method
        if self.adb:
            self.adb.set_control_method(method)

    def set_screenshot_method(self, method):
        self.screenshot_method = method
        if self.adb:
            self.adb.set_screenshot_method(method)

    def set_mumu_path(self, path):
        self.mumu_path = (path or "").strip()
        if self.adb and path:
            self.adb.set_mumu_path(path)

    # ─── 模块/分支 ─────────────────────────────────────
    def _is_module_enabled(self, module_name):
        return self.module_flags.get(module_name, True)

    def set_module_enabled(self, module_name, enabled, log_change=True):
        if module_name in self.module_flags:
            self.module_flags[module_name] = bool(enabled)
            if log_change:
                self.log(f">>> [模块] {module_name}: {'开启' if enabled else '关闭'}")

    def set_module_flags(self, flags, log_change=True):
        if isinstance(flags, dict):
            for k, v in flags.items():
                if k in self.module_flags:
                    self.module_flags[k] = bool(v)
            if log_change:
                enabled = [k for k, v in self.module_flags.items() if v]
                self.log(f">>> [模块] 已启用: {', '.join(enabled) if enabled else '(无)'}")

    def set_active_branch(self, branch_name, log_change=True):
        if branch_name in self.branch_definitions:
            self.active_branch = branch_name
            for key in self.module_flags:
                self.module_flags[key] = key in self.branch_definitions[branch_name]
            if log_change:
                self.log(f">>> [模块] 分支已切换为: {branch_name}")
