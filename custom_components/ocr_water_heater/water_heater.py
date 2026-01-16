"""Water Heater platform for OCR integration."""
from __future__ import annotations

import logging
import asyncio
import time
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
    CONF_OCR_X, CONF_OCR_Y, CONF_OCR_W, CONF_OCR_H, DEFAULT_ROI_OCR,
    CONF_PANEL_X, CONF_PANEL_Y, CONF_PANEL_W, CONF_PANEL_H, DEFAULT_ROI_PANEL,
    CONF_SET_X, CONF_SET_Y, CONF_SET_W, CONF_SET_H, DEFAULT_ROI_SETTING,
    CONF_LOW_X, CONF_LOW_Y, CONF_LOW_W, CONF_LOW_H, DEFAULT_ROI_LOW,
    CONF_HALF_X, CONF_HALF_Y, CONF_HALF_W, CONF_HALF_H, DEFAULT_ROI_HALF,
    CONF_FULL_X, CONF_FULL_Y, CONF_FULL_W, CONF_FULL_H, DEFAULT_ROI_FULL,
    CONF_GAMMA, DEFAULT_GAMMA, DEFAULT_NOISE_LIMIT,
    VALID_MIN, VALID_MAX,
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_STANDBY, MODE_SETTING, MODE_OFF
)

from .controller import WaterHeaterController

if TYPE_CHECKING:
    from .ocr_processor import OCRProcessor
    from .mode_processor import ModeProcessor

_LOGGER = logging.getLogger(__name__)

# 网络错误/未知错误的容错次数 (保持数据不变)
MAX_FAIL_TOLERANCE = 20

# 关机确认阈值 (次)
OFF_CONFIRM_COUNT = 3

# 主动操作防抖 (HA -> Device)
ACTIVE_DEBOUNCE_SECONDS = 5.0 

# 设置模式闪烁免疫时间 (秒)
# 只要最近 N 秒内出现过“正在设置”模式，即使屏幕全黑(OCR读不到温度)，
# 也认为是闪烁，不判定为关机。
SETTING_BLINK_IMMUNITY_TIME = 5.0

def _create_processors(config):
    from .ocr_processor import OCRProcessor
    from .mode_processor import ModeProcessor

    ocr_roi = (
        config.get(CONF_OCR_X, DEFAULT_ROI_OCR[0]),
        config.get(CONF_OCR_Y, DEFAULT_ROI_OCR[1]),
        config.get(CONF_OCR_W, DEFAULT_ROI_OCR[2]),
        config.get(CONF_OCR_H, DEFAULT_ROI_OCR[3])
    )
    
    panel_roi = (
        config.get(CONF_PANEL_X, DEFAULT_ROI_PANEL[0]),
        config.get(CONF_PANEL_Y, DEFAULT_ROI_PANEL[1]),
        config.get(CONF_PANEL_W, DEFAULT_ROI_PANEL[2]),
        config.get(CONF_PANEL_H, DEFAULT_ROI_PANEL[3])
    )

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
    
    controller = WaterHeaterController(hass, config)

    coordinator = OCRCoordinator(
        hass, ocr_processor, mode_processor, url, update_interval, debug_mode
    )

    await coordinator.async_config_entry_first_refresh()
    async_add_entities([OCRWaterHeaterEntity(coordinator, entry.title, controller, update_interval)])
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
        self._off_count = 0 
        
        # 记录最近一次“正在设置”模式出现的时间 (用于闪烁免疫)
        self._last_setting_active_time = 0.0

    async def _async_update_data(self) -> dict[str, Any] | None:
        max_retries = 5
        current_time = time.time()

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

                # === 核心逻辑修改 ===

                if temp_result is not None:
                    # 1. 成功识别到温度 -> 肯定是开机
                    final_mode = mode_result if mode_result else MODE_STANDBY
                    
                    # 更新闪烁免疫计时器
                    if final_mode == MODE_SETTING:
                        self._last_setting_active_time = current_time

                    current_data = {"temp": temp_result, "mode": final_mode}
                    
                    self._last_valid_data = current_data
                    self._fail_count = 0
                    self._off_count = 0 
                    return current_data
                
                else:
                    # 2. 没识别到温度 (Temp=None) -> 可能是关机，也可能是闪烁
                    
                    # 检查：是否处于“设置模式闪烁免疫期”？
                    # 如果最近 5秒 内都在设置模式，那现在的 Temp=None 八成是图标闪灭造成的
                    if (current_time - self._last_setting_active_time) < SETTING_BLINK_IMMUNITY_TIME:
                        # 触发免疫：忽略这次“关机信号”，强制保持上一次状态
                        self._off_count = 0 # 重置计数，避免累积
                        return self._last_valid_data if self._last_valid_data else None

                    # 正常逻辑：累积关机计数
                    self._off_count += 1
                    
                    if self._off_count >= OFF_CONFIRM_COUNT:
                        # 真的关机了
                        off_data = {"temp": None, "mode": STATE_OFF}
                        self._last_valid_data = off_data
                        self._fail_count = 0 
                        return off_data
                    else:
                        # 还没确认关机，保持上一次状态
                        return self._last_valid_data if self._last_valid_data else None

            except Exception as err:
                self._fail_count += 1
                if attempt < max_retries: 
                    await asyncio.sleep(1)
                elif self._fail_count <= MAX_FAIL_TOLERANCE:
                    return self._last_valid_data if self._last_valid_data else None
                else:
                    raise UpdateFailed(f"Failed: {err}")

class OCRWaterHeaterEntity(CoordinatorEntity[OCRCoordinator], WaterHeaterEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (WaterHeaterEntityFeature.TARGET_TEMPERATURE | WaterHeaterEntityFeature.OPERATION_MODE)
    _attr_operation_list = [MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_SETTING, MODE_STANDBY, STATE_OFF]
    _attr_precision = PRECISION_WHOLE
    _attr_has_entity_name = True
    _attr_name = None
    _attr_target_temperature_step = 1

    def __init__(self, coordinator: OCRCoordinator, device_name: str, controller: WaterHeaterController, interval: int) -> None:
        super().__init__(coordinator)
        self._controller = controller
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
        self._attr_current_temperature = None
        self._exit_debounce_time = (interval * 2.5) / 1000.0
        
        self._last_active_time = 0.0
        self._last_setting_seen_time = 0.0
        self._display_mode = MODE_STANDBY 

    @property
    def current_operation(self) -> str:
        return self._display_mode

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if not data:
            super()._handle_coordinator_update()
            return

        raw_val = data.get("temp")
        raw_mode = data.get("mode")

        if raw_mode == STATE_OFF:
            self._display_mode = STATE_OFF
            self._attr_current_temperature = None
            super()._handle_coordinator_update()
            return

        # 防御：开机状态下 temp 不能为 None (coordinator 应该已经处理过了，这里是双保险)
        if raw_val is None:
            return

        current_time = time.time()

        if raw_mode == MODE_SETTING:
            self._last_setting_seen_time = current_time

        # 动态防抖期判断
        time_since_setting = current_time - self._last_setting_seen_time
        in_setting_debounce = (raw_mode != MODE_SETTING) and (time_since_setting < self._exit_debounce_time)

        if raw_mode == MODE_SETTING:
            self._display_mode = MODE_SETTING
            # 只有当用户没有操作时，才同步目标温度
            if (current_time - self._last_active_time) > ACTIVE_DEBOUNCE_SECONDS:
                self._attr_target_temperature = raw_val
            
        elif in_setting_debounce:
            # 防抖期：保持设置模式，但【冻结数值】，不更新目标温度
            self._display_mode = MODE_SETTING
        
        else:
            self._display_mode = raw_mode
            self._attr_current_temperature = raw_val
            
        super()._handle_coordinator_update()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None: return

        old_value = self._attr_target_temperature
        self._last_active_time = time.time()
        self._attr_target_temperature = temp
        
        self._display_mode = MODE_SETTING
        self._last_setting_seen_time = time.time()

        self.async_write_ha_state()
        _LOGGER.info(f"主动模式: 用户设置目标温度为 {temp}°C")

        try:
            await self._controller.async_set_temperature(temp)
        except Exception as e:
            _LOGGER.error(f"主动模式: Controller调用失败: {e}")
            _LOGGER.warning(f"主动模式: 回滚目标温度 {temp} -> {old_value}")
            self._attr_target_temperature = old_value
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        self.async_write_ha_state()