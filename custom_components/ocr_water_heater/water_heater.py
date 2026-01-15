"""Water Heater platform for OCR integration."""
from __future__ import annotations

import logging
import asyncio # 【新增】用于重试等待
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
    CONF_UPDATE_INTERVAL,    # <--- 导入 Key
    DEFAULT_ROI, DEFAULT_SKEW, 
    DEFAULT_UPDATE_INTERVAL, # <--- 导入 Default
    VALID_MIN, VALID_MAX,
    STATE_PERFORMANCE,
)

if TYPE_CHECKING:
    from .ocr_processor import OCRProcessor

_LOGGER = logging.getLogger(__name__)

def _create_processor_instance(roi, skew):
    from .ocr_processor import OCRProcessor
    processor = OCRProcessor()
    processor.configure(roi=roi, skew=skew)
    return processor

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OCR water heater."""
    
    url = entry.data.get(CONF_IMAGE_URL)
    update_interval = entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    roi_x = entry.data.get(CONF_ROI_X, DEFAULT_ROI[0])
    roi_y = entry.data.get(CONF_ROI_Y, DEFAULT_ROI[1])
    roi_w = entry.data.get(CONF_ROI_W, DEFAULT_ROI[2])
    roi_h = entry.data.get(CONF_ROI_H, DEFAULT_ROI[3])
    roi = (roi_x, roi_y, roi_w, roi_h)

    skew = entry.data.get(CONF_SKEW, DEFAULT_SKEW)

    processor = await hass.async_add_executor_job(
        _create_processor_instance, roi, skew
    )

    coordinator = OCRCoordinator(hass, processor, url, update_interval)
    
    # 首次刷新数据
    await coordinator.async_config_entry_first_refresh()

    async_add_entities([OCRWaterHeaterEntity(coordinator, entry.title)])


class OCRCoordinator(DataUpdateCoordinator[int | None]):
    """Class to manage fetching OCR data."""

    def __init__(self, hass: HomeAssistant, processor: OCRProcessor, url: str, interval: int):
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name="OCR Water Heater",
            # 使用传入的时间
            update_interval=timedelta(seconds=interval),
        )
        self.processor = processor
        self.url = url
        self.session = aiohttp_client.async_get_clientsession(hass)

    async def _async_update_data(self) -> int | None:
        """Fetch data from URL and run OCR (With Retry Logic)."""
        
        # 【修改】重试机制：最多尝试 3 次
        max_retries = 3
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                # 设置较短的 timeout，防止卡住
                async with self.session.get(self.url, timeout=5) as response:
                    # 如果状态码不是 200，记录错误并重试
                    if response.status != 200:
                        msg = f"Fetching image failed, status: {response.status}"
                        _LOGGER.debug(f"Attempt {attempt}/{max_retries}: {msg}")
                        last_error = Exception(msg)
                        # 如果不是最后一次尝试，等待 1 秒后重试
                        if attempt < max_retries:
                            await asyncio.sleep(1)
                            continue
                        else:
                            # 最后一次也失败，抛出异常
                            raise UpdateFailed(msg)
                    
                    # 读取图片成功
                    content = await response.read()

                # 图片获取成功，跳出重试循环，进行 OCR 处理
                # 在 Executor 中运行 CPU 密集型 OCR 任务
                temperature = await self.hass.async_add_executor_job(
                    self.processor.process_image, content
                )

                if temperature is None:
                    _LOGGER.debug("OCR returned None (recognition failed)")
                    # 返回 None，Entity 会据此判断为“关闭”
                    return None

                return temperature

            except Exception as err:
                last_error = err
                _LOGGER.debug(f"Attempt {attempt}/{max_retries} connection error: {err}")
                if attempt < max_retries:
                    await asyncio.sleep(1)
                else:
                    # 3 次都失败了，抛出异常给 HA（此时会在日志显示 ERROR）
                    raise UpdateFailed(f"Failed to fetch image after {max_retries} attempts: {last_error}")


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

        # 初始目标温度
        self._attr_target_temperature = 50
        
        self._attr_min_temp = VALID_MIN
        self._attr_max_temp = VALID_MAX

    @property
    def current_operation(self) -> str:
        """Return current operation based on OCR result."""
        # 【修改】逻辑：如果有数据，就是 Performance；如果是 None，就是 Off
        if self.coordinator.data is not None:
            return STATE_PERFORMANCE
        return STATE_OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        # 如果 coordinator.data 是 None (Off)，这里也返回 None
        return self.coordinator.data

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temp
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set new target operation mode."""
        # 注意：因为 operation_mode 现在是完全由 OCR 结果驱动的
        # 用户手动设置模式其实没有意义，会在下一次更新时被覆盖。
        # 这里保留代码是为了不报错，但实际由 OCR 决定状态。
        if operation_mode in self.operation_list:
            # 可以在这里加逻辑，比如暂停 OCR 更新，或者手动 Override，
            # 但根据你的需求，这里暂时不做特殊处理。
            self.async_write_ha_state()