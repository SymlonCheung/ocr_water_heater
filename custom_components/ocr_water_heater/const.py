"""Constants for the OCR Water Heater integration."""
from homeassistant.const import Platform

DOMAIN = "ocr_water_heater"
DEFAULT_NAME = "Smart Water Heater"
PLATFORMS: list[Platform] = [Platform.WATER_HEATER]

# 状态常量 (HA Operation Modes)
STATE_PERFORMANCE = "performance" 

# 自定义模式常量
MODE_LOW_POWER = "低功率"
MODE_HALF = "速热半缸"
MODE_FULL = "速热全缸"
MODE_STANDBY = "待机"
MODE_OFF = "关闭" # 用于 UI 显示，实际实体状态会是 OFF

# 模式检测 ROI (left, top, width, height)
# 对应: extract({ left: 734, top: 340, width: 10, height: 23 })
MODE_ROI = (734, 340, 10, 23)

# 配置键
CONF_IMAGE_URL = "image_url"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_DEBUG_MODE = "debug_mode"
CONF_ROI_X = "roi_x"
CONF_ROI_Y = "roi_y"
CONF_ROI_W = "roi_w"
CONF_ROI_H = "roi_h"
CONF_SKEW = "skew_angle"

# 默认值
DEFAULT_ROI = (769, 339, 36, 26)
DEFAULT_SKEW = 8.0
DEFAULT_UPDATE_INTERVAL = 1000
DEFAULT_DEBUG_MODE = False

# Debug 保存路径
DEBUG_DIR_ROOT = "/workspaces/core/tmp/ocr_debug"

# OCR 参数
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