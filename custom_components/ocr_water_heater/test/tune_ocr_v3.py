"""
OCR 最终验证脚本 (No-OpenCV / PIL 版)
环境: Home Assistant Python 3.13 (需 Pillow, Numpy)
功能: 
1. 遍历 /workspaces/core/tmp/ocr (大图) 和 /workspaces/core/tmp/panel_pic (小图)
2. 自动裁剪 OCR 区域 -> 手动 Otsu 二值化 -> 白底黑字 -> 识别
"""
import os
import shutil
import numpy as np
from PIL import Image, ImageDraw, ImageOps

# ================= 配置区域 =================

# 待扫描的目录列表
INPUT_DIRS = [
    "/workspaces/core/tmp/panel_pic",  # 存放 119x30 小图
    "/workspaces/core/tmp/ocr"         # 存放 1280x720 大图
]

OUTPUT_DIR = "/workspaces/core/tmp/ocr_debug/pil_verify"

# === 坐标体系 (基于 1280x720 全局) ===
ROI_PANEL_GLOBAL = (728, 335, 119, 30) # 面板区域
ROI_OCR_GLOBAL   = (769, 339, 36, 26)  # OCR 核心区域

# 七段数码管坐标
RAW_SEGMENTS = {
    'a1': (780, 344), 'b1': (784, 347), 'c1': (782, 355),
    'd1': (777, 359), 'e1': (772, 355), 'f1': (774, 347), 'g1': (778, 351),
    'a0': (796, 344), 'b0': (800, 348), 'c0': (798, 354),
    'd0': (793, 358), 'e0': (789, 354), 'f0': (790, 347), 'g0': (794, 350)
}

# === 算法参数 ===
SEGMENT_SIZE = (2, 2)
ACTIVE_RATIO = 0.50             # 黑色像素占比 >= 50%
OCR_MIN_PEAK_BRIGHTNESS = 50    # 最小亮度检查

SEGMENT_MAP = {
    (1, 1, 1, 1, 1, 1, 0): 0, (0, 1, 1, 0, 0, 0, 0): 1, (1, 1, 0, 1, 1, 0, 1): 2,
    (1, 1, 1, 1, 0, 0, 1): 3, (0, 1, 1, 0, 0, 1, 1): 4, (1, 0, 1, 1, 0, 1, 1): 5,
    (1, 0, 1, 1, 1, 1, 1): 6, (1, 1, 1, 0, 0, 0, 0): 7, (1, 1, 1, 1, 1, 1, 1): 8,
    (1, 1, 1, 1, 0, 1, 1): 9, (0, 0, 0, 0, 0, 0, 0): None
}

# ================= 辅助函数 =================

def ensure_dir(path):
    if os.path.exists(path): shutil.rmtree(path)
    os.makedirs(path)

def get_images():
    """遍历所有目录寻找 01_Panel.jpg"""
    image_list = []
    for d in INPUT_DIRS:
        if not os.path.exists(d):
            print(f"⚠️  目录不存在跳过: {d}")
            continue
        for root, dirs, files in os.walk(d):
            if "01_Panel.jpg" in files:
                folder_name = os.path.basename(root)
                file_path = os.path.join(root, "01_Panel.jpg")
                image_list.append((folder_name, file_path))
    return image_list

def get_otsu_threshold(img_gray):
    """
    手动实现 Otsu 阈值算法 (替代 cv2.threshold)
    基于 PIL 的直方图计算
    """
    hist = img_gray.histogram() # 获取 256 个 bin 的直方图
    total = sum(hist)
    current_max, threshold = 0, 0
    sum_total, sum_foreground, weight_background, weight_foreground = 0, 0, 0, 0

    for i in range(256):
        sum_total += i * hist[i]

    for i in range(256):
        weight_background += hist[i]
        if weight_background == 0: continue
        weight_foreground = total - weight_background
        if weight_foreground == 0: break

        sum_foreground += i * hist[i]
        
        mean_bg = sum_foreground / weight_background
        mean_fg = (sum_total - sum_foreground) / weight_foreground
        
        # 类间方差
        between_class_variance = weight_background * weight_foreground * ((mean_bg - mean_fg) ** 2)
        
        if between_class_variance > current_max:
            current_max = between_class_variance
            threshold = i

    return threshold

def get_local_segments():
    """将全局坐标映射到 36x26 的 OCR 局部坐标"""
    ocr_x, ocr_y = ROI_OCR_GLOBAL[0], ROI_OCR_GLOBAL[1]
    local = {}
    for k, (gx, gy) in RAW_SEGMENTS.items():
        local[k] = (gx - ocr_x, gy - ocr_y)
    return local

# ================= 主逻辑 =================

def process_single_image(img_id, img_path, local_segs):
    try:
        # 1. 打开图片
        img = Image.open(img_path)
    except Exception as e:
        print(f"[{img_id}] 无法打开: {e}")
        return False

    w, h = img.size
    
    # 2. 智能裁剪 (根据图片尺寸决定)
    ocr_x, ocr_y, ocr_w, ocr_h = ROI_OCR_GLOBAL
    
    crop_box = None
    source_type = ""
    
    if w > 600: 
        # === 情况A: 1280x720 大图 ===
        source_type = "720P"
        crop_box = (ocr_x, ocr_y, ocr_x + ocr_w, ocr_y + ocr_h)
    else:
        # === 情况B: 119x30 面板小图 ===
        source_type = "CROP"
        # 计算 OCR 在 Panel 内的相对偏移
        # Panel原点: 728, 335. OCR原点: 769, 339.
        # 偏移 = 41, 4
        rel_x = ocr_x - ROI_PANEL_GLOBAL[0]
        rel_y = ocr_y - ROI_PANEL_GLOBAL[1]
        crop_box = (rel_x, rel_y, rel_x + ocr_w, rel_y + ocr_h)

    # 执行裁剪 -> 转灰度
    ocr_img = img.crop(crop_box).convert("L")
    
    # 3. 亮度检查
    # 获取最大亮度值
    np_img = np.array(ocr_img)
    max_val = np.max(np_img) if np_img.size > 0 else 0
    
    if max_val < OCR_MIN_PEAK_BRIGHTNESS:
        print(f"[{img_id}] 屏幕太暗 (Max:{max_val}) - 跳过")
        return False

    # 4. Otsu 二值化
    thresh_val = get_otsu_threshold(ocr_img)
    # point 函数用于像素级操作: <阈值 变0，>阈值 变255
    binary_img = ocr_img.point(lambda p: 255 if p > thresh_val else 0)
    
    # 5. 背景统一 (白底黑字)
    # 统计白色像素 (255)
    np_bin = np.array(binary_img)
    white_pixels = np.count_nonzero(np_bin == 255)
    total_pixels = np_bin.size
    
    # 如果白色少于一半，说明背景是黑的，需要反转
    if white_pixels < (total_pixels * 0.5):
        binary_img = ImageOps.invert(binary_img)
        # 更新 numpy 数组以便后续计算
        np_bin = np.array(binary_img)

    # 6. 识别逻辑 (检测黑色像素)
    # 转为 RGB 方便画框
    canvas = binary_img.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    
    digits_result = {}
    seg_order = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
    
    # 36x26 画布
    
    for pos in ['1', '0']:
        states = []
        for seg in seg_order:
            key = f"{seg}{pos}"
            rx, ry = local_segs[key] # 这里的坐标是基于 36x26 的
            rw, rh = SEGMENT_SIZE
            
            # 边界检查
            if rx < 0 or ry < 0 or rx+rw > ocr_w or ry+rh > ocr_h:
                states.append(0)
                continue
            
            # 提取区域像素 (Numpy 切片)
            # 注意 numpy 是 [y:y+h, x:x+w]
            zone = np_bin[ry:ry+rh, rx:rx+rw]
            
            # 计算黑色像素 (值=0) 的比例
            zone_total = zone.size
            zone_white = np.count_nonzero(zone == 255)
            zone_black = zone_total - zone_white
            
            ratio = zone_black / zone_total if zone_total > 0 else 0
            
            # 判定
            is_active = 1 if ratio >= ACTIVE_RATIO else 0
            states.append(is_active)
            
            # 绘图: 绿色=有笔画(黑), 红色=无笔画(白)
            # Pillow Draw rectangle: [x0, y0, x1, y1] (inclusive)
            color = (0, 255, 0) if is_active else (255, 0, 0)
            draw.rectangle([rx, ry, rx+rw-1, ry+rh-1], outline=color)

        digits_result[pos] = SEGMENT_MAP.get(tuple(states), "?")

    res_str = f"{digits_result['1']}{digits_result['0']}"
    safe_res = res_str.replace('?', 'X').replace('None', 'N')

    print(f"[{img_id}][{source_type}] 结果: {res_str}")

    # 7. 保存结果 (放大 5 倍)
    # NEAREST 保持像素格
    large_canvas = canvas.resize((ocr_w * 5, ocr_h * 5), resample=Image.NEAREST)
    draw_large = ImageDraw.Draw(large_canvas)
    
    # 写字 (Pillow 默认字体)
    draw_large.text((5, 5), res_str, fill=(0, 255, 255))
    
    filename = f"{img_id}_{source_type}_Res{safe_res}.jpg"
    large_canvas.save(os.path.join(OUTPUT_DIR, filename))
    return True

def main():
    print(f"🚀 [PIL版] 开始处理... 输出目录: {OUTPUT_DIR}")
    ensure_dir(OUTPUT_DIR)
    
    local_segs = get_local_segments()
    # print(f"DEBUG: OCR局部坐标 a1: {local_segs['a1']}")
    
    images = get_images()
    if not images:
        print("❌ 未找到图片，请检查 INPUT_DIRS")
        return

    count = 0
    for img_id, img_path in images:
        if process_single_image(img_id, img_path, local_segs):
            count += 1
            
    print(f"\n✅ 全部完成! 共处理 {count} 张图片。")
    print(f"请检查 {OUTPUT_DIR}")

if __name__ == "__main__":
    main()