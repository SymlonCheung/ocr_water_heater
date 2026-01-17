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
                _LOGGER.info(f"MIIO 设备初始化成功 IP: {self.ip}")
            except Exception as e:
                _LOGGER.error(f"MIIO 设备初始化失败: {e}")

    async def _async_send_raw(self, method: str, params: list):
        """通用发送方法，包含锁、延迟和返回值检查."""
        if not self._device:
            _LOGGER.error("MIIO 设备未配置，无法发送指令")
            return False

        async with self._lock:
            try:
                _LOGGER.info(f"[控制器] 正在发送指令: {method}...")
                # 在 executor 中运行阻塞的 miio 操作
                result = await self.hass.async_add_executor_job(
                    self._device.send, method, params
                )
                
                # 检查返回值是否为 ['ok']
                if result == ['ok']:
                    _LOGGER.info(f"[控制器] 指令发送成功. 返回: {result}")
                    await asyncio.sleep(COMMAND_DELAY)
                    return True
                else:
                    _LOGGER.error(f"[控制器] 指令已发送但返回异常: {result}")
                    return False
                    
            except (DeviceException, Exception) as e:
                _LOGGER.error(f"[控制器] 发送异常 ({method}): {e}")
                return False

    async def async_screen_on(self) -> bool:
        """发送屏显/唤醒指令."""
        _LOGGER.info("[控制器] 动作: 唤醒屏幕 (Screen On)")
        return await self._async_send_raw(CMD_METHOD_IR, CMD_VAL_SCREEN_ON)

    async def async_toggle_power(self) -> bool:
        """发送电源开关指令."""
        _LOGGER.info("[控制器] 动作: 电源开关 (Toggle Power)")
        return await self._async_send_raw(CMD_METHOD_ELE, CMD_VAL_TOGGLE)

    async def async_press_mode(self, times: int = 1) -> bool:
        """
        发送模式切换指令。
        """
        _LOGGER.info(f"[控制器] 动作: 切换模式 (按键 {times} 次)")
        success = True
        for i in range(times):
            _LOGGER.info(f"[控制器] 模式按键第 {i+1}/{times} 次")
            if not await self._async_send_raw(CMD_METHOD_IR, CMD_VAL_MODE):
                success = False
                _LOGGER.error(f"[控制器] 模式按键第 {i+1} 次失败!")
                break
        return success

    async def async_adjust_temperature(self, steps: int, need_activation: bool = False) -> bool:
        """
        调整温度。
        steps: 正数升温，负数降温。
        need_activation: 是否需要先发一次指令激活菜单。
        """
        if steps == 0 and not need_activation:
            return True

        cmd_val = CMD_VAL_TEMP_UP if steps > 0 else CMD_VAL_TEMP_DOWN
        
        # 如果 steps 为 0 但需要激活，默认使用 UP 激活
        if steps == 0 and need_activation:
            cmd_val = CMD_VAL_TEMP_UP

        count = abs(steps)
        
        # 日志记录意图
        if need_activation:
            _LOGGER.info(f"[控制器] 动作: 调节温度 (步数={steps}). 需要激活 (+1次点击).")
            # 激活那一击
            _LOGGER.info("[控制器] >> 发送激活点击 (Activation)...")
            if not await self._async_send_raw(CMD_METHOD_ELE, cmd_val):
                _LOGGER.error("[控制器] 激活点击失败!")
                return False
        else:
            _LOGGER.info(f"[控制器] 动作: 调节温度 (步数={steps}). 无需激活.")

        # 发送剩余的步数
        if count > 0:
            _LOGGER.info(f"[控制器] >> 发送 {count} 次调节点击...")
            for i in range(count):
                _LOGGER.info(f"[控制器] 调节点击 第 {i+1}/{count} 次")
                if not await self._async_send_raw(CMD_METHOD_ELE, cmd_val):
                    _LOGGER.error(f"[控制器] 第 {i+1} 次点击失败! 停止发送.")
                    return False
        
        return True