## Start

```bash
uv run main.py
```

Die API ist danach unter `http://localhost:8000` erreichbar. Eine Autorisierung ist nicht erforderlich.
Die interaktive Dokumentation gibt es unter `http://localhost:8000/docs`.

## API-Endpunkte

Alle Endpunkte verwenden `GET`. Eine Autorisierung ist nicht erforderlich.

### Status

```text
GET /health
GET /api/status
```

Beide Endpunkte liefern zum Beispiel:

```json
{"status":"ok","data":"loaded"}
```

### Sammlung abfragen

```text
GET /api/v1/{collection}
```

Verfügbare Collections:

| Collection | ID-Feld |
| --- | --- |
| `accounts` | `account_id` |
| `account-balances` | `account_id` |
| `employers` | `employer_id` |
| `events` | `event_id` |
| `transactions` | `txn_id` |
| `interactions` | `interaction_id` |
| `individuals` | `individual_id` |
| `individual-states` | `individual_id` |

Unterstützte Query-Parameter:

| Parameter | Bedeutung | Standard |
| --- | --- | --- |
| `limit` | Anzahl der Ergebnisse, maximal `1000` | `100` |
| `offset` | Anzahl übersprungener Ergebnisse | `0` |
| `run_id` | Nach Run filtern | kein Filter |
| `period` | Nach Zeitraum filtern | kein Filter |
| `individual_id` | Nach Person filtern | kein Filter |
| `account_id` | Nach Konto filtern | kein Filter |

Die Antwort enthält `collection`, `total`, `offset`, `limit` und `items`:

```bash
curl 'http://localhost:8000/api/v1/accounts?limit=5'
curl 'http://localhost:8000/api/v1/transactions?period=1&limit=10'
curl 'http://localhost:8000/api/v1/events?individual_id=INDIVIDUAL_ID&offset=0&limit=20'
```

### Einzelnes Objekt abfragen

```text
GET /api/v1/{collection}/{item_id}
```

Beispiele:

```bash
curl 'http://localhost:8000/api/v1/accounts/ACCOUNT_ID'
curl 'http://localhost:8000/api/v1/transactions/TXN_ID'
curl 'http://localhost:8000/api/v1/events/EVENT_ID?run_id=RUN_ID'
```

Bei Collections mit mehreren Einträgen derselben ID, zum Beispiel `account-balances` oder `individuals`, liefert der Endpunkt eine `items`-Liste zurück. Mit `run_id` kann das Ergebnis zusätzlich eingeschränkt werden.

### Features und Empfehlungen

Für die AI-Anbindung werden pro Kunde aggregierte Features und erklärbare Next-Best-Action-Empfehlungen angeboten:

```text
GET /api/v1/individuals/{individual_id}/features
GET /api/v1/individuals/{individual_id}/recommendations
```

Beispiele:

```bash
curl 'http://localhost:8000/api/v1/individuals/INDIVIDUAL_ID/features'
curl 'http://localhost:8000/api/v1/individuals/INDIVIDUAL_ID/recommendations'
```

Die Feature-Antwort enthält unter anderem Alter, Einkommen, Beschäftigung, Konten, aktuelle Salden, Transaktionssummen, Interaktionen, Stress und `has_pillar3a`. Die Empfehlungen enthalten jeweils `action`, `score` und `reasons`.

Die Features werden beim ersten Aufruf berechnet und anschließend im Speicher gecacht.

Für das AI-Projekt sind diese Scoring-Elemente vorgesehen:

- `offer_savings_account`: Sparkonto, Saldo und Einkommen
- `offer_pillar3a`: Alter, Beschäftigung, Einkommen und vorhandenes 3a-Produkt
- `offer_mortgage`: Alter, Eigenkapital/Saldo und Familienstand
- `offer_investment`: Saldo, negative Salden und Anlagehorizont
- `retention_call`: geschlossene Konten, negative Salden und offene Interaktionen
- `upsell_premium`: Anzahl Konten, Produktvielfalt und Saldo
- `financial_advice`: Stress, Ausgabenkategorie und negative Salden
- `retirement_planning`: Alter/Ruhestand, vorhandene Vorsorge und Beratungshistorie

Jede Empfehlung muss neben dem numerischen `score` nachvollziehbare `reasons` zurückgeben. Die Scores sind aktuell regelbasiert und dienen als erklärbare Baseline für ein späteres ML- oder LLM-Modell.

### Interaktive Dokumentation

Die automatisch erzeugte API-Dokumentation ist verfügbar unter:

```text
http://localhost:8000/docs
```
