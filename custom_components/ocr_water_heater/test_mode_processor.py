"""
独立测试模式识别逻辑 (Standalone Test)
用于验证: 低功率、速热半缸、速热全缸、正在设置、待机
"""
import sys
import os
import time
import requests
import cv2
import logging
import shutil
import numpy as np

# ================= 配置 =================
# 图片源 (建议用 Frigate 的 latest.jpg)
IMAGE_URL = "http://192.168.123.86:5000/api/reshuiqi/latest.jpg"
# 调试图片保存路径
SAVE_DIR = "/workspaces/core/tmp/ocr_debug/manual_test"
# 循环测试次数 (设为 1 则只测一次，设为 9999 则一直测方便你按热水器按钮)
LOOP_COUNT = 99999 
# 间隔时间 (秒)
INTERVAL = 0.5 
# =======================================

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("ModeTest")

# 路径 hack，以便能导入同级模块
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

try:
    from custom_components.ocr_water_heater.mode_processor import ModeProcessor
    # 重新加载一下 const 确保读到最新的配置
    import custom_components.ocr_water_heater.const as const_module
except ImportError as e:
    logger.error(f"导入模块失败: {e}")
    logger.error("请在 /workspaces/core/config 目录下运行: python3 -m custom_components.ocr_water_heater.test_mode_processor")
    sys.exit(1)

def save_images(res_str, images):
    """保存调试图片到文件夹"""
    if not images:
        return
    
    # 创建带时间戳和结果的子文件夹
    timestamp = time.strftime("%H%M%S")
    # 如果结果是 None，显示 Standby
    res_name = res_str if res_str else "Standby_or_Err"
    folder_name = f"{timestamp}_{res_name}"
    
    full_path = os.path.join(SAVE_DIR, folder_name)
    os.makedirs(full_path, exist_ok=True)
    
    for filename, img_array in images.items():
        if img_array is not None:
            file_path = os.path.join(full_path, filename)
            cv2.imwrite(file_path, img_array)
            
    # 清理旧文件夹 (保留最近 20 个)
    clean_old_folders()

def clean_old_folders():
    try:
        folders = sorted([os.path.join(SAVE_DIR, d) for d in os.listdir(SAVE_DIR) if os.path.isdir(os.path.join(SAVE_DIR, d))])
        if len(folders) > 20:
            for f in folders[:-20]:
                shutil.rmtree(f)
    except Exception:
        pass

def run_test():
    logger.info("=" * 40)
    logger.info("🧪 模式识别独立测试启动")
    logger.info(f"📍 图片源: {IMAGE_URL}")
    logger.info(f"📂 保存路径: {SAVE_DIR}")
    logger.info("=" * 40)

    # 1. 初始化处理器
    processor = ModeProcessor()
    
    # 打印当前的 ROI 配置以确认
    logger.info(f"⚙️  运行模式 ROI: {const_module.MODE_ROI}")
    logger.info(f"⚙️  设置模式 ROI: {const_module.SETTING_ROI}")

    # 2. 清空测试目录
    if os.path.exists(SAVE_DIR):
        shutil.rmtree(SAVE_DIR)
    os.makedirs(SAVE_DIR, exist_ok=True)

    last_mode = ""

    # 3. 循环测试
    for i in range(1, LOOP_COUNT + 1):
        try:
            # 下载图片
            t0 = time.time()
            resp = requests.get(IMAGE_URL, timeout=3)
            content = resp.content
            
            # 处理
            mode, debug_imgs = processor.process(content)
            
            # 结果处理
            display_mode = mode if mode else "待机 (无光标)"
            
            # 只有状态改变时，或者每 5 次，才打印 log，避免刷屏
            if mode != last_mode or i % 5 == 0:
                color_code = "\033[92m" if mode else "\033[90m" # 绿色或灰色
                reset_code = "\033[0m"
                logger.info(f"[{i}] Result: {color_code}{display_mode}{reset_code} (耗时: {(time.time()-t0)*1000:.1f}ms)")
                last_mode = mode
                
                # 保存图片 (只有状态变化 或 调试时保存)
                save_images(display_mode, debug_imgs)

            time.sleep(INTERVAL)

        except KeyboardInterrupt:
            logger.info("\n🛑 测试停止")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    run_test()