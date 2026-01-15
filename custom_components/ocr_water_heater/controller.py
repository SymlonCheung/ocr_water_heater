"""Controller logic for OCR Water Heater via MIIO."""
import logging
import miio
from .const import (
    CMD_METHOD_ELE, CMD_METHOD_IR,
    CMD_VAL_TEMP_UP, CMD_VAL_TEMP_DOWN, CMD_VAL_TOGGLE, CMD_VAL_SCREEN
)

_LOGGER = logging.getLogger(__name__)

class HeaterController:
    """Class to handle MIIO communication."""

    def __init__(self, ip: str, token: str):
        """Initialize the controller."""
        self._ip = ip
        self._token = token
        self._device = None
        self._initialized = False
        
        if self._ip and self._token:
            try:
                # 使用通用 Device 类，因为我们需要发送自定义命令 (send_other_ele_cmd)
                self._device = miio.Device(ip=self._ip, token=self._token)
                self._initialized = True
                _LOGGER.info(f"MIIO Device initialized at {self._ip}")
            except Exception as e:
                _LOGGER.error(f"Failed to initialize MIIO device: {e}")

    def send_command(self, method: str, params: list):
        """Send a raw command to the device."""
        if not self._initialized or not self._device:
            _LOGGER.warning("MIIO device not initialized, skipping command.")
            return False

        try:
            # miio 库调用 send 方法
            _LOGGER.debug(f"Sending MIIO cmd: {method} -> {params}")
            self._device.send(method, params)
            return True
        except Exception as e:
            _LOGGER.error(f"MIIO Send Error ({method}): {e}")
            return False

    def temp_up(self):
        """Send command to increase temperature."""
        return self.send_command(CMD_METHOD_ELE, CMD_VAL_TEMP_UP)

    def temp_down(self):
        """Send command to decrease temperature."""
        return self.send_command(CMD_METHOD_ELE, CMD_VAL_TEMP_DOWN)

    def toggle_power(self):
        """Send toggle power command."""
        return self.send_command(CMD_METHOD_ELE, CMD_VAL_TOGGLE)

    def toggle_screen(self):
        """Send screen/IR command."""
        return self.send_command(CMD_METHOD_IR, CMD_VAL_SCREEN)