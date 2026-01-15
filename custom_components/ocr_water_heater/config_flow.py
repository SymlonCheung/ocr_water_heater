"""Config flow for OCR Water Heater integration."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .const import (
    DOMAIN,
    CONF_IMAGE_URL, CONF_ROI_X, CONF_ROI_Y, CONF_ROI_W, CONF_ROI_H, CONF_SKEW,
    CONF_UPDATE_INTERVAL,  # <--- 记得导入这个
    DEFAULT_NAME, DEFAULT_ROI, DEFAULT_SKEW,
    DEFAULT_UPDATE_INTERVAL # <--- 记得导入这个
)

_LOGGER = logging.getLogger(__name__)

# 定义界面表单结构
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IMAGE_URL, default="http://192.168.123.86:1984/api/frame.jpeg?src=reshuiqi"): str,
        vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=1)),
        # 建议对 int 也加上 Coerce，防止前端偶尔传回字符串
        vol.Optional(CONF_ROI_X, default=DEFAULT_ROI[0]): vol.Coerce(int),
        vol.Optional(CONF_ROI_Y, default=DEFAULT_ROI[1]): vol.Coerce(int),
        vol.Optional(CONF_ROI_W, default=DEFAULT_ROI[2]): vol.Coerce(int),
        vol.Optional(CONF_ROI_H, default=DEFAULT_ROI[3]): vol.Coerce(int),
        # 必须修改下面这行，将 float 改为 vol.Coerce(float)
        vol.Optional(CONF_SKEW, default=DEFAULT_SKEW): vol.Coerce(float),
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )