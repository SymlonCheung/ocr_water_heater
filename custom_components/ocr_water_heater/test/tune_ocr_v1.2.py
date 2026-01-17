"""
OCR 参数调优脚本 (针对已裁剪的 ROI_PANEL 图片)
功能：读取已裁剪的面板图片 -> 遍历所有区域 -> 报告每个区域的高亮百分比
"""
import os
import cv2
import numpy as np
import requests
import time
import shutil

# ================= 配置区域 =================

# 输入源配置
INPUT_MODE = 'local' 
LOCAL_DIR = "/workspaces/core/tmp/panel_pic" 
IMAGE_URL = "http://192.168.123.86:5000/api/reshuiqi/latest.jpg"

# 输出目录
OUTPUT_DIR = "/workspaces/core/tmp/ocr_debug/tuning"

# === 相对坐标配置 (基于已裁剪图片的 0,0 点) ===
ROIS = {
    "ocr":     (41, 4, 36, 26),
    "setting": (47, 1, 11, 7),
    "low":     (5, 5, 13, 5),
    "half":    (5, 15, 13, 5),
    "full":    (5, 24, 13, 5)
}

# === 穷举参数范围 ===
GAMMA_LIST = [1.5, 2, 2.5]
NOISE_LIMIT_LIST = [10, 20, 30, 40]
ACTIVE_RATIO = 0.20  # 用于画框颜色区分的阈值

# ================= 逻辑代码 =================

def ensure_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)

def get_images():
    images = []
    if INPUT_MODE == 'url':
        try:
            resp = requests.get(IMAGE_URL, timeout=5)
            if resp.status_code == 200:
                images.append(("URL_Latest", resp.content))
        except Exception as e:
            print(f"下载失败: {e}")
    else:
        # --- 修改后的本地读取逻辑 ---
        if not os.path.exists(LOCAL_DIR):
            print(f"路径不存在: {LOCAL_DIR}")
            return []
        
        # 遍历 LOCAL_DIR 下的所有子文件夹
        for root, dirs, files in os.walk(LOCAL_DIR):
            if "01_Panel.jpg" in files:
                file_path = os.path.join(root, "01_Panel.jpg")
                # 使用父文件夹名称作为标识，防止重名
                folder_name = os.path.basename(root)
                with open(file_path, 'rb') as file:
                    images.append((f"{folder_name}_01_Panel.jpg", file.read()))
        # ---------------------------
    return images

def enhance_image(image, gamma):
    """Gamma 增强"""
    img_float = image.astype(float)
    min_val, max_val = np.min(img_float), np.max(img_float)
    if max_val - min_val < 5: return image
    img_norm = (img_float - min_val) / (max_val - min_val) * 255.0
    img_gamma = np.power(img_norm / 255.0, gamma) * 255.0
    return img_gamma.astype(np.uint8)

def process_single_case(img_name, img_bytes, gamma, noise_limit):
    # 1. 解码
    nparr = np.frombuffer(img_bytes, np.uint8)
    panel_color = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if panel_color is None:
        return
        
    ph, pw = panel_color.shape[:2]
    panel_gray = cv2.cvtColor(panel_color, cv2.COLOR_BGR2GRAY)

    # 2. Gamma 增强
    panel_enhanced = enhance_image(panel_gray, gamma)
    canvas_result = cv2.cvtColor(panel_enhanced, cv2.COLOR_GRAY2BGR)

    # 用于汇总当前图片的各区域结果
    roi_reports = []

    # 3. 遍历所有 ROI
    for name, (rx, ry, rw, rh) in ROIS.items():
        roi_local = panel_enhanced[max(0,ry):min(ph,ry+rh), max(0,rx):min(pw,rx+rw)]
        if roi_local.size == 0:
            continue
            
        lit_ratio = 0.0
        max_val = np.max(roi_local)
        
        # 阈值化计算亮部分比 (注意：这里必须使用 noise_limit 过滤背景噪声)
        if max_val >= noise_limit:
            try:
                _, roi_bin = cv2.threshold(roi_local, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                lit_ratio = cv2.countNonZero(roi_bin) / roi_bin.size
            except:
                pass
        
        roi_reports.append(f"{name}:{lit_ratio:.1%}")

        # 绘图逻辑
        status_color = (0, 255, 0) if (lit_ratio > ACTIVE_RATIO) else (0, 0, 255)
        cv2.rectangle(canvas_result, (rx, ry), (rx+rw, ry+rh), status_color, 1)

    # === 修改 1: 在控制台输出中添加参数信息 ===
    print(f"[{img_name}] G:{gamma} L:{noise_limit} | " + " | ".join(roi_reports))

    # === 修改 2: 在保存的文件名中添加参数信息 ===
    clean_name = os.path.splitext(img_name)[0]
    save_filename = f"{clean_name}_G{gamma}_L{noise_limit}_debug.jpg"
    cv2.imwrite(os.path.join(OUTPUT_DIR, save_filename), canvas_result)

    
def main():
    print(f"开始处理已裁剪图片，输出至: {OUTPUT_DIR}")
    ensure_dir(OUTPUT_DIR)
    images = get_images()
    
    if not images:
        print("未找到图片，请检查 LOCAL_DIR 路径或 URL")
        return

    count = 0
    for img_name, img_bytes in images:
        for gamma in GAMMA_LIST:
            for limit in NOISE_LIMIT_LIST:
                process_single_case(img_name, img_bytes, gamma, limit)
                count += 1
    
    print(f"\n完成！共处理 {count} 组参数组合。")

if __name__ == "__main__":
    main()
