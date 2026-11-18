"""Diagnostyka (Ustawienia → Urządzenia → Czynsz → Pobierz diagnostykę), z anonimizacją.

Usuwane: numer użytkownika, hasło, imię i nazwisko oraz adres (cała odpowiedź `WmsOsoby`),
adres lokalu wszędzie indziej, numery kont / długie ciągi cyfr, opisy wpłat (mogą zawierać
dane płatnika). Zostają kwoty, daty i tytuły obciążeń — potrzebne do diagnozy parserów.
"""
from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import CzynszConfigEntry
from .const import CONF_USER

REDACTED = "**REDACTED**"
_LONG_DIGITS = re.compile(r"\d{12,}")


def _scrub(value: Any, addresses: set[str], *, all_values: bool = False, user: int | None = None) -> Any:
    """`all_values=True` zostawia tylko strukturę (listy/słowniki), wszystkie wartości → znacznik."""
    if isinstance(value, list):
        return [_scrub(item, addresses, all_values=all_values, user=user) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item, addresses, all_values=all_values, user=user) for key, item in value.items()}
    if all_values and value is not None and not isinstance(value, bool):
        return REDACTED
    if user is not None and isinstance(value, int) and not isinstance(value, bool) and value == user:
        return REDACTED
    if isinstance(value, str):
        if user is not None:
            value = value.replace(str(user), REDACTED)
        for address in addresses:
            if address:
                value = value.replace(address, REDACTED)
        return _LONG_DIGITS.sub(REDACTED, value)
    return value


def _scrub_ledger(body: Any, addresses: set[str], user: int | None) -> Any:
    """`RozliczeniaSzczegolowe`: opisy wpłat (`[data, kwota, opis]`) zastępujemy znacznikiem."""
    body = _scrub(body, addresses, user=user)
    if not isinstance(body, list):
        return body
    for month in body:
        if isinstance(month, list) and len(month) > 4 and isinstance(month[4], list):
            for pay in month[4]:
                if isinstance(pay, list) and len(pay) > 2:
                    pay[2] = REDACTED
    return body


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: CzynszConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    accounts = coordinator.data or {}
    addresses = {acc.address for acc in accounts.values()}
    user = entry.data.get(CONF_USER)
    raw: dict[str, Any] = {}
    for key, body in coordinator.client.last_responses.items():
        if key.startswith("/app/api/WmsOsoby"):
            raw[key] = _scrub(body, addresses, all_values=True)
        elif key.startswith("/app/api/RozliczeniaSzczegolowe"):
            raw[key] = _scrub_ledger(body, addresses, user)
        else:
            raw[key] = _scrub(body, addresses, user=user)
    return {
        "entry": async_redact_data(dict(entry.data), {CONF_USER, CONF_PASSWORD}),
        "last_update_success": coordinator.last_update_success,
        "accounts": [
            {
                **_scrub({k: v for k, v in asdict(acc).items() if k not in ("address", "payments")}, addresses, user=user),
                "payments": [{"day": p.day, "amount": p.amount} for p in acc.payments],
            }
            for acc in accounts.values()
        ],
        "raw_responses": raw,
    }
