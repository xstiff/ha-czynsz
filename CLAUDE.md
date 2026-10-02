# Czynsz — przewodnik dla Claude Code

Custom integration HA pobierająca opłaty za mieszkanie z tomojdom.pl (Weles3, Weles sp. z o.o.). Zasady współpracy: `~/Projects/homeassistant/CLAUDE.md`.

## Architektura (`custom_components/czynsz/`)
- `api.py`: `TmdClient` (aiohttp) i czyste parsery (`parse_communities`, `parse_current_charges`, `parse_settlements`, `parse_ledger`) → `AccountData`. Kwoty jako float PLN (zaokrąglane do 2 miejsc).
  - `AccountData.to_pay` = suma nadchodzących − saldo (≥ 0); `next_due` pomija pozycje pokryte nadpłatą; `last_settlement` = najnowszy dokument nie-zaliczka.
  - `Document.kind`: `zaliczka` (tytuł „Zaliczka …”), `rozliczenie` („Rozliczenie”/„korekt”), `inne`.
- `coordinator.py`: co 6 h `async_fetch` (za każdym razem świeże logowanie). Widziane dokumenty w `Store` `.storage/czynsz.<entry_id>`; nowe nie-zaliczki → event `czynsz_new_settlement`. Pierwszy przebieg bez eventów.
- `sensor.py`: 5 sensorów na wspólnotę (`WId`), urządzenie „Czynsz” (przy kilku wspólnotach z adresem).
- `config_flow.py`: numer użytkownika (int) + hasło, `unique_id` = `tmd_<numer>`, reauth (tylko hasło). Hasło w `entry.data`, bo JWT żyje 10 min.

## Nieoficjalne API tomojdom.pl (rozpoznane 2026-10-02 z JS `/jsnew/es/LoginTMD/*`, `/jsnew/es/TMDApp/*`)
1. `POST https://main.tomojdom.pl/login/OsLogInPass` JSON `{"User": <int>, "Pass": "…"}` (bez reCAPTCHA — ta jest tylko przy logowaniu kodem z maila).
   - Odpowiedź: `[id, url serwera w3os, JWT, wymagana_zmiana_hasła, InfoPass, ?]`; **Set-Cookie `JWTPhrase` (domena `.tomojdom.pl`) — bez niego API zwraca 403** (JWT ma claim `fingerprint`).
   - JWT: `url` = serwer API (np. `https://taurus.tomojdom.pl`), `aud` = `https://tomojdom.pl/app/`, `ttl` 10 min, `maxcnt` 150 odświeżeń (`/app/api/Token`), `limit`.
2. Wywołania: zawsze `POST <url>/app/api/<Nazwa>`, treść JSON (bez parametrów `null`), nagłówki `Authorization: Bearer`, `Test: 0`, `Origin: https://tomojdom.pl`.
3. Odpowiedzi to drzewa `[klucz, *dane, dzieci|null]`:
   - `WmsOsoby` → właściciel → wspólnoty `[WId, adres, rok, rok, …]`;
   - `ObciazeniaBiezace` (param `WId`) → `[k, od, NTId, [[p, id, składnik, kwota, null]…]]`;
   - `Rozliczenia` (param `WId`) → `["o", …, [konto: [k, IBAN, ?, saldo, suma_nadchodzących, ostatnia_wpłata, [nazwy], ostatnie_księgowanie, [[l, -kwota, termin, null]…]]]]`;
   - `RozliczeniaSzczegolowe` (`{"WId", "Rok"}`) → miesiące `[m, miesiąc, obciążenia[[termin, tytuł, kwota, NTId, rId, ?, dtId]], ?, wpłaty[[data, kwota, opis]], ?, podsumowanie, ?, null]`.
   - Inne: `DaneLokali` (liczniki, powierzchnia), `WydrukObciazenia`/`WydrukDokument`/`WydrukKartoteka` (PDF), `Zgloszenia`, `Uchwaly*`, `Ankiety*`.

## Narzędzia
- `tools/tmd_discover.py`: `login` (getpass albo `TMD_USER`/`TMD_PASS`; uruchamiać w osobnym terminalu, `!` w Claude Code nie ma stdin), `token`, `js` (pobiera moduły i listę endpointów), `call <ścieżka> [json]`. Wszystko trafia do `.secrets/` (gitignored, chmod 600).

## Testy
`.venv/bin/pytest` (można użyć venv z `~/Projects/ha-paragony`). `tests/fixtures/tmd_responses.json` jest **syntetyczny** — nie commituj prawdziwych odpowiedzi (adres, IBAN, numer użytkownika).

## Powiązane
- Automatyzacja powiadomienia: `~/Projects/homeassistant/czynsz-rozliczenie.yaml` (id `czynsz_nowe_rozliczenie`, `notify.mobile_app_iphone_17_michal`).
