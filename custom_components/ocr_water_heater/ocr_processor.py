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

# === 核心配置 (移植自调试脚本) ===
# 判定阈值：黑色像素占比 >= 50% 视为笔画存在
ACTIVE_RATIO = 0.50
# 笔画检测区域大小 (宽, 高)
SEGMENT_SIZE = (2, 2)

# 七段数码管逻辑映射表
# 顺序: a, b, c, d, e, f, g
# 1=黑(有笔画), 0=白(无笔画)
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

# 局部坐标定义
# 基于调试脚本中的全局坐标 (769, 339) 计算得出的相对偏移量
# 例如 a1(780, 344) - Origin(769, 339) = (11, 5)
LOCAL_SEGMENTS = {
    # 左侧数字 (十位)
    'a1': (11, 5),  'b1': (15, 8),  'c1': (13, 16),
    'd1': (8, 20),  'e1': (3, 16),  'f1': (5, 8),   'g1': (9, 12),
    # 右侧数字 (个位)
    'a0': (27, 5),  'b0': (31, 8),  'c0': (29, 15),
    'd0': (24, 19), 'e0': (20, 15), 'f0': (21, 8),  'g0': (25, 11)
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
        手动实现 Otsu 阈值算法 (替代 cv2.threshold)
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
            # 1. 打开图片
            full_img = Image.open(io.BytesIO(img_bytes))
        except Exception as e:
            _LOGGER.error(f"Failed to open image: {e}")
            return None, debug_imgs

        # 2. 裁剪 ROI
        # self._roi 格式为 (x, y, w, h)
        rx, ry, rw, rh = self._roi
        # PIL crop 需要 (left, top, right, bottom)
        crop_box = (rx, ry, rx + rw, ry + rh)
        
        try:
            # 转换为灰度图 'L'
            ocr_img = full_img.crop(crop_box).convert("L")
            debug_imgs["01_Crop_Gray.jpg"] = ocr_img
        except Exception as e:
            _LOGGER.error(f"Crop failed: {e}")
            return None, debug_imgs

        # 3. 亮度检查 (防止黑屏噪音)
        np_img = np.array(ocr_img)
        max_val = np.max(np_img) if np_img.size > 0 else 0
        
        if max_val < OCR_MIN_PEAK_BRIGHTNESS:
            _LOGGER.debug(f"Skipping OCR: Image too dark (Max:{max_val})")
            debug_imgs["00_Skipped_Dark.jpg"] = ocr_img
            return None, debug_imgs

        # 4. Otsu 二值化
        thresh_val = self._get_otsu_threshold(ocr_img)
        # point: >阈值变255(白), <阈值变0(黑)
        binary_img = ocr_img.point(lambda p: 255 if p > thresh_val else 0)
        
        # 5. 背景统一 (确保白底黑字)
        # 统计白色像素
        np_bin = np.array(binary_img)
        white_pixels = np.count_nonzero(np_bin == 255)
        total_pixels = np_bin.size
        
        # 如果白色少于一半，说明背景是黑的(字是白的)，需要反转
        if white_pixels < (total_pixels * 0.5):
            binary_img = ImageOps.invert(binary_img)
            np_bin = np.array(binary_img) # 更新 numpy 数组

        # 6. 识别逻辑 (七段数码管扫描)
        # 转为 RGB 用于在 debug 图上画框
        canvas = binary_img.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        
        digits_result = {}
        seg_order = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
        
        # 遍历两个数字位: '1' (十位), '0' (个位)
        for pos in ['1', '0']:
            states = []
            for seg in seg_order:
                key = f"{seg}{pos}"
                # 获取局部坐标 (相对于 ROI 左上角)
                lx, ly = LOCAL_SEGMENTS.get(key, (0, 0))
                sw, sh = SEGMENT_SIZE
                
                # 边界安全检查
                if lx < 0 or ly < 0 or lx + sw > rw or ly + sh > rh:
                    states.append(0) # 越界视为无笔画
                    continue
                
                # 提取区域像素 (Numpy 切片 [row, col] -> [y, x])
                zone = np_bin[ly : ly + sh, lx : lx + sw]
                
                # 计算黑色像素 (值=0) 的比例
                zone_total = zone.size
                zone_white = np.count_nonzero(zone == 255)
                zone_black = zone_total - zone_white
                
                ratio = zone_black / zone_total if zone_total > 0 else 0
                
                # 判定: 黑色足够多说明有笔画
                is_active = 1 if ratio >= ACTIVE_RATIO else 0
                states.append(is_active)
                
                # Debug 绘图: 绿色=Active, 红色=Inactive
                color = (0, 255, 0) if is_active else (255, 0, 0)
                draw.rectangle([lx, ly, lx + sw - 1, ly + sh - 1], outline=color)

            # 查表获取数字
            digits_result[pos] = SEGMENT_MAP.get(tuple(states), "?")

        # 7. 结果组装与验证
        digit_ten = digits_result.get('1', '?')
        digit_one = digits_result.get('0', '?')
        
        res_str = f"{digit_ten}{digit_one}"
        
        # 保存带框的识别图供 Debug
        # 为了清晰，放大 5 倍
        large_canvas = canvas.resize((rw * 5, rh * 5), resample=Image.NEAREST)
        draw_large = ImageDraw.Draw(large_canvas)
        # 简单写一下识别结果
        # 注意: Home Assistant 容器内可能缺少默认字体，如果报错可移除 text 绘制
        try:
            draw_large.text((5, 5), res_str, fill=(0, 255, 255))
        except IOError:
            pass # 忽略字体缺失错误

        debug_imgs[f"02_Result_{res_str}.jpg"] = large_canvas

        # 转换为整数并验证范围
        try:
            if '?' in res_str or 'None' in res_str:
                _LOGGER.debug(f"OCR Unsure: {res_str}")
                return None, debug_imgs
                
            val = int(res_str)
            if VALID_MIN <= val <= VALID_MAX:
                return val, debug_imgs
            else:
                _LOGGER.debug(f"OCR Out of Range: {val}")
                return None, debug_imgs
        except ValueError:
            return None, debug_imgs