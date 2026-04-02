# OCR 模板匹配模块
# 从 main_adb.py 提取的独立模块

import cv2
import numpy as np
import os
import re


class StopSignal(Exception):
    pass


class SimpleOCR:
    def __init__(self, adb_controller, icon_path):
        self.adb = adb_controller
        self.root_path = os.path.join(icon_path, "digits")
        self.SCALE_FACTOR = 4
        self.templates_global = {}
        self.templates_task = {}
        self._load_templates("global", self.templates_global)
        self._load_templates("task", self.templates_task)

    def _process_image(self, img):
        if img is None or img.size == 0: return None
        h, w = img.shape[:2]
        try:
            scaled_img = cv2.resize(img, (w * self.SCALE_FACTOR, h * self.SCALE_FACTOR), interpolation=cv2.INTER_LINEAR)
            if len(scaled_img.shape) == 3:
                gray = cv2.cvtColor(scaled_img, cv2.COLOR_BGR2GRAY)
            else:
                gray = scaled_img
            _, binary = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
            return binary
        except Exception:
            return None

    def _load_templates(self, sub_folder, target_dict):
        folder_path = os.path.join(self.root_path, sub_folder) + os.sep
        if not os.path.exists(folder_path): return
        chars = [str(i) for i in range(10)] + ['slash', 'h', 'm', 's']
        for char in chars:
            path = folder_path + char + ".png"
            if os.path.exists(path):
                img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                target_dict[char] = img

    def recognize_number(self, region, mode='global', screen_image=None):
        x, y, w, h = region
        if screen_image is not None:
            full_screen = screen_image
        else:
            full_screen = self.adb.get_screenshot()
        if full_screen is None: return None

        if y < 0 or x < 0 or y + h > full_screen.shape[0] or x + w > full_screen.shape[1]:
            return None

        crop_img = full_screen[y:y + h, x:x + w]
        processed_crop = self._process_image(crop_img)
        if processed_crop is None: return None

        templates = self.templates_global if mode == 'global' else self.templates_task
        if not templates: return None
        matches = []
        threshold = 0.7
        for char, template in templates.items():
            if template.shape[0] > processed_crop.shape[0] or template.shape[1] > processed_crop.shape[1]:
                continue
            res = cv2.matchTemplate(processed_crop, template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)
            t_w = template.shape[1]
            for pt in zip(*loc[::-1]):
                score = res[pt[1], pt[0]]
                matches.append({'x': pt[0], 'char': '/' if char == 'slash' else char, 'score': score, 'width': t_w})
        if not matches: return None
        matches.sort(key=lambda k: k['x'])
        final_results = []
        while len(matches) > 0:
            curr = matches.pop(0)
            keep_curr = True
            if final_results:
                last = final_results[-1]
                is_one_slash = (curr['char'] == '1' and last['char'] == '/') or \
                               (curr['char'] == '/' and last['char'] == '1')
                if is_one_slash:
                    final_results.append(curr)
                    continue
                start = max(last['x'], curr['x'])
                end = min(last['x'] + last['width'], curr['x'] + curr['width'])
                overlap = max(0, end - start)
                min_width = min(last['width'], curr['width'])
                if overlap > min_width * 0.4:
                    if curr['score'] > last['score']:
                        final_results.pop()
                        final_results.append(curr)
                    keep_curr = False
            if keep_curr:
                final_results.append(curr)
        result_str = "".join([m['char'] for m in final_results])
        return result_str

    def parse_staff_count(self, text):
        try:
            if not text or '/' not in text: return None
            clean = "".join([c for c in text if c.isdigit() or c == '/'])
            parts = clean.split('/')
            if len(parts) < 2: return None
            used = int(parts[0])
            total = int(parts[1])
            avail = total - used
            if avail < 0: return None
            return used, total, avail
        except Exception:
            return None

    def parse_cost(self, text):
        try:
            if not text or '/' not in text: return None
            clean = "".join([c for c in text if c.isdigit() or c == '/'])
            parts = clean.split('/')
            if len(parts) < 2: return None
            cost_str = parts[1]
            if not cost_str: return None
            cost = int(cost_str)
            if cost == 0: return 10
            if cost < 0 or cost > 25: return None
            return cost
        except Exception:
            return None

    def parse_tower_time(self, text):
        """解析塔台倒计时文本，如 '0m56s' '8m35s' '2h05m'，返回总秒数，失败返回 None"""
        if not text:
            return None
        try:
            text = text.strip().replace(' ', '')
            # 匹配 XhYm 格式
            m = re.match(r'^(\d+)h(\d+)m$', text)
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60
            # 匹配 XmYs 格式
            m = re.match(r'^(\d+)m(\d+)s$', text)
            if m:
                return int(m.group(1)) * 60 + int(m.group(2))
            # 匹配纯 Xh
            m = re.match(r'^(\d+)h$', text)
            if m:
                return int(m.group(1)) * 3600
            # 匹配纯 Xm
            m = re.match(r'^(\d+)m$', text)
            if m:
                return int(m.group(1)) * 60
            # 匹配纯 Xs
            m = re.match(r'^(\d+)s$', text)
            if m:
                return int(m.group(1))
            return None
        except Exception:
            return None
