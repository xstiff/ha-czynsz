"""Klient HTTP tomojdom.pl: logowanie numerem użytkownika i hasłem, wywołania `/app/api/*`."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .models import AccountData
from .parsers import parse_communities, parse_current_charges, parse_ledger, parse_settlements

_LOGGER = logging.getLogger(__name__)

MAIN_URL = "https://main.tomojdom.pl"
ORIGIN = "https://tomojdom.pl"
COOKIE_NAME = "JWTPhrase"  # token jest powiązany z tym ciasteczkiem (claim `fingerprint`)
TIMEOUT = aiohttp.ClientTimeout(total=30)


class TmdError(Exception):
    """Błąd komunikacji z tomojdom.pl."""


class TmdAuthError(TmdError):
    """Nieprawidłowe dane logowania albo wymagana zmiana hasła."""


def jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def safe_base_url(url: Any) -> str:
    """Adres serwera API z claimu `url` JWT — tylko https://*.tomojdom.pl, inaczej serwer główny.

    Na ten adres wysyłany jest token i ciasteczko `JWTPhrase`, więc nie ufamy niezweryfikowanemu
    claimowi bez sprawdzenia schematu i domeny.
    """
    if not isinstance(url, str):
        return MAIN_URL
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "tomojdom.pl" or host.endswith(".tomojdom.pl")):
        if url:
            _LOGGER.warning("Pomijam nieoczekiwany adres serwera API z tokenu: %s", url)
        return MAIN_URL
    return f"https://{host}" + (f":{parsed.port}" if parsed.port else "")


class TmdClient:
    """Logowanie numerem użytkownika i hasłem; każda synchronizacja loguje się od nowa (JWT żyje 10 min)."""

    def __init__(self, session: aiohttp.ClientSession, user: int, password: str) -> None:
        self._session = session
        self._user = user
        self._password = password
        self._jwt: str | None = None
        self._cookie: str | None = None
        self._base: str | None = None
        self.last_responses: dict[str, Any] = {}

    async def async_login(self) -> None:
        try:
            async with self._session.post(
                f"{MAIN_URL}/login/OsLogInPass",
                json={"User": self._user, "Pass": self._password},
                headers={"Origin": ORIGIN, "Referer": f"{ORIGIN}/"},
                timeout=TIMEOUT,
            ) as resp:
                # tylko odrzucenie danych logowania to błąd uwierzytelnienia; 429 (limit) i inne
                # błędy 4xx/5xx są przejściowe i nie powinny wymuszać ponownego podania hasła
                if resp.status in (400, 401, 403):
                    raise TmdAuthError(f"logowanie odrzucone (HTTP {resp.status})")
                if resp.status != 200:
                    raise TmdError(f"logowanie: HTTP {resp.status}")
                body = await resp.json(content_type=None)
                cookie = resp.cookies.get(COOKIE_NAME)
        except aiohttp.ClientError as err:
            raise TmdError(f"logowanie: {err}") from err
        if not isinstance(body, list) or len(body) < 4 or not isinstance(body[2], str):
            raise TmdError("logowanie: nieoczekiwana odpowiedź")
        if body[3]:
            raise TmdAuthError("tomojdom.pl wymaga zmiany hasła — zmień je na stronie")
        self._jwt = body[2]
        self._cookie = cookie.value if cookie else None
        self._base = safe_base_url(jwt_claims(self._jwt).get("url"))

    async def _call(self, path: str, payload: Any = None, *, retry: bool = True) -> Any:
        if self._jwt is None:
            await self.async_login()
        try:
            async with self._session.post(
                f"{self._base}{path}",
                data=json.dumps(payload),
                headers={
                    "Authorization": f"Bearer {self._jwt}",
                    "Content-Type": "application/json",
                    "Test": "0",
                    "Origin": ORIGIN,
                    "Referer": f"{ORIGIN}/app/",
                },
                cookies={COOKIE_NAME: self._cookie} if self._cookie else None,
                timeout=TIMEOUT,
            ) as resp:
                if resp.status in (401, 403) and retry:
                    self._jwt = None
                    return await self._call(path, payload, retry=False)
                if resp.status != 200:
                    raise TmdError(f"{path}: HTTP {resp.status}")
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise TmdError(f"{path}: {err}") from err
        # ostatnie surowe odpowiedzi — tylko do diagnostyki (diagnostics.py je anonimizuje)
        self.last_responses[f"{path} {json.dumps(payload)}"] = body
        return body

    async def async_fetch(self) -> dict[int, AccountData]:
        await self.async_login()
        result: dict[int, AccountData] = {}
        for wm in parse_communities(await self._call("/app/api/WmsOsoby")):
            account = AccountData(wid=wm.wid, address=wm.address)
            parse_current_charges(await self._call("/app/api/ObciazeniaBiezace", wm.wid), account)
            parse_settlements(await self._call("/app/api/Rozliczenia", wm.wid), account)
            for year in wm.years:
                docs, pays = parse_ledger(await self._call("/app/api/RozliczeniaSzczegolowe", {"WId": wm.wid, "Rok": year}))
                account.documents.extend(docs)
                account.payments.extend(pays)
            account.documents.sort(key=lambda doc: (doc.month, doc.due or doc.month), reverse=True)
            account.payments.sort(key=lambda p: p.day, reverse=True)
            result[wm.wid] = account
        return result
