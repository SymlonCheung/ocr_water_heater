"""Water Heater platform for OCR integration."""
from __future__ import annotations

import logging
import asyncio
import time
from typing import Any
from datetime import timedelta
from collections import Counter

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
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    VALID_MIN, VALID_MAX,
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_STANDBY, MODE_SETTING, MODE_OFF,
    SCREEN_KEEP_ALIVE_INTERVAL, TARGET_TEMP_SYNC_INTERVAL
)

# 注意：Controller 的创建和传递现在由 Coordinator 管理
from .controller import WaterHeaterController

_LOGGER = logging.getLogger(__name__)

# --- 调优参数 ---
MAX_FAIL_TOLERANCE = 20
OFF_CONFIRM_COUNT = 8
ACTIVE_DEBOUNCE_SECONDS = 8.0
SYNC_WAIT_TIME = 2.5
SETTING_BRIDGE_TIME = 8.0
BOOT_GRACE_PERIOD = 10.0

MODE_ORDER = [MODE_LOW_POWER, MODE_HALF, MODE_FULL]

def _save_debug_job(result_str, images):
    from .debug_storage import save_debug_record
    save_debug_record(result_str, images)

async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Water Heater platform from a config entry."""
    # Bronze Standard: Retrieve the coordinator from runtime_data
    # 这一步要求你的 __init__.py 必须已经把 coordinator 放入了 entry.runtime_data
    coordinator: OCRCoordinator = entry.runtime_data

    # 从 coordinator 中获取 controller（需要在初始化 coordinator 时挂载）
    controller = coordinator.controller
    
    interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

    async_add_entities([OCRWaterHeaterEntity(coordinator, entry.title, controller, interval)])


class OCRCoordinator(DataUpdateCoordinator[dict[str, Any] | None]):
    """Class to manage fetching OCR data from single endpoint."""

    def __init__(self, hass, ocr_processor, mode_processor, controller, url, interval, debug_mode):
        super().__init__(
            hass, 
            _LOGGER, 
            name="OCR Water Heater", 
            update_interval=timedelta(milliseconds=interval)
        )
        self.ocr_p = ocr_processor
        self.mode_p = mode_processor
        self.controller = controller # 挂载 Controller 以便 Entity 使用
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

        in_boot_grace = self.expect_on and (current_time - self.last_on_command_time < BOOT_GRACE_PERIOD)
        if in_boot_grace and (temp_res is None or mode_res is None):
            return self._last_valid_data

        is_valid_reading = (temp_res is not None)

        if is_valid_reading:
            final_mode = mode_res if mode_res else MODE_STANDBY

            if self.is_confirmed_off and not in_boot_grace:
                if final_mode == MODE_SETTING:
                    is_valid_reading = False
                else:
                    self.is_confirmed_off = False
                    self.expect_on = False

            if is_valid_reading:
                if final_mode == MODE_SETTING:
                    self._last_setting_active_time = current_time

                new_data = {"temp": temp_res, "mode": final_mode}
                self._last_valid_data = new_data
                self._fail_count = 0
                self._off_count = 0
                self.is_confirmed_off = False
                return new_data

        if in_boot_grace:
            return self._last_valid_data

        was_setting = (self._last_valid_data.get("mode") == MODE_SETTING)
        bridge_time = SETTING_BRIDGE_TIME if was_setting else 2.0

        if (current_time - self._last_setting_active_time) < bridge_time:
            self._off_count = 0
            return self._last_valid_data

        self._off_count += 1
        if self._off_count >= OFF_CONFIRM_COUNT:
            self.is_confirmed_off = True
            off_data = {"temp": None, "mode": STATE_OFF}
            self._last_valid_data = off_data
            self._fail_count = 0
            return off_data

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

        # 定时器管理
        self._last_keep_alive = 0
        self._last_target_sync = 0 
        
        # 任务管理
        self._adjust_task: asyncio.Task | None = None
        self._sync_task: asyncio.Task | None = None
        self._startup_task: asyncio.Task | None = None

        # 启动自检标记
        self._startup_sequence_done = False

    @property
    def current_operation(self) -> str:
        return self._display_mode

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if not data:
            super()._handle_coordinator_update()
            return

        # 启动自检逻辑
        if not self._startup_sequence_done:
            self._startup_sequence_done = True
            _LOGGER.info("[实体] 检测到系统启动，执行【启动自检序列】...")
            self._startup_task = self.hass.async_create_task(self._async_run_startup_sequence())
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
            if (current_time - self._last_active_time) > ACTIVE_DEBOUNCE_SECONDS:
                self._attr_target_temperature = raw_val

        elif in_setting_debounce:
            self._display_mode = MODE_SETTING
        else:
            self._display_mode = raw_mode
            self._attr_current_temperature = raw_val

        # 1. 待机保活
        if self._display_mode == MODE_STANDBY:
            if (current_time - self._last_keep_alive) > SCREEN_KEEP_ALIVE_INTERVAL:
                self._last_keep_alive = current_time
                self.hass.async_create_task(self._async_run_keep_alive())

        # 2. 定时同步 (排除自检任务、调节任务)
        is_adjusting = (self._adjust_task and not self._adjust_task.done())
        is_syncing = (self._sync_task and not self._sync_task.done())
        is_startup = (self._startup_task and not self._startup_task.done())

        if not is_adjusting and not is_syncing and not is_startup:
             if self._last_target_sync == 0 or (current_time - self._last_target_sync) > TARGET_TEMP_SYNC_INTERVAL:
                 self._last_target_sync = current_time
                 self._sync_task = self.hass.async_create_task(self._async_sync_temp_process())

        super()._handle_coordinator_update()

    async def _async_run_keep_alive(self):
        _LOGGER.debug("[实体] 定时保活: 唤醒屏幕")
        await self._controller.async_screen_on()

    async def _read_reliable_temp(self, expected_hint: int, sample_count: int = 3) -> int | None:
        """可靠读取机制."""
        samples = []
        _LOGGER.info(f"[读取] 开始采样 ({sample_count} 次)...")

        for i in range(sample_count):
            await self.coordinator.async_request_refresh()
            val = self.coordinator.data.get("temp")
            if val is not None:
                samples.append(val)
            await asyncio.sleep(0.4)

        if not samples:
            _LOGGER.warning("[读取] 采样为空.")
            return None

        counts = Counter(samples)
        _LOGGER.info(f"[读取] 统计: {counts}")

        most_common = counts.most_common(1)
        best_val, count = most_common[0]

        if len(samples) > 1 and count == 1:
            best_val = min(samples, key=lambda x: abs(x - expected_hint))
            _LOGGER.info(f"[读取] 选取接近参考值({expected_hint}): {best_val}")

        return best_val

    async def _async_run_startup_sequence(self):
        """启动自检序列."""
        _LOGGER.info("[自检] 开始启动自检序列...")
        await asyncio.sleep(1.0)

        is_off = (self.coordinator.data.get("mode") == STATE_OFF)

        if not is_off:
            _LOGGER.info("[自检] 设备已处于开机状态，执行标准同步.")
            await self._async_sync_temp_process()
            self._last_target_sync = time.time()
            return

        _LOGGER.info("[自检] 设备处于【关机】状态，执行【闪电同步】.")
        self.coordinator.notify_turned_on() 
        if not await self._controller.async_toggle_power():
            _LOGGER.error("[自检] 开机失败，终止.")
            return

        _LOGGER.info(f"[自检] 等待 {SYNC_WAIT_TIME}秒...")
        await asyncio.sleep(SYNC_WAIT_TIME)

        await self._controller.async_adjust_temperature(0, need_activation=True)
        await asyncio.sleep(1.0)

        real_temp = await self._read_reliable_temp(expected_hint=self._attr_target_temperature, sample_count=2)

        if real_temp is not None:
            _LOGGER.info(f"[自检] 读取成功: {real_temp}°C. 更新 HA.")
            self._attr_target_temperature = real_temp
            self.async_write_ha_state()
        else:
            _LOGGER.warning("[自检] 读取失败.")

        _LOGGER.info("[自检] 执行关机...")
        await self._controller.async_toggle_power()
        self._display_mode = STATE_OFF
        self.async_write_ha_state()
        self._last_target_sync = time.time()
        _LOGGER.info("[自检] 完成.")

    async def _async_sync_temp_process(self):
        """定时同步任务."""
        try:
            _LOGGER.info("[同步] 开始定时同步目标温度...")
            await self._controller.async_adjust_temperature(0, need_activation=True)
            _LOGGER.info(f"[同步] 等待 {SYNC_WAIT_TIME}秒...")
            await asyncio.sleep(SYNC_WAIT_TIME)

            real_temp = await self._read_reliable_temp(self._attr_target_temperature)

            if real_temp is not None:
                _LOGGER.info(f"[同步] 读取成功: 设备目标={real_temp}°C. 更新 HA.")
                self._attr_target_temperature = real_temp
                self.async_write_ha_state()
            else:
                _LOGGER.warning("[同步] 读取失败，跳过更新.")

        except asyncio.CancelledError:
            _LOGGER.info("[同步] 任务被取消.")
        except Exception as e:
            _LOGGER.error(f"[同步] 异常: {e}")

    async def async_turn_on(self, **kwargs: Any) -> None:
        _LOGGER.info("[实体] 请求: 开机")
        if self._adjust_task and not self._adjust_task.done(): self._adjust_task.cancel()
        if self._sync_task and not self._sync_task.done(): self._sync_task.cancel()
        if self._startup_task and not self._startup_task.done(): self._startup_task.cancel()

        self.coordinator.notify_turned_on()
        prev_mode = self._display_mode
        self._display_mode = MODE_LOW_POWER
        self.async_write_ha_state()

        success = await self._controller.async_toggle_power()
        if not success:
            _LOGGER.error("[实体] 开机失败，回滚")
            self._display_mode = prev_mode
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        _LOGGER.info("[实体] 请求: 关机")
        if self._adjust_task and not self._adjust_task.done(): self._adjust_task.cancel()
        if self._sync_task and not self._sync_task.done(): self._sync_task.cancel()
        if self._startup_task and not self._startup_task.done(): self._startup_task.cancel()

        prev_mode = self._display_mode
        self._display_mode = STATE_OFF
        self.async_write_ha_state()

        success = await self._controller.async_toggle_power()
        if not success:
            _LOGGER.error("[实体] 关机失败，回滚")
            self._display_mode = prev_mode
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        _LOGGER.info(f"[实体] 请求: 设置模式 {operation_mode}")
        if self._adjust_task and not self._adjust_task.done(): self._adjust_task.cancel()
        if self._sync_task and not self._sync_task.done(): self._sync_task.cancel()
        if self._startup_task and not self._startup_task.done(): self._startup_task.cancel()

        if operation_mode == STATE_OFF:
            await self.async_turn_off()
            return

        old_mode = self._display_mode

        if self._display_mode == STATE_OFF:
            _LOGGER.info("[实体] 设备关机中，先开机...")
            self.coordinator.notify_turned_on()
            self._display_mode = MODE_LOW_POWER
            self.async_write_ha_state()
            if not await self._controller.async_toggle_power():
                self._display_mode = old_mode
                self.async_write_ha_state()
                return
            await asyncio.sleep(2.0)

        if operation_mode in MODE_ORDER:
            current_mode_guess = self._display_mode
            if current_mode_guess not in MODE_ORDER:
                 _LOGGER.info("[实体] 模式未知，尝试唤醒")
                 await self._controller.async_press_mode(1)
                 return

            if current_mode_guess in MODE_ORDER and operation_mode in MODE_ORDER:
                curr_idx = MODE_ORDER.index(current_mode_guess)
                target_idx = MODE_ORDER.index(operation_mode)
                clicks = (target_idx - curr_idx) % 3
                if clicks > 0:
                    _LOGGER.info(f"[实体] 切换模式 {current_mode_guess} -> {operation_mode} ({clicks} 次)")
                    self._display_mode = operation_mode
                    self.async_write_ha_state()
                    success = await self._controller.async_press_mode(clicks)
                    if not success:
                        self._display_mode = old_mode
                        self.async_write_ha_state()

        elif operation_mode == MODE_STANDBY:
            _LOGGER.info("[实体] 请求待机")
            await self._controller.async_screen_on()

        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        new_target = kwargs.get(ATTR_TEMPERATURE)
        if new_target is None: return

        old_target = self._attr_target_temperature
        self._attr_target_temperature = new_target
        self._display_mode = MODE_SETTING
        self._last_active_time = time.time()
        self.async_write_ha_state()

        _LOGGER.info(f"[实体] 收到新目标温度: {new_target}")

        if self._adjust_task and not self._adjust_task.done():
            self._adjust_task.cancel()
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
        if self._startup_task and not self._startup_task.done():
            self._startup_task.cancel()

        self._adjust_task = self.hass.async_create_task(
            self._async_adjust_temp_process(new_target, old_target)
        )

    async def _async_adjust_temp_process(self, new_target: float, old_target_backup: float):
        try:
            _LOGGER.info(f"[任务] === 开始调节: -> {new_target} ===")
            activated_successfully = False
            raw_mode = self.coordinator.data.get("mode") if self.coordinator.data else MODE_STANDBY

            if raw_mode == MODE_SETTING:
                activated_successfully = True
            else:
                 if raw_mode == MODE_STANDBY:
                     await self._controller.async_screen_on()
                     await asyncio.sleep(0.8)
                 activated_successfully = await self._controller.async_adjust_temperature(0, need_activation=True)

            if not activated_successfully and raw_mode != MODE_SETTING:
                _LOGGER.error("[任务] 激活失败.")
                self._attr_target_temperature = old_target_backup
                self.async_write_ha_state()
                return

            _LOGGER.info(f"[任务] 等待 {SYNC_WAIT_TIME}秒...")
            await asyncio.sleep(SYNC_WAIT_TIME)

            start_temp = await self._read_reliable_temp(expected_hint=old_target_backup)
            if start_temp is None:
                start_temp = old_target_backup

            steps = int(new_target - start_temp)
            if steps != 0:
                success = await self._controller.async_adjust_temperature(steps, need_activation=False)
                if success:
                    _LOGGER.info("[任务] 完成.")
                else:
                    self._attr_target_temperature = old_target_backup
                    self.async_write_ha_state()
            else:
                _LOGGER.info("[任务] 无需调节.")

        except asyncio.CancelledError:
            _LOGGER.warning(f"[任务] 被取消.")
            raise
        except Exception as e:
            _LOGGER.error(f"[任务] 异常: {e}")