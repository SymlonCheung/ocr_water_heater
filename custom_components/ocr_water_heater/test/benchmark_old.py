"""
OCR Water Heater Benchmark Script
用于测试 go2rtc 图片获取速度和 OCR 处理极限速度
"""
import time
import requests
import statistics
import sys
import os
import logging

# 配置部分 (请根据实际情况修改)
IMAGE_URL = "http://192.168.123.86:5000/api/reshuiqi/latest.jpg"
TEST_ITERATIONS = 50  # 测试循环次数
ROI = (769, 339, 36, 26) # 你的 OCR ROI
SKEW = 8.0               # 你的倾斜角度

# 日志设置
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Benchmark")

# ------------------------------------------------------------------
# 动态路径处理：为了能直接导入同级目录的模块
# ------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

try:
    # 尝试作为模块导入 (模拟 HA 环境)
    from ocr_water_heater.ocr_processor import OCRProcessor
    from ocr_water_heater.const import DEFAULT_ROI, DEFAULT_SKEW
except ImportError:
    # 如果失败，尝试直接路径修改 (Hack)
    sys.path.append(current_dir)
    # 注意：如果 ocr_processor.py 里用了 relative import (from .const)，
    # 直接运行可能会报错。建议使用 python -m 方式运行。
    try:
        from ocr_processor import OCRProcessor
    except ImportError as e:
        print(f"导入错误: {e}")
        print("请在 custom_components 目录的上级目录运行此脚本，例如:")
        print("python3 -m custom_components.ocr_water_heater.benchmark")
        sys.exit(1)

def run_benchmark():
    logger.info("=" * 40)
    logger.info("🚀 开始 OCR 极限压力测试")
    logger.info(f"📍 目标 URL: {IMAGE_URL}")
    logger.info(f"🔄 测试轮数: {TEST_ITERATIONS}")
    logger.info("=" * 40)

    # 1. 初始化处理器
    logger.info("正在初始化 OCR 引擎 (加载模型)...")
    init_start = time.time()
    processor = OCRProcessor()
    processor.configure(roi=ROI, skew=SKEW)
    logger.info(f"✅ 引擎初始化完成，耗时: {time.time() - init_start:.3f}s")

    # 数据记录
    fetch_times = []
    ocr_times = []
    total_times = []
    success_count = 0

    # 2. 预热 (Warmup) - 第一次运行通常较慢
    logger.info("🔥 正在预热 (Warmup)...")
    try:
        resp = requests.get(IMAGE_URL, timeout=5)
        processor.process_image(resp.content)
    except Exception as e:
        logger.error(f"❌ 预热失败，请检查 URL 是否正确: {e}")
        return

    # 3. 正式测试循环
    logger.info("🏁 测试开始...")
    
    for i in range(1, TEST_ITERATIONS + 1):
        try:
            # --- 阶段 A: 下载 ---
            t0 = time.time()
            resp = requests.get(IMAGE_URL, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"请求失败: {resp.status_code}")
                continue
            content = resp.content
            t1 = time.time()

            # --- 阶段 B: 处理 ---
            result, _ = processor.process_image(content)
            t2 = time.time()

            # --- 记录数据 ---
            fetch_time = (t1 - t0) * 1000 # 转毫秒
            ocr_time = (t2 - t1) * 1000   # 转毫秒
            total_time = (t2 - t0) * 1000

            fetch_times.append(fetch_time)
            ocr_times.append(ocr_time)
            total_times.append(total_time)

            if result is not None:
                success_count += 1
            
            res_str = f"{result}" if result is not None else "None"
            # 实时打印每5次的结果
            if i % 5 == 0:
                logger.info(f"[{i:02d}/{TEST_ITERATIONS}] Fetch: {fetch_time:3.0f}ms | OCR: {ocr_time:3.0f}ms | Total: {total_time:3.0f}ms | Res: {res_str}")

        except Exception as e:
            logger.error(f"Error in loop {i}: {e}")
            time.sleep(0.1)

    # 4. 统计结果
    if not total_times:
        logger.error("没有成功的数据。")
        return

    avg_fetch = statistics.mean(fetch_times)
    avg_ocr = statistics.mean(ocr_times)
    avg_total = statistics.mean(total_times)
    
    max_fps = 1000 / avg_total
    
    logger.info("\n" + "=" * 40)
    logger.info("📊 测试报告")
    logger.info("=" * 40)
    logger.info(f"✅ 成功识别率: {success_count}/{TEST_ITERATIONS} ({(success_count/TEST_ITERATIONS)*100:.1f}%)")
    logger.info("-" * 40)
    logger.info(f"📡 网络下载 (Fetch):")
    logger.info(f"   平均: {avg_fetch:.2f} ms")
    logger.info(f"   最小: {min(fetch_times):.2f} ms")
    logger.info(f"   最大: {max(fetch_times):.2f} ms")
    logger.info("-" * 40)
    logger.info(f"🧠 OCR 计算 (Process):")
    logger.info(f"   平均: {avg_ocr:.2f} ms")
    logger.info(f"   最小: {min(ocr_times):.2f} ms")
    logger.info(f"   最大: {max(ocr_times):.2f} ms")
    logger.info("-" * 40)
    logger.info(f"⏱️ 总耗时 (Total):")
    logger.info(f"   平均: {avg_total:.2f} ms")
    logger.info("-" * 40)
    logger.info(f"🚀 理论极限 FPS: {max_fps:.2f} 帧/秒")
    logger.info("=" * 40)

    # 5. 瓶颈分析建议
    logger.info("\n💡 瓶颈分析:")
    if avg_fetch > avg_ocr:
        logger.info(f"⚠️  瓶颈在【网络传输】。下载耗时是计算的 {avg_fetch/avg_ocr:.1f} 倍。")
        logger.info("   -> 建议: 检查 Wi-Fi 信号，或接受现状 (go2rtc 抓图通常很快)。")
    else:
        logger.info(f"⚠️  瓶颈在【CPU计算】。计算耗时是下载的 {avg_ocr/avg_fetch:.1f} 倍。")
        logger.info("   -> 建议: 减少 update_interval 负担，不要设置得太频繁。")

if __name__ == "__main__":
    run_benchmark()