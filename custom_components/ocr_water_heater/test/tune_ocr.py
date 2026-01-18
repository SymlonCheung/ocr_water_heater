#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import glob
import time
from PIL import Image, ImageDraw

# ================= 调试配置区 (核心修改区) =================

SOURCE_DIR = "/workspaces/core/tmp/panel_pic"
MAX_IMAGES = 20  # 先只看20张

# 输出文件路径 (改为 tmp 防止权限问题)
OUTPUT_PATH = f"/tmp/ocr_calib_{int(time.time())}.jpg"

# 【ROI 调整】
# 01_Panel.jpg 是剪切好的长条图。我们需要在其中定位两个数字。
# 尝试根据你的 44 截图微调：
# 假设 01_Panel.jpg 大小约为 119x30
# 之前的 ROI_OCR_X=769, PANEL_X=728 -> 相对X=41
ROI_OCR_REL_X = 41
ROI_OCR_REL_Y = 4
ROI_OCR_W = 36
ROI_OCR_H = 26

# 【阈值调整】
# LED 屏幕通常有光晕，调高阈值只认最亮的核心部分
THRESHOLD = 120 

# 【采样点微调】
# 这里的坐标是相对于【单个数字区域 (18x26)】左上角的
SEGMENT_POINTS = {
    'A': (9, 3),   # 上横 (稍微下移一点避开边缘)
    'B': (14, 7),  # 右上竖
    'C': (14, 18), # 右下竖
    'D': (9, 23),  # 下横 (稍微上移)
    'E': (4, 18),  # 左下竖
    'F': (4, 7),   # 左上竖
    'G': (9, 13)   # 中横
}

# ========================================================

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
    (0, 0, 0, 0, 0, 0, 0): None
}

def get_states(img_crop, points):
    w, h = img_crop.size
    pixels = img_crop.load()
    states = []
    debug_str = []
    pts_coords = []
    
    for key in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
        px, py = points[key]
        is_on = 0
        val = 0
        if 0 <= px < w and 0 <= py < h:
            val = pixels[px, py]
            if val > THRESHOLD:
                is_on = 1
        states.append(is_on)
        pts_coords.append((px, py, is_on))
        # 记录调试信息: "A:1(200)" 表示A点亮，亮度200
        debug_str.append(f"{key}:{is_on}({val})")
        
    return tuple(states), pts_coords, " ".join(debug_str)

def process_single_image(file_path):
    try:
        img = Image.open(file_path).convert("L")
    except:
        return None

    ocr_crop = img.crop((
        ROI_OCR_REL_X, ROI_OCR_REL_Y, 
        ROI_OCR_REL_X + ROI_OCR_W, ROI_OCR_REL_Y + ROI_OCR_H
    ))
    
    debug_img = ocr_crop.convert("RGB")
    draw = ImageDraw.Draw(debug_img)
    
    half_w = ROI_OCR_W // 2
    
    # 十位
    tens_crop = ocr_crop.crop((0, 0, half_w, ROI_OCR_H))
    tens_states, tens_pts, tens_dbg = get_states(tens_crop, SEGMENT_POINTS)
    tens_val = SEGMENT_MAP.get(tens_states, "?")
    
    for px, py, is_on in tens_pts:
        color = (0, 255, 0) if is_on else (255, 0, 0)
        draw.point((px, py), fill=color)
        draw.rectangle((px-1, py-1, px+1, py+1), outline=color)

    # 个位
    ones_crop = ocr_crop.crop((half_w, 0, half_w * 2, ROI_OCR_H))
    ones_states, ones_pts, ones_dbg = get_states(ones_crop, SEGMENT_POINTS)
    ones_val = SEGMENT_MAP.get(ones_states, "?")
    
    for px, py, is_on in ones_pts:
        color = (0, 255, 0) if is_on else (255, 0, 0)
        draw.rectangle((px+half_w-1, py-1, px+half_w+1, py+1), outline=color)

    # 扩展画布放原图
    final_h = debug_img.height + 2
    final_canvas = Image.new("RGB", (debug_img.width, final_h))
    final_canvas.paste(debug_img, (0, 0))
    
    # 提取文件名里的真值 (例如 ...T_44_... -> 44)
    fname = os.path.basename(file_path)
    real_val = "?"
    if "_T_" in fname:
        try:
            parts = fname.split("_T_")[1].split("_")[0]
            real_val = parts
        except: pass
        
    print(f"[{real_val.ljust(2)}] -> 读出: {tens_val}{ones_val}")
    if str(tens_val)+str(ones_val) != real_val:
        print(f"    十位状态: {tens_dbg}")
        print(f"    个位状态: {ones_dbg}")
        
    return final_canvas

def main():
    files = glob.glob(os.path.join(SOURCE_DIR, "**", "01_Panel.jpg"), recursive=True)
    files.so