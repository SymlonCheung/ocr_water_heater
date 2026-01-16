"""Controller for sending commands to the Water Heater (MIIO/IR)."""
import logging
import asyncio
from miio import Device, DeviceException
from .const import (
    CONF_MIIO_IP, CONF_MIIO_TOKEN,
    CMD_METHOD_IR, CMD_METHOD_ELE,
    CMD_VAL_SCREEN_ON, CMD_VAL_TEMP_UP, CMD_VAL_TEMP_DOWN, CMD_VAL_TOGGLE, CMD_VAL_MODE
)

_LOGGER = logging.getLogger(__name__)

# 发送指令的最小间隔 (秒)
COMMAND_DELAY = 0.6

class WaterHeaterController:
    """处理热水器的控制指令 (基于 python-miio)."""

    def __init__(self, hass, config):
        self.hass = hass
        self.ip = config.get(CONF_MIIO_IP)
        self.token = config.get(CONF_MIIO_TOKEN)
        self._device = None
        self._lock = asyncio.Lock()

        if self.ip and self.token:
            try:
                self._device = Device(self.ip, self.token)
                _LOGGER.info(f"MIIO Device initialized at {self.ip}")
            except Exception as e:
                _LOGGER.error(f"Failed to initialize MIIO device: {e}")

    async def _async_send_raw(self, method: str, params: list):
        """通用发送方法，包含锁和延迟."""
        if not self._device:
            return False

        async with self._lock:
            try:
                await self.hass.async_add_executor_job(
                    self._device.send, method, params
                )
                await asyncio.sleep(COMMAND_DELAY)
                return True
            except (DeviceException, Exception) as e:
                _LOGGER.error(f"Failed to send command ({method}): {e}")
                return False

    async def async_screen_on(self) -> bool:
        """发送屏显/唤醒指令."""
        return await self._async_send_raw(CMD_METHOD_IR, CMD_VAL_SCREEN_ON)

    async def async_toggle_power(self) -> bool:
        """发送电源开关指令."""
        return await self._async_send_raw(CMD_METHOD_ELE, CMD_VAL_TOGGLE)

    async def async_press_mode(self, times: int = 1) -> bool:
        """
        发送模式切换指令。
        参数 times: 发送次数。
        """
        success = True
        for _ in range(times):
            if not await self._async_send_raw(CMD_METHOD_IR, CMD_VAL_MODE):
                success = False
        return success

    async def async_adjust_temperature(self, steps: int, need_activation: bool = False) -> bool:
        """
        调整温度。
        steps: 正数升温，负数降温。
        need_activation: 如果 True，说明当前未处于设置模式，需要多发一次指令来激活菜单。
                         (例如: 目标+1度，实际发送2次UP；第一次唤醒菜单，第二次加一)
        """
        if steps == 0:
            return True

        cmd_val = CMD_VAL_TEMP_UP if steps > 0 else CMD_VAL_TEMP_DOWN
        
        # 计算实际点击次数
        # 如果需要激活，则总次数 = 步数绝对值 + 1
        # 如果不需要激活，则总次数 = 步数绝对值
        count = abs(steps)
        if need_activation:
            count += 1
            _LOGGER.info(f"Adjusting temp: {steps} steps (+1 for activation). Total clicks: {count}")
        else:
            _LOGGER.info(f"Adjusting temp: {steps} steps. Total clicks: {count}")
        
        success = True
        for i in range(count):
            if not await self._async_send_raw(CMD_METHOD_ELE, cmd_val):
                success = False
                break
        
        return success