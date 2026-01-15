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
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_STANDBY, MODE_OFF
)

if TYPE_CHECKING:
    from .ocr_processor import OCRProcessor
    from .mode_processor import ModeProcessor

_LOGGER = logging.getLogger(__name__)

# 【新增】防抖容错次数
# 假设更新频率是 500ms，设置为 20 次意味着：
# 只有连续识别失败超过 10秒 (20 * 0.5)，才认为是真关机。
MAX_FAIL_TOLERANCE = 5

# 工厂函数：创建处理器
def _create_processors(roi, skew):
    from .ocr_processor import OCRProcessor
    from .mode_processor import ModeProcessor
    
    ocr_p = OCRProcessor()
    ocr_p.configure(roi=roi, skew=skew)
    
    mode_p = ModeProcessor()
    
    return ocr_p, mode_p

# 包装保存图片的函数，以便放入 executor
def _save_debug_job(result_str, images):
    from .debug_storage import save_debug_record
    # 这里我们把 result 改为一个字符串描述，例如 "Temp_50_Mode_Full"
    save_debug_record(result_str, images)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OCR water heater."""

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

    # 在 executor 中初始化两个处理器
    ocr_processor, mode_processor = await hass.async_add_executor_job(
        _create_processors, roi, skew
    )

    coordinator = OCRCoordinator(
        hass, 
        ocr_processor, 
        mode_processor, 
        url, 
        update_interval, 
        debug_mode
    )

    await coordinator.async_config_entry_first_refresh()

    async_add_entities([OCRWaterHeaterEntity(coordinator, entry.title)])
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)

class OCRCoordinator(DataUpdateCoordinator[dict[str, Any] | None]):
    """Class to manage fetching OCR data."""

    def __init__(
        self, 
        hass: HomeAssistant, 
        ocr_processor: OCRProcessor, 
        mode_processor: ModeProcessor,
        url: str, 
        interval: int, 
        debug_mode: bool
    ):
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name="OCR Water Heater",
            # 注意：这里使用 milliseconds，因为你在 const.py 里把默认值改大了
            update_interval=timedelta(milliseconds=interval),
        )
        self.ocr_processor = ocr_processor
        self.mode_processor = mode_processor
        self.url = url
        self.debug_mode = debug_mode
        self.session = aiohttp_client.async_get_clientsession(hass)

        # 【新增】状态缓存和计数器
        self._last_valid_data: dict[str, Any] | None = None
        self._fail_count = 0

    async def _async_update_data(self) -> dict[str, Any] | None:
        """Fetch data and run OCR + Mode Detection."""
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                # 考虑到弱网环境，超时给足 10 秒
                async with self.session.get(self.url, timeout=10) as response:
                    if response.status != 200:
                        msg = f"Fetching image failed: {response.status}"
                        if attempt == 1: _LOGGER.debug(msg)
                        if attempt < max_retries:
                            await asyncio.sleep(1)
                            continue
                        raise UpdateFailed(msg)
                    content = await response.read()

                # 在 Executor 中运行 OCR 和 Mode 识别
                # 定义一个内部函数来同时运行两个
                def _process_job():
                    # 1. OCR (Temp)
                    temp_val, temp_imgs = self.ocr_processor.process_image(content)
                    # 2. Mode
                    mode_val, mode_imgs = self.mode_processor.process(content)
                    
                    # 合并 Debug 图片
                    all_imgs = {**temp_imgs, **mode_imgs}
                    return temp_val, mode_val, all_imgs

                temp_result, mode_result, all_debug_imgs = await self.hass.async_add_executor_job(
                    _process_job
                )

                # 处理保存 Debug 逻辑
                if self.debug_mode and all_debug_imgs:
                    # 构造结果字符串用于文件夹命名
                    res_str = f"T_{temp_result}_M_{mode_result}"
                    await self.hass.async_add_executor_job(
                        _save_debug_job, res_str, all_debug_imgs
                    )

                # =========================================================
                # 【核心修改：防抖逻辑】
                # =========================================================
                
                # 1. 判断本次识别是否有效 (只要温度识别出来就算有效)
                if temp_result is not None:
                    # 如果 mode 没识别出来，默认给待机
                    final_mode = mode_result if mode_result else MODE_STANDBY
                    
                    current_data = {
                        "temp": temp_result,
                        "mode": final_mode
                    }
                    
                    # 【成功】：更新缓存，重置计数器
                    self._last_valid_data = current_data
                    self._fail_count = 0
                    return current_data
                
                else:
                    # 【失败】：可能是真关机，也可能是闪烁/OCR失败
                    self._fail_count += 1
                    
                    # 2. 检查是否在容忍范围内
                    if self._fail_count <= MAX_FAIL_TOLERANCE:
                        if self._last_valid_data is not None:
                            # _LOGGER.debug("Using cached data due to blink/glitch.")
                            # 返回上一次的数据，假装一切正常
                            return self._last_valid_data
                        else:
                            # 刚启动 HA 就识别失败，无缓存可用
                            return None
                    else:
                        # 3. 超过容忍次数，判定为真关机
                        # _LOGGER.debug("Fail limit reached. Setting state to OFF.")
                        self._last_valid_data = None # 清空缓存
                        return None

            except Exception as err:
                if attempt == 1: _LOGGER.debug(f"Connection error: {err}")
                if attempt < max_retries:
                    await asyncio.sleep(1)
                else:
                    raise UpdateFailed(f"Failed: {err}")

class OCRWaterHeaterEntity(CoordinatorEntity[OCRCoordinator], WaterHeaterEntity):
    """Representation of an OCR Water Heater."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE |
        WaterHeaterEntityFeature.OPERATION_MODE
    )
    # 定义操作模式列表
    _attr_operation_list = [
        MODE_LOW_POWER,
        MODE_HALF,
        MODE_FULL,
        MODE_STANDBY,
        STATE_OFF
    ]
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

    @property
    def current_operation(self) -> str:
        """Return current operation ie. heat, cool, idle."""
        data = self.coordinator.data
        
        # 1. 如果没有数据 (None)，视为 OFF
        if data is None:
            return STATE_OFF
        
        # 2. 如果有数据，读取 mode
        # mode 只会是: MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_STANDBY
        return data.get("mode", MODE_STANDBY)

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.get("temp")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temp
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set new target operation mode."""
        # OCR 是只读的，这里只能在 HA 界面上假装改变状态，或者留空
        # 如果你想记录用户期望的模式，可以保存到 self._attr_current_operation 
        # 但因为是 polling，会被下一次 update 覆盖
        self.async_write_ha_state()