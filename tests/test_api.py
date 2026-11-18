"""Testy parserów odpowiedzi tomojdom.pl."""
from datetime import date

from czynsz.api import AccountData, parse_communities, parse_current_charges, parse_ledger, parse_settlements


def build(tmd: dict) -> AccountData:
    account = AccountData(wid=7, address="TESTOWA 1-3")
    parse_current_charges(tmd["ObciazeniaBiezace"], account)
    parse_settlements(tmd["Rozliczenia"], account)
    account.documents, account.payments = parse_ledger(tmd["RozliczeniaSzczegolowe"])
    return account


def test_communities(tmd):
    [wm] = parse_communities(tmd["WmsOsoby"])
    assert (wm.wid, wm.address, wm.years) == (7, "TESTOWA 1-3", [2026])


def test_monthly_fee(tmd):
    account = build(tmd)
    assert account.monthly_since == date(2026, 10, 1)
    assert account.monthly_total == 381.5
    assert account.monthly_components["Media"] == 200.0


def test_balance_and_due(tmd):
    account = build(tmd)
    assert account.balance == 20.0
    assert account.upcoming == [(date(2026, 10, 5), 20.0), (date(2026, 10, 15), 381.5)]
    # korektę z 5.10 pokrywa nadpłata, więc liczy się zaliczka z 15.10
    assert account.to_pay == 381.5
    assert account.next_due == date(2026, 10, 15)
    assert account.last_payment == date(2026, 9, 16)


def test_ledger(tmd):
    account = build(tmd)
    assert [d.kind for d in account.documents] == ["zaliczka", "rozliczenie", "zaliczka"]
    settlement = account.last_settlement
    assert settlement.title == "Rozliczenie/korekta 1/KOR/26-06"
    assert settlement.amount == 20.0
    assert account.payments[0].amount == 401.5


def test_no_upcoming_when_balance_covers_all(tmd):
    account = build(tmd)
    account.balance = 500.0
    assert account.to_pay == 0.0
    assert account.next_due is None


def test_safe_base_url_accepts_tomojdom():
    from czynsz.api import safe_base_url
    assert safe_base_url("https://taurus.tomojdom.pl") == "https://taurus.tomojdom.pl"
    assert safe_base_url("https://taurus.tomojdom.pl/app/") == "https://taurus.tomojdom.pl"
    assert safe_base_url("https://TAURUS.tomojdom.pl") == "https://taurus.tomojdom.pl"


def test_safe_base_url_rejects_foreign_or_insecure():
    from czynsz.api import MAIN_URL, safe_base_url
    for bad in (None, "", 123, "http://taurus.tomojdom.pl", "https://evil.example.com",
                "https://tomojdom.pl.evil.com", "https://eviltomojdom.pl", "https://x@evil.com/.tomojdom.pl"):
        assert safe_base_url(bad) == MAIN_URL, bad


def test_iban_not_exposed(tmd):
    account = build(tmd)
    assert not hasattr(account, "iban")
