"""Okresowe pobieranie czynszu i wykrywanie nowych rozliczeń."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AccountData, TmdAuthError, TmdClient, TmdError
from .const import DOMAIN, EVENT_NEW_SETTLEMENT, PORTAL_URL, STORAGE_VERSION, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class CzynszCoordinator(DataUpdateCoordinator[dict[int, AccountData]]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: TmdClient) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.client = client
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._seen: set[str] | None = None

    async def _async_update_data(self) -> dict[int, AccountData]:
        try:
            data = await self.client.async_fetch()
        except TmdAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TmdError as err:
            raise UpdateFailed(str(err)) from err
        await self._async_detect_new(data)
        return data

    async def _async_detect_new(self, data: dict[int, AccountData]) -> None:
        if self._seen is None:
            stored = await self._store.async_load()
            self._seen = set(stored["seen"]) if stored else None
        # pierwsze uruchomienie tylko zapamiętuje istniejące dokumenty, bez powiadomień
        initial = self._seen is None
        seen = self._seen or set()
        current: set[str] = set()
        for account in data.values():
            for doc in account.documents:
                uid = f"{account.wid}|{doc.uid}"
                current.add(uid)
                if initial or uid in seen or doc.kind == "zaliczka":
                    continue
                _LOGGER.info("Nowe rozliczenie: %s", doc.title)
                self.hass.bus.async_fire(
                    EVENT_NEW_SETTLEMENT,
                    {
                        "wid": account.wid,
                        "address": account.address,
                        "title": doc.title,
                        "kind": doc.kind,
                        "amount": doc.amount,
                        "refund": doc.amount < 0,
                        "due": doc.due.isoformat() if doc.due else None,
                        "month": doc.month.isoformat(),
                        "to_pay": account.to_pay,
                        "balance": account.balance,
                        "url": PORTAL_URL,
                    },
                )
        # zostawiamy też stare wpisy — kartoteka pokazuje tylko bieżący i poprzedni rok
        merged = seen | current
        if merged != self._seen:
            self._seen = merged
            await self._store.async_save({"seen": sorted(merged)})
