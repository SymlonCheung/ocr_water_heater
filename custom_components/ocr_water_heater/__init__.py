"""The OCR Water Heater integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import (
    CONF_IMAGE_URL, CONF_UPDATE_INTERVAL, CONF_DEBUG_MODE, CONF_SKEW, CONF_GAMMA,
    DEFAULT_UPDATE_INTERVAL, DEFAULT_DEBUG_MODE, DEFAULT_SKEW, DEFAULT_GAMMA,
    CONF_OCR_X, CONF_OCR_Y, CONF_OCR_W, CONF_OCR_H, DEFAULT_ROI_OCR,
    CONF_PANEL_X, CONF_PANEL_Y, CONF_PANEL_W, CONF_PANEL_H, DEFAULT_ROI_PANEL,
    CONF_SET_X, CONF_SET_Y, CONF_SET_W, CONF_SET_H, DEFAULT_ROI_SETTING,
    CONF_LOW_X, CONF_LOW_Y, CONF_LOW_W, CONF_LOW_H, DEFAULT_ROI_LOW,
    CONF_HALF_X, CONF_HALF_Y, CONF_HALF_W, CONF_HALF_H, DEFAULT_ROI_HALF,
    CONF_FULL_X, CONF_FULL_Y, CONF_FULL_W, CONF_FULL_H, DEFAULT_ROI_FULL
)

from .controller import WaterHeaterController
# 这里的 import 需要指向 water_heater.py 里的类，
# 如果出现循环引用，建议把 OCRCoordinator 单独拆分到一个 coordinator.py 文件里。
# 暂时保持简单，在函数内部 import 或直接 import
from .water_heater import OCRCoordinator 

PLATFORMS: list[Platform] = [Platform.WATER_HEATER]

# 工厂函数 (原本在 water_heater.py 里的)
def _create_processors(config):
    from .ocr_processor import OCRProcessor
    from .mode_processor import ModeProcessor
    ocr_roi = (config.get(CONF_OCR_X, DEFAULT_ROI_OCR[0]), config.get(CONF_OCR_Y, DEFAULT_ROI_OCR[1]), config.get(CONF_OCR_W, DEFAULT_ROI_OCR[2]), config.get(CONF_OCR_H, DEFAULT_ROI_OCR[3]))
    panel_roi = (config.get(CONF_PANEL_X, DEFAULT_ROI_PANEL[0]), config.get(CONF_PANEL_Y, DEFAULT_ROI_PANEL[1]), config.get(CONF_PANEL_W, DEFAULT_ROI_PANEL[2]), config.get(CONF_PANEL_H, DEFAULT_ROI_PANEL[3]))
    skew = config.get(CONF_SKEW, DEFAULT_SKEW)
    gamma = config.get(CONF_GAMMA, DEFAULT_GAMMA)
    ocr_p = OCRProcessor()
    ocr_p.configure(roi=ocr_roi, skew=skew)
    mode_rois = {
        "setting": (config.get(CONF_SET_X, DEFAULT_ROI_SETTING[0]), config.get(CONF_SET_Y, DEFAULT_ROI_SETTING[1]), config.get(CONF_SET_W, DEFAULT_ROI_SETTING[2]), config.get(CONF_SET_H, DEFAULT_ROI_SETTING[3])),
        "low":     (config.get(CONF_LOW_X, DEFAULT_ROI_LOW[0]), config.get(CONF_LOW_Y, DEFAULT_ROI_LOW[1]), config.get(CONF_LOW_W, DEFAULT_ROI_LOW[2]), config.get(CONF_LOW_H, DEFAULT_ROI_LOW[3])),
        "half":    (config.get(CONF_HALF_X, DEFAULT_ROI_HALF[0]), config.get(CONF_HALF_Y, DEFAULT_ROI_HALF[1]), config.get(CONF_HALF_W, DEFAULT_ROI_HALF[2]), config.get(CONF_HALF_H, DEFAULT_ROI_HALF[3])),
        "full":    (config.get(CONF_FULL_X, DEFAULT_ROI_FULL[0]), config.get(CONF_FULL_Y, DEFAULT_ROI_FULL[1]), config.get(CONF_FULL_W, DEFAULT_ROI_FULL[2]), config.get(CONF_FULL_H, DEFAULT_ROI_FULL[3]))
    }
    mode_p = ModeProcessor()
    mode_p.configure(panel_roi=panel_roi, sub_rois=mode_rois, ocr_roi=ocr_roi, gamma=gamma)
    return ocr_p, mode_p

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OCR Water Heater from a config entry."""
    config = {**entry.data, **entry.options}
    url = config.get(CONF_IMAGE_URL)
    interval = config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    debug = config.get(CONF_DEBUG_MODE, DEFAULT_DEBUG_MODE)

    # 1. 创建处理器
    ocr_p, mode_p = await hass.async_add_executor_job(_create_processors, config)
    
    # 2. 创建控制器
    controller = WaterHeaterController(hass, config)

    # 3. 创建 Coordinator
    coordinator = OCRCoordinator(hass, ocr_p, mode_p, controller, url, interval, debug)
    
    # 4. 首次刷新
    await coordinator.async_config_entry_first_refresh()

    # 5. 存入 Runtime Data (Bronze Requirement)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)