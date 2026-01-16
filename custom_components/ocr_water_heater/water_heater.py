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
    CONF_GAMMA, DEFAULT_GAMMA,
    VALID_MIN, VALID_MAX,
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_STANDBY, MODE_SETTING, MODE_OFF
)

from .controller import WaterHeaterController

if TYPE_CHECKING:
    from .ocr_processor import OCRProcessor
    from .mode_processor import ModeProcessor

_LOGGER = logging.getLogger(__name__)

# --- 调优参数 ---
MAX_FAIL_TOLERANCE = 20
# 提高关机确认次数，防止闪烁导致误判关机 (1000ms间隔下，8次约等于8秒)
OFF_CONFIRM_COUNT = 8 
# 主动控制后的防抖时间
ACTIVE_DEBOUNCE_SECONDS = 8.0 
# 激活后的同步等待时间
SYNC_WAIT_TIME = 4.0 
# "正在设置"模式的强效保持时间 (无敌帧)
SETTING_BRIDGE_TIME = 8.0 
# 开机保护期
BOOT_GRACE_PERIOD = 10.0 

MODE_ORDER = [MODE_LOW_POWER, MODE_HALF, MODE_FULL]

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

def _save_debug_job(result_str, images):
    from .debug_storage import save_debug_record
    save_debug_record(result_str, images)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    config = {**entry.data, **entry.options}
    url = config.get(CONF_IMAGE_URL)
    interval = config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    debug = config.get(CONF_DEBUG_MODE, DEFAULT_DEBUG_MODE)
    ocr_p, mode_p = await hass.async_add_executor_job(_create_processors, config)
    controller = WaterHeaterController(hass, config)
    coord = OCRCoordinator(hass, ocr_p, mode_p, url, interval, debug)
    await coord.async_config_entry_first_refresh()
    async_add_entities([OCRWaterHeaterEntity(coord, entry.title, controller, interval)])
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

class OCRCoordinator(DataUpdateCoordinator[dict[str, Any] | None]):
    def __init__(self, hass, ocr_processor, mode_processor, url, interval, debug_mode):
        super().__init__(hass, _LOGGER, name="OCR Water Heater", update_interval=timedelta(milliseconds=interval))
        self.ocr_p = ocr_processor
        self.mode_p = mode_processor
        self.url = url
        self.debug_mode = debug_mode
        self.session = aiohttp_client.async_get_clientsession(hass)
        
        self._last_valid_data = {"temp": 50, "mode": STATE_OFF} 
        self._fail_count = 0
        self._off_count = 0
        self._last_setting_active_time = 0.0
        
        self.expect_on = False
        self.last_on_command_time = 0.0
        self.is_confirmed_off = True

    def notify_turned_on(self):
        self.expect_on = True
        self.last_on_command_time = time.time()
        self.is_confirmed_off = False
        self._off_count = 0

    async def _async_update_data(self) -> dict[str, Any] | None:
        current_time = time.time()
        
        try:
            async with self.session.get(self.url, timeout=10) as resp:
                if resp.status != 200: raise UpdateFailed(f"HTTP {resp.status}")
                content = await resp.read()
        except Exception as e:
            raise UpdateFailed(f"Connection error: {e}")

        def _process():
            t_val, t_imgs = self.ocr_p.process_image(content)
            m_res, m_imgs = self.mode_p.process(content)
            return t_val, m_res, {**t_imgs, **m_imgs}
        
        temp_res, mode_res, debug_imgs = await self.hass.async_add_executor_job(_process)
        
        if self.debug_mode and debug_imgs:
            await self.hass.async_add_executor_job(_save_debug_job, f"T_{temp_res}_M_{mode_res}", debug_imgs)

        # ---------------------------------------------------------------------
        # 核心状态判定逻辑
        # ---------------------------------------------------------------------

        # 1. 开机保护期：如果刚开机，忽略所有无效数据，直接返回旧数据（避免关机）
        in_boot_grace = self.expect_on and (current_time - self.last_on_command_time < BOOT_GRACE_PERIOD)
        if in_boot_grace and (temp_res is None or mode_res is None):
            return self._last_valid_data

        is_valid_reading = (temp_res is not None)
        
        if is_valid_reading:
            final_mode = mode_res if mode_res else MODE_STANDBY
            
            # 过滤：如果处于“确认关机”状态，突然看到“正在设置”但没有开机动作，视为反光干扰
            if self.is_confirmed_off and not in_boot_grace:
                if final_mode == MODE_SETTING:
                    is_valid_reading = False 
                else:
                    # 如果读到其他模式（低功率等），说明真的亮了
                    self.is_confirmed_off = False
                    self.expect_on = False

            if is_valid_reading:
                # 更新活跃时间
                if final_mode == MODE_SETTING:
                    self._last_setting_active_time = current_time
                
                new_data = {"temp": temp_res, "mode": final_mode}
                self._last_valid_data = new_data
                self._fail_count = 0
                self._off_count = 0
                self.is_confirmed_off = False
                return new_data

        # 2. 读取无效 (Temp=None) 时的处理逻辑
        
        # 保护期内不处理
        if in_boot_grace:
            return self._last_valid_data
        
        # 检查是否处于“正在设置”模式的保持时间内
        was_setting = (self._last_valid_data.get("mode") == MODE_SETTING)
        # 如果是 Setting 模式，给予更长的容忍时间 (8秒)
        # 如果是其他模式，容忍 2 秒
        bridge_time = SETTING_BRIDGE_TIME if was_setting else 2.0

        if (current_time - self._last_setting_active_time) < bridge_time:
            # === 核心修复 ===
            # 在 Bridge 时间内，即使读不到数据，也重置关机计数器，并强制返回上一次的数据。
            # 这保证了调节温度时，中间夹杂的 None/Standby 不会触发关机。
            self._off_count = 0 
            return self._last_valid_data
            
        # 3. 超过保持时间，开始累积关机计数
        self._off_count += 1
        if self._off_count >= OFF_CONFIRM_COUNT:
            self.is_confirmed_off = True
            off_data = {"temp": None, "mode": STATE_OFF}
            self._last_valid_data = off_data
            self._fail_count = 0
            return off_data
        
        # 还没达到关机阈值，返回旧数据（保持状态）
        return self._last_valid_data


class OCRWaterHeaterEntity(CoordinatorEntity[OCRCoordinator], WaterHeaterEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE | 
        WaterHeaterEntityFeature.OPERATION_MODE |
        WaterHeaterEntityFeature.ON_OFF
    )
    _attr_operation_list = [MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_SETTING, MODE_STANDBY, STATE_OFF]
    _attr_precision = PRECISION_WHOLE
    _attr_has_entity_name = True
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
        self._display_mode = STATE_OFF
        
        self._exit_debounce_time = (interval * 2.5) / 1000.0
        self._last_active_time = 0.0
        self._last_setting_seen_time = 0.0

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

        if raw_val is None:
            return

        current_time = time.time()

        if raw_mode == MODE_SETTING:
            self._last_setting_seen_time = current_time
        
        in_setting_debounce = (raw_mode != MODE_SETTING) and \
                              (current_time - self._last_setting_seen_time < self._exit_debounce_time)

        if raw_mode == MODE_SETTING:
            self._display_mode = MODE_SETTING
            # Debounce: 主动操作后一段时间内，不听OCR的旧数据
            if (current_time - self._last_active_time) > ACTIVE_DEBOUNCE_SECONDS:
                self._attr_target_temperature = raw_val

        elif in_setting_debounce:
            self._display_mode = MODE_SETTING
        else:
            self._display_mode = raw_mode
            self._attr_current_temperature = raw_val

        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        _LOGGER.info("Sending Turn On (Toggle)")
        self.coordinator.notify_turned_on()
        
        # 乐观更新
        prev_mode = self._display_mode
        self._display_mode = MODE_LOW_POWER 
        self.async_write_ha_state()

        success = await self._controller.async_toggle_power()
        if not success:
            _LOGGER.error("Failed to turn on. Reverting state.")
            self._display_mode = prev_mode
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        _LOGGER.info("Sending Turn Off (Toggle)")
        
        prev_mode = self._display_mode
        self._display_mode = STATE_OFF
        self.async_write_ha_state()

        success = await self._controller.async_toggle_power()
        if not success:
            _LOGGER.error("Failed to turn off. Reverting state.")
            self._display_mode = prev_mode
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode == STATE_OFF:
            await self.async_turn_off()
            return

        # 记录旧状态用于回滚
        old_mode = self._display_mode

        if self._display_mode == STATE_OFF:
            _LOGGER.info(f"Device is OFF. Turning ON to reach {operation_mode}...")
            self.coordinator.notify_turned_on()
            
            self._display_mode = MODE_LOW_POWER
            self.async_write_ha_state()
            
            if not await self._controller.async_toggle_power():
                _LOGGER.error("开机指令失败，回滚状态")
                self._display_mode = old_mode
                self.async_write_ha_state()
                return

            await asyncio.sleep(2.0) 
            
        if operation_mode in MODE_ORDER:
            current_mode_guess = self._display_mode
            if current_mode_guess not in MODE_ORDER:
                 # 唤醒尝试
                 await self._controller.async_press_mode(1) 
                 return 

            if current_mode_guess in MODE_ORDER and operation_mode in MODE_ORDER:
                curr_idx = MODE_ORDER.index(current_mode_guess)
                target_idx = MODE_ORDER.index(operation_mode)
                clicks = (target_idx - curr_idx) % 3
                if clicks > 0:
                    _LOGGER.info(f"Switching {current_mode_guess} -> {operation_mode} ({clicks} clicks).")
                    
                    self._display_mode = operation_mode
                    self.async_write_ha_state()

                    success = await self._controller.async_press_mode(clicks)
                    if not success:
                        _LOGGER.error(f"模式切换失败，回滚到 {old_mode}")
                        self._display_mode = old_mode
                        self.async_write_ha_state()
            
        elif operation_mode == MODE_STANDBY:
            await self._controller.async_screen_on()
            
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        new_target = kwargs.get(ATTR_TEMPERATURE)
        if new_target is None: return

        self._last_active_time = time.time()
        
        # 保存旧值用于回滚
        old_target = self._attr_target_temperature
        old_mode = self._display_mode
        
        # 立即乐观更新
        self._attr_target_temperature = new_target
        self._display_mode = MODE_SETTING
        self._last_setting_seen_time = time.time()
        self.async_write_ha_state()

        _LOGGER.info(f"智能调节启动: 目标 {new_target}°C")

        # 1. 激活阶段 (如果失败直接回滚)
        if old_mode == MODE_STANDBY:
             _LOGGER.info("-> 待机唤醒...")
             if not await self._controller.async_screen_on():
                 _LOGGER.error("唤醒失败，回滚")
                 self._attr_target_temperature = old_target
                 self._display_mode = old_mode
                 self.async_write_ha_state()
                 return
             await asyncio.sleep(0.8) 

        elif old_mode != MODE_SETTING:
             _LOGGER.info("-> 发送激活点击(UP)并同步...")
             if not await self._controller.async_adjust_temperature(0, need_activation=True):
                 _LOGGER.error("激活点击失败，回滚")
                 self._attr_target_temperature = old_target
                 self._display_mode = old_mode
                 self.async_write_ha_state()
                 return
        else:
             _LOGGER.info("-> 当前已是设置模式，直接计算")

        # 2. 同步等待阶段
        if old_mode != MODE_SETTING:
             _LOGGER.info(f"-> 等待摄像头同步 ({SYNC_WAIT_TIME}s)...")
             await asyncio.sleep(SYNC_WAIT_TIME)
             await self.coordinator.async_request_refresh()

        # 3. 读取 & 计算阶段
        real_device_temp = self.coordinator.data.get("temp")
        start_temp = old_target
        if real_device_temp is not None:
             _LOGGER.info(f"-> 同步后读到设备温度: {real_device_temp}°C")
             start_temp = real_device_temp

        steps = int(new_target - start_temp)
        
        # 4. 执行调节阶段 (关键回滚点)
        if steps != 0:
            _LOGGER.info(f"-> 执行最终调节: {start_temp} -> {new_target} (步数: {steps})")
            success = await self._controller.async_adjust_temperature(steps, need_activation=False)
            
            if not success:
                _LOGGER.error("调节指令发送失败 (MIIO错误)，回滚设置")
                self._attr_target_temperature = old_target
                self._display_mode = old_mode 
                self.async_write_ha_state()
        else:
            _LOGGER.info("-> 温度已一致，无需调节")