"""Mode Processing logic for OCR Water Heater."""
import logging
import cv2
import numpy as np
from .const import (
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_SETTING, MODE_STANDBY
)

_LOGGER = logging.getLogger(__name__)

class ModeProcessor:
    """Class to handle Mode detection logic."""

    def __init__(self):
        # 初始化时为空，等待 configure 注入
        self.rois = {}

    def configure(self, rois: dict):
        """
        配置所有模式的 ROI
        rois 结构: { "setting": (x,y,w,h), "low": (x,y,w,h), ... }
        """
        self.rois = rois

    def _is_roi_active(self, img_origin, roi, debug_name, debug_store):
        """
        检测指定 ROI 区域是否亮起 (基于亮度阈值)。
        """
        x, y, w, h = roi
        h_img, w_img = img_origin.shape[:2]
        
        # 1. 裁剪
        crop_img = img_origin[max(0, y):min(h_img, y+h), max(0, x):min(w_img, x+w)]
        if crop_img.size == 0:
            return False

        debug_store[f"{debug_name}_01.jpg"] = crop_img

        # 2. 转灰度 (直接看亮度)
        gray_img = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
        
        # 3. 固定亮度阈值
        # 只要像素亮度 > 90 视为点亮
        BRIGHTNESS_THRESHOLD = 90
        _, thresholded_img = cv2.threshold(gray_img, BRIGHTNESS_THRESHOLD, 255, cv2.THRESH_BINARY)
        
        debug_store[f"{debug_name}_02.jpg"] = thresholded_img

        # 4. 统计亮点
        lit_pixels = cv2.countNonZero(thresholded_img)
        
        # 5. 判定标准:
        # ROI 通常很小 (13x5=65像素)，只要有 > 3 个像素亮起就认为激活
        # 可以根据实际情况调整这个阈值
        MIN_LIT_PIXELS = 3
        
        return lit_pixels >= MIN_LIT_PIXELS

    def process(self, image_bytes):
        """
        处理图像并检测模式。
        """
        debug_imgs = {}
        if not image_bytes:
            return None, debug_imgs

        try:
            image_array = np.asarray(bytearray(image_bytes), dtype=np.uint8)
            img_origin = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            
            if img_origin is None:
                return None, debug_imgs

            # 1. 优先检测：正在设置
            if self._is_roi_active(img_origin, self.rois['setting'], "mode_set", debug_imgs):
                return MODE_SETTING, debug_imgs

            # 2. 检测其他模式 (互斥检测)
            if self._is_roi_active(img_origin, self.rois['full'], "mode_full", debug_imgs):
                return MODE_FULL, debug_imgs
                
            if self._is_roi_active(img_origin, self.rois['half'], "mode_half", debug_imgs):
                return MODE_HALF, debug_imgs
                
            if self._is_roi_active(img_origin, self.rois['low'], "mode_low", debug_imgs):
                return MODE_LOW_POWER, debug_imgs

            # 3. 都没亮 -> 待机 (或者面板无显示)
            return MODE_STANDBY, debug_imgs

        except Exception as e:
            _LOGGER.error(f"Mode processing error: {e}")
            return None, debug_imgs