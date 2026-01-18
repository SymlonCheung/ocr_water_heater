"""Mode Processing logic for OCR Water Heater (PIL/Numpy Version)."""
import logging
import io
import numpy as np
from PIL import Image, ImageOps

from .const import (
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_SETTING, MODE_STANDBY,
    MODE_ACTIVE_RATIO, DEFAULT_ROI_PANEL, DEFAULT_GAMMA, DEFAULT_NOISE_LIMIT
)

_LOGGER = logging.getLogger(__name__)

class ModeProcessor:
    """
    使用局部 Otsu + Gamma 增强 + 动态底噪门限 (PIL Version).
    """

    def __init__(self):
        self.panel_roi = DEFAULT_ROI_PANEL
        self.sub_rois = {}
        self.ocr_roi = None
        self.gamma = DEFAULT_GAMMA

    def configure(self, panel_roi: tuple, sub_rois: dict, ocr_roi: tuple, gamma: float = DEFAULT_GAMMA):
        self.panel_roi = panel_roi
        self.sub_rois = sub_rois
        self.ocr_roi = ocr_roi
        self.gamma = gamma

    def _get_relative_roi(self, abs_roi):
        """将绝对坐标转换为相对于 panel_roi 的坐标"""
        px, py, pw, ph = self.panel_roi
        ax, ay, aw, ah = abs_roi
        
        rx = max(0, min(ax - px, pw))
        ry = max(0, min(ay - py, ph))
        rw = min(aw, pw - rx)
        rh = min(ah, ph - ry)
        
        return (rx, ry, rw, rh)

    def _enhance_contrast(self, image_pil):
        """Gamma 增强"""
        img_arr = np.array(image_pil, dtype=float)
        min_val = np.min(img_arr)
        max_val = np.max(img_arr)
        
        if max_val - min_val < 5:
            return image_pil 
            
        img_norm = (img_arr - min_val) / (max_val - min_val) * 255.0
        img_gamma = np.power(img_norm / 255.0, self.gamma) * 255.0
        
        return Image.fromarray(img_gamma.astype(np.uint8))

    def _get_otsu_threshold(self, img_pil):
        """手动实现 Otsu 阈值"""
        if img_pil.mode != 'L':
            img_pil = img_pil.convert('L')
            
        hist = img_pil.histogram()
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

    def _analyze_roi_local(self, gray_panel_pil, rel_roi, debug_name, debug_store):
        """局部二值化分析"""
        x, y, w, h = rel_roi
        if w <= 0 or h <= 0: return 0.0
        
        roi_img = gray_panel_pil.crop((x, y, x + w, y + h))
        roi_arr = np.array(roi_img)
        if roi_arr.size == 0: return 0.0

        max_val = np.max(roi_arr)
        if max_val < DEFAULT_NOISE_LIMIT: 
            return 0.0

        thresh_val = self._get_otsu_threshold(roi_img)
        roi_binary = roi_img.point(lambda p: 255 if p > thresh_val else 0)
        
        debug_store[f"05_{debug_name}_Bin_{int(thresh_val)}.jpg"] = roi_binary

        bin_arr = np.array(roi_binary)
        lit_pixels = np.count_nonzero(bin_arr == 255)
        
        return lit_pixels / bin_arr.size

    def process(self, image_bytes):
        debug_imgs = {}
        if not image_bytes:
            return None, debug_imgs

        try:
            img_origin = Image.open(io.BytesIO(image_bytes))
            
            # 裁剪面板
            px, py, pw, ph = self.panel_roi
            w_orig, h_orig = img_origin.size
            left = max(0, min(px, w_orig))
            top = max(0, min(py, h_orig))
            right = min(left + pw, w_orig)
            bottom = min(top + ph, h_orig)
            
            if right - left <= 0 or bottom - top <= 0:
                return MODE_STANDBY, debug_imgs
                
            panel_img = img_origin.crop((left, top, right, bottom))
            debug_imgs["01_Panel.jpg"] = panel_img

            # 增强
            gray_panel = panel_img.convert("L")
            enhanced_panel = self._enhance_contrast(gray_panel)
            debug_imgs[f"02_Enhanced_G{self.gamma}.jpg"] = enhanced_panel

            # 全局亮度初筛
            if np.max(np.array(enhanced_panel)) < DEFAULT_NOISE_LIMIT:
                return MODE_STANDBY, debug_imgs

            # === 修改顺序 ===
            
            # 1. 优先检查：正在设置
            # 如果 SET 亮了，说明屏幕肯定是亮着的，不需要管 OCR 分数
            rel_set = self._get_relative_roi(self.sub_rois['setting'])
            set_score = self._analyze_roi_local(enhanced_panel, rel_set, "SET", debug_imgs)
            
            if set_score > MODE_ACTIVE_RATIO:
                return MODE_SETTING, debug_imgs

            # 2. 其次检查：OCR 区域安全锁
            # 如果不是在设置，且数字区域全黑，那才是真的待机
            rel_ocr = self._get_relative_roi(self.ocr_roi)
            ocr_ratio = self._analyze_roi_local(enhanced_panel, rel_ocr, "OCR", debug_imgs)
            
            if ocr_ratio < 0.10:
                # _LOGGER.debug(f"OCR too dark ({ocr_ratio:.2f}), forcing STANDBY")
                return MODE_STANDBY, debug_imgs

            # 3. 最后检查：互斥模式 (Low/Half/Full)
            scores = {}
            for mode_key in ['low', 'half', 'full']:
                rel = self._get_relative_roi(self.sub_rois[mode_key])
                scores[mode_key] = self._analyze_roi_local(enhanced_panel, rel, f"Mode_{mode_key}", debug_imgs)
            
            best_mode = max(scores, key=scores.get)
            best_score = scores[best_mode]

            if best_score > MODE_ACTIVE_RATIO:
                if best_mode == 'low': return MODE_LOW_POWER, debug_imgs
                if best_mode == 'half': return MODE_HALF, debug_imgs
                if best_mode == 'full': return MODE_FULL, debug_imgs

            return MODE_STANDBY, debug_imgs

        except Exception as e:
            _LOGGER.error(f"Mode processing error: {e}")
            return MODE_STANDBY, debug_imgs