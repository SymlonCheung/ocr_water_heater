"""Controller for sending commands to the Water Heater (MIIO/IR)."""
import logging

_LOGGER = logging.getLogger(__name__)

class WaterHeaterController:
    """处理热水器的控制指令 (下一步开发)."""

    def __init__(self, hass, config):
        self.hass = hass
        self.config = config

    async def async_set_temperature(self, temperature: float) -> bool:
        """
        设置目标温度。
        目前版本暂未实现，直接抛出异常以测试回滚逻辑。
        """
        # TODO: 下个版本在此处实现 miio 指令发送
        # return True 
        raise NotImplementedError("Controller function pending implementation.")