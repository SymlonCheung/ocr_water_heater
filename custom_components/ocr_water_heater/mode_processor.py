"""Mode Processing logic for OCR Water Heater."""
import logging
import cv2
import numpy as np
from .const import (
    MODE_ROI,
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_STANDBY
)

_LOGGER = logging.getLogger(__name__)

class ModeProcessor:
    """Class to handle Mode detection logic."""

    def __init__(self):
        # 这里的 ROI 是基于原图的绝对坐标
        self._roi = MODE_ROI  # (734, 340, 10, 23)

    def process(self, image_bytes):
        """
        处理图像并检测模式。
        返回: (模式字符串, 调试图片字典)
        """
        debug_imgs = {}
        
        if not image_bytes:
            return None, debug_imgs

        try:
            # 1. 解码图像
            image_array = np.asarray(bytearray(image_bytes), dtype=np.uint8)
            img_origin = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            
            if img_origin is None:
                return None, debug_imgs

            # 2. 裁剪 ROI
            x, y, w, h = self._roi
            h_img, w_img = img_origin.shape[:2]
            
            # 边界检查
            crop_img = img_origin[max(0, y):min(h_img, y+h), max(0, x):min(w_img, x+w)]
            
            if crop_img.size == 0:
                _LOGGER.debug("Mode crop resulted in empty image")
                return None, debug_imgs

            debug_imgs["mode_01_crop.jpg"] = crop_img

            # 3. 转灰度 -> 反转 -> 归一化 -> 阈值处理
            # 逻辑参考你提供的 Python 代码: process_and_detect_black_regions
            gray_img = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
            inverted_img = cv2.bitwise_not(gray_img)
            normalized_img = cv2.normalize(inverted_img, None, 0, 255, cv2.NORM_MINMAX)
            
            # 阈值 165
            _, thresholded_img = cv2.threshold(normalized_img, 165, 255, cv2.THRESH_BINARY)
            
            debug_imgs["mode_02_thresh.jpg"] = thresholded_img

            # 4. 检测黑色区域 (像素值为0的地方)
            # 注意：因为前面做了 bitwise_not 和 normalize，这里的逻辑需要严格遵循你的提供的代码
            # 你的代码里: black_pixels = np.where(thresholded_img == 0)
            black_pixels = np.where(thresholded_img == 0)

            # 如果没有黑色像素
            if len(black_pixels[0]) == 0:
                # 没有任何黑色块，通常意味着没有光标，即“待机”状态的逻辑分支
                return None, debug_imgs

            # 5. 计算边界框
            y_min, x_min = np.min(black_pixels, axis=1)
            y_max, x_max = np.max(black_pixels, axis=1)

            blob_w = x_max - x_min
            blob_h = y_max - y_min
            blob_y = y_min # 这里的 y 是相对于 10x23 这个小图的

            # 6. 模式匹配逻辑
            # 参考 JS 逻辑:
            # if (data.width >= 7 && data.height < 7)
            detected_mode = None
            
            # 你的逻辑：宽>=7 且 高<7
            if blob_w >= 7 and blob_h < 7:
                if blob_y <= 3:
                    detected_mode = MODE_LOW_POWER
                elif 7 <= blob_y <= 13:
                    detected_mode = MODE_HALF
                elif 17 <= blob_y <= 23:
                    detected_mode = MODE_FULL
                else:
                    detected_mode = MODE_STANDBY
            else:
                detected_mode = MODE_STANDBY

            return detected_mode, debug_imgs

        except Exception as e:
            _LOGGER.error(f"Mode processing error: {e}")
            return None, debug_imgs