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

Die Feature-Antwort enthält unter anderem Alter, Einkommen, Beschäftigung, Konten, aktuelle Salden, Transaktionssummen, Interaktionen, Stress, `has_pillar3a` und `product_inventory`. Das Inventar enthält bereits vorhandene Produktnamen und Kontotypen.

Die Recommendation-Antwort enthält zusätzlich `product_suggestions`. Diese ordnen einer Action ein konkretes Produkt aus dem Katalog zu und schlagen keine Produkte vor, die der Kunde bereits besitzt.

Erkannte Produkte sind unter anderem:

```text
Privatkonto, Sparkonto, Sparkonto Young, Jugendkonto, Jugendsparkonto
Säule 3a-Konto, Säule 3a Fondssparplan, Lebensversicherung 3a
Festhypothek
Anlagesparkonto, Anlagekonto, Fondssparplan, Wertschriftendepot
Freizügigkeitskonto, Kreditkarte Visa/Mastercard, Rechtsschutzversicherung
```

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

## Response-Modell mit 7-Tage-Fenster

Das Modul `src/response_model.py` erzeugt Trainingsbeispiele aus Events und Transaktionen. Für jede Kunden-/Action-Kombination wird geprüft, ob zwischen dem Beobachtungszeitpunkt und den folgenden sieben simulierten Tagen eine passende Aktivität stattfindet.

Die Zeitachse wird als `period * 31 + day_of_month` geordnet. Sie ist eine simulierte Ordnung und kein echtes Kalenderdatum. Bei `individual_state.csv` wird mangels Tagesfeld Tag `1` verwendet.

Beispielverwendung:

```python
from src.response_model import build_response_examples, train_response_model

examples = build_response_examples("data/")
classifier, metrics = train_response_model(examples)

features = {
	"age": 70,
	"income_chf": 5000,
	"total_balance_chf": 99488.34,
	"num_accounts": 3,
	"has_employer": False,
	"stress": 40,
}
print(classifier.rank_actions(features))
print(metrics)
```

Das Modell verwendet eine zeitbasierte Trennung: frühere Perioden werden zum Training und spätere Perioden zum Test verwendet. Es nutzt aktuell eine erklärbare Logistic Regression und liefert pro Action eine Conversion-Wahrscheinlichkeit für das 7-Tage-Fenster.

Aktuelle Event-/Transaktions-Mappings:

```text
savings_transfer       -> offer_savings_account
pillar3a                -> offer_pillar3a
mortgage/mortgage_payment/property_purchase -> offer_mortgage
investment/investment_contribution/investment_return -> offer_investment
advice/financial_advice/consultation -> financial_advice
retirement/pension/retirement_planning -> retirement_planning
```

Wichtig: Die Daten enthalten nicht, welche NBA einem Kunden tatsächlich angezeigt wurde. Das Modell misst daher historische Response-Wahrscheinlichkeit und keine kausale Wirkung einer Empfehlung. Für ein echtes Uplift-Modell müssen Recommendation-Impressions mit `individual_id`, Zeitpunkt, Action und Rank gespeichert werden.

### Interaktive Dokumentation

Die automatisch erzeugte API-Dokumentation ist verfügbar unter:

```text
http://localhost:8000/docs
```
