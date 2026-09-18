"""
Build data/nba_marketplace_real.db (SQLite) from the 8 challenge CSVs, on the model of
DATABASE_AGENT_GUIDE.md, and document it in DATABASE_AGENT_GUIDE_REAL_DATA.md.

Every field of the CSVs lands somewhere in the database (the script checks the row counts):
the tables of the original guide are rebuilt where the data allows it, and the information the
original schema has no place for gets tables of its own (life events, relationships, transfers,
profile, health, outcomes, ...). Names and addresses live in client_pii only.

Building data comes from the federal register (GWR) through scripts/gwr_lookup.py, which must
run first (data/gwr_cache.jsonl). Without it, gwr_building_data is created empty.

Calendar: period = 12 * year + month, month 1..12 (24289 = 2024-01, 24301 = 2025-01). This is
an inference, not a given: the 13th salaries all fall on 24300 (December) and the bonuses on 24291
(March), which is also what the original guide describes. The source period is kept everywhere.

Usage:  uv run --with duckdb python scripts/build_marketplace_db.py [--data data] [--out data/nba_marketplace_real.db]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import duckdb

REF, W0, W1 = 24301, 24290, 24301

# --------------------------------------------------------------------------- reference data

# MCC -> (cv_cat, cv_cp_cat). The descriptions in the source are often a generic "Retail"; the
# mapping follows the standard MCC meaning, checked against the top merchants of each code.
MCC_MAP = {
    "0742": ("veterinary", "animals.veterinary"), "1711": ("heating_plumbing", "craftsman.heating_sanitary"),
    "1731": ("electrical_contractor", "craftsman.electrical"), "1750": ("home_renovation", "craftsman.painting"),
    "1751": ("home_renovation", "craftsman.carpentry"), "4121": ("taxi", "mobility.taxi"),
    "4812": ("telecommunication", "telecom.shop"), "5047": ("medical_equipment", "healthcare.medical_devices"),
    "5251": ("hardware_store", "shop.diy_hardware"), "5261": ("garden_center", "shop.garden"),
    "5311": ("department_store", "shop.department_store"), "5331": ("kiosk_convenience", "shop.convenience"),
    "5411": ("supermarket", "shop.food_beverages"), "5422": ("butcher_fishmonger", "shop.food_beverages"),
    "5431": ("farm_shop_greengrocer", "shop.food_beverages"), "5441": ("confectionery", "shop.food_beverages"),
    "5462": ("bakery", "shop.food_beverages"), "5499": ("food_specialty", "shop.food_beverages"),
    "5511": ("car_dealer_garage", "mobility.car_services"), "5531": ("car_parts", "mobility.car_services"),
    "5541": ("petrol_station", "mobility.fuel"), "5571": ("motorbike_tyres", "mobility.car_services"),
    "5651": ("clothing", "shop.fashion"), "5661": ("shoes", "shop.fashion"), "5699": ("accessories", "shop.fashion"),
    "5712": ("furniture", "shop.home_living"), "5732": ("electronics_shop_other", "shop.electronics"),
    "5733": ("music_store", "shop.leisure"), "5734": ("computer_services", "shop.electronics"),
    "5812": ("restaurant", "gastronomy.restaurant"), "5813": ("bar", "gastronomy.bar"),
    "5814": ("fast_food", "gastronomy.fast_food"), "5912": ("pharmacy", "healthcare.pharmacy"),
    "5921": ("wine_liquor", "shop.food_beverages"), "5932": ("second_hand", "shop.second_hand"),
    "5940": ("bicycle", "mobility.bicycle"), "5941": ("sporting_goods", "shop.sports"),
    "5942": ("books", "shop.books_stationery"), "5943": ("stationery", "shop.books_stationery"),
    "5944": ("jewelry", "shop.luxury"), "5945": ("toys", "shop.leisure"), "5947": ("gifts_souvenirs", "shop.leisure"),
    "5970": ("art_supplies", "shop.leisure"), "5977": ("cosmetics", "shop.beauty"),
    "5992": ("florist", "shop.home_living"), "5993": ("tobacco", "shop.convenience"),
    "5994": ("newsstand", "shop.convenience"), "5995": ("pet_shop", "animals.pet_shop"),
    "6011": ("cash_withdrawal", "financial_institution.atm"),
    "6300": ("insurance_premium", "professional_service_provider.financial.insurance"),
    "6512": ("real_estate_services", "professional_service_provider.real_estate"),
    "7011": ("hotel", "travel.accommodation"), "7033": ("camping", "travel.accommodation"),
    "7230": ("hairdresser", "personal_care.hairdresser"), "7395": ("photo", "shop.leisure"),
    "7512": ("public_transport", "mobility.public_transport"),   # mostly station ticket offices here
    "7523": ("parking", "mobility.parking"), "7832": ("cinema", "leisure.culture"),
    "7922": ("theatre", "leisure.culture"), "7941": ("fitness", "leisure.sports"),
    "7991": ("museum_attractions", "leisure.culture"), "7999": ("leisure_other", "leisure.other"),
    "8011": ("doctor", "healthcare.doctor"), "8021": ("dentist", "healthcare.dentist"),
    "8042": ("optician", "healthcare.optician"), "8049": ("therapist", "healthcare.therapist"),
    "8062": ("hospital", "healthcare.hospital"), "8111": ("legal_services", "professional_service_provider.legal"),
    "8211": ("school", "education.school"), "8220": ("university", "education.higher_education"),
    "8231": ("library", "education.library"), "8351": ("childcare", "education.childcare"),
    "8931": ("accounting_services", "professional_service_provider.accounting"),
    "9402": ("postal_services", "public_service.post"),
}
# purchases without MCC (agent-generated or vendor-only): by source category
CATEGORY_FALLBACK = {
    "food": ("groceries_other", "shop.food_beverages"), "restaurants": ("restaurant", "gastronomy.restaurant"),
    "transport": ("transport_other", "mobility.other"), "health": ("health_other", "healthcare.other"),
    "clothing": ("clothing", "shop.fashion"), "communication": ("telecommunication", "telecom.other"),
    "education": ("education_other", "education.other"), "recreation": ("leisure_other", "leisure.other"),
    "other": ("other_expense", "other"),
}

# Official labels, GWR Merkmalskatalog v4.2 (BFS, housing-stat.ch/files/881-2200.pdf)
GWR_CODES = {
    "gstat": {1001: "Projektiert", 1002: "Bewilligt", 1003: "Im Bau", 1004: "Bestehend", 1005: "Nicht nutzbar",
              1007: "Abgebrochen", 1008: "Nicht realisiert"},
    "gkat": {1010: "Provisorische Unterkunft", 1020: "Gebäude mit ausschliesslicher Wohnnutzung",
             1030: "Andere Wohngebäude (Wohngebäude mit Nebennutzung)", 1040: "Gebäude mit teilweiser Wohnnutzung",
             1060: "Gebäude ohne Wohnnutzung", 1080: "Sonderbau"},
    "gklas": {1110: "Gebäude mit einer Wohnung", 1121: "Gebäude mit zwei Wohnungen",
              1122: "Gebäude mit drei oder mehr Wohnungen", 1130: "Wohngebäude für Gemeinschaften",
              1211: "Hotelgebäude", 1212: "Andere Gebäude für kurzfristige Beherbergungen", 1220: "Bürogebäude",
              1230: "Gross- und Einzelhandelsgebäude", 1231: "Restaurants und Bars in Gebäuden ohne Wohnnutzung",
              1241: "Bahnhöfe, Abfertigungsgebäude, Fernsprechvermittlungszentralen", 1242: "Garagengebäude",
              1251: "Industriegebäude", 1252: "Behälter, Silos und Lagergebäude",
              1261: "Gebäude für Kultur- und Freizeitzwecke", 1262: "Museen / Bibliotheken",
              1263: "Schul- und Hochschulgebäude, Forschungseinrichtungen",
              1264: "Krankenhäuser und Facheinrichtungen des Gesundheitswesens", 1265: "Sporthallen",
              1271: "Landwirtschaftliche Betriebsgebäude", 1272: "Kirchen und sonstige Kultgebäude",
              1273: "Denkmäler oder unter Denkmalschutz stehende Bauwerke",
              1274: "Sonstige Hochbauten, anderweitig nicht genannt", 1275: "Andere Gebäude für die kollektive Unterkunft",
              1276: "Gebäude für die Tierhaltung", 1277: "Gebäude für den Pflanzenbau",
              1278: "Andere landwirtschaftliche Gebäude"},
    "gbaup": {8011: "Periode vor 1919", 8012: "Periode von 1919 bis 1945", 8013: "Periode von 1946 bis 1960",
              8014: "Periode von 1961 bis 1970", 8015: "Periode von 1971 bis 1980", 8016: "Periode von 1981 bis 1985",
              8017: "Periode von 1986 bis 1990", 8018: "Periode von 1991 bis 1995", 8019: "Periode von 1996 bis 2000",
              8020: "Periode von 2001 bis 2005", 8021: "Periode von 2006 bis 2010", 8022: "Periode von 2011 bis 2015",
              8023: "Periode ab 2016"},
    "gwaerzh": {7400: "Kein Wärmeerzeuger", 7410: "Wärmepumpe für ein Gebäude", 7411: "Wärmepumpe für mehrere Gebäude",
                7420: "Thermische Solaranlage für ein Gebäude", 7421: "Thermische Solaranlage für mehrere Gebäude",
                7430: "Heizkessel (generisch) für ein Gebäude", 7431: "Heizkessel (generisch) für mehrere Gebäude",
                7432: "Heizkessel nicht kondensierend für ein Gebäude",
                7433: "Heizkessel nicht kondensierend für mehrere Gebäude",
                7434: "Heizkessel kondensierend für ein Gebäude", 7435: "Heizkessel kondensierend für mehrere Gebäude",
                7436: "Ofen", 7440: "Wärmekraftkopplungsanlage für ein Gebäude",
                7441: "Wärmekraftkopplungsanlage für mehrere Gebäude",
                7450: "Elektrospeicher-Zentralheizung für ein Gebäude",
                7451: "Elektrospeicher-Zentralheizung für mehrere Gebäude", 7452: "Elektro direkt",
                7460: "Wärmetauscher (einschliesslich für Fernwärme) für ein Gebäude",
                7461: "Wärmetauscher (einschliesslich für Fernwärme) für mehrere Gebäude", 7499: "Andere"},
    "genh": {7500: "Keine", 7501: "Luft", 7510: "Erdwärme (generisch)", 7511: "Erdwärmesonde", 7512: "Erdregister",
             7513: "Wasser (Grundwasser, Oberflächenwasser, Abwasser)", 7520: "Gas", 7530: "Heizöl",
             7540: "Holz (generisch)", 7541: "Holz (Stückholz)", 7542: "Holz (Pellets)", 7543: "Holz (Schnitzel)",
             7550: "Abwärme (innerhalb des Gebäudes)", 7560: "Elektrizität", 7570: "Sonne (thermisch)",
             7580: "Fernwärme (generisch)", 7581: "Fernwärme (Hochtemperatur)", 7582: "Fernwärme (Niedertemperatur)",
             7598: "Unbestimmt", 7599: "Andere"},
    "gwaerzw": {7600: "Kein Wärmeerzeuger", 7610: "Wärmepumpe", 7620: "Thermische Solaranlage",
                7630: "Heizkessel (generisch)", 7632: "Heizkessel nicht kondensierend", 7634: "Heizkessel kondensierend",
                7640: "Wärmekraftkopplungsanlage", 7650: "Zentraler Elektroboiler", 7651: "Kleinboiler",
                7660: "Wärmetauscher (einschliesslich für Fernwärme)", 7699: "Andere"},
}

ACCOUNT_TYPES = {  # source kind -> (type, cv_type), in the style of the original guide
    "checking": ("CURRENT", "CURRENT_ACCOUNT"), "savings": ("SAVING", "SAVINGS_ACCOUNT"),
    "pillar3a": ("PILLAR 3A", "PILLAR_3A_ACCOUNT"), "credit_card": ("CREDIT CARD", "CREDIT_CARD_ACCOUNT"),
    "investment": ("INVESTMENT", "SECURITIES_ACCOUNT"), "insurance": ("INSURANCE", "INSURANCE_POLICY"),
    "mortgage": ("MORTGAGE", "MORTGAGE_ACCOUNT"),
}

TRANSFER_TYPES = ("savings_transfer", "pillar3a", "pillar3a_withdrawal", "investment_contribution")

# Primary keys of the SQLite tables (other tables get indexes below)
PRIMARY_KEYS = {
    "dataset_metadata": "key", "calendar": "period", "core_clients": "user_id", "client_pii": "user_id",
    "gwr_building_data": "user_id", "accounts": "acc_id", "account_balances": "acc_id",
    "transactions": "trx_id", "transfers": "event_id", "opening_balances": "event_id",
    "monthly_financial_summaries": "summary_id", "client_analytics_events": "event_uuid",
    "client_analytics_features": "feat_uuid", "client_analytics_characteristics": "chr_uuid",
    "debt_details": "detail_id", "employers": "employer_id", "client_profile": "user_id",
    "client_health": "user_id", "client_housing": "user_id", "client_outcomes": "user_id",
    "client_life_events": "event_id", "interactions": "interaction_id", "client_features": "individual_id",
    "ref_mcc": "mcc",
}
INDEXES = [
    ("idx_clients_canton_uid", "core_clients(canton, user_id)"),
    ("idx_gwr_heat_year", "gwr_building_data(heat_generator, build_year, user_id)"),
    ("idx_summaries_user_month", "monthly_financial_summaries(user_id, year_month)"),
    ("idx_feat_user_type", "client_analytics_features(user_id, feature_type)"),
    ("idx_feat_type_disc", "client_analytics_features(feature_type, discriminator)"),
    ("idx_evt_user_type_date", "client_analytics_events(user_id, event_type, event_date)"),
    ("idx_chr_type_user", "client_analytics_characteristics(characteristic_type, user_id)"),
    ("idx_debt_user_type", "debt_details(user_id, debt_type)"),
    ("idx_acc_user", "accounts(usr_id, type)"),
    ("idx_trx_user_date", "transactions(usr_id, book_date)"),
    ("idx_trx_acc_date", "transactions(acc_id, book_date)"),
    ("idx_trx_cat", "transactions(cv_cat, usr_id, book_date, amount)"),   # covering: no table lookups
    ("idx_accmb_acc_month", "account_monthly_balances(acc_id, year_month)"),
    ("idx_transfers_user", "transfers(usr_id, transfer_type)"),
    ("idx_life_user_type", "client_life_events(user_id, event_type)"),
    ("idx_rel_user", "client_relationships(user_id, relation_type)"),
    ("idx_interests_user", "client_interests(user_id)"),
    ("idx_declared_user", "client_declared_products(user_id)"),
]


def ym(p: str) -> str:
    return f"printf('%04d-%02d', ({p} - 1) // 12, ({p} - 1) % 12 + 1)"


def month_date(p: str, day: str = "1") -> str:
    """First day of the period's month, or the given day clamped to the month's last day."""
    first = f"make_date(({p} - 1) // 12, ({p} - 1) % 12 + 1, 1)"
    return f"least({first} + to_days(CAST(({day}) - 1 AS INTEGER)), last_day({first}))::DATE"


# --------------------------------------------------------------------------- build (DuckDB)

def build(con: duckdb.DuckDBPyConnection, data: Path, features_parquet: Path | None) -> None:
    csv = lambda t: f"read_csv_auto('{(data / f'{t}.csv').as_posix()}', sample_size=-1)"  # noqa: E731
    x = con.execute

    # raw sources
    x(f"CREATE TABLE src_individual AS SELECT *, attributes::JSON AS a FROM {csv('individual')}")
    x(f"CREATE TABLE src_state AS SELECT * FROM {csv('individual_state')}")
    x(f"CREATE TABLE src_account AS SELECT * FROM {csv('account')}")
    x(f"CREATE TABLE src_balance AS SELECT * FROM {csv('account_balance')}")
    x(f"CREATE TABLE src_employer AS SELECT * FROM {csv('employer')}")
    x(f"CREATE TABLE src_txn AS SELECT * FROM {csv('transaction')}")
    x(f"CREATE TABLE src_interaction AS SELECT * FROM read_csv('{(data / 'interaction.csv').as_posix()}', "
      f"all_varchar=true, header=true)")
    x(f"""CREATE TABLE src_event AS
          SELECT event_id, run_id, individual_id, counterparty_id, period, type, generated_by, effects::JSON AS e
          FROM {csv('event')}""")
    run_id = con.execute("SELECT any_value(run_id) FROM src_individual").fetchone()[0]

    # reference tables
    x("CREATE TABLE ref_mcc (mcc VARCHAR, cv_cat VARCHAR, cv_cp_cat VARCHAR)")
    con.executemany("INSERT INTO ref_mcc VALUES (?, ?, ?)", [(k, *v) for k, v in MCC_MAP.items()])
    x("""CREATE OR REPLACE TABLE ref_mcc AS
         SELECT r.mcc, d.mcc_description AS source_description, r.cv_cat, r.cv_cp_cat, coalesce(d.n, 0) AS n_transactions
         FROM ref_mcc r LEFT JOIN (SELECT (e->>'mcc') AS mcc, any_value(e->>'mcc_description') AS mcc_description, count(*) n
                                   FROM src_event WHERE type = 'purchase' AND (e->>'mcc') IS NOT NULL GROUP BY 1) d USING (mcc)""")
    x("CREATE TABLE ref_gwr_codes (characteristic VARCHAR, code INTEGER, label_de VARCHAR)")
    con.executemany("INSERT INTO ref_gwr_codes VALUES (?, ?, ?)",
                    [(ch, c, lab) for ch, d in GWR_CODES.items() for c, lab in d.items()])
    x("CREATE TABLE ref_fallback (source_category VARCHAR, cv_cat VARCHAR, cv_cp_cat VARCHAR)")
    con.executemany("INSERT INTO ref_fallback VALUES (?, ?, ?)", [(k, *v) for k, v in CATEGORY_FALLBACK.items()])

    x(f"""CREATE TABLE calendar AS
          SELECT p AS period, {ym('p')} AS year_month, {month_date('p')} AS month_start,
                 (p = 24289) AS is_opening_state, (p BETWEEN {W0} AND {W1}) AS in_flow_window
          FROM range(24289, 24302) t(p)""")

    # clients
    x(f"""CREATE TABLE core_clients AS
        SELECT i.individual_id AS user_id, i.run_id, i.birth_period,
               {month_date('i.birth_period')} AS birth_date,
               ({REF} - i.birth_period) // 12 AS age_years,
               (i.a->>'age')::INTEGER AS age_source,
               i.sex AS gender,
               CASE (i.a->>'nationality') WHEN 'swiss' THEN 'CH' WHEN 'eu_efta' THEN 'EU_EFTA' WHEN 'other' THEN 'OTHER' END
                   AS nationality,
               (i.a->>'canton') AS canton,
               upper(s.marital_status) AS marital_status,
               s.education_level, (i.a->>'education') AS education_profile,
               (i.a->>'occupation') AS occupation, nullif(i.a->>'sector', '') AS occupation_sector,
               s.employment_type, s.employer_id, s.income_chf AS income_monthly_chf,
               s.household_id, s.period AS state_period, {ym('s.period')} AS state_month,
               (i.a->>'onboarded_period') IS NOT NULL AS onboarded_during_run,
               (i.a->>'onboarded_period')::INTEGER AS onboarded_period,
               i.death_period IS NULL AS is_active
        FROM src_individual i JOIN src_state s USING (individual_id)""")
    x("""CREATE TABLE client_pii AS
         SELECT individual_id AS user_id, (a->>'first_name') AS first_name, (a->>'last_name') AS last_name,
                (a->>'street') AS street, (a->>'house_number') AS house_number, (a->>'plz') AS plz,
                (a->>'city') AS city,
                (a->>'street') || ' ' || (a->>'house_number') AS address,
                (a->>'plz') || ' ' || (a->>'city') AS city_zip,
                CASE WHEN (a->>'street') IS NOT NULL THEN (a->>'plz') || '|' || lower(trim(a->>'street')) || '|' ||
                     lower(trim(a->>'house_number')) END AS address_key
         FROM src_individual""")
    big5 = ", ".join(f"(a->'bigfive'->>'{k}')::INTEGER AS big5_{n}" for k, n in
                     [("O", "openness"), ("C", "conscientiousness"), ("E", "extraversion"), ("A", "agreeableness"),
                      ("N", "neuroticism")])
    values = ", ".join(f"(a->'values'->>'{v}')::DOUBLE AS value_{v}" for v in
                       ["power", "hedonism", "security", "tradition", "conformity", "achievement", "benevolence",
                        "stimulation", "universalism", "self_direction"])
    x(f"""CREATE TABLE client_profile AS
          SELECT individual_id AS user_id, (a->>'risk_appetite')::DOUBLE AS risk_appetite,
                 (a->>'wallet_share')::DOUBLE AS wallet_share, (a->>'life_sat')::INTEGER AS life_satisfaction,
                 {big5}, {values}, (a->'portfolio_allocation')::VARCHAR AS portfolio_allocation_json
          FROM src_individual""")
    x("""CREATE TABLE client_health AS
         SELECT individual_id AS user_id, (a->>'bmi')::DOUBLE AS bmi, (a->>'health_score')::INTEGER AS health_score,
                (a->>'stress')::INTEGER AS stress, (a->'health_conditions')::VARCHAR AS health_conditions_json,
                coalesce(json_array_length(a->'health_conditions'), 0)::INTEGER AS n_health_conditions
         FROM src_individual""")
    x("""CREATE TABLE client_interests AS
         SELECT individual_id AS user_id, k AS interest, (a->'interests'->>k)::DOUBLE AS score
         FROM (SELECT individual_id, a, unnest(json_keys(a, '$.interests')) AS k FROM src_individual)""")
    x("""CREATE TABLE client_declared_products AS
         SELECT individual_id AS user_id, unnest(from_json(a->'products', '["VARCHAR"]')) AS product_name
         FROM src_individual""")
    x("""CREATE TABLE client_housing AS
         SELECT individual_id AS user_id, coalesce((a->>'owns_property')::BOOLEAN, false) AS owns_property,
                (a->>'property_value')::DOUBLE AS property_value_chf,
                (a->>'mortgage_outstanding')::DOUBLE AS mortgage_outstanding_chf,
                (a->>'mortgage_monthly')::DOUBLE AS mortgage_monthly_chf,
                (a->>'fixed_rent')::DOUBLE AS fixed_rent_chf,
                coalesce((a->>'mortgage_monthly')::DOUBLE / (a->>'mortgage_outstanding')::DOUBLE > 0.5, false)
                    AS is_mortgage_data_anomaly
         FROM src_individual""")
    x(f"""CREATE TABLE client_outcomes AS
          SELECT i.individual_id AS user_id, i.death_period AS exit_period, {ym('i.death_period')} AS exit_month,
                 CASE WHEN i.death_period IS NULL THEN NULL
                      WHEN (i.a->>'churn_reason') IS NOT NULL THEN 'churn_with_reason'
                      WHEN d.individual_id IS NOT NULL THEN 'death' ELSE 'other_exit' END AS exit_type,
                 (i.a->>'churn_reason') AS churn_reason,
                 (i.a->>'onboarded_period')::INTEGER AS onboarded_period, nullif(i.a->>'onboarding_reason', '')
                     AS onboarding_reason
          FROM src_individual i
          LEFT JOIN (SELECT DISTINCT individual_id FROM src_event WHERE type = 'death') d USING (individual_id)
          WHERE i.death_period IS NOT NULL OR (i.a->>'onboarded_period') IS NOT NULL""")
    x("CREATE TABLE employers AS SELECT employer_id, run_id, sector, region, size_band FROM src_employer")

    # accounts
    x("CREATE TABLE ref_account_types (kind VARCHAR, type VARCHAR, cv_type VARCHAR)")
    con.executemany("INSERT INTO ref_account_types VALUES (?, ?, ?)", [(k, *v) for k, v in ACCOUNT_TYPES.items()])
    x(f"""CREATE TABLE accounts AS
          SELECT a.account_id AS acc_id, a.individual_id AS usr_id, t.type, t.cv_type,
                 CASE WHEN a.product_name LIKE 'Geschaeftskonto%' THEN 'BUSINESS' ELSE 'PERSONAL' END AS usage,
                 'CHF' AS curr, a.product_name, a.kind AS source_kind,
                 a.opened_period, {ym('a.opened_period')} AS opened_month,
                 a.closed_period, {ym('a.closed_period')} AS closed_month,
                 a.closed_period IS NULL AS is_open, a.run_id
          FROM src_account a JOIN ref_account_types t ON t.kind = a.kind""")
    x(f"""CREATE TABLE account_balances AS
          SELECT account_id AS acc_id, period AS balance_period, {ym('period')} AS balance_month, balance_chf
          FROM src_balance""")

    # events split by use
    x(f"""CREATE TABLE ev_money AS
          SELECT event_id, individual_id, period, type,
                 (e->>'vendor') AS vendor, (e->>'mcc') AS mcc, (e->>'mcc_description') AS mcc_description,
                 (e->>'category') AS ev_category, (e->>'decision_by') AS decision_by, (e->>'rationale') AS rationale
          FROM src_event WHERE type IN ('purchase', 'income', 'salary', 'rent', 'mortgage_payment', 'investment_return',
                                        'savings_adjustment', 'property_purchase')""")

    # transactions (full ledger)
    x(f"""CREATE TABLE transactions AS
          SELECT t.txn_id AS trx_id, t.account_id AS acc_id, a.individual_id AS usr_id, t.period,
                 {ym('t.period')} AS year_month,
                 {month_date('t.period', 'coalesce(t.day_of_month, 1)')} AS book_date,
                 {month_date('t.period', 'coalesce(t.day_of_month, 1)')} AS val_date,
                 t.day_of_month IS NULL AS date_is_estimated, t.day_of_month,
                 t.amount_chf AS amount, t.category AS source_category,
                 CASE
                   WHEN t.category = 'salary' AND ev.ev_category IN ('thirteenth_salary', 'annual_bonus') THEN 'irregular_wage_credit'
                   WHEN t.category = 'salary' AND s.employment_type = 'retired' THEN 'pension_credit'
                   WHEN t.category = 'salary' THEN 'regular_wage_credit'
                   WHEN t.category = 'rent' THEN 'rent_payment'
                   WHEN t.category = 'mortgage' THEN 'mortgage'
                   WHEN t.category = 'initial_balance' THEN 'opening_balance'
                   WHEN t.category = 'investment_return' THEN 'capital_income'
                   WHEN t.category = 'property_down_payment' THEN 'property_down_payment'
                   WHEN t.category IN {TRANSFER_TYPES} THEN 'internal_' || t.category
                   WHEN ev.type = 'income' THEN 'other_income'
                   WHEN t.mcc_map_cat IS NOT NULL THEN t.mcc_map_cat
                   ELSE coalesce(f.cv_cat, 'other_expense') END AS cv_cat,
                 CASE
                   WHEN t.category = 'salary' AND s.employment_type = 'retired' THEN 'institution.pension_fund'
                   WHEN t.category = 'salary' THEN 'employer'
                   WHEN t.category = 'rent' THEN 'real_estate.landlord'
                   WHEN t.category = 'mortgage' THEN 'financial_institution.lender'
                   WHEN t.category IN ('initial_balance', 'investment_return', 'property_down_payment')
                        OR t.category IN {TRANSFER_TYPES} THEN 'own_account'
                   WHEN ev.type = 'income' THEN 'other'
                   WHEN t.mcc_map_cp IS NOT NULL THEN t.mcc_map_cp
                   ELSE coalesce(f.cv_cp_cat, 'other') END AS cv_cp_cat,
                 ev.vendor AS cp_name,   -- salaries: payer not named in the source (see core_clients.employer_id)
                 CASE WHEN ev.vendor IS NOT NULL THEN md5(lower(trim(ev.vendor))) END AS cv_merch_uuid,
                 ev.mcc, ev.mcc_description, ev.ev_category AS source_event_category,
                 t.source_event_id, ev.type AS source_event_type, ev.decision_by, ev.rationale
          FROM (SELECT t.*, m.cv_cat AS mcc_map_cat, m.cv_cp_cat AS mcc_map_cp
                FROM src_txn t
                LEFT JOIN ev_money em ON em.event_id = t.source_event_id
                LEFT JOIN ref_mcc m ON m.mcc = em.mcc) t
          JOIN src_account a ON a.account_id = t.account_id
          JOIN src_state s ON s.individual_id = a.individual_id
          LEFT JOIN ev_money ev ON ev.event_id = t.source_event_id
          LEFT JOIN ref_fallback f ON f.source_category = t.category""")
    # MCC 7512 is mostly station ticket offices in this data; the real rental brands are car rental
    x("""UPDATE transactions SET cv_cat = 'car_rental', cv_cp_cat = 'mobility.car_rental'
         WHERE mcc = '7512' AND regexp_matches(cp_name, '(?i)hertz|avis|europcar|sixt|enterprise|budget|mobility')""")
    # one-off incomes (agent-generated): classified by the payer description
    x("""UPDATE transactions SET cv_cat = CASE
             WHEN regexp_matches(cp_name, '(?i)erbschaft|erbe\\b|erbteil|erbvorbezug|erbengemeinschaft|nachlass|succession|successione|h[ée]ritage|legat|verm[aä]chtnis|eredit') THEN 'heritage_credit'
             WHEN regexp_matches(cp_name, '(?i)schenkung|donation|geschenk|dono\\b') THEN 'gift_credit'
             WHEN regexp_matches(cp_name, '(?i)abgangsentsch|abfindung|indemnit[ée] de d[ée]part') THEN 'severance_credit'
             WHEN regexp_matches(cp_name, '(?i)lebensversicherung|versicherung.*auszahlung|assurance.*(vie|versement)|swiss life') THEN 'insurance_payout'
             WHEN regexp_matches(cp_name, '(?i)honorar|anzahlung|vorauszahlung|debitoren|mandat|projektauftrag|rechnung|facture|kunde|client') THEN 'business_income'
             ELSE 'other_income' END
         WHERE source_event_type = 'income' AND amount > 0""")
    # 3a contributions paid to another provider (agent-generated purchases such as "Säule 3a Einzahlung (VIAC)")
    x("""UPDATE transactions SET cv_cat = 'pillar3a_external',
                cv_cp_cat = 'professional_service_provider.financial.pillar3a_provider'
         WHERE amount < 0 AND source_event_type = 'purchase'
           AND regexp_matches(cp_name, '(?i)säule 3a|pilier 3a|\\b3a\\b|viac|frankly|finpension')""")

    x(f"""CREATE TABLE transfers AS
          SELECT event_id, type AS transfer_type, individual_id AS usr_id, period, {ym('period')} AS year_month,
                 (e->>'from_account_id') AS from_acc_id, (e->>'to_account_id') AS to_acc_id,
                 (e->>'amount_chf')::DOUBLE AS amount_chf, (e->>'decision_by') AS decision_by
          FROM src_event WHERE type IN {TRANSFER_TYPES}""")
    x(f"""CREATE TABLE opening_balances AS
          SELECT e.event_id, (e.e->>'account_id') AS acc_id, e.individual_id AS usr_id, e.period,
                 {ym('e.period')} AS year_month, (e.e->>'amount_chf')::DOUBLE AS amount_chf,
                 t.txn_id IS NOT NULL AS has_ledger_row
          FROM src_event e LEFT JOIN src_txn t ON t.source_event_id = e.event_id
          WHERE e.type = 'initial_balance'""")

    # monthly balances per account, rebuilt from the ledger (+ opening balances without ledger row)
    x(f"""CREATE TABLE account_monthly_balances AS
          WITH flows AS (
              SELECT acc_id, period, sum(amount) AS flow FROM transactions GROUP BY ALL
              UNION ALL
              SELECT acc_id, period, amount_chf FROM opening_balances WHERE NOT has_ledger_row),
          f AS (SELECT acc_id, period, sum(flow) AS flow FROM flows GROUP BY ALL),
          grid AS (SELECT a.acc_id, a.usr_id, a.source_kind, c.period FROM accounts a CROSS JOIN calendar c)
          SELECT g.acc_id, g.usr_id, g.source_kind, g.period, {ym('g.period')} AS year_month,
                 round(sum(coalesce(f.flow, 0)) OVER (PARTITION BY g.acc_id ORDER BY g.period), 2) AS ending_balance_chf
          FROM grid g LEFT JOIN f USING (acc_id, period)""")

    # monthly financial summaries (12 months of flows)
    x(f"""CREATE TABLE monthly_financial_summaries AS
          WITH t AS (SELECT * FROM transactions WHERE period BETWEEN {W0} AND {W1}),
          inc AS (SELECT usr_id, period, cv_cat, sum(amount) AS amt FROM t
                  WHERE cv_cat IN ('regular_wage_credit', 'irregular_wage_credit', 'pension_credit', 'other_income',
                                   'capital_income', 'heritage_credit', 'gift_credit', 'severance_credit',
                                   'insurance_payout', 'business_income') GROUP BY ALL),
          sp AS (SELECT usr_id, period, cv_cat, -sum(amount) AS amt FROM t
                 WHERE amount < 0 AND cv_cat NOT LIKE 'internal_%' AND cv_cat NOT IN ('opening_balance', 'capital_income')
                 GROUP BY ALL),
          spcp AS (SELECT usr_id, period, cv_cp_cat, -sum(amount) AS amt FROM t
                   WHERE amount < 0 AND cv_cat NOT LIKE 'internal_%' AND cv_cat NOT IN ('opening_balance', 'capital_income')
                   GROUP BY ALL),
          tr AS (SELECT usr_id, period, transfer_type, sum(amount_chf) AS amt FROM transfers
                 WHERE period BETWEEN {W0} AND {W1} GROUP BY ALL),
          bal AS (SELECT usr_id, period,
                         sum(ending_balance_chf) FILTER (WHERE source_kind = 'checking') AS ending_checking_balance,
                         sum(ending_balance_chf) FILTER (WHERE source_kind = 'savings') AS ending_savings_balance,
                         sum(ending_balance_chf) FILTER (WHERE source_kind = 'pillar3a') AS ending_pillar3a_balance,
                         sum(ending_balance_chf) FILTER (WHERE source_kind = 'investment') AS ending_investment_balance
                  FROM account_monthly_balances WHERE period BETWEEN {W0} AND {W1} GROUP BY ALL),
          j_inc AS (SELECT usr_id, period, round(sum(amt), 2) AS total, json_group_object(cv_cat, round(amt, 2)) AS js
                    FROM inc GROUP BY ALL),
          j_sp AS (SELECT usr_id, period, round(sum(amt), 2) AS total, json_group_object(cv_cat, round(amt, 2)) AS js
                   FROM sp GROUP BY ALL),
          j_cp AS (SELECT usr_id, period, json_group_object(cv_cp_cat, round(amt, 2)) AS js FROM spcp GROUP BY ALL),
          j_tr AS (SELECT usr_id, period, json_group_object(transfer_type, round(amt, 2)) AS js FROM tr GROUP BY ALL)
          SELECT 'SUM-' || b.usr_id || '-' || {ym('b.period')} AS summary_id, b.usr_id AS user_id,
                 {ym('b.period')} AS year_month, b.period,
                 coalesce(i.total, 0) AS monthly_income, coalesce(s.total, 0) AS monthly_expense,
                 coalesce(i.js, '{{}}'::JSON)::VARCHAR AS income_by_cat_json,
                 coalesce(s.js, '{{}}'::JSON)::VARCHAR AS spending_by_cat_json,
                 coalesce(c.js, '{{}}'::JSON)::VARCHAR AS spending_by_cp_cat_json,
                 coalesce(r.js, '{{}}'::JSON)::VARCHAR AS transfers_by_type_json,
                 round(coalesce(b.ending_checking_balance, 0), 2) AS ending_checking_balance,
                 round(coalesce(b.ending_savings_balance, 0), 2) AS ending_savings_balance,
                 round(coalesce(b.ending_pillar3a_balance, 0), 2) AS ending_pillar3a_balance,
                 round(coalesce(b.ending_investment_balance, 0), 2) AS ending_investment_balance,
                 h.mortgage_outstanding_chf AS mortgage_balance_profile
          FROM bal b
          LEFT JOIN j_inc i USING (usr_id, period) LEFT JOIN j_sp s USING (usr_id, period)
          LEFT JOIN j_cp c USING (usr_id, period) LEFT JOIN j_tr r USING (usr_id, period)
          LEFT JOIN client_housing h ON h.user_id = b.usr_id""")

    # life events and relationships (simulation ground truth)
    x(f"""CREATE TABLE client_life_events AS
          SELECT event_id, individual_id AS user_id, type AS event_type, period, {month_date('period')} AS event_date,
                 counterparty_id AS counterparty_user_id,
                 (e->>'new_employer_id') AS new_employer_id, (e->>'new_income_chf')::DOUBLE AS new_income_chf,
                 (e->>'new_sector') AS new_sector, (e->>'new_canton') AS new_canton,
                 (e->>'relationship_id') AS relationship_id, (e->>'child_id') AS child_user_id,
                 (e->>'child_sex') AS child_sex, (e->>'mother_rel_id') AS mother_relationship_id,
                 (e->>'father_rel_id') AS father_relationship_id,
                 (e->>'property_value')::DOUBLE AS property_value_chf, (e->>'down_payment_chf')::DOUBLE AS down_payment_chf,
                 (e->>'mortgage_outstanding')::DOUBLE AS mortgage_outstanding_chf,
                 (e->>'mortgage_monthly')::DOUBLE AS mortgage_monthly_chf, (e->>'canton') AS property_canton,
                 (e->>'savings_account_id') AS savings_account_id,
                 (e->'child_attributes')::VARCHAR AS child_attributes_json
          FROM src_event WHERE type IN ('job_change', 'migration', 'marriage', 'divorce', 'birth', 'death',
                                        'property_purchase')""")
    x("""CREATE TABLE client_relationships AS
         SELECT user_id, counterparty_user_id AS related_user_id, 'spouse' AS relation_type, period AS since_period,
                event_id AS source_event_id FROM client_life_events WHERE event_type = 'marriage'
         UNION ALL SELECT counterparty_user_id, user_id, 'spouse', period, event_id
                   FROM client_life_events WHERE event_type = 'marriage'
         UNION ALL SELECT user_id, counterparty_user_id, 'ex_spouse', period, event_id
                   FROM client_life_events WHERE event_type = 'divorce' AND counterparty_user_id IS NOT NULL
         UNION ALL SELECT counterparty_user_id, user_id, 'ex_spouse', period, event_id
                   FROM client_life_events WHERE event_type = 'divorce' AND counterparty_user_id IS NOT NULL
         UNION ALL SELECT user_id, child_user_id, 'parent_of', period, event_id
                   FROM client_life_events WHERE event_type = 'birth'
         UNION ALL SELECT counterparty_user_id, child_user_id, 'parent_of', period, event_id
                   FROM client_life_events WHERE event_type = 'birth' AND counterparty_user_id IS NOT NULL
         UNION ALL SELECT child_user_id, user_id, 'child_of', period, event_id
                   FROM client_life_events WHERE event_type = 'birth'
         UNION ALL SELECT s.individual_id, s.household_id, 'household_member_of', NULL, NULL
                   FROM src_state s WHERE s.household_id IS NOT NULL AND s.household_id <> s.individual_id""")

    # Contovista-style detected events
    x(f"""CREATE TABLE client_analytics_events AS
          WITH wage AS (
              SELECT usr_id, period, sum(amount) AS wage FROM transactions
              WHERE cv_cat = 'regular_wage_credit' GROUP BY ALL),
          wage_chg AS (
              SELECT usr_id, period, wage, lag(wage) OVER (PARTITION BY usr_id ORDER BY period) AS prev FROM wage),
          first_any AS (SELECT usr_id, min(period) AS p FROM transactions WHERE period >= {W0} GROUP BY 1),
          debit_first AS (
              SELECT d.usr_id, d.cv_cat, d.first_period FROM (
                  SELECT usr_id, cv_cat, min(period) AS first_period FROM transactions
                  WHERE cv_cat IN ('rent_payment', 'mortgage') GROUP BY ALL) d
              JOIN first_any f USING (usr_id) WHERE d.first_period > f.p)
          SELECT event_id AS event_uuid, user_id, 'NEW_EMPLOYER' AS event_type, event_date, period,
                 new_income_chf AS new_amount, 'CHF' AS currency, 'employer ' || new_employer_id AS counterparty_name,
                 'source job_change event' AS derivation
          FROM client_life_events WHERE event_type = 'job_change'
          UNION ALL
          SELECT md5('SALARY_CHANGE' || usr_id || period), usr_id, 'SALARY_CHANGE', {month_date('period')}, period,
                 round(wage, 2), 'CHF', NULL, 'regular wage differs > 5% from previous month'
          FROM wage_chg WHERE prev > 0 AND abs(wage - prev) / prev > 0.05
          UNION ALL
          SELECT t.source_event_id, t.usr_id, 'UNUSUALLY_HIGH_SALARY_PAYMENT', t.book_date, t.period, t.amount, 'CHF',
                 t.cp_name, 'source salary event, category ' || t.source_event_category
          FROM transactions t WHERE t.cv_cat = 'irregular_wage_credit'
          UNION ALL
          SELECT md5('NEW_DIRECT_DEBIT' || usr_id || cv_cat), usr_id, 'NEW_DIRECT_DEBIT', {month_date('first_period')},
                 first_period, NULL, 'CHF', cv_cat || ' (payee not identified)',
                 'first ' || cv_cat || ' debit of a client already active in earlier months'
          FROM debit_first
          UNION ALL
          SELECT md5('START_OF_PENSION' || c.user_id), c.user_id, 'START_OF_PENSION',
                 {month_date('c.birth_period + 780')}, c.birth_period + 780, NULL, 'CHF', NULL,
                 'approximated: 65th birthday within the window and retired at the reference date'
          FROM core_clients c WHERE c.employment_type = 'retired' AND c.birth_period + 780 BETWEEN {W0} AND {W1}
          UNION ALL
          SELECT source_event_id, usr_id, 'PILLAR3A_WITHDRAWAL', book_date, period, amount, 'CHF', NULL,
                 'source pillar3a_withdrawal event (credit leg on the current account)'
          FROM transactions WHERE cv_cat = 'internal_pillar3a_withdrawal' AND amount > 0
          UNION ALL
          SELECT source_event_id, usr_id,
                 CASE cv_cat WHEN 'heritage_credit' THEN 'HERITAGE' WHEN 'gift_credit' THEN 'GIFT'
                             WHEN 'severance_credit' THEN 'SEVERANCE_PAY' WHEN 'insurance_payout' THEN 'INSURANCE_PAYOUT'
                             WHEN 'business_income' THEN 'BUSINESS_INCOME' ELSE 'OTHER_ONE_OFF_INCOME' END,
                 book_date, period, amount, 'CHF', cp_name,
                 'agent-generated income event, type from the payer description'
          FROM transactions WHERE source_event_type = 'income' AND amount > 0""")

    # Contovista-style features (12 months)
    x(f"""CREATE TABLE client_analytics_features AS
          WITH t AS (SELECT * FROM transactions WHERE period BETWEEN {W0} AND {W1}),
          agg AS (
            SELECT usr_id, 'ANNUAL_SALARY' AS feature_type, NULL AS discriminator, sum(amount) AS credit_amount,
                   0.0 AS debit_amount, NULL AS debit_category, 'regular_wage_credit' AS credit_category,
                   count(DISTINCT period) AS n_months FROM t WHERE cv_cat = 'regular_wage_credit' GROUP BY usr_id
            UNION ALL
            SELECT usr_id, 'ANNUAL_BONUS_AND_EXTRA_PAY', NULL, sum(amount), 0.0, NULL, 'irregular_wage_credit',
                   count(DISTINCT period) FROM t WHERE cv_cat = 'irregular_wage_credit' GROUP BY usr_id
            UNION ALL
            SELECT usr_id, 'ANNUAL_PENSION', NULL, sum(amount), 0.0, NULL, 'pension_credit', count(DISTINCT period)
            FROM t WHERE cv_cat = 'pension_credit' GROUP BY usr_id
            UNION ALL
            SELECT usr_id, 'RENT', 'landlord not identified', 0.0, -sum(amount), 'rent_payment', NULL,
                   count(DISTINCT period) FROM t WHERE cv_cat = 'rent_payment' GROUP BY usr_id
            UNION ALL
            SELECT usr_id, 'MORTGAGE', 'lender not identified', 0.0, -sum(amount), 'mortgage', NULL,
                   count(DISTINCT period) FROM t WHERE cv_cat = 'mortgage' GROUP BY usr_id
            UNION ALL
            SELECT usr_id, 'THIRD_PARTY_ACCOUNT', provider, sum(amount) FILTER (WHERE amount > 0),
                   -sum(amount) FILTER (WHERE amount < 0), any_value(cv_cat), NULL, count(DISTINCT period)
            FROM (SELECT *, CASE lower(regexp_extract(cp_name, '(?i)(viac|frankly|finpension|revolut|neon|yuh|swissquote|kraken|coinbase|bitcoin suisse)', 1))
                              WHEN 'viac' THEN 'VIAC' WHEN 'frankly' THEN 'Frankly (ZKB)' WHEN 'finpension' THEN 'Finpension'
                              WHEN 'revolut' THEN 'Revolut' WHEN 'neon' THEN 'Neon' WHEN 'yuh' THEN 'Yuh'
                              WHEN 'swissquote' THEN 'Swissquote' WHEN 'kraken' THEN 'Kraken' WHEN 'coinbase' THEN 'Coinbase'
                              WHEN 'bitcoin suisse' THEN 'Bitcoin Suisse' END AS provider FROM t) tp
            WHERE provider IS NOT NULL GROUP BY usr_id, provider)
          SELECT md5(feature_type || usr_id || coalesce(discriminator, '')) AS feat_uuid, usr_id AS user_id, feature_type,
                 discriminator, round(coalesce(credit_amount, 0), 2) AS credit_amount,
                 round(coalesce(debit_amount, 0), 2) AS debit_amount, debit_category, credit_category, n_months
          FROM agg""")

    # Contovista-style characteristics
    x(f"""CREATE TABLE client_analytics_characteristics AS
          WITH t AS (SELECT * FROM transactions WHERE period BETWEEN {W0} AND {W1} AND amount < 0),
          sig AS (
            SELECT usr_id,
              count(*) FILTER (WHERE cv_cat IN ('hotel', 'camping', 'car_rental')
                               OR regexp_matches(cp_name, '(?i)hotel|booking\\.com|easyjet|swiss intl|airbnb')) AS n_travel,
              -sum(amount) FILTER (WHERE cv_cat IN ('hotel', 'camping', 'car_rental')
                               OR regexp_matches(cp_name, '(?i)hotel|booking\\.com|easyjet|swiss intl|airbnb')) AS chf_travel,
              count(*) FILTER (WHERE cv_cat IN ('second_hand', 'bicycle', 'farm_shop_greengrocer')
                               OR regexp_matches(cp_name, '(?i)alnatura|\\bbio\\b|reformhaus|unverpackt|claro')) AS n_sust,
              count(*) FILTER (WHERE regexp_matches(cp_name, '(?i)digitec|galaxus|zalando|amazon|brack\\.ch|temu|aliexpress|netflix|spotify')) AS n_digital,
              count(*) FILTER (WHERE cv_cat = 'cash_withdrawal') AS n_cash,
              count(*) FILTER (WHERE cv_cat = 'childcare') AS n_childcare,
              count(*) FILTER (WHERE cv_cat IN ('petrol_station', 'parking', 'car_dealer_garage', 'car_parts')) AS n_car,
              count(*) FILTER (WHERE cv_cat IN ('veterinary', 'pet_shop')) AS n_pet,
              count(*) FILTER (WHERE cv_cat IN ('heating_plumbing', 'electrical_contractor', 'home_renovation',
                                                'hardware_store')) AS n_reno,
              count(*) FILTER (WHERE cv_cat = 'real_estate_services') AS n_realestate,
              count(*) FILTER (WHERE cv_cat = 'insurance_premium') AS n_insurance,
              count(*) AS n_all
            FROM t GROUP BY usr_id),
          scored AS (
            SELECT *, round(100 * percent_rank() OVER (ORDER BY n_travel), 1) AS s_travel,
                      round(100 * percent_rank() OVER (ORDER BY n_sust), 1) AS s_sust,
                      round(100 * percent_rank() OVER (ORDER BY n_digital), 1) AS s_digital FROM sig),
          cards AS (
            SELECT usr_id AS user_id, list(DISTINCT src ORDER BY src) AS sources FROM (
              SELECT usr_id, 'account' AS src FROM accounts WHERE source_kind = 'credit_card' AND is_open
              UNION ALL SELECT user_id, 'declared_profile' FROM client_declared_products
                        WHERE product_name = 'Kreditkarte Visa/Mastercard') GROUP BY 1),
          loans AS (
            SELECT user_id, list(DISTINCT product_name ORDER BY product_name) AS products FROM client_declared_products
            WHERE product_name IN ('Barkredit / Privatkredit', 'Umweltdarlehen') GROUP BY 1),
          rows AS (
            SELECT usr_id AS user_id, 'FREQUENT_TRAVELER' AS characteristic_type,
                   json_object('active', n_travel >= 6, 'score', s_travel, 'travel_spend_chf', round(chf_travel, 2))
                       AS characteristic_value, n_travel AS trx_count FROM scored WHERE n_travel > 0
            UNION ALL SELECT usr_id, 'SUSTAINABILITY', json_object('active', n_sust >= 6, 'score', s_sust), n_sust
                      FROM scored WHERE n_sust > 0
            UNION ALL SELECT usr_id, 'DIGITAL_AFFINITY', json_object('active', n_digital >= 3, 'score', s_digital,
                                                                     'note', 'weak signal: online merchants only'), n_digital
                      FROM scored WHERE n_digital > 0
            UNION ALL SELECT usr_id, 'CASH_USER', json_object('active', n_cash >= 12), n_cash FROM scored WHERE n_cash > 0
            UNION ALL SELECT usr_id, 'FAMILY_WITH_CHILDCARE', json_object('active', true), n_childcare
                      FROM scored WHERE n_childcare > 0
            UNION ALL SELECT usr_id, 'CAR_OWNER', json_object('active', n_car >= 6), n_car FROM scored WHERE n_car > 0
            UNION ALL SELECT usr_id, 'PET_OWNER', json_object('active', true), n_pet FROM scored WHERE n_pet > 0
            UNION ALL SELECT usr_id, 'HOME_RENOVATION_ACTIVITY', json_object('active', true), n_reno
                      FROM scored WHERE n_reno > 0
            UNION ALL SELECT usr_id, 'REAL_ESTATE_INTEREST', json_object('active', true), n_realestate
                      FROM scored WHERE n_realestate > 0
            UNION ALL SELECT usr_id, 'INSURANCE_PAYER', json_object('active', true), n_insurance
                      FROM scored WHERE n_insurance > 0
            UNION ALL SELECT user_id, 'CREDIT_CARD_USER', json_object('active', true, 'sources', sources), NULL FROM cards
            UNION ALL SELECT user_id, 'PERSONAL_LOAN_USER', json_object('active', true, 'products', products), NULL FROM loans)
          SELECT md5(characteristic_type || user_id) AS chr_uuid, user_id, characteristic_type,
                 characteristic_value::VARCHAR AS characteristic_value, trx_count FROM rows""")

    # debts (lender not identified: renamed from internal_debt_details)
    x(f"""CREATE TABLE debt_details AS
          WITH mp AS (SELECT usr_id, -avg(amount) AS obs FROM transactions WHERE cv_cat = 'mortgage' GROUP BY 1),
          mt AS (SELECT user_id, min(product_name) AS product_name FROM client_declared_products
                 WHERE product_name IN ('Festhypothek', 'SARON Rollover-Hypothek', 'Starthypothek') GROUP BY 1),
          pp AS (SELECT user_id, min(period) AS p FROM client_life_events WHERE event_type = 'property_purchase' GROUP BY 1)
          SELECT 'DBT-MRT-' || h.user_id AS detail_id, NULL::VARCHAR AS account_id, h.user_id, 'MORTGAGE' AS debt_type,
                 mt.product_name,
                 CASE mt.product_name WHEN 'Festhypothek' THEN 'FIXED' WHEN 'SARON Rollover-Hypothek' THEN 'SARON'
                                      WHEN 'Starthypothek' THEN 'START' END AS rate_type,
                 NULL::DOUBLE AS original_principal, h.mortgage_outstanding_chf AS remaining_balance,
                 h.property_value_chf AS property_value,
                 round(100 * h.mortgage_outstanding_chf / nullif(h.property_value_chf, 0), 1) AS loan_to_value_pct,
                 NULL::DOUBLE AS interest_rate_pct, pp.p AS start_period, {ym('pp.p')} AS start_month,
                 NULL::VARCHAR AS maturity_date, h.mortgage_monthly_chf AS monthly_installment,
                 round(mp.obs, 2) AS observed_monthly_payment, false AS lender_identified,
                 h.is_mortgage_data_anomaly AS is_data_anomaly
          FROM client_housing h LEFT JOIN mp ON mp.usr_id = h.user_id LEFT JOIN mt USING (user_id)
          LEFT JOIN pp USING (user_id)
          WHERE h.mortgage_outstanding_chf IS NOT NULL
          UNION ALL
          SELECT 'DBT-' || CASE product_name WHEN 'Umweltdarlehen' THEN 'GRN-' ELSE 'PLN-' END || user_id, NULL, user_id,
                 CASE product_name WHEN 'Umweltdarlehen' THEN 'GREEN_LOAN' ELSE 'PERSONAL_LOAN' END, product_name,
                 NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, false
          FROM (SELECT DISTINCT user_id, product_name FROM client_declared_products
                WHERE product_name IN ('Barkredit / Privatkredit', 'Umweltdarlehen'))""")

    # interactions: empty in the source, schema kept
    x("CREATE TABLE interactions AS SELECT * FROM src_interaction")

    # buildings (GWR)
    cache = data / "gwr_cache.jsonl"
    labels = lambda ch, col: (f"(SELECT label_de FROM ref_gwr_codes r WHERE r.characteristic = '{ch}' "  # noqa: E731
                              f"AND r.code = TRY_CAST(g.a->>'{col}' AS INTEGER))")
    if cache.exists():
        x(f"""CREATE TABLE gwr_raw AS
              SELECT address_key, status, attributes AS a, queried_at
              FROM read_json('{cache.as_posix()}', format='newline_delimited', ignore_errors=true,
                             columns={{'address_key': 'VARCHAR', 'status': 'VARCHAR', 'attributes': 'JSON',
                                      'queried_at': 'VARCHAR'}})
              QUALIFY row_number() OVER (PARTITION BY address_key ORDER BY queried_at DESC) = 1""")
    else:
        x("CREATE TABLE gwr_raw (address_key VARCHAR, status VARCHAR, a JSON, queried_at VARCHAR)")
    x(f"""CREATE TABLE gwr_building_data AS
          SELECT p.user_id,
                 CASE WHEN (g.a->>'egid') IS NOT NULL THEN 'GWR-EGID-' || (g.a->>'egid') END AS address_id,
                 p.address AS street_address, p.plz AS zip_code, (g.a->>'egid') AS egid, (g.a->>'egrid') AS egrid,
                 (g.a->>'ggdename') AS municipality, TRY_CAST(g.a->>'ggdenr' AS INTEGER) AS municipality_bfs_nr,
                 TRY_CAST(g.a->>'gbauj' AS INTEGER) AS build_year, TRY_CAST(g.a->>'gbaup' AS INTEGER) AS build_period_code,
                 {labels('gbaup', 'gbaup')} AS build_period,
                 TRY_CAST(g.a->>'gkat' AS INTEGER) AS building_category_code, {labels('gkat', 'gkat')} AS building_category,
                 TRY_CAST(g.a->>'gklas' AS INTEGER) AS building_class_code, {labels('gklas', 'gklas')} AS building_class,
                 TRY_CAST(g.a->>'gastw' AS INTEGER) AS floors, TRY_CAST(g.a->>'ganzwhg' AS INTEGER) AS dwellings,
                 TRY_CAST(g.a->>'garea' AS INTEGER) AS footprint_m2,
                 TRY_CAST(g.a->>'gwaerzh1' AS INTEGER) AS heat_generator_code,
                 {labels('gwaerzh', 'gwaerzh1')} AS heat_generator_label_de,
                 TRY_CAST(g.a->>'genh1' AS INTEGER) AS energy_source_code, {labels('genh', 'genh1')} AS energy_source,
                 CASE WHEN TRY_CAST(g.a->>'gwaerzh1' AS INTEGER) IN (7410, 7411) THEN 'Heat Pump'
                      WHEN TRY_CAST(g.a->>'genh1' AS INTEGER) = 7530 THEN 'Oil Heating'
                      WHEN TRY_CAST(g.a->>'genh1' AS INTEGER) = 7520 THEN 'Gas'
                      WHEN TRY_CAST(g.a->>'genh1' AS INTEGER) IN (7580, 7581, 7582)
                           OR TRY_CAST(g.a->>'gwaerzh1' AS INTEGER) IN (7460, 7461) THEN 'District Heating'
                      WHEN TRY_CAST(g.a->>'genh1' AS INTEGER) IN (7540, 7541, 7542, 7543) THEN 'Wood/Pellet'
                      WHEN TRY_CAST(g.a->>'gwaerzh1' AS INTEGER) IN (7450, 7451, 7452)
                           OR TRY_CAST(g.a->>'genh1' AS INTEGER) = 7560 THEN 'Electric'
                      WHEN TRY_CAST(g.a->>'gwaerzh1' AS INTEGER) IN (7420, 7421)
                           OR TRY_CAST(g.a->>'genh1' AS INTEGER) = 7570 THEN 'Solar Thermal'
                      WHEN TRY_CAST(g.a->>'gwaerzh1' AS INTEGER) = 7400 OR TRY_CAST(g.a->>'genh1' AS INTEGER) = 7500
                           THEN 'None'
                      WHEN g.a IS NOT NULL AND (g.a->>'gwaerzh1') IS NULL AND (g.a->>'genh1') IS NULL THEN 'Not recorded'
                      WHEN g.a IS NOT NULL THEN 'Other/Undetermined' END AS heat_generator,
                 (g.a->>'gwaerdath1') AS heating_info_date,
                 TRY_CAST(g.a->>'gwaerzw1' AS INTEGER) AS hot_water_generator_code,
                 {labels('gwaerzw', 'gwaerzw1')} AS hot_water_generator,
                 TRY_CAST(g.a->>'gstat' AS INTEGER) AS building_status_code, {labels('gstat', 'gstat')} AS building_status,
                 TRY_CAST(g.a->>'gkode' AS DOUBLE) AS lv95_east, TRY_CAST(g.a->>'gkodn' AS DOUBLE) AS lv95_north,
                 CASE WHEN g.status IN ('exact', 'via_search', 'exact_no_number', 'via_search_no_number') THEN 1 ELSE 0 END AS gwr_verified,
                 coalesce(g.status, CASE WHEN p.address_key IS NULL THEN 'no_address' ELSE 'not_queried' END) AS match_status,
                 (g.a->>'gexpdat') AS register_extract_date
          FROM client_pii p LEFT JOIN gwr_raw g USING (address_key)""")

    # the documented 83-column feature table, for ML convenience
    if features_parquet and features_parquet.exists():
        x(f"CREATE TABLE client_features AS SELECT * FROM read_parquet('{features_parquet.as_posix()}')")

    counts = {t: con.execute(f"SELECT count(*) FROM src_{t}").fetchone()[0]
              for t in ["individual", "state", "account", "balance", "employer", "txn", "event", "interaction"]}
    x("CREATE TABLE dataset_metadata (key VARCHAR, value VARCHAR)")
    meta = {
        "run_id": run_id, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "calendar_assumption": "period = 12*year + month (24289 = 2024-01, 24301 = 2025-01); inferred, not confirmed",
        "reference_month": "2025-01", "flow_window": "2024-02 .. 2025-01 (periods 24290..24301)",
        "event_generated_by": ",".join(r[0] for r in con.execute("SELECT DISTINCT generated_by FROM src_event").fetchall()),
        "gwr_source": "api3.geo.admin.ch layer ch.bfs.gebaeude_wohnungs_register; labels: GWR Merkmalskatalog v4.2",
        **{f"source_rows_{k}": str(v) for k, v in counts.items()},
    }
    con.executemany("INSERT INTO dataset_metadata VALUES (?, ?)", list(meta.items()))


# --------------------------------------------------------------------------- checks

def check(con) -> list[str]:
    """Lossless and consistency checks. Returns failures (empty = OK)."""
    q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
    fails = []
    expect = {
        "core_clients": q("SELECT count(*) FROM src_individual"), "client_pii": q("SELECT count(*) FROM src_individual"),
        "accounts": q("SELECT count(*) FROM src_account"), "account_balances": q("SELECT count(*) FROM src_balance"),
        "transactions": q("SELECT count(*) FROM src_txn"), "employers": q("SELECT count(*) FROM src_employer"),
        "transfers": q("SELECT count(*) FROM src_event WHERE type IN ('savings_transfer','pillar3a','pillar3a_withdrawal','investment_contribution')"),
        "opening_balances": q("SELECT count(*) FROM src_event WHERE type = 'initial_balance'"),
        "client_life_events": q("SELECT count(*) FROM src_event WHERE type IN ('job_change','migration','marriage','divorce','birth','death','property_purchase')"),
        "interactions": q("SELECT count(*) FROM src_interaction"),
    }
    for t, n in expect.items():
        got = q(f"SELECT count(*) FROM {t}")
        if got != n:
            fails.append(f"{t}: {got} rows, expected {n}")
    # every event is represented: money events through the ledger, the others in their own tables
    orphan = q("""SELECT count(*) FROM src_event e WHERE e.type IN ('purchase','income','salary','rent','mortgage_payment',
                  'investment_return','savings_adjustment') AND NOT EXISTS
                  (SELECT 1 FROM transactions t WHERE t.source_event_id = e.event_id)""")
    if orphan:
        fails.append(f"{orphan} money events without a ledger row")
    bad = q("""SELECT count(*) FROM account_monthly_balances m JOIN account_balances b USING (acc_id)
               WHERE m.period = 24301 AND abs(m.ending_balance_chf - b.balance_chf) >= 0.01""")
    if bad:
        fails.append(f"{bad} accounts where the rebuilt balance differs from account_balance.csv")
    jsum = lambda c: (f"coalesce(list_sum(list_transform(json_keys({c}::JSON), "  # noqa: E731
                      f"k -> ({c}::JSON ->> k)::DOUBLE)), 0)")
    rec = q(f"""SELECT count(*) FROM monthly_financial_summaries
                WHERE abs(monthly_income - {jsum('income_by_cat_json')}) > 0.05
                   OR abs(monthly_expense - {jsum('spending_by_cat_json')}) > 0.05""")
    if rec:
        fails.append(f"{rec} monthly summaries where totals differ from the category sums")
    return fails


# --------------------------------------------------------------------------- SQLite export

def to_sqlite(con, out: Path, tables: list[str]) -> None:
    if out.exists():
        out.unlink()
    lite = sqlite3.connect(out)
    lite.execute("PRAGMA journal_mode = OFF")
    lite.execute("PRAGMA synchronous = OFF")
    for t in tables:
        cols = con.execute(f"DESCRIBE {t}").fetchall()
        decl, sel = [], []
        for name, ctype, *_ in cols:
            ct = ctype.upper()
            if ct in ("BOOLEAN",) or any(k in ct for k in ("INT",)):
                decl.append(f'"{name}" INTEGER')
                sel.append(f'CAST("{name}" AS BIGINT) AS "{name}"')
            elif any(k in ct for k in ("DOUBLE", "FLOAT", "DECIMAL", "REAL")):
                decl.append(f'"{name}" REAL')
                sel.append(f'CAST("{name}" AS DOUBLE) AS "{name}"')
            else:
                decl.append(f'"{name}" TEXT')
                sel.append(f'CAST("{name}" AS VARCHAR) AS "{name}"')
        pk = PRIMARY_KEYS.get(t)
        if pk:
            decl = [d + " PRIMARY KEY" if d.split()[0].strip('"') == pk else d for d in decl]
        lite.execute(f'CREATE TABLE "{t}" ({", ".join(decl)})')
        cur = con.execute(f"SELECT {', '.join(sel)} FROM {t}")
        ph = ",".join("?" * len(cols))
        while batch := cur.fetchmany(200_000):
            lite.executemany(f'INSERT INTO "{t}" VALUES ({ph})', batch)
        lite.commit()
    for name, spec in INDEXES:
        table = spec.split("(")[0]
        if table in tables:
            lite.execute(f"CREATE INDEX {name} ON {spec}")
    lite.execute("ANALYZE")
    lite.commit()
    lite.close()


EXPORT = ["dataset_metadata", "calendar", "core_clients", "client_pii", "gwr_building_data", "accounts",
          "account_balances", "account_monthly_balances", "transactions", "transfers", "opening_balances",
          "monthly_financial_summaries", "client_analytics_events", "client_analytics_features",
          "client_analytics_characteristics", "debt_details", "employers", "client_profile", "client_health",
          "client_interests", "client_declared_products", "client_housing", "client_outcomes", "client_life_events",
          "client_relationships", "interactions", "ref_mcc", "ref_gwr_codes", "client_features"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="data/nba_marketplace_real.db")
    ap.add_argument("--features", default="client_features/client_features.parquet")
    args = ap.parse_args()
    t0 = time.time()
    con = duckdb.connect()
    build(con, Path(args.data), Path(args.features))
    print(f"built in DuckDB: {time.time() - t0:.0f}s", flush=True)
    fails = check(con)
    for f in fails:
        print("CHECK FAILED:", f)
    if fails:
        raise SystemExit(1)
    print("checks passed", flush=True)
    tables = [t for t in EXPORT if con.execute(f"SELECT count(*) FROM information_schema.tables WHERE table_name = '{t}'").fetchone()[0]]
    to_sqlite(con, Path(args.out), tables)
    size = Path(args.out).stat().st_size / 1e6
    print(f"{args.out}: {len(tables)} tables, {size:.0f} MB, total {time.time() - t0:.0f}s")
    for t in tables:
        print(f"  {t}: {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:,}")


if __name__ == "__main__":
    main()
