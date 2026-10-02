# Czynsz — opłaty z tomojdom.pl w Home Assistant

Custom integration pobierająca z portalu **tomojdom.pl** (system Weles3) bieżący czynsz, saldo,
nadchodzące płatności i kartotekę dokumentów. Gdy w kartotece pojawi się **rozliczenie lub korekta**,
wysyła event `czynsz_new_settlement`, który można zamienić na powiadomienie w telefonie.

> Integracja korzysta z nieoficjalnego API portalu i może przestać działać po zmianach po stronie Weles3.

## Instalacja
1. Skopiuj `custom_components/czynsz` do `/config/custom_components/` (albo HACS → *Custom repositories*).
2. Zrestartuj Home Assistant.
3. Ustawienia → Urządzenia i usługi → Dodaj integrację → **Czynsz (tomojdom.pl)** → numer użytkownika i hasło
   (to samo logowanie co na stronie; logowanie samym e-mailem z kodem nie jest obsługiwane).

Dane odświeżane są co 6 h; natychmiast — akcją `czynsz.refresh`.

## Encje (urządzenie „Czynsz”)
| Encja | Opis |
|---|---|
| `sensor.czynsz_oplata_miesieczna` | bieżąca opłata miesięczna; atrybuty `od`, `skladniki` (media, eksploatacja, fundusz remontowy…) |
| `sensor.czynsz_do_zaplaty` | kwota do zapłaty po uwzględnieniu nadpłaty; atrybuty `nadchodzace` (termin, kwota, tytuł), `konto`, `saldo` |
| `sensor.czynsz_saldo` | saldo na dziś (dodatnie = nadpłata, ujemne = zaległość); data i kwota ostatniej wpłaty |
| `sensor.czynsz_termin_platnosci` | najbliższy termin płatności niepokryty nadpłatą |
| `sensor.czynsz_ostatnie_rozliczenie` | kwota ostatniego rozliczenia/korekty (ujemna = zwrot); atrybuty `tytul`, `miesiac`, `termin` |

## Event `czynsz_new_settlement`
Wysyłany dla każdej nowej pozycji kartoteki, która nie jest zwykłą zaliczką (rozliczenie, korekta, nota).
Pierwsza synchronizacja tylko zapamiętuje istniejące dokumenty. Dane: `title`, `kind`, `amount`, `refund`,
`due`, `month`, `to_pay`, `balance`, `address`, `url`.

Przykładowa automatyzacja:
```yaml
triggers:
  - trigger: event
    event_type: czynsz_new_settlement
actions:
  - action: notify.mobile_app_telefon
    data:
      title: "Nowe rozliczenie czynszu"
      message: "{{ trigger.event.data.title }}: {{ trigger.event.data.amount }} zł"
      data:
        url: "{{ trigger.event.data.url }}"
```

## Testy
```bash
python3 -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/pytest
```
