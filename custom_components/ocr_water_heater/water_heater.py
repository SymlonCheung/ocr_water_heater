"""Water Heater platform for OCR integration."""
from __future__ import annotations

import logging
import asyncio
from typing import Any, TYPE_CHECKING
from datetime import timedelta

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_WHOLE,
    UnitOfTemperature,
    STATE_OFF,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
    UpdateFailed,
)
from homeassistant.helpers import aiohttp_client

from .const import (
    DOMAIN,
    CONF_IMAGE_URL, CONF_UPDATE_INTERVAL, CONF_DEBUG_MODE, CONF_SKEW,
    DEFAULT_UPDATE_INTERVAL, DEFAULT_DEBUG_MODE, DEFAULT_SKEW,
    CONF_PANEL_X, CONF_PANEL_Y, CONF_PANEL_W, CONF_PANEL_H, DEFAULT_ROI_PANEL,
    CONF_OCR_X, CONF_OCR_Y, CONF_OCR_W, CONF_OCR_H, DEFAULT_ROI_OCR,
    CONF_SET_X, CONF_SET_Y, CONF_SET_W, CONF_SET_H, DEFAULT_ROI_SETTING,
    CONF_LOW_X, CONF_LOW_Y, CONF_LOW_W, CONF_LOW_H, DEFAULT_ROI_LOW,
    CONF_HALF_X, CONF_HALF_Y, CONF_HALF_W, CONF_HALF_H, DEFAULT_ROI_HALF,
    CONF_FULL_X, CONF_FULL_Y, CONF_FULL_W, CONF_FULL_H, DEFAULT_ROI_FULL,
    VALID_MIN, VALID_MAX,
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_STANDBY, MODE_SETTING, MODE_OFF
)

if TYPE_CHECKING:
    from .ocr_processor import OCRProcessor
    from .mode_processor import ModeProcessor

_LOGGER = logging.getLogger(__name__)

# 防抖容错次数
MAX_FAIL_TOLERANCE = 20

def _create_processors(config):
    from .ocr_processor import OCRProcessor
    from .mode_processor import ModeProcessor

    ocr_roi = (
        config.get(CONF_OCR_X, DEFAULT_ROI_OCR[0]),
        config.get(CONF_OCR_Y, DEFAULT_ROI_OCR[1]),
        config.get(CONF_OCR_W, DEFAULT_ROI_OCR[2]),
        config.get(CONF_OCR_H, DEFAULT_ROI_OCR[3])
    )
    
    # 获取 Panel ROI (如果 config 里没有，就用默认值)
    panel_roi = (
        config.get(CONF_PANEL_X, DEFAULT_ROI_PANEL[0]),
        config.get(CONF_PANEL_Y, DEFAULT_ROI_PANEL[1]),
        config.get(CONF_PANEL_W, DEFAULT_ROI_PANEL[2]),
        config.get(CONF_PANEL_H, DEFAULT_ROI_PANEL[3])
    )

    skew = config.get(CONF_SKEW, DEFAULT_SKEW)

    ocr_p = OCRProcessor()
    ocr_p.configure(roi=ocr_roi, skew=skew)

    mode_rois = {
        "setting": (config.get(CONF_SET_X, DEFAULT_ROI_SETTING[0]), config.get(CONF_SET_Y, DEFAULT_ROI_SETTING[1]), config.get(CONF_SET_W, DEFAULT_ROI_SETTING[2]), config.get(CONF_SET_H, DEFAULT_ROI_SETTING[3])),
        "low":     (config.get(CONF_LOW_X, DEFAULT_ROI_LOW[0]), config.get(CONF_LOW_Y, DEFAULT_ROI_LOW[1]), config.get(CONF_LOW_W, DEFAULT_ROI_LOW[2]), config.get(CONF_LOW_H, DEFAULT_ROI_LOW[3])),
        "half":    (config.get(CONF_HALF_X, DEFAULT_ROI_HALF[0]), config.get(CONF_HALF_Y, DEFAULT_ROI_HALF[1]), config.get(CONF_HALF_W, DEFAULT_ROI_HALF[2]), config.get(CONF_HALF_H, DEFAULT_ROI_HALF[3])),
        "full":    (config.get(CONF_FULL_X, DEFAULT_ROI_FULL[0]), config.get(CONF_FULL_Y, DEFAULT_ROI_FULL[1]), config.get(CONF_FULL_W, DEFAULT_ROI_FULL[2]), config.get(CONF_FULL_H, DEFAULT_ROI_FULL[3]))
    }

    mode_p = ModeProcessor()
    # 注意这里传参变了：加入了 panel_roi 和 ocr_roi
    mode_p.configure(panel_roi=panel_roi, sub_rois=mode_rois, ocr_roi=ocr_roi)

    return ocr_p, mode_p

def _save_debug_job(result_str, images):
    from .debug_storage import save_debug_record
    save_debug_record(result_str, images)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    config = {**entry.data, **entry.options}
    
    url = config.get(CONF_IMAGE_URL)
    update_interval = config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    debug_mode = config.get(CONF_DEBUG_MODE, DEFAULT_DEBUG_MODE)

    ocr_processor, mode_processor = await hass.async_add_executor_job(
        _create_processors, config
    )

    coordinator = OCRCoordinator(
        hass, ocr_processor, mode_processor, url, update_interval, debug_mode
    )

    await coordinator.async_config_entry_first_refresh()
    async_add_entities([OCRWaterHeaterEntity(coordinator, entry.title)])
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

class OCRCoordinator(DataUpdateCoordinator[dict[str, Any] | None]):
    def __init__(self, hass: HomeAssistant, ocr_processor: OCRProcessor, mode_processor: ModeProcessor, url: str, interval: int, debug_mode: bool):
        super().__init__(
            hass, _LOGGER, name="OCR Water Heater",
            update_interval=timedelta(milliseconds=interval),
        )
        self.ocr_processor = ocr_processor
        self.mode_processor = mode_processor
        self.url = url
        self.debug_mode = debug_mode
        self.session = aiohttp_client.async_get_clientsession(hass)
        self._last_valid_data = None
        self._fail_count = 0

    async def _async_update_data(self) -> dict[str, Any] | None:
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                async with self.session.get(self.url, timeout=10) as response:
                    if response.status != 200:
                        if attempt < max_retries: await asyncio.sleep(1); continue
                        raise UpdateFailed(f"Fetching image failed: {response.status}")
                    content = await response.read()

                def _process_job():
                    temp_val, temp_imgs = self.ocr_processor.process_image(content)
                    mode_val, mode_imgs = self.mode_processor.process(content)
                    return temp_val, mode_val, {**temp_imgs, **mode_imgs}

                temp_result, mode_result, all_debug_imgs = await self.hass.async_add_executor_job(_process_job)

                if self.debug_mode and all_debug_imgs:
                    res_str = f"T_{temp_result}_M_{mode_result}"
                    await self.hass.async_add_executor_job(_save_debug_job, res_str, all_debug_imgs)

                # 核心逻辑
                if temp_result is not None:
                    final_mode = mode_result if mode_result else MODE_STANDBY
                    current_data = {"temp": temp_result, "mode": final_mode}
                    
                    self._last_valid_data = current_data
                    self._fail_count = 0
                    return current_data
                else:
                    self._fail_count += 1
                    if self._fail_count <= MAX_FAIL_TOLERANCE:
                        return self._last_valid_data if self._last_valid_data else None
                    else:
                        self._last_valid_data = None
                        return None

            except Exception as err:
                if attempt < max_retries: await asyncio.sleep(1)
                else: raise UpdateFailed(f"Failed: {err}")

class OCRWaterHeaterEntity(CoordinatorEntity[OCRCoordinator], WaterHeaterEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (WaterHeaterEntityFeature.TARGET_TEMPERATURE | WaterHeaterEntityFeature.OPERATION_MODE)
    _attr_operation_list = [MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_SETTING, MODE_STANDBY, STATE_OFF]
    _attr_precision = PRECISION_WHOLE
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: OCRCoordinator, device_name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ocr_wh_{coordinator.url}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.url)},
            "name": device_name,
            "manufacturer": "OCR Integration",
            "model": "Camera OCR Dual Processor",
        }
        self._attr_target_temperature = 50
        self._attr_min_temp = VALID_MIN
        self._attr_max_temp = VALID_MAX
        
        # 【修改】初始化当前温度为 None，改用 _attr 变量存储，不再使用 @property 动态获取
        self._attr_current_temperature = None

    @property
    def current_operation(self) -> str:
        data = self.coordinator.data
        if data is None: return STATE_OFF
        return data.get("mode", MODE_STANDBY)

    # 【修改】删除了 @property def current_temperature ...
    # WaterHeaterEntity 默认会读取 self._attr_current_temperature
    # 这样我们就可以在 update 回调中控制它的更新逻辑

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.data
        if data and data.get("temp"):
            ocr_val = data.get("temp")
            mode = data.get("mode")

            if mode == MODE_SETTING:
                # 【场景 A】正在设置：
                # OCR 读到的是目标温度，更新 target_temperature
                self._attr_target_temperature = ocr_val
                # ！！！重点：_attr_current_temperature 保持不变 (维持上一次的真实水温)
            else:
                # 【场景 B】正常运行：
                # OCR 读到的是实际水温，更新 current_temperature
                self._attr_current_temperature = ocr_val
            
        super()._handle_coordinator_update()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temp
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        self.async_write_ha_state()