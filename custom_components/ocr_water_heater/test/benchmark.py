"""
OCR Water Heater Benchmark Script
用于测试 Frigate 图片获取速度、OCR 识别秒数及视频流延迟
"""
import time
import requests
import statistics
import sys
import os
import logging
import datetime

# ================= 配置区域 =================
# 改为 Frigate 的 API (速度极快)
IMAGE_URL = "http://192.168.123.86:5000/api/reshuiqi/latest.jpg"

TEST_ITERATIONS = 50  # 测试次数

# 秒数显示的 ROI 区域 (x, y, w, h)
ROI = (383, 51, 34, 28) 

SKEW = 0.0 # 识别OSD通常不需要倾斜校正，设为0即可，如果有倾斜可改回 8.0
# ===========================================

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Benchmark")

# 动态路径处理
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# 导入模块
try:
    # 1. 导入模块
    import custom_components.ocr_water_heater.ocr_processor as ocr_module
    from custom_components.ocr_water_heater.ocr_processor import OCRProcessor
    
    # 2. 【热补丁】修改验证范围
    # 原代码只允许 10-80 (热水器温度)，我们要识别秒数 (0-59)，所以必须强制修改
    print("🛠️  正在调整 OCR 验证范围以适配秒数 (0-60)...")
    ocr_module.VALID_MIN = 0
    ocr_module.VALID_MAX = 60
    
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    print("请在 /workspaces/core/config 目录下运行命令:")
    print("python3 -m custom_components.ocr_water_heater.benchmark")
    sys.exit(1)

def run_benchmark():
    logger.info("=" * 60)
    logger.info("🚀 OCR 延迟与同步测试 (Frigate Source)")
    logger.info(f"📍 目标 URL: {IMAGE_URL}")
    logger.info(f"📐 ROI 区域: {ROI}")
    logger.info("=" * 60)

    # 初始化
    logger.info("正在初始化 OCR 引擎...")
    processor = OCRProcessor()
    processor.configure(roi=ROI, skew=SKEW)

    fetch_times = []
    lags = []
    success_count = 0

    logger.info("🏁 测试开始...")
    logger.info(f"{'Fetch(ms)':<10} | {'OCR(ms)':<8} | {'Sys Sec':<8} | {'Cam Sec':<8} | {'Lag(s)':<8}")
    logger.info("-" * 60)

    for i in range(1, TEST_ITERATIONS + 1):
        try:
            # 1. 获取系统时间 (秒)
            now = datetime.datetime.now()
            sys_sec = now.second

            # 2. 下载图片
            t0 = time.time()
            resp = requests.get(IMAGE_URL, timeout=5)
            t1 = time.time()
            
            if resp.status_code != 200:
                logger.warning(f"请求失败: {resp.status_code}")
                continue

            # 3. OCR 识别
            # process_image 返回 (val, debug_imgs)
            cam_sec, _ = processor.process_image(resp.content)
            t2 = time.time()

            # 4. 数据计算
            fetch_time = (t1 - t0) * 1000
            ocr_time = (t2 - t1) * 1000
            fetch_times.append(fetch_time)

            # 5. 计算延迟 (Lag)
            lag_str = "N/A"
            if cam_sec is not None:
                success_count += 1
                # 计算秒数差，处理跨分钟的情况 (例如系统01秒，摄像头59秒，延迟2秒)
                # 公式：(系统秒 - 摄像头秒 + 60) % 60
                lag = (sys_sec - cam_sec + 60) % 60
                
                # 如果误差非常大（比如超过30秒），可能是时钟没对准，或者是负延迟（摄像头快了?）
                if lag > 30:
                    lag = lag - 60 # 显示为负数
                
                lags.append(lag)
                lag_str = f"{lag}s"
            
            # 打印
            cam_sec_str = str(cam_sec) if cam_sec is not None else "None"
            logger.info(f"{fetch_time:<10.1f} | {ocr_time:<8.1f} | {sys_sec:<8} | {cam_sec_str:<8} | {lag_str:<8}")
            
            # 稍微sleep一下，避免刷太快
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"Loop error: {e}")
            time.sleep(1)

    # 统计
    if not fetch_times:
        return

    avg_fetch = statistics.mean(fetch_times)
    avg_lag = statistics.mean(lags) if lags else 0

    logger.info("=" * 60)
    logger.info(f"✅ 成功率: {success_count}/{TEST_ITERATIONS}")
    logger.info(f"⚡ 平均网络耗时 (Fetch): {avg_fetch:.2f} ms")
    if lags:
        logger.info(f"🐢 平均画面延迟 (Lag)  : {avg_lag:.2f} 秒")
        logger.info("   (注意: 此延迟包含 '传输延迟' + '摄像头系统时钟误差')")
    logger.info("=" * 60)

if __name__ == "__main__":
    run_benchmark()