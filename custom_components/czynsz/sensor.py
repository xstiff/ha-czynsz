"""Sensory czynszu: opłata miesięczna, do zapłaty, saldo, termin, ostatnie rozliczenie."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CzynszConfigEntry
from .api import AccountData
from .const import DOMAIN, PORTAL_URL
from .coordinator import CzynszCoordinator

CURRENCY = "PLN"


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _upcoming(acc: AccountData) -> list[dict]:
    titles = {doc.due: doc.title for doc in acc.documents}
    return [{"termin": d.isoformat(), "kwota": amount, "tytul": titles.get(d)} for d, amount in acc.upcoming]


def _settlement_attrs(acc: AccountData) -> dict[str, Any]:
    doc = acc.last_settlement
    if doc is None:
        return {}
    return {"tytul": doc.title, "rodzaj": doc.kind, "miesiac": _iso(doc.month), "termin": _iso(doc.due), "zwrot": doc.amount < 0}


@dataclass(frozen=True, kw_only=True)
class CzynszSensorDescription(SensorEntityDescription):
    value_fn: Callable[[AccountData], Any]
    attrs_fn: Callable[[AccountData], dict[str, Any]] = lambda _: {}


SENSORS: tuple[CzynszSensorDescription, ...] = (
    CzynszSensorDescription(
        key="oplata_miesieczna",
        translation_key="oplata_miesieczna",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY,
        suggested_display_precision=2,
        value_fn=lambda a: a.monthly_total if a.monthly_components else None,
        attrs_fn=lambda a: {"od": _iso(a.monthly_since), "skladniki": a.monthly_components},
    ),
    CzynszSensorDescription(
        key="do_zaplaty",
        translation_key="do_zaplaty",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY,
        suggested_display_precision=2,
        value_fn=lambda a: a.to_pay,
        attrs_fn=lambda a: {"nadchodzace": _upcoming(a), "konto": a.iban, "saldo": a.balance},
    ),
    CzynszSensorDescription(
        key="saldo",
        translation_key="saldo",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY,
        suggested_display_precision=2,
        value_fn=lambda a: a.balance,
        attrs_fn=lambda a: {
            "ostatnia_wplata": _iso(a.last_payment),
            "ostatnia_wplata_kwota": a.payments[0].amount if a.payments else None,
            "ostatnie_ksiegowanie": _iso(a.last_booking),
        },
    ),
    CzynszSensorDescription(
        key="termin_platnosci",
        translation_key="termin_platnosci",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda a: a.next_due,
    ),
    CzynszSensorDescription(
        key="ostatnie_rozliczenie",
        translation_key="ostatnie_rozliczenie",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY,
        suggested_display_precision=2,
        value_fn=lambda a: a.last_settlement.amount if a.last_settlement else None,
        attrs_fn=_settlement_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: CzynszConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    single = len(coordinator.data) == 1
    async_add_entities(
        CzynszSensor(coordinator, wid, desc, single) for wid in coordinator.data for desc in SENSORS
    )


class CzynszSensor(CoordinatorEntity[CzynszCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: CzynszSensorDescription

    def __init__(self, coordinator: CzynszCoordinator, wid: int, description: CzynszSensorDescription, single: bool) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._wid = wid
        address = coordinator.data[wid].address
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{wid}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.config_entry.unique_id}_{wid}")},
            name="Czynsz" if single else f"Czynsz {address}",
            model=address,
            manufacturer="tomojdom.pl (Weles3)",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=PORTAL_URL,
        )

    @property
    def _account(self) -> AccountData | None:
        return self.coordinator.data.get(self._wid)

    @property
    def available(self) -> bool:
        return super().available and self._account is not None

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._account) if self._account else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attrs_fn(self._account) if self._account else None
