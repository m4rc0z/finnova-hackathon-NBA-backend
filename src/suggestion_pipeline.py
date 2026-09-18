from dataclasses import asdict, dataclass
from typing import Any

from src.feature_engineering import ScoredAction
from src.parsers.csv_parser import Account


ACTION_PRODUCTS = {
    "offer_savings_account": (
        "Sparkonto",
        "Jugendsparkonto",
        "Sparkonto Young",
    ),
    "offer_pillar3a": (
        "Säule 3a-Konto",
        "Säule 3a Fondssparplan",
        "Lebensversicherung 3a",
    ),
    "offer_mortgage": ("Festhypothek",),
    "offer_investment": (
        "Anlagesparkonto",
        "Anlagekonto",
        "Fondssparplan",
        "Wertschriftendepot",
    ),
    "retirement_planning": (
        "Freizügigkeitskonto",
        "Säule 3a Fondssparplan",
        "Wertschriftendepot",
    ),
    "upsell_premium": (
        "Wertschriftendepot",
        "Anlagekonto",
    ),
}


@dataclass(frozen=True)
class ProductSuggestion:
    action: str
    product_name: str | None
    score: float
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def account_inventory(accounts: list[Account], individual_id: str) -> dict[str, Any]:
    customer_accounts = [
        account for account in accounts if account.individual_id == individual_id
    ]
    return {
        "product_names": sorted({account.product_name for account in customer_accounts}),
        "kinds": sorted({account.kind for account in customer_accounts}),
        "account_count": len(customer_accounts),
        "has_pillar3a": any(account.kind == "pillar3a" for account in customer_accounts),
        "has_savings": any(account.kind == "savings" for account in customer_accounts),
        "has_mortgage": any(account.kind == "mortgage" for account in customer_accounts),
        "has_investment": any(account.kind == "investment" for account in customer_accounts),
    }


def _savings_reasons(product_name: str, features: dict[str, Any]) -> list[str]:
    reasons = ["Noch kein Sparkonto vorhanden"]
    if (features.get("total_balance_chf") or 0) > 5000:
        reasons.append("Liquidität für regelmässiges Sparen vorhanden")
    if (features.get("age") or 0) < 26 and "Young" in product_name:
        reasons.append("Produkt passt zum jungen Kundenprofil")
    return reasons


def _pillar3a_reasons(features: dict[str, Any]) -> list[str]:
    reasons = ["Vorsorgeprodukt für steuerbegünstigtes Sparen"]
    if 25 <= (features.get("age") or 0) < 55:
        reasons.append("Alter liegt im typischen Ansparzeitraum")
    return reasons


def _mortgage_reasons(features: dict[str, Any]) -> list[str]:
    reasons = ["Hypothekenprodukt im Produktkatalog vorhanden"]
    if (features.get("total_balance_chf") or 0) > 20000:
        reasons.append("Eigenkapitalpotenzial vorhanden")
    return reasons


def _investment_reasons(product_name: str) -> list[str]:
    reasons = ["Anlageprodukt passend zu verfügbarem Kapital"]
    if product_name in {"Fondssparplan", "Wertschriftendepot"}:
        reasons.append("Langfristiger Vermögensaufbau möglich")
    return reasons


def _retirement_reasons(inventory: dict[str, Any]) -> list[str]:
    reasons = ["Produkt unterstützt die Ruhestandsplanung"]
    if inventory["has_pillar3a"]:
        reasons.append("Bestehende Vorsorge kann optimiert werden")
    return reasons


def _product_reasons(
    action: str,
    product_name: str,
    features: dict[str, Any],
    inventory: dict[str, Any],
) -> list[str]:
    handlers = {
        "offer_savings_account": lambda: _savings_reasons(product_name, features),
        "offer_pillar3a": lambda: _pillar3a_reasons(features),
        "offer_mortgage": lambda: _mortgage_reasons(features),
        "offer_investment": lambda: _investment_reasons(product_name),
        "retirement_planning": lambda: _retirement_reasons(inventory),
        "upsell_premium": lambda: ["Erweitert das bestehende Produktportfolio"],
    }
    return handlers.get(action, lambda: [])()


def build_product_suggestions(
    scored_actions: list[ScoredAction],
    features: dict[str, Any],
    accounts: list[Account],
) -> list[ProductSuggestion]:
    """Attach concrete, not-yet-owned products to scored actions."""
    individual_id = features["individual_id"]
    inventory = account_inventory(accounts, individual_id)
    owned_products = set(inventory["product_names"])
    suggestions = []

    for scored_action in scored_actions:
        products = ACTION_PRODUCTS.get(scored_action.action, ())
        if scored_action.action == "offer_pillar3a" and inventory["has_pillar3a"]:
            continue
        if scored_action.action == "offer_mortgage" and inventory["has_mortgage"]:
            continue
        if scored_action.action == "offer_investment" and inventory["has_investment"]:
            continue
        available = [product for product in products if product not in owned_products]
        if not available:
            continue
        product_name = available[0]
        suggestions.append(
            ProductSuggestion(
                action=scored_action.action,
                product_name=product_name,
                score=scored_action.score,
                reasons=scored_action.reasons + _product_reasons(
                    scored_action.action,
                    product_name,
                    features,
                    inventory,
                ),
            )
        )
    return suggestions
