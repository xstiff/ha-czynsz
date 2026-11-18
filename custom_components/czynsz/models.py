"""Modele danych tomojdom.pl: wspólnoty, dokumenty kartoteki, wpłaty i stan konta."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


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
