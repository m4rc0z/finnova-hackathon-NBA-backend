from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from src.parsers.csv_parser import DataLoader


ACTIONS = (
    "offer_savings_account",
    "offer_pillar3a",
    "offer_mortgage",
    "offer_investment",
    "retention_call",
    "upsell_premium",
    "financial_advice",
    "retirement_planning",
)


@dataclass
class ScoredAction:
    action: str
    score: float
    reasons: list[str]


def _empty_features(individual_id: str) -> dict[str, Any]:
    return {
        "individual_id": individual_id,
        "age": None,
        "bmi": None,
        "sex": None,
        "canton": None,
        "stress": None,
        "birth_period": None,
        "is_deceased": False,
        "income_chf": None,
        "marital_status": None,
        "education_level": None,
        "employment": None,
        "has_employer": False,
        "num_accounts": 0,
        "num_closed_accounts": 0,
        "has_savings": False,
        "has_checking": False,
        "has_pillar3a": False,
        "unique_products": 0,
        "total_balance_chf": 0.0,
        "avg_balance_chf": 0.0,
        "min_balance_chf": 0.0,
        "max_balance_chf": 0.0,
        "has_negative_balance": False,
        "total_spent_chf": 0.0,
        "total_income_chf": 0.0,
        "num_transactions": 0,
        "unique_categories": 0,
        "avg_txn_amount": 0.0,
        "top_spend_category": None,
        "num_interactions": 0,
        "num_open_interactions": 0,
        "preferred_channel": None,
        "last_interaction_period": None,
    }


def build_customer_features(loader: DataLoader) -> list[dict[str, Any]]:
    """Build one feature dictionary per individual from the loaded CSV models."""
    features: dict[str, dict[str, Any]] = {}

    def get(individual_id: str) -> dict[str, Any]:
        if individual_id not in features:
            features[individual_id] = _empty_features(individual_id)
        return features[individual_id]

    for state in loader.individual_states:
        row = get(state.individual_id)
        row.update(
            age=state.attributes.age,
            bmi=state.attributes.bmi,
            sex=state.attributes.sex,
            canton=state.attributes.canton,
            stress=state.attributes.stress,
            birth_period=state.birth_period,
            is_deceased=state.death_period is not None,
        )

    latest_individuals: dict[str, Any] = {}
    for individual in loader.individuals:
        previous = latest_individuals.get(individual.individual_id)
        if previous is None or individual.period >= previous.period:
            latest_individuals[individual.individual_id] = individual
    for individual in latest_individuals.values():
        row = get(individual.individual_id)
        row.update(
            income_chf=individual.income_chf,
            marital_status=individual.marital_status,
            education_level=individual.education_level,
            employment=individual.employment,
            has_employer=individual.employer_id is not None,
        )

    account_to_individual: dict[str, str] = {}
    product_sets: dict[str, set[str]] = defaultdict(set)
    for account in loader.accounts:
        row = get(account.individual_id)
        account_to_individual[account.account_id] = account.individual_id
        row["num_accounts"] += 1
        row["num_closed_accounts"] += int(account.closed_period is not None)
        row["has_savings"] |= account.kind == "savings"
        row["has_checking"] |= account.kind == "checking"
        row["has_pillar3a"] |= account.kind == "pillar3a"
        product_sets[account.individual_id].add(account.product_name)
    for individual_id, products in product_sets.items():
        get(individual_id)["unique_products"] = len(products)

    latest_balances: dict[str, Any] = {}
    for balance in loader.account_balances:
        previous = latest_balances.get(balance.account_id)
        if previous is None or balance.period >= previous.period:
            latest_balances[balance.account_id] = balance
    balances_by_individual: dict[str, list[float]] = defaultdict(list)
    for account_id, balance in latest_balances.items():
        individual_id = account_to_individual.get(account_id)
        if individual_id is not None:
            balances_by_individual[individual_id].append(balance.balance_chf)
    for individual_id, balances in balances_by_individual.items():
        row = get(individual_id)
        row["total_balance_chf"] = sum(balances)
        row["avg_balance_chf"] = sum(balances) / len(balances)
        row["min_balance_chf"] = min(balances)
        row["max_balance_chf"] = max(balances)
        row["has_negative_balance"] = any(balance < 0 for balance in balances)

    transaction_totals: dict[str, dict[str, Any]] = {}
    spend_categories: dict[str, Counter[str]] = defaultdict(Counter)
    for transaction in loader.transactions:
        individual_id = account_to_individual.get(transaction.account_id)
        if individual_id is None:
            continue
        aggregate = transaction_totals.setdefault(
            individual_id,
            {"spent": 0.0, "income": 0.0, "count": 0, "categories": set(), "amount": 0.0},
        )
        aggregate["count"] += 1
        aggregate["amount"] += transaction.amount_chf
        aggregate["categories"].add(transaction.category)
        if transaction.amount_chf < 0:
            aggregate["spent"] += transaction.amount_chf
            spend_categories[individual_id][transaction.category] += 1
        else:
            aggregate["income"] += transaction.amount_chf
    for individual_id, aggregate in transaction_totals.items():
        row = get(individual_id)
        row["total_spent_chf"] = aggregate["spent"]
        row["total_income_chf"] = aggregate["income"]
        row["num_transactions"] = aggregate["count"]
        row["unique_categories"] = len(aggregate["categories"])
        row["avg_txn_amount"] = aggregate["amount"] / aggregate["count"]
        if spend_categories[individual_id]:
            row["top_spend_category"] = spend_categories[individual_id].most_common(1)[0][0]

    interaction_channels: dict[str, Counter[str]] = defaultdict(Counter)
    for interaction in loader.interactions:
        row = get(interaction.individual_id)
        row["num_interactions"] += 1
        row["num_open_interactions"] += int(interaction.status == "open")
        row["last_interaction_period"] = max(
            row["last_interaction_period"] or interaction.period,
            interaction.period,
        )
        interaction_channels[interaction.individual_id][interaction.channel] += 1
    for individual_id, channels in interaction_channels.items():
        get(individual_id)["preferred_channel"] = channels.most_common(1)[0][0]

    return list(features.values())


def _score_savings(row: dict[str, Any]) -> ScoredAction:
    score, reasons = 0.0, []
    if not row.get("has_savings", False):
        score, reasons = score + 30, reasons + ["Kein Sparkonto vorhanden"]
    if (row.get("total_balance_chf") or 0) > 5000:
        score, reasons = score + 20, reasons + ["Hoher Gesamtsaldo"]
    if (row.get("income_chf") or 0) > 5000:
        score, reasons = score + 15, reasons + ["Hohes Einkommen"]
    return ScoredAction("offer_savings_account", score, reasons)


def _score_pillar3a(row: dict[str, Any]) -> ScoredAction:
    score, reasons = 0.0, []
    age = row.get("age") or 0
    if not row.get("has_pillar3a", False) and 25 <= age < 55:
        score, reasons = score + 30, reasons + ["Optimales Alter für Säule 3a"]
    if not row.get("has_pillar3a", False) and row.get("employment") == "employed":
        score, reasons = score + 20, reasons + ["Angestellt"]
    if not row.get("has_pillar3a", False) and (row.get("income_chf") or 0) > 4000:
        score, reasons = score + 15, reasons + ["Ausreichendes Einkommen"]
    if row.get("has_pillar3a", False):
        reasons.append("Säule 3a bereits vorhanden")
    return ScoredAction("offer_pillar3a", score, reasons)


def _score_mortgage(row: dict[str, Any]) -> ScoredAction:
    score, reasons = 0.0, []
    age = row.get("age") or 0
    balance = row.get("total_balance_chf") or 0
    if 30 <= age < 60:
        score, reasons = score + 20, reasons + ["Typisches Hypothekenalter"]
    if balance > 20000:
        score, reasons = score + 30, reasons + ["Ausreichend Eigenkapital"]
    if row.get("marital_status") == "married":
        score, reasons = score + 10, reasons + ["Verheiratet"]
    return ScoredAction("offer_mortgage", score, reasons)


def _score_investment(row: dict[str, Any]) -> ScoredAction:
    score, reasons = 0.0, []
    if (row.get("total_balance_chf") or 0) > 10000:
        score, reasons = score + 25, reasons + ["Hoher Saldo - Investitionspotenzial"]
    if not row.get("has_negative_balance", False):
        score, reasons = score + 15, reasons + ["Keine negativen Salden"]
    if (row.get("age") or 0) < 50:
        score, reasons = score + 10, reasons + ["Langer Anlagehorizont"]
    return ScoredAction("offer_investment", score, reasons)


def _score_retention(row: dict[str, Any]) -> ScoredAction:
    score, reasons = 0.0, []
    if row.get("num_closed_accounts", 0) > 0:
        score, reasons = score + 35, reasons + ["Geschlossene Konten detektiert"]
    if row.get("has_negative_balance", False):
        score, reasons = score + 25, reasons + ["Negativer Saldo"]
    if row.get("num_open_interactions", 0) > 2:
        score, reasons = score + 20, reasons + ["Mehrere offene Interaktionen"]
    return ScoredAction("retention_call", score, reasons)


def _score_premium(row: dict[str, Any]) -> ScoredAction:
    score, reasons = 0.0, []
    if row.get("num_accounts", 0) >= 2:
        score, reasons = score + 20, reasons + ["Mehrere Konten"]
    if (row.get("total_balance_chf") or 0) > 15000:
        score, reasons = score + 25, reasons + ["Premium-Saldo"]
    if row.get("unique_products", 0) >= 2:
        score, reasons = score + 15, reasons + ["Mehrere Produkte"]
    return ScoredAction("upsell_premium", score, reasons)


def _score_advice(row: dict[str, Any]) -> ScoredAction:
    score, reasons = 0.0, []
    if (row.get("stress") or 0) > 60:
        score, reasons = score + 30, reasons + ["Hoher Stress-Score"]
    category = row.get("top_spend_category")
    if category in {"health", "rent"}:
        score, reasons = score + 20, reasons + [f"Hohe Ausgaben: {category}"]
    if row.get("has_negative_balance", False):
        score, reasons = score + 25, reasons + ["Negativer Saldo"]
    return ScoredAction("financial_advice", score, reasons)


def _score_retirement(row: dict[str, Any]) -> ScoredAction:
    score, reasons = 0.0, []
    age = row.get("age") or 0
    if age >= 60 or row.get("employment") in {"retired", "Pensioniert"}:
        score += 40
        reasons.append("Ruhestand oder naher Ruhestand")
    if row.get("has_pillar3a", False):
        score += 20
        reasons.append("Vorhandenes Vorsorgeprodukt optimieren")
    if row.get("num_interactions", 0) == 0:
        score += 15
        reasons.append("Keine bisherigen Beratungsgespräche")
    return ScoredAction("retirement_planning", score, reasons)


def score_actions(row: dict[str, Any]) -> list[ScoredAction]:
    """Score the configured next-best-actions for one feature row."""
    scorers = (
        _score_savings,
        _score_pillar3a,
        _score_mortgage,
        _score_investment,
        _score_retention,
        _score_premium,
        _score_advice,
        _score_retirement,
    )
    return sorted((scorer(row) for scorer in scorers), key=lambda item: item.score, reverse=True)


def get_top_actions(row: dict[str, Any], top_n: int = 3) -> list[dict[str, Any]]:
    return [asdict(action) for action in score_actions(row)[:top_n]]
