"""Config flow for OCR Water Heater integration."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import aiohttp_client

from .const import (
    DOMAIN,
    CONF_IMAGE_URL, CONF_ROI_X, CONF_ROI_Y, CONF_ROI_W, CONF_ROI_H, CONF_SKEW,
    CONF_UPDATE_INTERVAL, CONF_DEBUG_MODE,
    DEFAULT_NAME, DEFAULT_ROI, DEFAULT_SKEW, 
    DEFAULT_UPDATE_INTERVAL, DEFAULT_DEBUG_MODE
)

_LOGGER = logging.getLogger(__name__)

def get_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_IMAGE_URL, default=defaults.get(CONF_IMAGE_URL)): str,
            vol.Optional(CONF_UPDATE_INTERVAL, default=defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)): vol.All(vol.Coerce(int), vol.Range(min=100)),
            vol.Optional(CONF_DEBUG_MODE, default=defaults.get(CONF_DEBUG_MODE, DEFAULT_DEBUG_MODE)): bool,
            
            vol.Optional(CONF_ROI_X, default=defaults.get(CONF_ROI_X, DEFAULT_ROI[0])): vol.Coerce(int),
            vol.Optional(CONF_ROI_Y, default=defaults.get(CONF_ROI_Y, DEFAULT_ROI[1])): vol.Coerce(int),
            vol.Optional(CONF_ROI_W, default=defaults.get(CONF_ROI_W, DEFAULT_ROI[2])): vol.Coerce(int),
            vol.Optional(CONF_ROI_H, default=defaults.get(CONF_ROI_H, DEFAULT_ROI[3])): vol.Coerce(int),
            vol.Optional(CONF_SKEW, default=defaults.get(CONF_SKEW, DEFAULT_SKEW)): vol.Coerce(float),
        }
    )

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    session = aiohttp_client.async_get_clientsession(hass)
    try:
        async with session.get(data[CONF_IMAGE_URL], timeout=5) as resp:
            if resp.status != 200:
                raise ValueError(f"Could not connect, status: {resp.status}")
    except Exception as err:
        raise ValueError(f"Connection error: {err}") from err
    return {"title": DEFAULT_NAME}

class OCRWaterHeaterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OCR Water Heater."""
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow."""
        return OCRWaterHeaterOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        defaults = {
            CONF_IMAGE_URL: "http://192.168.123.86:5000/api/reshuiqi/latest.jpg",
            CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_DEBUG_MODE: DEFAULT_DEBUG_MODE,
            CONF_ROI_X: DEFAULT_ROI[0],
            CONF_ROI_Y: DEFAULT_ROI[1],
            CONF_ROI_W: DEFAULT_ROI[2],
            CONF_ROI_H: DEFAULT_ROI[3],
            CONF_SKEW: DEFAULT_SKEW
        }
        
        return self.async_show_form(
            step_id="user", data_schema=get_schema(defaults), errors=errors
        )

class OCRWaterHeaterOptionsFlow(OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        # 【修复关键点】不要给 self.config_entry 赋值，改用 self._config_entry
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="", data=user_input)

        # 这里也要改用 self._config_entry
        current_config = {**self._config_entry.data, **self._config_entry.options}
        
        return self.async_show_form(
            step_id="init",
            data_schema=get_schema(current_config),
            errors=errors
        )