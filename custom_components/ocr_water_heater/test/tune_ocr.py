"""
OCR 参数调优脚本 (Grid Search / 穷举模式)
功能：读取图片 -> 遍历不同的Gamma和阈值参数 -> 生成带有调试信息的结果图
"""
import os
import cv2
import numpy as np
import requests
import time
import shutil

# ================= 配置区域 =================

# 输入源配置
# 模式: 'local' (读取文件夹) 或 'url' (读取单张网络图)
INPUT_MODE = 'local' 
LOCAL_DIR = "/workspaces/core/tmp/pic"
IMAGE_URL = "http://192.168.123.86:5000/api/reshuiqi/latest.jpg"

# 输出目录
OUTPUT_DIR = "/workspaces/core/tmp/ocr_debug/tuning"

# === 坐标配置 (使用你提供的最新坐标) ===
# 面板大图 ROI (x, y, w, h)
ROI_PANEL = (728, 335, 119, 30)

# 各个图标的【绝对坐标】 (需在 Panel 范围内)
ROIS = {
    "ocr":     (769, 339, 36, 26), # 数字区域
    "setting": (775, 336, 11, 7),  # 正在设置
    "low":     (733, 340, 13, 5),  # 低功率
    "half":    (733, 350, 13, 5),  # 半缸
    "full":    (733, 359, 13, 5)   # 全缸
}

# === 穷举参数范围 ===
# 1. Gamma 值列表 (对比度增强，越大背景越黑)
# 建议范围: 1.0 (无效果) ~ 5.0 (极强)
GAMMA_LIST = [1.0, 1.5, 2, 2.5]

# 2. 局部亮度门限 (Local Noise Gate)
# 局部区域最大亮度低于此值时，强制视为黑屏 (0-255)
# 建议范围: 30 ~ 60
NOISE_LIMIT_LIST = [10, 20, 30, 40, 50]

# 激活判定比例 (大于此比例认为图标亮起)
ACTIVE_RATIO = 0.20

# ================= 逻辑代码 =================

def ensure_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)

def get_images():
    images = [] # list of (name, image_bytes)
    
    if INPUT_MODE == 'url':
        print(f"正在从 URL 下载: {IMAGE_URL}")
        try:
            resp = requests.get(IMAGE_URL, timeout=5)
            if resp.status_code == 200:
                images.append(("URL_Latest", resp.content))
            else:
                print("下载失败")
        except Exception as e:
            print(f"连接错误: {e}")
            
    else: # local
        print(f"正在扫描目录: {LOCAL_DIR}")
        if not os.path.exists(LOCAL_DIR):
            print(f"目录不存在: {LOCAL_DIR}")
            return []
        
        for f in sorted(os.listdir(LOCAL_DIR)):
            if f.lower().endswith(('.jpg', '.png', '.jpeg')):
                path = os.path.join(LOCAL_DIR, f)
                with open(path, 'rb') as file:
                    images.append((f, file.read()))
    
    return images

def get_relative_roi(panel_roi, abs_roi):
    """将绝对坐标转为相对坐标"""
    px, py, pw, ph = panel_roi
    ax, ay, aw, ah = abs_roi
    rx = max(0, min(ax - px, pw))
    ry = max(0, min(ay - py, ph))
    rw = min(aw, pw - rx)
    rh = min(ah, ph - ry)
    return (rx, ry, rw, rh)

def enhance_image(image, gamma):
    """Gamma 增强"""
    img_float = image.astype(float)
    min_val = np.min(img_float)
    max_val = np.max(img_float)
    if max_val - min_val < 5: return image
    img_norm = (img_float - min_val) / (max_val - min_val) * 255.0
    img_gamma = np.power(img_norm / 255.0, gamma) * 255.0
    return img_gamma.astype(np.uint8)

def process_single_case(img_name, img_bytes, gamma, noise_limit):
    """处理单张图片、单个参数组合"""
    
    # 1. 解码
    nparr = np.frombuffer(img_bytes, np.uint8)
    img_origin = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img_origin is None: return

    # 2. 裁剪 Panel
    px, py, pw, ph = ROI_PANEL
    # 边界保护
    h, w = img_origin.shape[:2]
    px, py = max(0, px), max(0, py)
    pw, ph = min(pw, w-px), min(ph, h-py)
    
    panel_color = img_origin[py:py+ph, px:px+pw].copy()
    panel_gray = cv2.cvtColor(panel_color, cv2.COLOR_BGR2GRAY)

    # 3. Gamma 增强
    panel_enhanced = enhance_image(panel_gray, gamma)
    
    # 创建一个画布用于显示结果 (RGB)
    # 左边放增强后的灰度图，右边放处理后的二值图叠加结果
    canvas_gray = cv2.cvtColor(panel_enhanced, cv2.COLOR_GRAY2BGR)
    canvas_result = canvas_gray.copy()

    # 4. 遍历每个 ROI 进行局部处理
    for name, abs_roi in ROIS.items():
        rx, ry, rw, rh = get_relative_roi(ROI_PANEL, abs_roi)
        
        # 切割局部
        roi_local = panel_enhanced[ry:ry+rh, rx:rx+rw]
        
        status_color = (0, 0, 255) # 默认红 (未激活)
        lit_ratio = 0.0
        thresh_disp = 0
        
        # 局部亮度检查
        if roi_local.size > 0:
            max_val = np.max(roi_local)
            
            # 只有足够亮才进行 Otsu
            if max_val >= noise_limit:
                try:
                    thresh_val, roi_bin = cv2.threshold(roi_local, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    lit_pixels = cv2.countNonZero(roi_bin)
                    lit_ratio = lit_pixels / roi_bin.size
                    thresh_disp = int(thresh_val)
                    
                    # 激活判定
                    is_active = False
                    if name == "ocr":
                        is_active = lit_ratio > 0.1 # OCR 阈值低一点
                    else:
                        is_active = lit_ratio > ACTIVE_RATIO
                    
                    if is_active:
                        status_color = (0, 255, 0) # 绿 (激活)
                        
                    # 将二值化结果贴回画布，方便观察细节
                    # 只有激活或者亮度足够时才贴，不然保持灰度背景
                    roi_bin_bgr = cv2.cvtColor(roi_bin, cv2.COLOR_GRAY2BGR)
                    canvas_result[ry:ry+rh, rx:rx+rw] = roi_bin_bgr
                    
                except Exception:
                    pass
        
        # 画框
        cv2.rectangle(canvas_result, (rx, ry), (rx+rw, ry+rh), status_color, 1)
        # 写字 (R: 比例, T: 阈值)
        # 由于图很小，我们在框上方写简单的 info
        # info = f"{lit_ratio:.2f}"
        # cv2.putText(canvas_result, info, (rx, ry-2), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 0), 1)

    # 5. 拼接大图保存
    # 上面：原始 Panel (Crop)
    # 中间：Gamma 增强后的 Panel
    # 下面：识别结果 (绿色/红色框 + 二值化填充)
    
    final_h = ph * 3
    final_img = np.zeros((final_h, pw, 3), dtype=np.uint8)
    
    final_img[0:ph, :] = panel_color
    final_img[ph:ph*2, :] = canvas_gray
    final_img[ph*2:ph*3, :] = canvas_result
    
    # 文件名生成
    clean_name = os.path.splitext(img_name)[0]
    out_name = f"{clean_name}_G{gamma}_L{noise_limit}.jpg"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    
    cv2.imwrite(out_path, final_img)
    # print(f"已保存: {out_name}")

def main():
    print("=== OCR 参数调优工具 ===")
    ensure_dir(OUTPUT_DIR)
    
    images = get_images()
    if not images:
        print("未找到图片，请检查路径或 URL")
        return

    print(f"找到 {len(images)} 张图片，开始穷举处理...")
    print(f"Gamma 列表: {GAMMA_LIST}")
    print(f"Noise Limit 列表: {NOISE_LIMIT_LIST}")
    
    count = 0
    start_time = time.time()
    
    for img_name, img_bytes in images:
        for gamma in GAMMA_LIST:
            for limit in NOISE_LIMIT_LIST:
                process_single_case(img_name, img_bytes, gamma, limit)
                count += 1
                if count % 10 == 0:
                    print(f"已处理 {count} 个组合...")
    
    print(f"完成！共生成 {count} 张调试图。")
    print(f"请查看目录: {OUTPUT_DIR}")
    print("="*30)
    print("图解说明:")
    print("第一行: 原始裁剪画面")
    print("第二行: Gamma 增强后的画面 (越黑对比度越高)")
    print("第三行: 算法识别结果")
    print("   - 绿色框: 判定为【亮】 (Active)")
    print("   - 红色框: 判定为【灭】 (Inactive)")
    print("   - 框内图像: 算法看到的二值化结果 (白色为亮像素)")

if __name__ == "__main__":
    main()