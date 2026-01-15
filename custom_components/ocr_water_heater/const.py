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

DEFAULT_ROI = (769, 339, 36, 26)
DEFAULT_ROI_OCR = (769, 339, 36, 26)


DEFAULT_ROI_SETTING = (775, 336, 11, 7)   # 正在设置图标
DEFAULT_ROI_LOW     = (733, 340, 13, 5)   # 低功率图标
DEFAULT_ROI_HALF    = (733, 350, 13, 5)   # 速热半缸图标
DEFAULT_ROI_FULL    = (733, 359, 13, 5)   # 速热全缸图标
DEFAULT_SKEW = 8.0
DEFAULT_UPDATE_INTERVAL = 1000 
DEFAULT_DEBUG_MODE = False

# === 配置键 (用于 Config Flow) ===
CONF_IMAGE_URL = "image_url"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_DEBUG_MODE = "debug_mode"
CONF_SKEW = "skew_angle"
CONF_OCR_X, CONF_OCR_Y, CONF_OCR_W, CONF_OCR_H = "ocr_x", "ocr_y", "ocr_w", "ocr_h"
CONF_SET_X, CONF_SET_Y, CONF_SET_W, CONF_SET_H = "set_x", "set_y", "set_w", "set_h"
CONF_LOW_X, CONF_LOW_Y, CONF_LOW_W, CONF_LOW_H = "low_x", "low_y", "low_w", "low_h"
CONF_HALF_X, CONF_HALF_Y, CONF_HALF_W, CONF_HALF_H = "half_x", "half_y", "half_w", "half_h"
CONF_FULL_X, CONF_FULL_Y, CONF_FULL_W, CONF_FULL_H = "full_x", "full_y", "full_w", "full_h"
# Debug 保存路径
DEBUG_DIR_ROOT = "/workspaces/core/tmp/ocr_debug"

RESIZE_FACTOR = 5.0
SIDE_CROP_PIXELS = 4
UNSHARP_AMOUNT = 2.0
VALID_MIN = 10
VALID_MAX = 80
MODE_A_SMART_SLIM = True
MODE_A_SLIM_THRESHOLD = 0.30
MODE_A_FORCE_ERODE = False

SPLIT_OVERLAP_PX = 12
SOLVER_THRESHOLDS = [50, 80, 110, 140, 170]

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

# === MIIO 配置键 ===
CONF_MIIO_IP = "miio_ip"
CONF_MIIO_TOKEN = "miio_token"

# === MIIO 指令 (Hex) ===
CMD_METHOD_ELE = "send_other_ele_cmd"
CMD_METHOD_IR = "send_ir_code"

# 升高目标温度
CMD_VAL_TEMP_UP = ["00000c00d0135500032100040ED8010010390016001500160040010004015A00AD00000106015A00560015050058A701FE"]
# 降低目标温度
CMD_VAL_TEMP_DOWN = ["00000c00d0135500042100040ED8010010390016001500160040010004015A00AD00000106015A00560015050058A703FC"]
# 开关 (Toggle)
CMD_VAL_TOGGLE = ["00000c00d0135500012100040ED8010010390016001500160040010004015A00AD00000106015A00560015050058A700FF"]
# 屏显/IR
CMD_VAL_SCREEN = ["FE00000000000094701fff7a0107002427ed003600AB00DF01C403850F9B1388430000000101000100010101000001000100010100010000000100000100010101054206F2"]
