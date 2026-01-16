"""Switch platform for OCR Water Heater (Display Control)."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_MIIO_IP, CONF_MIIO_TOKEN
from .controller import WaterHeaterController

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the switch platform."""
    config = {**entry.data, **entry.options}
    ip = config.get(CONF_MIIO_IP)
    token = config.get(CONF_MIIO_TOKEN)

    if not ip or not token:
        return

    # Use a separate controller instance for the switch to keep it simple, 
    # or we could share it, but for now independent instantiation is safer for threading.
    controller = await hass.async_add_executor_job(WaterHeaterController, ip, token)
    
    async_add_entities([WaterHeaterDisplaySwitch(controller, entry.title)])

class WaterHeaterDisplaySwitch(SwitchEntity):
    """Representation of the Water Heater Display Switch."""

    _attr_has_entity_name = True
    _attr_name = "Screen Display"
    _attr_icon = "mdi:monitor-shimmer"

    def __init__(self, controller: WaterHeaterController, device_name: str) -> None:
        """Initialize the switch."""
        self._controller = controller
        self._attr_unique_id = f"{DOMAIN}_display_{controller.ip}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_name)},  # Attach to same device
            "name": device_name,
        }
        self._is_on = True # Assume on by default since we can't easily read it separately without OCR logic for it

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        await self.hass.async_add_executor_job(self._controller.toggle_display)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        await self.hass.async_add_executor_job(self._controller.toggle_display)
        self._is_on = False
        self.async_write_ha_state()