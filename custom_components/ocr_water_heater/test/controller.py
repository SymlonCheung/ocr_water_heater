"""Controller logic for interaction with Miio device (Aqara AC Partner)."""
import logging
import time
from miio import Device, DeviceException

_LOGGER = logging.getLogger(__name__)

# Node-RED payload constants
CMD_IR_CODE = "send_ir_code"
CMD_ELEC = "send_other_ele_cmd"

# Values from user provided Node-RED logic
VAL_DISPLAY_TOGGLE = ["FE00000000000094701fff7a0107002427ed003600AB00DF01C403850F9B1388430000000101000100010101000001000100010100010000000100000100010101054206F2"]
VAL_TEMP_UP        = ["00000c00d0135500032100040ED8010010390016001500160040010004015A00AD00000106015A00560015050058A701FE"]
VAL_TEMP_DOWN      = ["00000c00d0135500042100040ED8010010390016001500160040010004015A00AD00000106015A00560015050058A703FC"]
VAL_POWER_TOGGLE   = ["00000c00d0135500012100040ED8010010390016001500160040010004015A00AD00000106015A00560015050058A700FF"]

class WaterHeaterController:
    """Class to control the water heater via Aqara AC Partner."""

    def __init__(self, ip: str, token: str):
        """Initialize the controller."""
        self.ip = ip
        self.token = token
        self._device = None
        self._available = False

    def connect(self) -> bool:
        """Establish connection to the device."""
        if not self.ip or not self.token:
            _LOGGER.warning("Miio IP or Token not configured.")
            return False
        
        try:
            self._device = Device(self.ip, self.token)
            # Try a lightweight command to verify connection
            self._device.send("get_model_and_state", [])
            self._available = True
            return True
        except DeviceException as ex:
            _LOGGER.error("Failed to connect to Miio device: %s", ex)
            self._available = False
            return False

    def _send(self, method: str, value: list) -> bool:
        """Internal helper to send commands."""
        if not self._device:
            if not self.connect():
                return False
        
        try:
            # Equivalent to device.call(method, value) in Node.js
            self._device.send(method, value)
            return True
        except DeviceException as ex:
            _LOGGER.error("Miio command failed: %s", ex)
            return False

    def toggle_display(self) -> bool:
        """Send IR code to toggle display."""
        return self._send(CMD_IR_CODE, VAL_DISPLAY_TOGGLE)

    def toggle_power(self) -> bool:
        """Send command to toggle power."""
        return self._send(CMD_ELEC, VAL_POWER_TOGGLE)

    def temp_up(self) -> bool:
        """Send command to increase temperature."""
        return self._send(CMD_ELEC, VAL_TEMP_UP)

    def temp_down(self) -> bool:
        """Send command to decrease temperature."""
        return self._send(CMD_ELEC, VAL_TEMP_DOWN)