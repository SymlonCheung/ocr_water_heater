"""
OCR 最终调优脚本 (针对 36x26 OCR 区域裁剪 + 仿生产环境算法)
功能：
1. 读取原图 (1280x720) -> 裁剪 OCR 区域 (36x26)
2. 执行 Gamma -> Otsu -> 背景统一(白底黑字) -> 腐蚀
3. 在处理后的小图上计算七段数码管状态 (检测黑像素)
"""
import os
import cv2
import numpy as np
import shutil

# ================= 配置区域 =================

LOCAL_DIR = "/workspaces/core/tmp/ocr"
OUTPUT_DIR = "/workspaces/core/tmp/ocr_debug/final_tuning"

# 1. 全局坐标配置
# OCR 区域裁剪框 (x, y, w, h)
DEFAULT_ROI_OCR = (769, 339, 36, 26)

# 七段数码管坐标 (基于 1280x720 原图)
RAW_SEGMENTS = {
    'a1': (779, 344), 'b1': (784, 347), 'c1': (782, 355),
    'd1': (777, 359), 'e1': (772, 355), 'f1': (774, 347), 'g1': (778, 351),
    'a0': (795, 344), 'b0': (800, 348), 'c0': (798, 354),
    'd0': (793, 358), 'e0': (789, 354), 'f0': (790, 347), 'g0': (794, 350)
}

# 检测框大小 (因为是36x26的小图，建议用 2x2 或 3x3)
SEGMENT_SIZE = (2, 2)

# === 调优参数穷举 ===
# 1. Gamma 值 (你的代码默认是 1.5)
GAMMA_LIST = [1.0]

# 2. 腐蚀迭代次数 (对应 Smart Slimming, 0=不腐蚀, 1=轻微变细, 2=强力变细)
ERODE_ITER_LIST = [0]

# 3. 判定阈值 (黑色像素占比多少算"亮")
# 注意：处理后是白底黑字，所以我们检测黑色像素占比
# 0.25 表示 2x2 区域里有一个黑点就算亮 #[0.25, 0.50] 都成功
ACTIVE_RATIO_LIST = [0.50]

# 4. 最小亮度阈值 (防止全黑图片处理)
OCR_MIN_PEAK_BRIGHTNESS = 50

# === 数码管解码表 ===
SEGMENT_MAP = {
    (1, 1, 1, 1, 1, 1, 0): 0, (0, 1, 1, 0, 0, 0, 0): 1, (1, 1, 0, 1, 1, 0, 1): 2,
    (1, 1, 1, 1, 0, 0, 1): 3, (0, 1, 1, 0, 0, 1, 1): 4, (1, 0, 1, 1, 0, 1, 1): 5,
    (1, 0, 1, 1, 1, 1, 1): 6, (1, 1, 1, 0, 0, 0, 0): 7, (1, 1, 1, 1, 1, 1, 1): 8,
    (1, 1, 1, 1, 0, 1, 1): 9, (0, 0, 0, 0, 0, 0, 0): None
}

# ================= 逻辑代码 =================

def ensure_dir(path):
    if os.path.exists(path): shutil.rmtree(path)
    os.makedirs(path)

def get_images():
    images = []
    if not os.path.exists(LOCAL_DIR): return []
    for root, dirs, files in os.walk(LOCAL_DIR):
        if "01_Panel.jpg" in files:
            # 兼容不同层级，用文件夹名做前缀
            folder = os.path.basename(root)
            images.append((folder, os.path.join(root, "01_Panel.jpg")))
    return images

def get_local_rois():
    """将全局 RAW_SEGMENTS 转换为相对于 DEFAULT_ROI_OCR 的坐标"""
    rois = {}
    ocr_x, ocr_y, _, _ = DEFAULT_ROI_OCR
    
    for key, (gx, gy) in RAW_SEGMENTS.items():
        # 相对坐标 = 全局 - OCR原点
        rx = gx - ocr_x
        ry = gy - ocr_y
        rois[key] = (rx, ry, SEGMENT_SIZE[0], SEGMENT_SIZE[1])
    return rois

def preprocess_ocr_region(img_origin, gamma, erode_iters):
    """
    核心处理函数：完全复刻你的 process_image 逻辑
    """
    # 1. 裁剪 ROI
    x, y, w, h = DEFAULT_ROI_OCR
    # 保护边界
    if y+h > img_origin.shape[0] or x+w > img_origin.shape[1]:
        return None, "CropError"
        
    roi = img_origin[y:y+h, x:x+w]
    gray_base = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    
    # 2. 亮度检查 (模拟你的 check)
    if np.max(gray_base) < OCR_MIN_PEAK_BRIGHTNESS:
        return None, "TooDark"

    # 3. Gamma 增强 (LUT 方式)
    invGamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
    gray_proc = cv2.LUT(gray_base, table)

    # 4. Otsu 二值化
    _, binary = cv2.threshold(gray_proc, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 5. 背景统一 (确保白底黑字)
    # countNonZero 计算的是白色像素(255)
    # 如果白色像素少于一半，说明背景是黑的，需要反转
    if cv2.countNonZero(binary) < (binary.size * 0.5):
        binary = cv2.bitwise_not(binary)

    # 6. 细化处理 (Slimming)
    if erode_iters > 0:
        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.erode(binary, kernel, iterations=erode_iters)
        # 这里为了调试简单，暂时省略了那个 findContours 的保护逻辑，
        # 因为那个逻辑是为了防止把字腐蚀没了，调试时如果字没了正好说明参数不对。

    # 注意：这里不进行 Padding，因为 Padding 会改变坐标。
    # 我们直接在未 Padding 的 36x26 图片上进行坐标点检测。
    return binary, "OK"

def decode_7seg(states):
    return SEGMENT_MAP.get(tuple(states), "?")

def process_single_case(img_id, img_path, gamma, erode, active_ratio, local_rois):
    img_origin = cv2.imread(img_path)
    if img_origin is None: return

    # 运行处理管线
    binary_roi, status = preprocess_ocr_region(img_origin, gamma, erode)
    
    if binary_roi is None:
        print(f"[{img_id}] 跳过: {status}")
        return

    # 此时 binary_roi 是 白底(255) 黑字(0)
    # 转回 BGR 用于画红绿框
    canvas = cv2.cvtColor(binary_roi, cv2.COLOR_GRAY2BGR)
    h, w = binary_roi.shape[:2]

    brightness_map = {} # 记录每个段的"黑色占比"

    # === 检测逻辑 ===
    for key, (rx, ry, rw, rh) in local_rois.items():
        if rx < 0 or ry < 0 or rx+rw > w or ry+rh > h:
            brightness_map[key] = 0.0
            continue
            
        roi_zone = binary_roi[ry:ry+rh, rx:rx+rw]
        
        # 关键修改：计算黑色像素(0)的比例
        # total pixels
        total = roi_zone.size
        # white pixels (255)
        white_pixels = cv2.countNonZero(roi_zone)
        # black pixels
        black_pixels = total - white_pixels
        
        ratio = black_pixels / total
        brightness_map[key] = ratio

    # === 识别逻辑 ===
    digits_result = {}
    seg_order = ['a', 'b', 'c', 'd', 'e', 'f', 'g']

    for pos in ['1', '0']:
        states = []
        for seg in seg_order:
            key = f"{seg}{pos}"
            val = brightness_map.get(key, 0.0)
            
            # 如果黑色占比 > 阈值，则是“亮”(笔画存在)
            is_active = 1 if val >= active_ratio else 0
            states.append(is_active)
            
            # 绘图: 绿色=识别为亮(有笔画), 红色=识别为灭(背景)
            # 这里的框画在 36x26 的小图上
            color = (0, 255, 0) if is_active else (0, 0, 255)
            if key in local_rois:
                rx, ry, rw, rh = local_rois[key]
                # 画实心框方便看覆盖率，或者空心框看内容
                # 这里画空心框，保留中间像素以便观察是否真的黑
                cv2.rectangle(canvas, (rx, ry), (rx+rw, ry+rh), color, 1)

        digits_result[pos] = decode_7seg(states)

    res_str = f"{digits_result['1']}{digits_result['0']}"
    safe_res = res_str.replace('?', 'X').replace('None', 'N')
    
    # 文件名: 结果_Gamma_Erode_Ratio
    filename = f"{img_id}_Res{safe_res}_G{gamma}_E{erode}_R{active_ratio}.jpg"
    
    print(f"[{img_id}] Res:{res_str} | G:{gamma} E:{erode} R:{active_ratio}")
    
    # 图片标注
    cv2.putText(canvas, res_str, (0, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (128, 128, 128), 1)
    
    # 为了方便看清，把 36x26 的小图放大保存
    scale = 5
    large_canvas = cv2.resize(canvas, (w*scale, h*scale), interpolation=cv2.INTER_NEAREST)
    
    cv2.imwrite(os.path.join(OUTPUT_DIR, filename), large_canvas)

def main():
    print(f"🚀 [最终版] 开始处理... 输出至: {OUTPUT_DIR}")
    ensure_dir(OUTPUT_DIR)
    
    # 1. 计算相对坐标
    local_rois = get_local_rois()
    print("ROI 相对坐标 (基于 36x26 画布):")
    print(f"  a1: {local_rois['a1']}")
    print(f"  g0: {local_rois['g0']}")
    
    images = get_images()
    
    count = 0
    for img_id, img_path in images:
        for g in GAMMA_LIST:
            for e in ERODE_ITER_LIST:
                for r in ACTIVE_RATIO_LIST:
                    process_single_case(img_id, img_path, g, e, r, local_rois)
                    count += 1
    
    print(f"\n✅ 完成。请检查生成的图片。注意：图片已被放大5倍以便观察。")
    print("绿色框 = 判定为笔画(黑色)")
    print("红色框 = 判定为背景(白色)")

if __name__ == "__main__":
    main()