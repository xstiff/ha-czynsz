"""Kreator: numer użytkownika tomojdom.pl + hasło, z obsługą reauth."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import TmdAuthError, TmdClient, TmdError
from .const import CONF_USER, DOMAIN

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password"))


class CzynszConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _async_check(self, user: int, password: str) -> str | None:
        client = TmdClient(async_get_clientsession(self.hass), user, password)
        try:
            await client.async_login()
        except TmdAuthError:
            return "invalid_auth"
        except TmdError as err:
            _LOGGER.warning("Logowanie do tomojdom.pl nieudane: %s", err)
            return "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            raw_user = str(user_input[CONF_USER]).strip()
            if not raw_user.isdigit() or not 0 < int(raw_user) <= 2147483647:
                errors[CONF_USER] = "invalid_user"
            else:
                user = int(raw_user)
                await self.async_set_unique_id(f"tmd_{user}")
                self._abort_if_unique_id_configured()
                if (error := await self._async_check(user, user_input[CONF_PASSWORD])) is None:
                    return self.async_create_entry(
                        title=f"tomojdom.pl {user}",
                        data={CONF_USER: user, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    )
                errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_USER): str, vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._async_check(entry.data[CONF_USER], user_input[CONF_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]})
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"user": str(entry.data[CONF_USER])},
            errors=errors,
        )
