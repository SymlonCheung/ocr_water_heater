"""Mode Processing logic for OCR Water Heater (Final Optimized)."""
import logging
import cv2
import numpy as np
from .const import (
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_SETTING, MODE_STANDBY,
    MODE_ACTIVE_RATIO, DEFAULT_ROI_PANEL, DEFAULT_GAMMA, DEFAULT_NOISE_LIMIT
)

_LOGGER = logging.getLogger(__name__)

class ModeProcessor:
    """
    使用局部 Otsu + Gamma 增强 + 动态底噪门限。
    配置基于 Grid Search 调优结果：Gamma 2.0 / Limit 30
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

    def _enhance_contrast(self, image):
        """Gamma 增强"""
        img_float = image.astype(float)
        min_val = np.min(img_float)
        max_val = np.max(img_float)
        
        if max_val - min_val < 5:
            return image
            
        img_norm = (img_float - min_val) / (max_val - min_val) * 255.0
        img_gamma = np.power(img_norm / 255.0, self.gamma) * 255.0
        
        return img_gamma.astype(np.uint8)

    def _analyze_roi_local(self, gray_panel, rel_roi, debug_name, debug_store):
        """
        局部二值化分析
        """
        x, y, w, h = rel_roi
        if w <= 0 or h <= 0: return 0.0
        
        # 1. 切割局部灰度图
        roi_gray = gray_panel[y:y+h, x:x+w]
        if roi_gray.size == 0: return 0.0

        # 2. 局部亮度检查 (使用 const 中的配置值 30)
        max_val = np.max(roi_gray)
        if max_val < DEFAULT_NOISE_LIMIT: 
            return 0.0

        # 3. 局部 Otsu 二值化
        thresh_val, roi_binary = cv2.threshold(
            roi_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        
        debug_store[f"05_{debug_name}_Bin_{int(thresh_val)}.jpg"] = roi_binary

        # 4. 计算比例
        lit_pixels = cv2.countNonZero(roi_binary)
        return lit_pixels / roi_binary.size

    def process(self, image_bytes):
        debug_imgs = {}
        if not image_bytes:
            return None, debug_imgs

        try:
            # 1. 解码
            image_array = np.asarray(bytearray(image_bytes), dtype=np.uint8)
            img_origin = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            if img_origin is None: return None, debug_imgs

            # 2. 裁剪面板
            px, py, pw, ph = self.panel_roi
            h_orig, w_orig = img_origin.shape[:2]
            px = max(0, min(px, w_orig))
            py = max(0, min(py, h_orig))
            pw = min(pw, w_orig - px)
            ph = min(ph, h_orig - py)
            
            panel_img = img_origin[py:py+ph, px:px+pw]
            if panel_img.size == 0: return MODE_STANDBY, debug_imgs

            debug_imgs["01_Panel.jpg"] = panel_img

            # 3. 转灰度 & Gamma 增强
            gray_panel = cv2.cvtColor(panel_img, cv2.COLOR_BGR2GRAY)
            enhanced_panel = self._enhance_contrast(gray_panel)
            debug_imgs[f"02_Enhanced_G{self.gamma}.jpg"] = enhanced_panel

            # 4. 全局亮度初筛 (防止全黑死机)
            if np.max(enhanced_panel) < DEFAULT_NOISE_LIMIT:
                return MODE_STANDBY, debug_imgs

            # 5. 逐个区域进行【局部】分析
            
            # A. OCR 区域检查
            rel_ocr = self._get_relative_roi(self.ocr_roi)
            ocr_ratio = self._analyze_roi_local(enhanced_panel, rel_ocr, "OCR", debug_imgs)
            
            if ocr_ratio < 0.10:
                return MODE_STANDBY, debug_imgs

            # B. 正在设置
            rel_set = self._get_relative_roi(self.sub_rois['setting'])
            if self._analyze_roi_local(enhanced_panel, rel_set, "SET", debug_imgs) > MODE_ACTIVE_RATIO:
                return MODE_SETTING, debug_imgs

            # C. 互斥模式
            scores = {}
            for mode_key in ['low', 'half', 'full']:
                rel = self._get_relative_roi(self.sub_rois[mode_key])
                scores[mode_key] = self._analyze_roi_local(enhanced_panel, rel, f"Mode_{mode_key}", debug_imgs)

            best_mode = max(scores, key=scores.get)
            if scores[best_mode] > MODE_ACTIVE_RATIO:
                if best_mode == 'low': return MODE_LOW_POWER, debug_imgs
                if best_mode == 'half': return MODE_HALF, debug_imgs
                if best_mode == 'full': return MODE_FULL, debug_imgs

            return MODE_STANDBY, debug_imgs

        except Exception as e:
            _LOGGER.error(f"Mode processing error: {e}")
            return MODE_STANDBY, debug_imgs