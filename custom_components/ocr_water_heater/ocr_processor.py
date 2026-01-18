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

# 七段数码管逻辑映射表 (1=黑/有笔画, 0=白/无笔画)
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

# 局部坐标定义 (基于 36x26 OCR 区域)
LOCAL_SEGMENTS = {
    # 左侧数字 (十位)
    'a1': (11, 5),  'b1': (15, 8),  'c1': (13, 16),
    'd1': (8, 20),  'e1': (3, 16),  'f1': (5, 8),   'g1': (9, 12),
    # 右侧数字 (个位)
    'a0': (27, 5),  'b0': (31, 8),  'c0': (29, 15),
    'd0': (24, 19), 'e0': (20, 15), 'f0': (21, 8),  'g0': (25, 11)
}

# === 新增: 特征验证点 (必须为空白的区域) ===
# 格式: Name: (x, y, w, h)
# 如果这些区域检测到黑色，说明是全屏噪点，直接丢弃
VALIDATION_SPOTS = {
    # f1(5,8) 左侧 4 像素 -> x=1, y=8
    'check_left_f1': (1, 8, 2, 2), 
    
    # a0(27,5) 上方 4 像素 -> x=27, y=1
    'check_top_a0':  (27, 1, 2, 2),
    
    # d1(8,20) 下方 4 像素 -> x=8, y=24
    'check_bot_d1':  (8, 24, 2, 2),
    
    # d0(24,19) 下方 6 像素 -> x=24, y=25 (稍微往下一点)
    'check_bot_d0':  (24, 24, 2, 2)
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
        """
        手动实现 Otsu 阈值算法
        """
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

        # 2. 亮度检查
        np_img = np.array(ocr_img)
        max_val = np.max(np_img) if np_img.size > 0 else 0
        
        if max_val < OCR_MIN_PEAK_BRIGHTNESS:
            # 屏幕太暗，直接跳过
            debug_imgs["00_Skipped_Dark.jpg"] = ocr_img
            return None, debug_imgs

        # 3. Otsu 二值化
        thresh_val = self._get_otsu_threshold(ocr_img)
        # >阈值变255(白), <阈值变0(黑)
        binary_img = ocr_img.point(lambda p: 255 if p > thresh_val else 0)
        
        # 4. 背景统一 (确保白底黑字)
        np_bin = np.array(binary_img)
        white_pixels = np.count_nonzero(np_bin == 255)
        total_pixels = np_bin.size
        
        if white_pixels < (total_pixels * 0.5):
            binary_img = ImageOps.invert(binary_img)
            np_bin = np.array(binary_img)

        # 准备画板
        canvas = binary_img.convert("RGB")
        draw = ImageDraw.Draw(canvas)

        # === 5. 特征点噪声验证 (新增) ===
        # 如果这些本该是空白的地方被检测出黑色，说明这是一张噪点图
        noise_detected = False
        for name, (vx, vy, vw, vh) in VALIDATION_SPOTS.items():
            # 边界检查
            if vx < 0 or vy < 0 or vx + vw > rw or vy + vh > rh: continue

            # 提取区域
            zone = np_bin[vy : vy + vh, vx : vx + vw]
            
            # 检查黑色占比
            zone_total = zone.size
            zone_white = np.count_nonzero(zone == 255)
            zone_black = zone_total - zone_white
            ratio = zone_black / zone_total if zone_total > 0 else 0

            # 画框框 (黄色表示检查点)
            draw.rectangle([vx, vy, vx + vw - 1, vy + vh - 1], outline=(255, 255, 0))

            if ratio >= ACTIVE_RATIO:
                _LOGGER.debug(f"Noise Check Failed: {name} is active (Ratio: {ratio:.2f})")
                noise_detected = True
                # 只要有一个点挂了，就认为是噪点图，但为了画出完整的 debug 图，我们不在这里立刻 return
                # 而是标记一下，最后统一处理

        # === 6. 识别逻辑 (七段数码管) ===
        digits_result = {}
        seg_order = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
        
        for pos in ['1', '0']:
            states = []
            for seg in seg_order:
                key = f"{seg}{pos}"
                lx, ly = LOCAL_SEGMENTS.get(key, (0, 0))
                sw, sh = SEGMENT_SIZE
                
                if lx < 0 or ly < 0 or lx + sw > rw or ly + sh > rh:
                    states.append(0)
                    continue
                
                zone = np_bin[ly : ly + sh, lx : lx + sw]
                zone_total = zone.size
                zone_white = np.count_nonzero(zone == 255)
                zone_black = zone_total - zone_white
                ratio = zone_black / zone_total if zone_total > 0 else 0
                
                is_active = 1 if ratio >= ACTIVE_RATIO else 0
                states.append(is_active)
                
                color = (0, 255, 0) if is_active else (255, 0, 0)
                draw.rectangle([lx, ly, lx + sw - 1, ly + sh - 1], outline=color)

            digits_result[pos] = SEGMENT_MAP.get(tuple(states), "?")

        # === 7. 结果输出 ===
        
        # 如果刚才的噪声检查挂了，强制视为无效
        if noise_detected:
            res_str = "NOISE"
            final_val = None
            _LOGGER.debug("OCR rejected due to failed validation spots.")
        else:
            digit_ten = digits_result.get('1', '?')
            digit_one = digits_result.get('0', '?')
            res_str = f"{digit_ten}{digit_one}"
            
            # 尝试转换
            try:
                if '?' in res_str or 'None' in res_str:
                    final_val = None
                else:
                    val = int(res_str)
                    if VALID_MIN <= val <= VALID_MAX:
                        final_val = val
                    else:
                        final_val = None
            except ValueError:
                final_val = None

        # 保存放大图
        large_canvas = canvas.resize((rw * 5, rh * 5), resample=Image.NEAREST)
        draw_large = ImageDraw.Draw(large_canvas)
        try:
            draw_large.text((5, 5), res_str, fill=(0, 255, 255))
        except IOError: pass

        debug_imgs[f"02_Result_{res_str}.jpg"] = large_canvas

        return final_val, debug_imgs