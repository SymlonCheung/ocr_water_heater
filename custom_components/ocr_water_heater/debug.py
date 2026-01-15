# 文件位置: custom_components/ocr_water_heater/debug.py
import logging
import requests
import sys
import os
import time

# 设置日志显示 (这样能看到 ocr_processor 里的 _LOGGER 输出)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# 导入同目录下的模块 (注意：运行时需要用模块方式运行)
from .ocr_processor import OCRProcessor
from .const import DEFAULT_ROI, DEFAULT_SKEW, CONF_ROI_X, CONF_ROI_Y, CONF_ROI_W, CONF_ROI_H

# =================配置区域=================
# 你的摄像头 URL
TEST_URL = "http://192.168.123.86:1984/api/frame.jpeg?src=menkou"

# 你想测试的参数 (可以在这里微调，测试好后再填入 HA)
TEST_ROI = (769, 339, 36, 26)  # (x, y, w, h)
TEST_SKEW = 8.0                # 倾斜角度
# =========================================

def main():
    print("="*60)
    print(" 🛠️  OCR Processor 独立测试工具")
    print("="*60)

    # 1. 初始化处理器
    print("[1] 初始化 OCR 引擎 (加载 ddddocr)...")
    try:
        processor = OCRProcessor()
        # 模拟 HA 中的配置过程
        processor.configure(roi=TEST_ROI, skew=TEST_SKEW)
        print("    ✅ 初始化完成")
    except Exception as e:
        print(f"    ❌ 初始化失败: {e}")
        return

    # 2. 获取图片
    print(f"\n[2] 正在下载图片: {TEST_URL}")
    try:
        resp = requests.get(TEST_URL, timeout=10)
        if resp.status_code != 200:
            print(f"    ❌ HTTP 错误: {resp.status_code}")
            return
        image_bytes = resp.content
        print(f"    ✅ 下载成功, 大小: {len(image_bytes)} bytes")
    except Exception as e:
        print(f"    ❌ 连接失败: {e}")
        return

    # 3. 执行识别
    print(f"\n[3] 开始识别 (debug 图片将保存在 ./tmp/ocr_debug_1.1)")
    start_time = time.time()
    
    # 调用核心处理函数
    result = processor.process_image(image_bytes)
    
    end_time = time.time()
    duration = end_time - start_time

    # 4. 输出结果
    print("-" * 60)
    if result is not None:
        print(f"🎉 识别成功! 结果: 【 {result} 】")
    else:
        print("⚠️  识别失败 (返回 None)")
    print(f"⏱️  耗时: {duration:.4f} 秒")
    print("-" * 60)

if __name__ == "__main__":
    main()