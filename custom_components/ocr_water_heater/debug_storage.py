"""Handles debug image storage for OCR Water Heater."""
import os
import time
import logging
import cv2
from .const import DEBUG_DIR_ROOT

_LOGGER = logging.getLogger(__name__)

def save_debug_record(result: int | None, images: dict[str, any]):
    """
    保存 OCR 调试记录到文件夹。
    
    Args:
        result: OCR 识别结果 (int 或 None)
        images: 字典 {"filename.jpg": numpy_image_array}
    """
    if not images:
        return

    try:
        # 1. 构造文件夹名称
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        res_str = str(result) if result is not None else "None"
        folder_name = f"{timestamp}_RES_{res_str}"
        
        save_dir = os.path.join(DEBUG_DIR_ROOT, folder_name)

        # 2. 创建文件夹
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        # 3. 遍历字典保存图片
        for filename, img_array in images.items():
            if img_array is not None:
                file_path = os.path.join(save_dir, filename)
                cv2.imwrite(file_path, img_array)
                
    except Exception as e:
        _LOGGER.error(f"Failed to save debug record: {e}")