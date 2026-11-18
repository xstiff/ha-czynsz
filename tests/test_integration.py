"""Testy integracji w prawdziwym Home Assistancie z podmienionym API tomojdom.pl."""
import base64
import copy
import json
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.czynsz.client import MAIN_URL, TmdAuthError, TmdClient
from custom_components.czynsz.const import DOMAIN, EVENT_NEW_SETTLEMENT

CLIENT = "custom_components.czynsz.client.TmdClient"
SERVER = "https://test.tomojdom.pl"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def fake_jwt() -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"url": SERVER, "ttl": "10"}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def mock_api(aioclient_mock, tmd: dict) -> None:
    aioclient_mock.post(
        f"{MAIN_URL}/login/OsLogInPass",
        json=[1, "https://test.e-adm.pl/w3os/", fake_jwt(), False, "x", None],
        cookies={"JWTPhrase": "phrase"},
    )
    aioclient_mock.post(f"{SERVER}/app/api/WmsOsoby", json=tmd["WmsOsoby"])
    aioclient_mock.post(f"{SERVER}/app/api/ObciazeniaBiezace", json=tmd["ObciazeniaBiezace"])
    aioclient_mock.post(f"{SERVER}/app/api/Rozliczenia", json=tmd["Rozliczenia"])
    aioclient_mock.post(f"{SERVER}/app/api/RozliczeniaSzczegolowe", json=tmd["RozliczeniaSzczegolowe"])


def make_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="tmd_1000001", title="tomojdom.pl", data={"user": 1000001, "password": "haslo"}
    )
    entry.add_to_hass(hass)
    return entry


async def test_client_login_and_fetch(hass: HomeAssistant, aioclient_mock, tmd) -> None:
    mock_api(aioclient_mock, tmd)
    client = TmdClient(async_get_clientsession(hass), 1000001, "haslo")
    data = await client.async_fetch()

    login_call = aioclient_mock.mock_calls[0]
    assert login_call[2] == {"User": 1000001, "Pass": "haslo"}
    _, url, body, headers = aioclient_mock.mock_calls[-1]
    assert str(url) == f"{SERVER}/app/api/RozliczeniaSzczegolowe"
    assert json.loads(body) == {"WId": 7, "Rok": 2026}
    assert headers["Authorization"] == f"Bearer {fake_jwt()}"
    assert data[7].to_pay == 381.5


async def test_client_bad_password(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(f"{MAIN_URL}/login/OsLogInPass", status=403)
    client = TmdClient(async_get_clientsession(hass), 1, "zle")
    with pytest.raises(TmdAuthError):
        await client.async_login()


async def test_config_flow(hass: HomeAssistant) -> None:
    with (
        patch(f"{CLIENT}.async_login", AsyncMock(side_effect=[TmdAuthError("x"), None])),
        patch("custom_components.czynsz.async_setup_entry", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"user": "abc", "password": "x"})
        assert result["errors"] == {"user": "invalid_user"}
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"user": "1000001", "password": "zle"})
        assert result["errors"] == {"base": "invalid_auth"}
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"user": "1000001", "password": "dobre"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"user": 1000001, "password": "dobre"}
    assert result["result"].unique_id == "tmd_1000001"


async def test_sensors_and_settlement_event(hass: HomeAssistant, aioclient_mock, tmd) -> None:
    events = async_capture_events(hass, EVENT_NEW_SETTLEMENT)
    hass.config.language = "pl"
    entry = make_entry(hass)
    mock_api(aioclient_mock, tmd)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    fee = hass.states.get("sensor.czynsz_oplata_miesieczna")
    assert fee.state == "381.5"
    assert fee.attributes["skladniki"]["Fundusz remontowy"] == 30.0
    assert hass.states.get("sensor.czynsz_do_zaplaty").state == "381.5"
    assert hass.states.get("sensor.czynsz_saldo").state == "20.0"
    assert hass.states.get("sensor.czynsz_termin_platnosci").state == "2026-10-15"
    last = hass.states.get("sensor.czynsz_ostatnie_rozliczenie")
    assert last.state == "20.0"
    assert last.attributes["tytul"] == "Rozliczenie/korekta 1/KOR/26-06"
    # pierwsza synchronizacja nie powiadamia o istniejących dokumentach
    assert events == []

    # w kartotece pojawia się nowe rozliczenie (zwrot) i nowa zaliczka
    updated = copy.deepcopy(tmd)
    updated["RozliczeniaSzczegolowe"][0][2].append(
        ["2026-10-20T00:00:00", "Rozliczenie mediów 9/ROZ/26", -55.25, 1, 2, None, 1]
    )
    updated["RozliczeniaSzczegolowe"][0][2].append(["2026-11-15T00:00:00", "Zaliczka 4/ZAL/26-11", 381.5, 1, None, None, 1])
    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, updated)
    await hass.services.async_call(DOMAIN, "refresh", blocking=True)
    await hass.async_block_till_done()

    assert len(events) == 1
    data = events[0].data
    assert data["title"] == "Rozliczenie mediów 9/ROZ/26"
    assert data["amount"] == -55.25
    assert data["refund"] is True
    assert data["due"] == "2026-10-20"

    # stan „widzianych” dokumentów przetrwa restart — bez ponownego powiadomienia
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_auth_error_starts_reauth(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    with patch(f"{CLIENT}.async_fetch", AsyncMock(side_effect=TmdAuthError("x"))):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert flows and flows[0]["context"]["source"] == config_entries.SOURCE_REAUTH
