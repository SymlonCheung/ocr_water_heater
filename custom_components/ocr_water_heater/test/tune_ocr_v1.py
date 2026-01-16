"""
OCR 参数调优脚本 (针对已裁剪的 ROI_PANEL 图片)
功能：读取已裁剪的面板图片 -> 遍历 Gamma 和阈值 -> 生成调试结果
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
LOCAL_DIR = "/workspaces/core/tmp/panel_pic" # 这里的图片必须已经是 ROI_PANEL 裁剪后的
IMAGE_URL = "http://192.168.123.86:5000/api/reshuiqi/latest.jpg"

# 输出目录
OUTPUT_DIR = "/workspaces/core/tmp/ocr_debug/tuning"

# === 相对坐标配置 (基于已裁剪图片的 0,0 点) ===
# 假设您的输入图片尺寸已经是 (119, 30)
ROIS = {
    "ocr":     (41, 4, 36, 26),  # (769-728, 339-335, ...)
    "setting": (47, 1, 11, 7),   # (775-728, 336-335, ...)
    "low":     (5, 5, 13, 5),    # (733-728, 340-335, ...)
    "half":    (5, 15, 13, 5),   # (733-728, 350-335, ...)
    "full":    (5, 24, 13, 5)    # (733-728, 359-335, ...)
}

# === 穷举参数范围 ===
GAMMA_LIST = [2.0]
NOISE_LIMIT_LIST = [30]
ACTIVE_RATIO = 0.20

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
        if not os.path.exists(LOCAL_DIR): return []
        for f in sorted(os.listdir(LOCAL_DIR)):
            if f.lower().endswith(('.jpg', '.png', '.jpeg')):
                with open(os.path.join(LOCAL_DIR, f), 'rb') as file:
                    images.append((f, file.read()))
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
    if panel_color is None: return
    
    ph, pw = panel_color.shape[:2]
    panel_gray = cv2.cvtColor(panel_color, cv2.COLOR_BGR2GRAY)

    # 2. Gamma 增强
    panel_enhanced = enhance_image(panel_gray, gamma)
    canvas_result = cv2.cvtColor(panel_enhanced, cv2.COLOR_GRAY2BGR)

    # 3. 遍历 ROI
    for name, (rx, ry, rw, rh) in ROIS.items():
        roi_local = panel_enhanced[max(0,ry):min(ph,ry+rh), max(0,rx):min(pw,rx+rw)]
        if roi_local.size == 0: continue
        
        lit_ratio = 0.0
        max_val = np.max(roi_local)
        
        if max_val >= noise_limit:
            try:
                _, roi_bin = cv2.threshold(roi_local, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                lit_ratio = cv2.countNonZero(roi_bin) / roi_bin.size
            except:
                pass
        
        # --- 仅输出 low 区域的百分比 ---
        if name == "low":
            print(f"[{img_name}] Low 区域高亮占比: {lit_ratio:.2%}")

        # 保持原来的画框逻辑以便生成对比图
        status_color = (0, 255, 0) if (lit_ratio > ACTIVE_RATIO) else (0, 0, 255)
        cv2.rectangle(canvas_result, (rx, ry), (rx+rw, ry+rh), status_color, 1)

    # 4. 保存图片
    clean_name = os.path.splitext(img_name)[0]
    cv2.imwrite(os.path.join(OUTPUT_DIR, f"{clean_name}_debug.jpg"), canvas_result)
    
def main():
    print(f"开始处理已裁剪图片，输出至: {OUTPUT_DIR}")
    ensure_dir(OUTPUT_DIR)
    images = get_images()
    
    count = 0
    for img_name, img_bytes in images:
        for gamma in GAMMA_LIST:
            for limit in NOISE_LIMIT_LIST:
                process_single_case(img_name, img_bytes, gamma, limit)
                count += 1
    
    print(f"完成！生成 {count} 张测试对比图。")

if __name__ == "__main__":
    main()