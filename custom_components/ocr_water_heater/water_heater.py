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
    # 引入 HA 标准模式常量
    STATE_ECO,
    STATE_PERFORMANCE,
    STATE_HIGH_DEMAND,
    STATE_OFF,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_WHOLE,
    UnitOfTemperature,
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
    MODE_LOW_POWER, MODE_HALF, MODE_FULL, MODE_STANDBY, MODE_SETTING,
    SCREEN_KEEP_ALIVE_INTERVAL, TARGET_TEMP_SYNC_INTERVAL
)

from .controller import WaterHeaterController

_LOGGER = logging.getLogger(__name__)

# --- 调优参数 ---
OFF_CONFIRM_COUNT = 8
ACTIVE_DEBOUNCE_SECONDS = 8.0
SYNC_WAIT_TIME = 2.5
SETTING_BRIDGE_TIME = 8.0
BOOT_GRACE_PERIOD = 10.0

# 仅包含有效运行模式的列表 (OCR 识别到的原始中文)
VALID_RUNNING_MODES = [MODE_LOW_POWER, MODE_HALF, MODE_FULL]
# 排序列表 (用于计算按键次数)
MODE_ORDER = [MODE_LOW_POWER, MODE_HALF, MODE_FULL]

# === 核心修改: 建立映射关系 ===
# 目的：让 HA 前端显示漂亮的图标 (Eco=叶子, Performance=火箭, HighDemand=闪电)
# 键: OCR识别的中文 / 值: HA标准英文
INTERNAL_TO_HA = {
    MODE_LOW_POWER: STATE_ECO,
    MODE_HALF: STATE_PERFORMANCE,
    MODE_FULL: STATE_HIGH_DEMAND,
    STATE_OFF: STATE_OFF,
    # 临时状态映射
    MODE_SETTING: STATE_ECO, 
    MODE_STANDBY: STATE_ECO 
}

# 反向映射: HA标准英文 -> 控制器需要的中文
HA_TO_INTERNAL = {
    STATE_ECO: MODE_LOW_POWER,
    STATE_PERFORMANCE: MODE_HALF,
    STATE_HIGH_DEMAND: MODE_FULL,
    STATE_OFF: STATE_OFF
}

def _save_debug_job(result_str, images):
    from .debug_storage import save_debug_record
    save_debug_record(result_str, images)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Water Heater platform from a config entry."""
    coordinator: OCRCoordinator = entry.runtime_data
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
        self.controller = controller
        self.url = url
        self.debug_mode = debug_mode
        self.session = aiohttp_client.async_get_clientsession(hass)

        self._last_valid_data = {"temp": 50, "mode": STATE_OFF}
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
            return off_data

        return self._last_valid_data


class OCRWaterHeaterEntity(CoordinatorEntity[OCRCoordinator], WaterHeaterEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE |
        WaterHeaterEntityFeature.OPERATION_MODE |
        WaterHeaterEntityFeature.ON_OFF
    )
    
    # === 修改 1: 使用 HA 标准模式列表 (这样前端才有图标) ===
    _attr_operation_list = [STATE_ECO, STATE_PERFORMANCE, STATE_HIGH_DEMAND, STATE_OFF]
    
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
        
        # 内部状态使用 HA 标准模式
        self._display_mode = STATE_OFF
        
        # 记忆变量也使用 HA 标准模式
        self._last_known_on_mode = STATE_ECO 

        self._exit_debounce_time = (interval * 2.5) / 1000.0
        self._last_active_time = 0.0
        self._last_setting_seen_time = 0.0

        self._last_keep_alive = 0
        self._last_target_sync = 0

        self._adjust_task: asyncio.Task | None = None
        self._sync_task: asyncio.Task | None = None
        self._startup_task: asyncio.Task | None = None

        self._startup_sequence_done = False
        
        self._is_adjusting_temp = False
        self._is_adjusting_mode = False

    @property
    def current_operation(self) -> str:
        return self._display_mode

    @callback
    def _handle_coordinator_update(self) -> None:
        """接收 OCR 数据更新 (raw_mode 是中文)，映射为 HA 标准模式更新 UI."""
        data = self.coordinator.data
        if not data:
            super()._handle_coordinator_update()
            return

        if not self._startup_sequence_done:
            self._startup_sequence_done = True
            _LOGGER.info("[实体] 检测到系统启动，执行【启动自检序列】...")
            self._startup_task = self.hass.async_create_task(self._async_run_startup_sequence())
            return

        raw_val = data.get("temp")
        raw_mode_chinese = data.get("mode") # 这是中文: "低功率", "速热半缸"...

        # 1. 关机状态特殊处理
        if raw_mode_chinese == STATE_OFF:
            if not self._is_adjusting_mode and not self._is_adjusting_temp:
                self._display_mode = STATE_OFF
                self._attr_current_temperature = None
            super()._handle_coordinator_update()
            return

        if raw_val is None:
            return

        current_time = time.time()

        # 2. 模式更新逻辑
        if not self._is_adjusting_mode:
            
            if raw_mode_chinese == MODE_SETTING:
                self._last_setting_seen_time = current_time

            if raw_mode_chinese in VALID_RUNNING_MODES:
                # 中文 -> 英文标准模式
                ha_mode = INTERNAL_TO_HA.get(raw_mode_chinese, STATE_ECO)
                
                self._display_mode = ha_mode
                self._last_known_on_mode = ha_mode
                
            elif raw_mode_chinese == MODE_SETTING or raw_mode_chinese == MODE_STANDBY:
                # Masking: 显示上次已知模式
                if self._display_mode == STATE_OFF:
                    self._display_mode = STATE_ECO
                    self._last_known_on_mode = STATE_ECO
                else:
                    self._display_mode = self._last_known_on_mode
            
            else:
                self._display_mode = self._last_known_on_mode

        # 3. 温度更新逻辑
        if not self._is_adjusting_temp:
            if raw_mode_chinese != MODE_SETTING:
                self._attr_current_temperature = raw_val
            
            if raw_mode_chinese == MODE_SETTING:
                if (current_time - self._last_active_time) > ACTIVE_DEBOUNCE_SECONDS:
                    self._attr_target_temperature = raw_val

        # 4. 待机保活
        if raw_mode_chinese == MODE_STANDBY and not self._is_adjusting_mode:
            if (current_time - self._last_keep_alive) > SCREEN_KEEP_ALIVE_INTERVAL:
                self._last_keep_alive = current_time
                self.hass.async_create_task(self._async_run_keep_alive())

        # 5. 定时同步
        is_adjusting = (self._is_adjusting_temp or self._is_adjusting_mode)
        is_startup = (self._startup_task and not self._startup_task.done())

        if not is_adjusting and not is_startup:
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
        most_common = counts.most_common(1)
        best_val, count = most_common[0]

        if len(samples) > 1 and count == 1:
            best_val = min(samples, key=lambda x: abs(x - expected_hint))

        return best_val

    async def _async_run_startup_sequence(self):
        """启动自检序列."""
        _LOGGER.info("[自检] 开始启动自检序列...")
        await asyncio.sleep(1.0)
        
        self._is_adjusting_temp = True
        try:
            is_off = (self.coordinator.data.get("mode") == STATE_OFF)
            if not is_off:
                _LOGGER.info("[自检] 设备已处于开机状态，执行标准同步.")
                await self._async_sync_temp_process()
                return

            _LOGGER.info("[自检] 设备关机中，执行闪电同步.")
            self.coordinator.notify_turned_on()
            await self._controller.async_toggle_power()
            await asyncio.sleep(SYNC_WAIT_TIME)

            await self._controller.async_adjust_temperature(0, need_activation=True)
            await asyncio.sleep(1.0)

            real_temp = await self._read_reliable_temp(expected_hint=self._attr_target_temperature, sample_count=2)

            if real_temp is not None:
                _LOGGER.info(f"[自检] 读取成功: {real_temp}°C.")
                self._attr_target_temperature = real_temp
            
            await self._controller.async_toggle_power()
            self._display_mode = STATE_OFF
            self._last_target_sync = time.time()
            _LOGGER.info("[自检] 完成.")
        
        finally:
            if self._startup_task == asyncio.current_task():
                self._is_adjusting_temp = False
            self.async_write_ha_state()

    async def _async_sync_temp_process(self):
        """定时同步."""
        try:
            _LOGGER.info("[同步] 开始定时同步...")
            self._is_adjusting_temp = True
            
            await self._controller.async_adjust_temperature(0, need_activation=True)
            await asyncio.sleep(SYNC_WAIT_TIME)

            real_temp = await self._read_reliable_temp(self._attr_target_temperature)

            if real_temp is not None:
                _LOGGER.info(f"[同步] 读取成功: {real_temp}°C.")
                self._attr_target_temperature = real_temp
            
        except Exception as e:
            _LOGGER.error(f"[同步] 异常: {e}")
        finally:
            if self._sync_task == asyncio.current_task():
                self._is_adjusting_temp = False
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        _LOGGER.info("[实体] 请求: 开机")
        if self._adjust_task: self._adjust_task.cancel()
        if self._sync_task: self._sync_task.cancel()

        self.coordinator.notify_turned_on()
        
        # 使用上次的模式 (英文)
        target_mode = self._last_known_on_mode
        self._display_mode = target_mode
        self.async_write_ha_state()

        if not await self._controller.async_toggle_power():
            self._display_mode = STATE_OFF
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        _LOGGER.info("[实体] 请求: 关机")
        if self._adjust_task: self._adjust_task.cancel()
        if self._sync_task: self._sync_task.cancel()

        prev_mode = self._display_mode
        self._display_mode = STATE_OFF
        self.async_write_ha_state()

        if not await self._controller.async_toggle_power():
            self._display_mode = prev_mode
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """设置模式 (operation_mode 传入的是 HA 标准英文)."""
        _LOGGER.info(f"[实体] 请求: 设置模式 {operation_mode}")
        
        if self._adjust_task: self._adjust_task.cancel()
        if self._sync_task: self._sync_task.cancel()

        if operation_mode == STATE_OFF:
            await self.async_turn_off()
            return

        old_mode = self._display_mode

        # 锁定 UI
        self._is_adjusting_mode = True
        self._display_mode = operation_mode
        self._last_known_on_mode = operation_mode
        self.async_write_ha_state()

        # 传入的 operation_mode 是英文 (e.g., 'eco')
        # 我们需要把它转回中文逻辑 (old_mode_backup 也是英文)
        self._adjust_task = self.hass.async_create_task(
            self._async_set_mode_process(operation_mode, old_mode)
        )

    async def _async_set_mode_process(self, target_mode_ha: str, old_mode_ha_backup: str):
        try:
            # 这里的参数都是 HA 标准英文 ('eco', 'performance'...)
            
            if old_mode_ha_backup == STATE_OFF:
                self.coordinator.notify_turned_on()
                if not await self._controller.async_toggle_power():
                    raise Exception("开机失败")
                await asyncio.sleep(2.0)
                old_mode_ha_backup = STATE_ECO # 开机默认低功率

            # 将 HA 英文模式 转回 内部中文模式 来计算按键
            target_mode_cn = HA_TO_INTERNAL.get(target_mode_ha)
            old_mode_cn = HA_TO_INTERNAL.get(old_mode_ha_backup)
            
            # 安全兜底
            if not target_mode_cn: target_mode_cn = MODE_LOW_POWER
            if not old_mode_cn: old_mode_cn = MODE_LOW_POWER

            if target_mode_cn in VALID_RUNNING_MODES:
                # 尽量使用上一次真实的模式来计算
                current_mode_guess = old_mode_cn
                if current_mode_guess not in VALID_RUNNING_MODES:
                    current_mode_guess = MODE_LOW_POWER

                curr_idx = MODE_ORDER.index(current_mode_guess)
                target_idx = MODE_ORDER.index(target_mode_cn)
                clicks = (target_idx - curr_idx) % 3
                
                if clicks > 0:
                    _LOGGER.info(f"[任务] 切换模式 {clicks} 次")
                    if not await self._controller.async_press_mode(clicks):
                        raise Exception("指令发送失败")

            _LOGGER.info("[任务] 模式完成.")

        except Exception as e:
            _LOGGER.error(f"[任务] 模式失败: {e}")
            self._display_mode = old_mode_ha_backup
        finally:
            if self._adjust_task == asyncio.current_task():
                self._is_adjusting_mode = False
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """设置温度."""
        new_target = kwargs.get(ATTR_TEMPERATURE)
        if new_target is None: return

        old_target = self._attr_target_temperature
        _LOGGER.info(f"[实体] 请求调温: {new_target}")

        if self._adjust_task: self._adjust_task.cancel()
        if self._sync_task: self._sync_task.cancel()

        self._is_adjusting_temp = True
        self._attr_target_temperature = new_target
        self._last_active_time = time.time()
        self.async_write_ha_state()

        self._adjust_task = self.hass.async_create_task(
            self._async_adjust_temp_process(new_target, old_target)
        )

    async def _async_adjust_temp_process(self, new_target: float, old_target_backup: float):
        try:
            _LOGGER.info(f"[任务] === 开始调节: -> {new_target} ===")
            
            # A. 激活菜单
            activated = False
            raw_mode_chinese = self.coordinator.data.get("mode") if self.coordinator.data else MODE_STANDBY

            if raw_mode_chinese == MODE_SETTING:
                activated = True
            else:
                 if raw_mode_chinese == MODE_STANDBY:
                     await self._controller.async_screen_on()
                     await asyncio.sleep(0.8)
                 activated = await self._controller.async_adjust_temperature(0, need_activation=True)

            if not activated and raw_mode_chinese != MODE_SETTING:
                raise Exception("无法激活设置菜单")

            _LOGGER.info("[任务] 等待读取当前值...")
            await asyncio.sleep(SYNC_WAIT_TIME)

            # B. 读取起点
            start_temp = await self._read_reliable_temp(expected_hint=old_target_backup)
            if start_temp is None:
                _LOGGER.warning("[任务] 无法读取起点，使用推测值")
                start_temp = old_target_backup

            # C. 计算并执行
            steps = int(new_target - start_temp)
            if steps != 0:
                _LOGGER.info(f"[任务] 执行步数: {steps}")
                if not await self._controller.async_adjust_temperature(steps, need_activation=False):
                    raise Exception("指令发送失败")
            else:
                _LOGGER.info("[任务] 步数为0")
                
            _LOGGER.info("[任务] 完成.")

        except asyncio.CancelledError:
            _LOGGER.warning("[任务] 被新调节打断 (正常).")
            raise
        except Exception as e:
            _LOGGER.error(f"[任务] 异常: {e}")
            self._attr_target_temperature = old_target_backup
        finally:
            if self._adjust_task == asyncio.current_task():
                self._is_adjusting_temp = False
            self.async_write_ha_state()