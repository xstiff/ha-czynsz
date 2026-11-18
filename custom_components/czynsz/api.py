"""Klient nieoficjalnego API tomojdom.pl (Weles3) i parsery odpowiedzi.

Odpowiedzi `/app/api/*` to drzewa węzłów `[klucz, *dane, dzieci]`: ostatni element to lista
dzieci albo `null` (tak jak `DataRoot` w `WlsCore/data.js` aplikacji).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import date, datetime
import json
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

MAIN_URL = "https://main.tomojdom.pl"
ORIGIN = "https://tomojdom.pl"
COOKIE_NAME = "JWTPhrase"  # token jest powiązany z tym ciasteczkiem (claim `fingerprint`)
TIMEOUT = aiohttp.ClientTimeout(total=30)


class TmdError(Exception):
    """Błąd komunikacji z tomojdom.pl."""


class TmdAuthError(TmdError):
    """Nieprawidłowe dane logowania albo wymagana zmiana hasła."""


@dataclass(slots=True)
class Document:
    """Pozycja kartoteki: zaliczka, rozliczenie, korekta…"""

    month: date
    due: date | None
    title: str
    amount: float  # dodatnia = do zapłaty, ujemna = zwrot

    @property
    def kind(self) -> str:
        lowered = self.title.casefold()
        if lowered.startswith("zaliczka"):
            return "zaliczka"
        if "rozliczenie" in lowered or "korekt" in lowered:
            return "rozliczenie"
        return "inne"

    @property
    def uid(self) -> str:
        return f"{self.month.isoformat()}|{self.due}|{self.title}"


@dataclass(slots=True)
class Payment:
    day: date
    amount: float
    title: str


@dataclass(slots=True)
class Community:
    """Wspólnota (lokal) przypisana do konta."""

    wid: int
    address: str
    years: list[int]


@dataclass(slots=True)
class AccountData:
    wid: int
    address: str
    monthly_since: date | None = None
    monthly_components: dict[str, float] = field(default_factory=dict)
    balance: float = 0.0  # dodatnie = nadpłata
    upcoming: list[tuple[date, float]] = field(default_factory=list)  # (termin, kwota do zapłaty)
    last_payment: date | None = None
    last_booking: date | None = None
    documents: list[Document] = field(default_factory=list)  # od najnowszych
    payments: list[Payment] = field(default_factory=list)  # od najnowszych

    @property
    def monthly_total(self) -> float:
        return round(sum(self.monthly_components.values()), 2)

    @property
    def to_pay(self) -> float:
        """Kwota do zapłaty po uwzględnieniu salda (jak „Razem” na stronie)."""
        return round(max(0.0, sum(amount for _, amount in self.upcoming) - self.balance), 2)

    @property
    def next_due(self) -> date | None:
        """Najbliższy termin, którego nie pokrywa nadpłata."""
        credit = self.balance
        for due, amount in self.upcoming:
            if amount <= credit:
                credit -= amount
                continue
            return due
        return None

    @property
    def last_settlement(self) -> Document | None:
        return next((d for d in self.documents if d.kind != "zaliczka"), None)


def _children(node: list) -> list[list]:
    last = node[-1] if node else None
    return last if isinstance(last, list) else []


def _data(node: list) -> list:
    return node[1:-1]


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        return None


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


def parse_communities(raw: list) -> list[Community]:
    result = []
    for owner in raw:
        for wm in _children(owner):
            d = _data(wm)
            years = [y for y in d[2:4] if isinstance(y, int)]
            last = max(years) if years else datetime.now().year
            first = min(years) if years else last
            # przy przełomie roku zaliczki z grudnia są jeszcze w poprzednim roku
            result.append(Community(wid=d[0], address=d[1], years=list(range(max(first, last - 1), last + 1))))
    return result


def parse_current_charges(raw: list, account: AccountData) -> None:
    """`ObciazeniaBiezace`: `[klucz, od, NTId, [[klucz, id, nazwa, kwota, null], …]]`."""
    if not raw:
        return
    root = raw[0]
    account.monthly_since = _date(_data(root)[0])
    components: dict[str, float] = {}
    for item in _children(root):
        d = _data(item)
        components[d[1]] = round(components.get(d[1], 0.0) + float(d[2]), 2)
    account.monthly_components = components


def parse_settlements(raw: list, account: AccountData) -> None:
    """`Rozliczenia`: konta bankowe z saldem i nadchodzącymi płatnościami."""
    balance = 0.0
    upcoming: list[tuple[date, float]] = []
    last_payment = last_booking = None
    for root in raw:
        for acc in _children(root):
            # [konto, ?, saldo dziś, suma nadchodzących, ostatnia wpłata, [nazwy], ostatnie księgowanie]
            d = _data(acc)
            balance += float(d[2] or 0)
            last_payment = max(filter(None, [last_payment, _date(d[4])]), default=None)
            last_booking = max(filter(None, [last_booking, _date(d[6])]), default=None)
            for item in _children(acc):
                amount, due = _data(item)[:2]
                if (due_date := _date(due)) is not None:
                    upcoming.append((due_date, round(-float(amount), 2)))
    account.balance = round(balance, 2)
    account.upcoming = sorted(upcoming)
    account.last_payment = last_payment
    account.last_booking = last_booking


def parse_ledger(raw: list) -> tuple[list[Document], list[Payment]]:
    """`RozliczeniaSzczegolowe`: miesiące `[klucz, miesiąc, obciążenia, ?, wpłaty, …, null]`.

    Obciążenie: `[termin, tytuł, kwota, NTId, rId, ?, dtId]`, wpłata: `[data, kwota, opis]`.
    """
    documents: list[Document] = []
    payments: list[Payment] = []
    for month_node in raw:
        d = _data(month_node)
        month = _date(d[0])
        if month is None:
            continue
        for charge in d[1] or []:
            documents.append(Document(month=month, due=_date(charge[0]), title=str(charge[1]).strip(), amount=float(charge[2])))
        for pay in d[3] or []:
            if (day := _date(pay[0])) is not None:
                payments.append(Payment(day=day, amount=float(pay[1]), title=str(pay[2]).strip()))
    documents.sort(key=lambda doc: (doc.month, doc.due or doc.month), reverse=True)
    payments.sort(key=lambda p: p.day, reverse=True)
    return documents, payments


class TmdClient:
    """Logowanie numerem użytkownika i hasłem; każda synchronizacja loguje się od nowa (JWT żyje 10 min)."""

    def __init__(self, session: aiohttp.ClientSession, user: int, password: str) -> None:
        self._session = session
        self._user = user
        self._password = password
        self._jwt: str | None = None
        self._cookie: str | None = None
        self._base: str | None = None

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
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise TmdError(f"{path}: {err}") from err

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
