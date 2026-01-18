"""OCR Processing logic (No-OpenCV / PIL Version)."""
import logging
import io
import numpy as np
from PIL import Image, ImageOps, ImageDraw

from .const import (
    DEFAULT_ROI, DEFAULT_SKEW,
    OCR_MIN_PEAK_BRIGHTNESS,
    VALID_MIN, VALID_MAX,
    DEBUG_DIR_ROOT
)

_LOGGER = logging.getLogger(__name__)

# === 核心配置 ===
# 判定阈值：黑色像素占比 >= 50% 视为笔画存在
ACTIVE_RATIO = 0.50
# 笔画检测区域大小 (宽, 高)
SEGMENT_SIZE = (2, 2)

# 七段数码管逻辑映射表
# 顺序: a, b, c, d, e, f, g
SEGMENT_MAP = {
    (1, 1, 1, 1, 1, 1, 0): 0, 
    (0, 1, 1, 0, 0, 0, 0): 1, 
    (1, 1, 0, 1, 1, 0, 1): 2,
    (1, 1, 1, 1, 0, 0, 1): 3, 
    (0, 1, 1, 0, 0, 1, 1): 4, 
    (1, 0, 1, 1, 0, 1, 1): 5,
    (1, 0, 1, 1, 1, 1, 1): 6, 
    (1, 1, 1, 0, 0, 0, 0): 7, 
    (1, 1, 1, 1, 1, 1, 1): 8,
    (1, 1, 1, 1, 0, 1, 1): 9, 
    (0, 0, 0, 0, 0, 0, 0): None
}

# 局部坐标定义 (相对 ROI 左上角)
# 用于识别数字笔画
LOCAL_SEGMENTS = {
    # 十位
    'a1': (11, 5),  'b1': (15, 8),  'c1': (13, 16),
    'd1': (8, 20),  'e1': (3, 16),  'f1': (5, 8),   'g1': (9, 12),
    # 个位
    'a0': (27, 5),  'b0': (31, 8),  'c0': (29, 15),
    'd0': (24, 19), 'e0': (20, 15), 'f0': (21, 8),  'g0': (25, 11)
}

# === 新增：哨兵点 (Guard Points) ===
# 这些坐标必须是背景（白色/0像素占比低）。
# 如果这些点被检测为黑色（有笔画），说明图像二值化异常（如全黑），应直接丢弃。
# 坐标计算：
# 上方哨兵：a1(y=5) - 4 = y=1
# 下方哨兵：d1(y=20) + 高度2 + 2 = y=24
GUARD_SEGMENTS = {
    'Check_Top_10': (11, 1),   # 十位上方
    'Check_Bot_10': (8, 24),   # 十位下方
    'Check_Top_01': (27, 1),   # 个位上方
    'Check_Bot_01': (24, 23)   # 个位下方 (d0在19, +4=23)
}

class OCRProcessor:
    """Class to handle OCR logic using PIL only (No OpenCV)."""

    def __init__(self):
        self._roi = DEFAULT_ROI
        self._skew = DEFAULT_SKEW

    def configure(self, roi, skew):
        """Update parameters."""
        self._roi = roi
        self._skew = skew

    def _get_otsu_threshold(self, img_gray):
        """手动实现 Otsu 阈值算法"""
        hist = img_gray.histogram()
        total = sum(hist)
        current_max, threshold = 0, 0
        sum_total, sum_foreground, weight_background, weight_foreground = 0, 0, 0, 0

        for i in range(256):
            sum_total += i * hist[i]

        for i in range(256):
            weight_background += hist[i]
            if weight_background == 0: continue
            weight_foreground = total - weight_background
            if weight_foreground == 0: break

            sum_foreground += i * hist[i]
            
            mean_bg = sum_foreground / weight_background
            mean_fg = (sum_total - sum_foreground) / weight_foreground
            
            between_class_variance = weight_background * weight_foreground * ((mean_bg - mean_fg) ** 2)
            
            if between_class_variance > current_max:
                current_max = between_class_variance
                threshold = i

        return threshold

    def _check_zone_active(self, np_bin, x, y, w, h):
        """检查指定区域是否“激活”（黑色像素占比高）"""
        # 边界检查
        max_h, max_w = np_bin.shape
        if x < 0 or y < 0 or x + w > max_w or y + h > max_h:
            return False, 0.0

        # 提取区域 (注意 numpy 是 [y, x])
        zone = np_bin[y : y + h, x : x + w]
        
        zone_total = zone.size
        # 统计黑色像素 (假设处理后 0=黑/笔画, 255=白/背景)
        zone_white = np.count_nonzero(zone == 255)
        zone_black = zone_total - zone_white
        
        ratio = zone_black / zone_total if zone_total > 0 else 0
        return (ratio >= ACTIVE_RATIO), ratio

    def process_image(self, img_bytes):
        """
        Main function. Processes image using PIL and Heuristic Segment Analysis.
        Returns: (int_value, debug_imgs_dict)
        """
        debug_imgs = {}
        if not img_bytes:
            return None, debug_imgs

        try:
            full_img = Image.open(io.BytesIO(img_bytes))
        except Exception as e:
            _LOGGER.error(f"Failed to open image: {e}")
            return None, debug_imgs

        # 1. 裁剪 ROI
        rx, ry, rw, rh = self._roi
        crop_box = (rx, ry, rx + rw, ry + rh)
        
        try:
            ocr_img = full_img.crop(crop_box).convert("L")
            debug_imgs["01_Crop_Gray.jpg"] = ocr_img
        except Exception as e:
            _LOGGER.error(f"Crop failed: {e}")
            return None, debug_imgs

        # 2. 亮度检查 (防止严重黑屏)
        np_img = np.array(ocr_img)
        max_val = np.max(np_img) if np_img.size > 0 else 0
        
        if max_val < OCR_MIN_PEAK_BRIGHTNESS:
            # _LOGGER.debug(f"Skipping OCR: Image too dark (Max:{max_val})")
            debug_imgs["00_Skipped_Dark.jpg"] = ocr_img
            return None, debug_imgs

        # 3. Otsu 二值化 & 背景统一
        thresh_val = self._get_otsu_threshold(ocr_img)
        binary_img = ocr_img.point(lambda p: 255 if p > thresh_val else 0)
        
        # 统计白色像素，如果白色少于一半，说明背景是黑的，反转为“白底黑字”
        np_bin = np.array(binary_img)
        white_pixels = np.count_nonzero(np_bin == 255)
        if white_pixels < (np_bin.size * 0.5):
            binary_img = ImageOps.invert(binary_img)
            np_bin = np.array(binary_img) # 更新 numpy 数组用于后续计算

        # 准备画板
        canvas = binary_img.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        sw, sh = SEGMENT_SIZE

        # === 4. 哨兵检查 (Guard Check) ===
        # 必须确保数字上方和下方的背景区域是“白”的(非激活)。
        # 如果这些地方是黑的，说明全图噪音或反转错误，直接视为无效。
        guard_failed = False
        for g_name, (gx, gy) in GUARD_SEGMENTS.items():
            is_active, ratio = self._check_zone_active(np_bin, gx, gy, sw, sh)
            
            # 画出来看看：蓝色=正常(背景), 黄色=异常(检测到笔画)
            g_color = (0, 0, 255) # Blue (Pass)
            if is_active:
                guard_failed = True
                g_color = (255, 255, 0) # Yellow (Fail)
                _LOGGER.debug(f"Guard Failed: {g_name} active ratio {ratio:.2f}")

            draw.rectangle([gx, gy, gx + sw - 1, gy + sh - 1], outline=g_color)

        if guard_failed:
            # _LOGGER.debug("OCR rejected by guard points (Background noise detected)")
            # 即使失败也保存图片，方便调试看出是哪个点挂了
            large_canvas = canvas.resize((rw * 5, rh * 5), resample=Image.NEAREST)
            debug_imgs["02_Guard_Failed.jpg"] = large_canvas
            return None, debug_imgs

        # === 5. 正常数字识别逻辑 ===
        digits_result = {}
        seg_order = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
        
        for pos in ['1', '0']:
            states = []
            for seg in seg_order:
                key = f"{seg}{pos}"
                lx, ly = LOCAL_SEGMENTS.get(key, (0, 0))
                
                is_active, _ = self._check_zone_active(np_bin, lx, ly, sw, sh)
                states.append(1 if is_active else 0)
                
                # 绿色=有笔画, 红色=无笔画
                color = (0, 255, 0) if is_active else (255, 0, 0)
                draw.rectangle([lx, ly, lx + sw - 1, ly + sh - 1], outline=color)

            digits_result[pos] = SEGMENT_MAP.get(tuple(states), "?")

        # 6. 结果输出
        digit_ten = digits_result.get('1', '?')
        digit_one = digits_result.get('0', '?')
        res_str = f"{digit_ten}{digit_one}"
        
        # 绘制结果文字
        large_canvas = canvas.resize((rw * 5, rh * 5), resample=Image.NEAREST)
        draw_large = ImageDraw.Draw(large_canvas)
        try:
            draw_large.text((5, 5), res_str, fill=(0, 255, 255))
        except IOError:
            pass 

        debug_imgs[f"02_Result_{res_str}.jpg"] = large_canvas

        try:
            if '?' in res_str or 'None' in res_str:
                return None, debug_imgs
                
            val = int(res_str)
            if VALID_MIN <= val <= VALID_MAX:
                return val, debug_imgs
            else:
                return None, debug_imgs
        except ValueError:
            return None, debug_imgs