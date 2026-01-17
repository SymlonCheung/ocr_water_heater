"""Constants for the OCR Water Heater integration."""
from homeassistant.const import Platform

DOMAIN = "ocr_water_heater"
DEFAULT_NAME = "Smart Water Heater"
PLATFORMS: list[Platform] = [Platform.WATER_HEATER]


MODE_LOW_POWER = "低功率"
MODE_HALF = "速热半缸"
MODE_FULL = "速热全缸"
MODE_STANDBY = "待机"
MODE_SETTING = "正在设置"
MODE_OFF = "关闭"

# === 默认 ROI 配置 (已更新为你提供的新坐标) ===
# 728, 335, 119, 30
DEFAULT_ROI_PANEL = (728, 335, 119, 30)

DEFAULT_ROI_OCR = (769, 339, 36, 26)
DEFAULT_ROI = DEFAULT_ROI_OCR
# 图标坐标 (保持原有，因为 ModeProcessor 会自动计算相对位置，只要它们在 Panel 范围内即可)
# 如果发现识别不准，后续可能需要微调这些相对 Panel 的位置
DEFAULT_ROI_SETTING = (775, 336, 11, 7)
DEFAULT_ROI_LOW     = (733, 340, 13, 5)
DEFAULT_ROI_HALF    = (733, 350, 13, 5)
DEFAULT_ROI_FULL    = (733, 359, 13, 5)

DEFAULT_SKEW = 8.0
DEFAULT_UPDATE_INTERVAL = 1000
DEFAULT_DEBUG_MODE = False

# === 图像处理核心参数 (基于你的测试结果优化) ===
# 1. 对比度增强系数 (1.5 - 2.5 均可，推荐 2.0) G+L 1.5+40 2.5+10 2+20
DEFAULT_GAMMA = 2.0 

# 2. 局部亮度底噪门限 (0-255)
# 在 Gamma 增强后，如果一个图标区域内的最大亮度低于此值，直接视为灭
# 你的测试表明 20-40 都是 2.0 的好区间，选 30 比较稳
DEFAULT_NOISE_LIMIT = 20

# === 配置键 ===
CONF_IMAGE_URL = "image_url"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_DEBUG_MODE = "debug_mode"
CONF_SKEW = "skew_angle"
CONF_GAMMA = "gamma" 
# --- NEW MIIO CONSTANTS ---
CONF_MIIO_IP = "miio_ip"
CONF_MIIO_TOKEN = "miio_token"

CONF_PANEL_X, CONF_PANEL_Y, CONF_PANEL_W, CONF_PANEL_H = "panel_x", "panel_y", "panel_w", "panel_h"

CONF_OCR_X, CONF_OCR_Y, CONF_OCR_W, CONF_OCR_H = "ocr_x", "ocr_y", "ocr_w", "ocr_h"
CONF_SET_X, CONF_SET_Y, CONF_SET_W, CONF_SET_H = "set_x", "set_y", "set_w", "set_h"
CONF_LOW_X, CONF_LOW_Y, CONF_LOW_W, CONF_LOW_H = "low_x", "low_y", "low_w", "low_h"
CONF_HALF_X, CONF_HALF_Y, CONF_HALF_W, CONF_HALF_H = "half_x", "half_y", "half_w", "half_h"
CONF_FULL_X, CONF_FULL_Y, CONF_FULL_W, CONF_FULL_H = "full_x", "full_y", "full_w", "full_h"

# === 算法常量 ===
RESIZE_FACTOR = 5.0
SIDE_CROP_PIXELS = 4
UNSHARP_AMOUNT = 2.0
VALID_MIN = 10
VALID_MAX = 80
MODE_A_SMART_SLIM = True
MODE_A_SLIM_THRESHOLD = 0.30
MODE_A_FORCE_ERODE = False

# OCR 亮度检查阈值 (增强对比度后，这个值可以稍微调高)
OCR_MIN_PEAK_BRIGHTNESS = 60 

# 模式识别 - 激活判定比例
MODE_ACTIVE_RATIO = 0.20

CHAR_REPLACE_MAP = {
    '/': '1', 'l': '1', 'I': '1', '|': '1', ']': '1', '[': '1', 'f': '1', 'i': '1', 't': '1',
    'D': '0', 'O': '0', 'o': '0', 'Q': '0', 'C': '0', 'U': '0',
    'Z': '2', 'z': '2', '?': '2',
    's': '5', 'S': '5', '$': '5',
    'B': '8', '&': '8',
    'A': '4',
    '(': '1', ')': '1',
    'g': '9', 'q': '9',
    '{': '7', '}': '7'
}

DEBUG_DIR_ROOT = "/workspaces/core/tmp/ocr_debug"

# --- MIIO COMMANDS ---
CMD_METHOD_IR = "send_ir_code"
CMD_METHOD_ELE = "send_other_ele_cmd"

# IR Code for Wake Up / Screen Display
CMD_VAL_SCREEN_ON = ["FE00000000000094701fff7a0107002427ed003600AB00DF01C403850F9B1388430000000101000100010101000001000100010100010000000100000100010101054206F2"]

# Electrical Commands
CMD_VAL_TEMP_UP = ["00000c00d0135500032100040ED8010010390016001500160040010004015A00AD00000106015A00560015050058A701FE"]
CMD_VAL_TEMP_DOWN = ["00000c00d0135500042100040ED8010010390016001500160040010004015A00AD00000106015A00560015050058A703FC"]
CMD_VAL_TOGGLE = ["00000c00d0135500012100040ED8010010390016001500160040010004015A00AD00000106015A00560015050058A700FF"]

# IR Command for Mode Switching (Low -> Half -> Full loop)
CMD_VAL_MODE = ["FE00000000000094701fff790107002427ec003600AB00E001C403850F9C1388430000000101000100010101000001000100010000000000000100010101010101054206F4"]
# 待机模式下的保活(防息屏)间隔 (秒)
# 建议设置为 30-50 秒，取决于热水器自动息屏的时间
SCREEN_KEEP_ALIVE_INTERVAL = 40

# 目标温度同步间隔 (秒)
# 每隔多久自动“激活”一次设置菜单，读取真实目标温度并同步到HA
TARGET_TEMP_SYNC_INTERVAL = 600