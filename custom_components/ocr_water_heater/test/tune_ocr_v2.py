"""
OCR 参数调优脚本 (七段数码管专用版)
功能：读取已裁剪的 ROI_PANEL 图片 -> 转换绝对坐标 -> 计算七段亮度 -> 穷举阈值 -> 识别数字
"""
import os
import cv2
import numpy as np
import shutil

# ================= 配置区域 =================

INPUT_MODE = 'local'
LOCAL_DIR = "/workspaces/core/tmp/panel_pic"
OUTPUT_DIR = "/workspaces/core/tmp/ocr_debug/segments"

# === 坐标系统配置 ===
# 面板在原图中的绝对位置 (x, y, w, h)
PANEL_GLOBAL_RECT = (728, 335, 119, 30)

# 七段数码管的中心点/左上角坐标 (基于 1280x720 原图)
# 格式: (x, y)
RAW_SEGMENTS = {
    # 十位 (1)
    'a1': (779, 343), 'b1': (784, 346), 'c1': (782, 355),
    'd1': (777, 358), 'e1': (772, 355), 'f1': (774, 346),
    'g1': (778, 351),
    # 个位 (0)
    'a0': (795, 343), 'b0': (800, 346), 'c0': (798, 354),
    'd0': (793, 357), 'e0': (788, 354), 'f0': (790, 346),
    'g0': (794, 351)  # 已修正: 原数据 500 越界，修正为 351
}

# 检测框大小 (宽, 高)
SEGMENT_SIZE = (3, 3)

# === 穷举参数范围 ===
GAMMA_LIST = [2]                # 图像增强系数
NOISE_LIMIT_LIST = [20] # 过滤背景噪点的亮度门槛
ACTIVE_RATIO_LIST = [0.25] # 判定为"亮"的像素占比阈值 (穷举此项以寻找最佳切分点)

# === 数码管字典 ===
# 顺序: a, b, c, d, e, f, g
SEGMENT_MAP = {
    (1, 1, 1, 1, 1, 1, 0): 0,
    (0, 1, 1, 0, 0, 0, 0): 1,
    (1, 1, 0, 1, 1, 0, 1): 2,
    (1, 1, 1, 1, 0, 0, 1): 3,
    (0, 1, 1, 0, 0, 1, 1): 4,
    (1, 0, 1, 1, 0, 1, 1): 5,
    (1, 0, 1, 1, 1, 1, 1): 6,
    (1, 1, 1, 0, 0, 0, 0): 7,
    (1, 1, 1, 1, 1, 1, 1): 8,
    (1, 1, 1, 1, 0, 1, 1): 9,
    (0, 0, 0, 0, 0, 0, 0): None # 空
}

# ================= 核心逻辑 =================

def ensure_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)

def get_relative_rois():
    """将全局坐标转换为相对于裁剪图片的坐标"""
    rois = {}
    px, py, _, _ = PANEL_GLOBAL_RECT
    for key, (gx, gy) in RAW_SEGMENTS.items():
        # 相对坐标 = 全局坐标 - 面板起始坐标
        rx = gx - px
        ry = gy - py
        rois[key] = (rx, ry, SEGMENT_SIZE[0], SEGMENT_SIZE[1])
    return rois

def get_images():
    images = []
    if not os.path.exists(LOCAL_DIR):
        print(f"路径不存在: {LOCAL_DIR}")
        return []
    for root, dirs, files in os.walk(LOCAL_DIR):
        if "01_Panel.jpg" in files:
            file_path = os.path.join(root, "01_Panel.jpg")
            folder_name = os.path.basename(root)
            with open(file_path, 'rb') as file:
                images.append((f"{folder_name}", file.read()))
    return images

def enhance_image(image, gamma):
    img_float = image.astype(float)
    min_val, max_val = np.min(img_float), np.max(img_float)
    if max_val - min_val < 5: return image
    img_norm = (img_float - min_val) / (max_val - min_val) * 255.0
    img_gamma = np.power(img_norm / 255.0, gamma) * 255.0
    return img_gamma.astype(np.uint8)

def decode_7seg(states):
    """根据7个布尔值解码数字"""
    # 确保是元组以便查表
    return SEGMENT_MAP.get(tuple(states), "?")

def process_single_case(img_name, img_bytes, gamma, noise_limit, active_ratio, roi_map):
    # 1. 图片预处理
    nparr = np.frombuffer(img_bytes, np.uint8)
    panel_color = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if panel_color is None: return
    
    ph, pw = panel_color.shape[:2]
    panel_gray = cv2.cvtColor(panel_color, cv2.COLOR_BGR2GRAY)
    panel_enhanced = enhance_image(panel_gray, gamma)
    
    # 结果画布
    canvas = cv2.cvtColor(panel_enhanced, cv2.COLOR_GRAY2BGR)
    
    # 2. 计算所有段的亮度
    # 存储格式: {'a1': 0.8, 'b1': 0.1, ...}
    brightness_map = {}
    
    for key, (rx, ry, rw, rh) in roi_map.items():
        # 边界保护
        if rx < 0 or ry < 0 or rx+rw > pw or ry+rh > ph:
            brightness_map[key] = 0.0
            continue
            
        roi_img = panel_enhanced[ry:ry+rh, rx:rx+rw]
        max_v = np.max(roi_img)
        
        ratio = 0.0
        if max_v >= noise_limit:
            # 使用 Otsu 二值化计算亮像素比例
            try:
                # 只有当区域内有足够对比度时才二值化，否则视为全黑
                _, roi_bin = cv2.threshold(roi_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                non_zero = cv2.countNonZero(roi_bin)
                ratio = non_zero / roi_img.size
            except:
                ratio = 0.0
        
        brightness_map[key] = ratio

    # 3. 识别数字 (根据 Active Ratio)
    digits_result = {}
    for pos_suffix in ['1', '0']: # 1=十位, 0=个位
        states = []
        # 标准顺序 a-g
        seg_order = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
        
        debug_str_parts = []
        
        for seg in seg_order:
            key = f"{seg}{pos_suffix}"
            val = brightness_map.get(key, 0.0)
            is_active = 1 if val > active_ratio else 0
            states.append(is_active)
            
            # 绘图: 绿色=激活, 红色=未激活
            color = (0, 255, 0) if is_active else (0, 0, 255)
            rx, ry, rw, rh = roi_map[key]
            cv2.rectangle(canvas, (rx, ry), (rx+rw, ry+rh), color, 1)
            
            # 记录详细日志用
            debug_str_parts.append(f"{seg}:{val:.2f}")

        digit = decode_7seg(states)
        digits_result[pos_suffix] = digit
        
        # 在控制台打印该位的详细亮度数据
        # print(f"  Pos{pos_suffix} [{digit}] Raw: " + " ".join(debug_str_parts))

    final_num_str = f"{digits_result['1']}{digits_result['0']}"
    
    # 4. 生成报告与保存
    # 文件名格式: [数字结果]_图片名_参数.jpg
    # 例如: Res42_timestamp_G2_L30_R0.20.jpg
    safe_num = final_num_str.replace('?', 'X').replace('None', 'N')
    
    print(f"[{img_name}] res:{safe_num} | G:{gamma} L:{noise_limit} R:{active_ratio} | 10s: {digits_result['1']} 1s: {digits_result['0']}")
    
    # 在图片上写结果
    cv2.putText(canvas, f"Res: {final_num_str}", (2, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
    cv2.putText(canvas, f"L:{noise_limit} R:{active_ratio}", (2, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (200, 200, 200), 1)

    filename = f"Res{safe_num}_{img_name}_G{gamma}_L{noise_limit}_R{active_ratio:.2f}.jpg"
    cv2.imwrite(os.path.join(OUTPUT_DIR, filename), canvas)

def main():
    print(f"初始化... 输出目录: {OUTPUT_DIR}")
    ensure_dir(OUTPUT_DIR)
    
    # 1. 计算相对坐标
    roi_map = get_relative_rois()
    print("ROI 相对坐标计算完成 (部分展示):")
    print(f"  a1 (十位a段): {roi_map['a1']}")
    print(f"  a0 (个位a段): {roi_map['a0']}")
    
    # 2. 读取图片
    images = get_images()
    print(f"找到 {len(images)} 张图片待处理")

    # 3. 穷举参数
    count = 0
    for img_name, img_bytes in images:
        for gamma in GAMMA_LIST:
            for limit in NOISE_LIMIT_LIST:
                for ratio in ACTIVE_RATIO_LIST:
                    process_single_case(img_name, img_bytes, gamma, limit, ratio, roi_map)
                    count += 1
    
    print(f"\n全部完成! 共生成 {count} 张调试图。")
    print(f"请打开 {OUTPUT_DIR} 查看文件名以 Res 开头的图片，寻找最准确的参数组合。")

if __name__ == "__main__":
    main()