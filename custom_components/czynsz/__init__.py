"""Czynsz — opłaty za mieszkanie z tomojdom.pl (Weles3) w Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .client import TmdClient
from .const import CONF_USER, DOMAIN, SERVICE_REFRESH, STORAGE_VERSION
from .coordinator import CzynszCoordinator

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type CzynszConfigEntry = ConfigEntry[CzynszCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def async_refresh(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await entry.runtime_data.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, async_refresh)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CzynszConfigEntry) -> bool:
    client = TmdClient(async_get_clientsession(hass), entry.data[CONF_USER], entry.data[CONF_PASSWORD])
    coordinator = CzynszCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CzynszConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
