"""Handles debug image storage for OCR Water Heater (PIL Version)."""
import os
import time
import logging
from PIL import Image
from .const import DEBUG_DIR_ROOT

_LOGGER = logging.getLogger(__name__)

def save_debug_record(result: str | int | None, images: dict[str, any]):
    """
    保存 OCR 调试记录到文件夹 (使用 PIL)。
    
    Args:
        result: OCR 识别结果 (int 或 None)
        images: 字典 {"filename.jpg": PIL.Image 对象}
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
        for filename, img_obj in images.items():
            if img_obj is not None:
                file_path = os.path.join(save_dir, filename)
                try:
                    # 确保是 PIL Image 对象
                    if isinstance(img_obj, Image.Image):
                        img_obj.save(file_path, quality=95)
                    else:
                        _LOGGER.warning(f"Skipping {filename}: Not a PIL Image object.")
                except Exception as save_err:
                    _LOGGER.error(f"Error saving {filename}: {save_err}")
                
    except Exception as e:
        _LOGGER.error(f"Failed to save debug record: {e}")