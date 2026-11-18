"""Parsery odpowiedzi nieoficjalnego API tomojdom.pl (Weles3).

Odpowiedzi `/app/api/*` to drzewa węzłów `[klucz, *dane, dzieci]`: ostatni element to lista
dzieci albo `null` (tak jak `DataRoot` w `WlsCore/data.js` aplikacji).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .models import AccountData, Community, Document, Payment


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
