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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
    UpdateFailed,
)
from homeassistant.helpers import aiohttp_client

from .const import (
    DOMAIN,
    CONF_IMAGE_URL,
    CONF_ROI_X, CONF_ROI_Y, CONF_ROI_W, CONF_ROI_H, CONF_SKEW,
    CONF_UPDATE_INTERVAL, CONF_DEBUG_MODE,
    DEFAULT_ROI, DEFAULT_SKEW, 
    DEFAULT_UPDATE_INTERVAL, DEFAULT_DEBUG_MODE,
    VALID_MIN, VALID_MAX,
    STATE_PERFORMANCE,
)

if TYPE_CHECKING:
    from .ocr_processor import OCRProcessor

_LOGGER = logging.getLogger(__name__)

def _create_processor_instance(roi, skew, debug_mode):
    from .ocr_processor import OCRProcessor
    processor = OCRProcessor()
    # 传递 debug_mode
    processor.configure(roi=roi, skew=skew, debug_mode=debug_mode)
    return processor

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OCR water heater."""
    
    # 1. 合并配置: Options 里的设置 覆盖 Data (初始设置)
    config = {**entry.data, **entry.options}

    url = config.get(CONF_IMAGE_URL)
    update_interval = config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    debug_mode = config.get(CONF_DEBUG_MODE, DEFAULT_DEBUG_MODE)

    roi_x = config.get(CONF_ROI_X, DEFAULT_ROI[0])
    roi_y = config.get(CONF_ROI_Y, DEFAULT_ROI[1])
    roi_w = config.get(CONF_ROI_W, DEFAULT_ROI[2])
    roi_h = config.get(CONF_ROI_H, DEFAULT_ROI[3])
    roi = (roi_x, roi_y, roi_w, roi_h)

    skew = config.get(CONF_SKEW, DEFAULT_SKEW)

    # 2. 初始化 Processor
    processor = await hass.async_add_executor_job(
        _create_processor_instance, roi, skew, debug_mode
    )

    # 3. 初始化 Coordinator
    coordinator = OCRCoordinator(hass, processor, url, update_interval)
    
    # 首次刷新
    await coordinator.async_config_entry_first_refresh()

    async_add_entities([OCRWaterHeaterEntity(coordinator, entry.title)])
    
    # 4. 监听更新: 当用户点击 Configure 修改参数时，触发重载
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


class OCRCoordinator(DataUpdateCoordinator[int | None]):
    """Class to manage fetching OCR data."""

    def __init__(self, hass: HomeAssistant, processor: OCRProcessor, url: str, interval: int):
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name="OCR Water Heater",
            update_interval=timedelta(seconds=interval),
        )
        self.processor = processor
        self.url = url
        self.session = aiohttp_client.async_get_clientsession(hass)

    async def _async_update_data(self) -> int | None:
        """Fetch data from URL and run OCR (With Retry Logic)."""
        max_retries = 3
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                async with self.session.get(self.url, timeout=5) as response:
                    if response.status != 200:
                        msg = f"Fetching image failed, status: {response.status}"
                        if attempt == 1: _LOGGER.debug(msg) # 只在第一次打日志避免刷屏
                        last_error = Exception(msg)
                        if attempt < max_retries:
                            await asyncio.sleep(1)
                            continue
                        else:
                            raise UpdateFailed(msg)
                    
                    content = await response.read()

                temperature = await self.hass.async_add_executor_job(
                    self.processor.process_image, content
                )

                if temperature is None:
                    _LOGGER.debug("OCR returned None (recognition failed)")
                    return None

                return temperature

            except Exception as err:
                last_error = err
                if attempt == 1: _LOGGER.debug(f"Connection error: {err}")
                if attempt < max_retries:
                    await asyncio.sleep(1)
                else:
                    raise UpdateFailed(f"Failed to fetch image: {last_error}")


class OCRWaterHeaterEntity(CoordinatorEntity[OCRCoordinator], WaterHeaterEntity):
    """Representation of an OCR Water Heater."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE |
        WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_operation_list = [STATE_PERFORMANCE, STATE_OFF]
    _attr_precision = PRECISION_WHOLE
    _attr_has_entity_name = True 
    _attr_name = None 

    def __init__(self, coordinator: OCRCoordinator, device_name: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"ocr_wh_{coordinator.url}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.url)},
            "name": device_name,
            "manufacturer": "OCR Integration",
            "model": "Camera OCR",
        }
        self._attr_target_temperature = 50
        self._attr_min_temp = VALID_MIN
        self._attr_max_temp = VALID_MAX

    @property
    def current_operation(self) -> str:
        if self.coordinator.data is not None:
            return STATE_PERFORMANCE
        return STATE_OFF

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temp
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        self.async_write_ha_state()