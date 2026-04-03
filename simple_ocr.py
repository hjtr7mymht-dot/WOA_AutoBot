# OCR 模板匹配模块
# 从 main_adb.py 提取的独立模块

import cv2
import numpy as np
import os
import re

# 资助功能完整性守卫标记（由 gui_launcher 在严格模式下联动校验）
WOA_FEATURE_GUARD_TOKEN = "WOA_DONATE_GUARD_V1"


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

    def _to_gray(self, img):
        if img is None or img.size == 0:
            return None
        if len(img.shape) == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    def _process_image(self, img):
        if img is None or img.size == 0:
            return None
        h, w = img.shape[:2]
        try:
            scaled_img = cv2.resize(img, (w * self.SCALE_FACTOR, h * self.SCALE_FACTOR), interpolation=cv2.INTER_CUBIC)
            gray = self._to_gray(scaled_img)
            if gray is None:
                return None
            _, binary = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
            return binary
        except Exception:
            return None

    def _build_processed_variants(self, img):
        gray = self._to_gray(img)
        if gray is None:
            return []
        h, w = gray.shape[:2]
        scale_candidates = [self.SCALE_FACTOR]
        if h <= 26 or w <= 90:
            scale_candidates.append(max(self.SCALE_FACTOR + 2, 6))
        variants = []
        seen = set()
        for scale in scale_candidates:
            try:
                scaled = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
            except Exception:
                continue
            normalized = cv2.normalize(scaled, None, 0, 255, cv2.NORM_MINMAX)
            blurred = cv2.GaussianBlur(normalized, (3, 3), 0)
            threshold_variants = []
            for threshold in (145, 160, 175, 190):
                _, binary = cv2.threshold(blurred, threshold, 255, cv2.THRESH_BINARY)
                threshold_variants.append(binary)
            _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            threshold_variants.append(otsu)
            adaptive = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            threshold_variants.append(adaptive)
            for binary in threshold_variants:
                signature = (binary.shape[0], binary.shape[1], int(binary.mean()))
                if signature in seen:
                    continue
                seen.add(signature)
                variants.append(binary)
        return variants

    def _region_candidates(self, region, screen_shape):
        x, y, w, h = region
        max_h, max_w = screen_shape[:2]
        pad_x = max(3, int(round(w * 0.18)))
        pad_y = max(2, int(round(h * 0.25)))
        candidates = []
        raw_candidates = [
            (x, y, w, h),
            (x - pad_x, y - pad_y, w + pad_x * 2, h + pad_y * 2),
            (x - pad_x, y, w + pad_x * 2, h),
            (x, y - pad_y, w, h + pad_y * 2),
            (x + pad_x // 2, y, w, h),
            (x - pad_x // 2, y, w, h),
        ]
        for cx, cy, cw, ch in raw_candidates:
            nx = max(0, cx)
            ny = max(0, cy)
            nw = min(max_w - nx, cw)
            nh = min(max_h - ny, ch)
            if nw <= 2 or nh <= 2:
                continue
            candidate = (nx, ny, nw, nh)
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _extract_text_from_processed(self, processed_crop, templates):
        if processed_crop is None or processed_crop.size == 0:
            return None, 0.0
        matches = []
        threshold = 0.7
        for char, template in templates.items():
            if template.shape[0] > processed_crop.shape[0] or template.shape[1] > processed_crop.shape[1]:
                continue
            res = cv2.matchTemplate(processed_crop, template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)
            t_w = template.shape[1]
            for pt in zip(*loc[::-1]):
                score = float(res[pt[1], pt[0]])
                matches.append({'x': pt[0], 'char': '/' if char == 'slash' else char, 'score': score, 'width': t_w})
        if not matches:
            return None, 0.0
        matches.sort(key=lambda k: k['x'])
        final_results = []
        while matches:
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
        if not result_str:
            return None, 0.0
        total_score = sum(m['score'] for m in final_results)
        quality = total_score / max(1, len(final_results))
        return result_str, quality

    def _score_text(self, text, quality, mode):
        if not text:
            return -1.0
        score = float(quality)
        digit_count = sum(ch.isdigit() for ch in text)
        score += min(digit_count, 6) * 0.03
        if '/' in text:
            score += 0.12
        if mode == 'global' and '/' in text and digit_count >= 2:
            score += 0.15
        if any(ch in text for ch in ('h', 'm', 's')):
            score += 0.08
        return score

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
        if screen_image is not None:
            full_screen = screen_image
        else:
            full_screen = self.adb.get_screenshot()
        if full_screen is None:
            return None
        templates = self.templates_global if mode == 'global' else self.templates_task
        if not templates:
            return None

        best_text = None
        best_score = -1.0
        for candidate_region in self._region_candidates(region, full_screen.shape):
            x, y, w, h = candidate_region
            if y < 0 or x < 0 or y + h > full_screen.shape[0] or x + w > full_screen.shape[1]:
                continue
            crop_img = full_screen[y:y + h, x:x + w]
            processed_variants = []
            primary = self._process_image(crop_img)
            if primary is not None:
                processed_variants.append(primary)
            processed_variants.extend(self._build_processed_variants(crop_img))
            for processed_crop in processed_variants:
                result_str, quality = self._extract_text_from_processed(processed_crop, templates)
                text_score = self._score_text(result_str, quality, mode)
                if text_score > best_score:
                    best_score = text_score
                    best_text = result_str
                if mode == 'global' and result_str and '/' in result_str and sum(ch.isdigit() for ch in result_str) >= 2:
                    return result_str
        return best_text

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
