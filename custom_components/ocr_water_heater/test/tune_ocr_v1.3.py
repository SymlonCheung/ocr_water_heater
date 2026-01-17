import os
import cv2
import numpy as np

# ================= 100% 还原你提供的 const.py 配置 =================
GAMMA = 2.0
NOISE_LIMIT = 30
ACTIVE_RATIO = 0.20
OCR_MIN_RATIO = 0.08  # 对应源码 if ocr_ratio < 0.10: return MODE_STANDBY

# 绝对坐标 (由你提供的配置而来)
PANEL_ROI = (728, 335, 119, 30)
ABS_ROIS = {
    "ocr":     (769, 339, 36, 26),
    "setting": (775, 336, 11, 7),
    "low":     (733, 340, 13, 5),
    "half":    (733, 350, 13, 5),
    "full":    (733, 359, 13, 5)
}

LOCAL_DIR = "/workspaces/core/tmp/panel_pic"

def get_relative_roi(abs_roi, panel_roi):
    """【完全还原源程序逻辑】将绝对坐标转换为相对于 panel_roi 的坐标"""
    px, py, pw, ph = panel_roi
    ax, ay, aw, ah = abs_roi
    rx = max(0, min(ax - px, pw))
    ry = max(0, min(ay - py, ph))
    rw = min(aw, pw - rx)
    rh = min(ah, ph - ry)
    return (rx, ry, rw, rh)

def diagnose_source_logic(img_path):
    panel_img = cv2.imread(img_path)
    if panel_img is None: return "错误: 读取失败"
    
    ph, pw = panel_img.shape[:2]
    gray_panel = cv2.cvtColor(panel_img, cv2.COLOR_BGR2GRAY)
    
    # 1. Gamma 增强 (还原 _enhance_contrast)
    img_float = gray_panel.astype(float)
    min_val, max_val = np.min(img_float), np.max(img_float)
    if max_val - min_val < 5:
        return "判定: [待机] | 原因: 增强前对比度太低，源程序直接跳过"
    
    img_norm = (img_float - min_val) / (max_val - min_val) * 255.0
    enhanced = np.power(img_norm / 255.0, GAMMA) * 255.0
    enhanced = enhanced.astype(np.uint8)

    # 2. 全局亮度初筛 (对应第4步：np.max(enhanced_panel) < DEFAULT_NOISE_LIMIT)
    if np.max(enhanced) < NOISE_LIMIT:
        return f"判定: [待机] | 原因: 全局最高亮度({np.max(enhanced)})低于门限{NOISE_LIMIT}"

    # 3. 模拟局部分析 (_analyze_roi_local)
    def analyze_local(roi_name, abs_coord):
        rel_x, rel_y, rel_w, rel_h = get_relative_roi(abs_coord, PANEL_ROI)
        roi = enhanced[rel_y:rel_y+rel_h, rel_x:rel_x+rel_w]
        
        if roi.size == 0: return 0.0, 0, "坐标越界"
        
        max_v = np.max(roi)
        if max_v < NOISE_LIMIT:
            return 0.0, max_v, "亮度不足"
            
        _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        ratio = cv2.countNonZero(binary) / binary.size
        return ratio, max_v, "正常"

    # --- 执行判定链 ---
    
    # A. OCR 区域检查 (这是最容易导致“明明有灯亮却判定为待机”的关卡)
    ocr_ratio, ocr_max, ocr_msg = analyze_local("ocr", ABS_ROIS['ocr'])
    if ocr_ratio < OCR_MIN_RATIO:
        return f"判定: [待机] | 原因: OCR占比({ocr_ratio:.1%})未达10% | OCR亮度:{ocr_max} | 状态:{ocr_msg}"

    # B. 设置灯检查
    set_ratio, _, _ = analyze_local("setting", ABS_ROIS['setting'])
    if set_ratio > ACTIVE_RATIO:
        return f"判定: [设置] | 数据: OCR={ocr_ratio:.1%}, SET={set_ratio:.1%}"

    # C. 功率模式竞争
    scores = {}
    details = []
    for m in ['low', 'half', 'full']:
        r, mx, msg = analyze_local(m, ABS_ROIS[m])
        scores[m] = r
        details.append(f"{m}:{r:.1%}(max:{mx})")

    best_m = max(scores, key=scores.get)
    if scores[best_m] > ACTIVE_RATIO:
        mode_map = {"low":"低功率", "half":"半功率", "full":"全功率"}
        return f"判定: [{mode_map[best_m]}] | 数据: OCR={ocr_ratio:.1%} | {', '.join(details)}"

    return f"判定: [待机] | 原因: 功率灯最高占比仅{scores[best_m]:.1%}, 未达{ACTIVE_RATIO:.0%}标线"

def main():
    print(f"{'文件夹名称':<45} | {'2026 源程序逻辑诊断结果'}")
    print("-" * 110)
    subdirs = [os.path.join(LOCAL_DIR, d) for d in os.listdir(LOCAL_DIR) if os.path.isdir(os.path.join(LOCAL_DIR, d))]
    subdirs.sort()

    for folder in subdirs:
        img_path = os.path.join(folder, "01_Panel.jpg")
        if os.path.exists(img_path):
            result = diagnose_source_logic(img_path)
            print(f"{os.path.basename(folder):<45} | {result}")

if __name__ == "__main__":
    main()
