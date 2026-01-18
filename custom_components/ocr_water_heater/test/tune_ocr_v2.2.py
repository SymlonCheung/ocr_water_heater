"""
OCR 最终验证脚本 (生产环境模拟)
输入: 119x30 的 Panel 裁剪图
过程: 自动裁剪出 36x26 OCR 区域 -> 执行确认好的算法 -> 输出结果
"""
import os
import cv2
import numpy as np
import shutil

# ================= 生产环境参数配置 =================

# 输入/输出目录
INPUT_DIR = "/workspaces/core/tmp/panel_pic"
OUTPUT_DIR = "/workspaces/core/tmp/ocr_debug/production_verify"

# === 1. 坐标体系 (基于 1280x720 全局) ===
# 面板区域 (你现在的图片就是根据这个裁剪的)
ROI_PANEL_GLOBAL = (728, 335, 119, 30)

# OCR 核心区域 (需要从面板中二次裁剪的区域)
ROI_OCR_GLOBAL = (769, 339, 36, 26)

# 确认的七段数码管坐标 (全局)
RAW_SEGMENTS = {
    'a1': (779, 344), 'b1': (784, 347), 'c1': (782, 355),
    'd1': (777, 359), 'e1': (772, 355), 'f1': (774, 347), 'g1': (778, 351),
    'a0': (795, 344), 'b0': (800, 348), 'c0': (798, 354),
    'd0': (793, 358), 'e0': (789, 354), 'f0': (790, 347), 'g0': (794, 350)
}

# === 2. 确认的算法参数 (100% 成功版) ===
SEGMENT_SIZE = (2, 2)            # 检测框大小
GAMMA = 1.0                      # 不做 Gamma 变换
ERODE_ITERS = 0                  # 不腐蚀
ACTIVE_RATIO = 0.50              # 2x2 像素中至少 2 个黑点 (>=50%)
OCR_MIN_PEAK_BRIGHTNESS = 50     # 亮度检查

# === 数码管映射表 ===
SEGMENT_MAP = {
    (1, 1, 1, 1, 1, 1, 0): 0, (0, 1, 1, 0, 0, 0, 0): 1, (1, 1, 0, 1, 1, 0, 1): 2,
    (1, 1, 1, 1, 0, 0, 1): 3, (0, 1, 1, 0, 0, 1, 1): 4, (1, 0, 1, 1, 0, 1, 1): 5,
    (1, 0, 1, 1, 1, 1, 1): 6, (1, 1, 1, 0, 0, 0, 0): 7, (1, 1, 1, 1, 1, 1, 1): 8,
    (1, 1, 1, 1, 0, 1, 1): 9, (0, 0, 0, 0, 0, 0, 0): None
}

# ================= 核心逻辑 =================

def ensure_dir(path):
    if os.path.exists(path): shutil.rmtree(path)
    os.makedirs(path)

def get_panel_images():
    """遍历所有子文件夹下的 01_Panel.jpg"""
    images = []
    if not os.path.exists(INPUT_DIR):
        print(f"❌ 路径不存在: {INPUT_DIR}")
        return []
    
    for root, dirs, files in os.walk(INPUT_DIR):
        if "01_Panel.jpg" in files:
            # 用文件夹名作为 ID
            folder_name = os.path.basename(root)
            file_path = os.path.join(root, "01_Panel.jpg")
            images.append((folder_name, file_path))
    return images

def get_relative_segments():
    """计算 Segment 相对于 OCR 小图的坐标"""
    ocr_global_x = ROI_OCR_GLOBAL[0]
    ocr_global_y = ROI_OCR_GLOBAL[1]
    
    local_segs = {}
    for key, (gx, gy) in RAW_SEGMENTS.items():
        rx = gx - ocr_global_x
        ry = gy - ocr_global_y
        local_segs[key] = (rx, ry)
    return local_segs

def get_crop_params():
    """计算从 Panel 到 OCR 的裁剪参数"""
    px, py, _, _ = ROI_PANEL_GLOBAL
    ox, oy, ow, oh = ROI_OCR_GLOBAL
    
    # OCR 在 Panel 图片里的起始位置
    crop_x = ox - px  # 769 - 728 = 41
    crop_y = oy - py  # 339 - 335 = 4
    return crop_x, crop_y, ow, oh

def decode_7seg(states):
    return SEGMENT_MAP.get(tuple(states), "?")

def process_single_image(img_id, img_path, local_segs, crop_params):
    # 1. 读取 Panel 图片 (119x30)
    panel_img = cv2.imread(img_path)
    if panel_img is None: return

    # 2. 二次裁剪：提取 OCR 区域 (36x26)
    cx, cy, cw, ch = crop_params
    # 边界保护
    if cy+ch > panel_img.shape[0] or cx+cw > panel_img.shape[1]:
        print(f"[{img_id}] 裁剪越界，跳过")
        return

    ocr_roi = panel_img[cy:cy+ch, cx:cx+cw]
    gray = cv2.cvtColor(ocr_roi, cv2.COLOR_BGR2GRAY)

    # 3. 亮度预检查
    if np.max(gray) < OCR_MIN_PEAK_BRIGHTNESS:
        print(f"[{img_id}] 屏幕太暗 (Off)")
        return

    # 4. 图像处理算法 (Gamma -> Otsu -> Invert -> Erode)
    # Gamma (1.0 跳过计算)
    if GAMMA != 1.0:
        invGamma = 1.0 / GAMMA
        table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
        gray = cv2.LUT(gray, table)
    
    # Otsu 二值化
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # 强制白底黑字 (如果白色像素少于一半，说明背景是黑的，反转)
    if cv2.countNonZero(binary) < (binary.size * 0.5):
        binary = cv2.bitwise_not(binary)
        
    # Erode (0 跳过)
    if ERODE_ITERS > 0:
        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.erode(binary, kernel, iterations=ERODE_ITERS)

    # 5. 识别逻辑 (检测黑色像素)
    # 准备画布 (转回彩色以便画框)
    canvas = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    h, w = binary.shape[:2]
    
    digits_result = {}
    seg_order = ['a', 'b', 'c', 'd', 'e', 'f', 'g']

    for pos in ['1', '0']:
        states = []
        for seg in seg_order:
            key = f"{seg}{pos}"
            rx, ry = local_segs[key]
            rw, rh = SEGMENT_SIZE
            
            # 越界保护
            if rx < 0 or ry < 0 or rx+rw > w or ry+rh > h:
                states.append(0)
                continue
            
            # 提取 2x2 区域
            zone = binary[ry:ry+rh, rx:rx+rw]
            
            # 计算黑色像素 (值=0) 的比例
            total_px = zone.size
            white_px = cv2.countNonZero(zone)
            black_px = total_px - white_px
            ratio = black_px / total_px
            
            # 判定
            is_active = 1 if ratio >= ACTIVE_RATIO else 0
            states.append(is_active)
            
            # 绘图: 绿色=有笔画(黑), 红色=无笔画(白)
            color = (0, 255, 0) if is_active else (0, 0, 255)
            # 画空心框，保留中间像素可见
            cv2.rectangle(canvas, (rx, ry), (rx+rw, ry+rh), color, 1)

        digits_result[pos] = decode_7seg(states)

    res_str = f"{digits_result['1']}{digits_result['0']}"
    safe_res = res_str.replace('?', 'X').replace('None', 'N')

    # 6. 保存结果 (放大 5 倍方便查看)
    print(f"[{img_id}] 结果: {res_str}")
    
    scale = 5
    large_canvas = cv2.resize(canvas, (w*scale, h*scale), interpolation=cv2.INTER_NEAREST)
    
    # 标注文字
    cv2.putText(large_canvas, res_str, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 200), 2)
    
    filename = f"{img_id}_Res{safe_res}.jpg"
    cv2.imwrite(os.path.join(OUTPUT_DIR, filename), large_canvas)
    return 1

def main():
    print(f"🚀 开始跑批验证... 输出目录: {OUTPUT_DIR}")
    ensure_dir(OUTPUT_DIR)
    
    # 准备参数
    crop_params = get_crop_params()
    local_segs = get_relative_segments()
    
    print(f"ℹ️  OCR裁剪参数 (x,y,w,h): {crop_params}")
    # print(f"ℹ️  相对坐标示例 a1: {local_segs['a1']}")
    
    images = get_panel_images()
    if not images:
        print("未找到图片")
        return
        
    count = 0
    for img_id, img_path in images:
        if process_single_image(img_id, img_path, local_segs, crop_params):
            count += 1
            
    print(f"\n✅ 全部完成! 共处理 {count} 张图片。")
    print(f"请检查 {OUTPUT_DIR} 确认所有结果是否符合预期。")

if __name__ == "__main__":
    main()