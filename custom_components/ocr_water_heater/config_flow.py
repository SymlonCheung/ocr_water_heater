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
    CONF_IMAGE_URL, CONF_UPDATE_INTERVAL, CONF_DEBUG_MODE, CONF_SKEW,
    DEFAULT_UPDATE_INTERVAL, DEFAULT_DEBUG_MODE, DEFAULT_SKEW,
    CONF_OCR_X, CONF_OCR_Y, CONF_OCR_W, CONF_OCR_H, DEFAULT_ROI_OCR,
    CONF_SET_X, CONF_SET_Y, CONF_SET_W, CONF_SET_H, DEFAULT_ROI_SETTING,
    CONF_LOW_X, CONF_LOW_Y, CONF_LOW_W, CONF_LOW_H, DEFAULT_ROI_LOW,
    CONF_HALF_X, CONF_HALF_Y, CONF_HALF_W, CONF_HALF_H, DEFAULT_ROI_HALF,
    CONF_FULL_X, CONF_FULL_Y, CONF_FULL_W, CONF_FULL_H, DEFAULT_ROI_FULL,
    DEFAULT_NAME
)

_LOGGER = logging.getLogger(__name__)

def get_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_IMAGE_URL, default=defaults.get(CONF_IMAGE_URL)): str,
            vol.Optional(CONF_UPDATE_INTERVAL, default=defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)): vol.All(vol.Coerce(int), vol.Range(min=100)),
            vol.Optional(CONF_SKEW, default=defaults.get(CONF_SKEW, DEFAULT_SKEW)): vol.Coerce(float),
            vol.Optional(CONF_DEBUG_MODE, default=defaults.get(CONF_DEBUG_MODE, DEFAULT_DEBUG_MODE)): bool,

            vol.Optional(CONF_OCR_X, default=defaults.get(CONF_OCR_X, DEFAULT_ROI_OCR[0])): int,
            vol.Optional(CONF_OCR_Y, default=defaults.get(CONF_OCR_Y, DEFAULT_ROI_OCR[1])): int,
            vol.Optional(CONF_OCR_W, default=defaults.get(CONF_OCR_W, DEFAULT_ROI_OCR[2])): int,
            vol.Optional(CONF_OCR_H, default=defaults.get(CONF_OCR_H, DEFAULT_ROI_OCR[3])): int,

            vol.Optional(CONF_SET_X, default=defaults.get(CONF_SET_X, DEFAULT_ROI_SETTING[0])): int,
            vol.Optional(CONF_SET_Y, default=defaults.get(CONF_SET_Y, DEFAULT_ROI_SETTING[1])): int,
            vol.Optional(CONF_SET_W, default=defaults.get(CONF_SET_W, DEFAULT_ROI_SETTING[2])): int,
            vol.Optional(CONF_SET_H, default=defaults.get(CONF_SET_H, DEFAULT_ROI_SETTING[3])): int,

            vol.Optional(CONF_LOW_X, default=defaults.get(CONF_LOW_X, DEFAULT_ROI_LOW[0])): int,
            vol.Optional(CONF_LOW_Y, default=defaults.get(CONF_LOW_Y, DEFAULT_ROI_LOW[1])): int,
            vol.Optional(CONF_LOW_W, default=defaults.get(CONF_LOW_W, DEFAULT_ROI_LOW[2])): int,
            vol.Optional(CONF_LOW_H, default=defaults.get(CONF_LOW_H, DEFAULT_ROI_LOW[3])): int,

            vol.Optional(CONF_HALF_X, default=defaults.get(CONF_HALF_X, DEFAULT_ROI_HALF[0])): int,
            vol.Optional(CONF_HALF_Y, default=defaults.get(CONF_HALF_Y, DEFAULT_ROI_HALF[1])): int,
            vol.Optional(CONF_HALF_W, default=defaults.get(CONF_HALF_W, DEFAULT_ROI_HALF[2])): int,
            vol.Optional(CONF_HALF_H, default=defaults.get(CONF_HALF_H, DEFAULT_ROI_HALF[3])): int,

            vol.Optional(CONF_FULL_X, default=defaults.get(CONF_FULL_X, DEFAULT_ROI_FULL[0])): int,
            vol.Optional(CONF_FULL_Y, default=defaults.get(CONF_FULL_Y, DEFAULT_ROI_FULL[1])): int,
            vol.Optional(CONF_FULL_W, default=defaults.get(CONF_FULL_W, DEFAULT_ROI_FULL[2])): int,
            vol.Optional(CONF_FULL_H, default=defaults.get(CONF_FULL_H, DEFAULT_ROI_FULL[3])): int,
        }
    )

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    session = aiohttp_client.async_get_clientsession(hass)
    try:
        async with session.get(data[CONF_IMAGE_URL], timeout=5) as resp:
            if resp.status != 200:
                raise ValueError(f"Could not connect, status: {resp.status}")
    except Exception as err:
        raise ValueError(f"Connection error: {err}") from err
    return {"title": DEFAULT_NAME}

class OCRWaterHeaterConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OCRWaterHeaterOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"

        defaults = {
            CONF_IMAGE_URL: "http://192.168.123.86:5000/api/reshuiqi/latest.jpg",
            CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_DEBUG_MODE: DEFAULT_DEBUG_MODE,
            CONF_SKEW: DEFAULT_SKEW,
            CONF_OCR_X: DEFAULT_ROI_OCR[0], CONF_OCR_Y: DEFAULT_ROI_OCR[1], CONF_OCR_W: DEFAULT_ROI_OCR[2], CONF_OCR_H: DEFAULT_ROI_OCR[3],
            CONF_SET_X: DEFAULT_ROI_SETTING[0], CONF_SET_Y: DEFAULT_ROI_SETTING[1], CONF_SET_W: DEFAULT_ROI_SETTING[2], CONF_SET_H: DEFAULT_ROI_SETTING[3],
            CONF_LOW_X: DEFAULT_ROI_LOW[0], CONF_LOW_Y: DEFAULT_ROI_LOW[1], CONF_LOW_W: DEFAULT_ROI_LOW[2], CONF_LOW_H: DEFAULT_ROI_LOW[3],
            CONF_HALF_X: DEFAULT_ROI_HALF[0], CONF_HALF_Y: DEFAULT_ROI_HALF[1], CONF_HALF_W: DEFAULT_ROI_HALF[2], CONF_HALF_H: DEFAULT_ROI_HALF[3],
            CONF_FULL_X: DEFAULT_ROI_FULL[0], CONF_FULL_Y: DEFAULT_ROI_FULL[1], CONF_FULL_W: DEFAULT_ROI_FULL[2], CONF_FULL_H: DEFAULT_ROI_FULL[3],
        }

        return self.async_show_form(
            step_id="user", data_schema=get_schema(defaults), errors=errors
        )

class OCRWaterHeaterOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_config = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=get_schema(current_config),
            errors=errors
        )