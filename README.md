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

### Interaktive Dokumentation

Die automatisch erzeugte API-Dokumentation ist verfügbar unter:

```text
http://localhost:8000/docs
```
