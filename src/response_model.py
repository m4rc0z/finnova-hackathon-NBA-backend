"""Streaming training data for next-best-action response modelling.

The source data has a simulated period and, for transactions/events, a day in
that period. ``period * 31 + day`` is used only as an ordering key; it is not a
calendar date.
"""

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sklearn.linear_model import LogisticRegression

from src.feature_engineering import ACTIONS


ACTION_CATEGORIES = {
    "offer_savings_account": {"savings_transfer", "savings_adjustment"},
    "offer_pillar3a": {"pillar3a", "pillar3a_withdrawal"},
    "offer_mortgage": {
        "mortgage",
        "mortgage_payment",
        "property_purchase",
        "property_down_payment",
    },
    "offer_investment": {"investment", "investment_contribution", "investment_return"},
    "financial_advice": {"advice", "financial_advice", "consultation"},
    "retirement_planning": {"retirement", "pension", "retirement_planning"},
}


@dataclass(frozen=True)
class ResponseExample:
    individual_id: str
    period: int
    day_of_month: int
    action: str
    converted_within_7_days: bool
    feature_values: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "individual_id": self.individual_id,
            "period": self.period,
            "day_of_month": self.day_of_month,
            "action": self.action,
            "converted_within_7_days": self.converted_within_7_days,
            "features": self.feature_values,
        }


class ResponseClassifier:
    """Small interpretable response model for action ranking."""

    def __init__(self, model: LogisticRegression, actions: tuple[str, ...]):
        self.model = model
        self.actions = actions

    def predict_probability(self, features: dict[str, Any], action: str) -> float:
        values = _vectorize(features, action, self.actions)
        return float(self.model.predict_proba([values])[0][1])

    def rank_actions(self, features: dict[str, Any]) -> list[dict[str, Any]]:
        ranked = [
            {
                "action": action,
                "score": self.predict_probability(features, action),
            }
            for action in self.actions
        ]
        return sorted(ranked, key=lambda item: item["score"], reverse=True)


def _vectorize(
    features: dict[str, Any], action: str, actions: tuple[str, ...]
) -> list[float]:
    return [
        float(features.get("income_chf") or 0),
        float(features.get("has_employer", False)),
        float(features.get("age") or 0),
        float(features.get("stress") or 0),
        float(features.get("total_balance_chf") or 0),
        float(features.get("num_accounts") or 0),
        *[float(action == candidate) for candidate in actions],
    ]


def train_response_model(
    examples: list[ResponseExample],
    actions: Iterable[str] = ACTIONS,
    test_period: int | None = None,
) -> tuple[ResponseClassifier, dict[str, float]]:
    """Train with past periods and evaluate on later periods only."""
    action_list = tuple(actions)
    periods = sorted({example.period for example in examples})
    if len(periods) < 2:
        raise ValueError("At least two periods are required for a temporal split")
    split_period = test_period or periods[-1]
    train = [example for example in examples if example.period < split_period]
    test = [example for example in examples if example.period >= split_period]
    if not train or not test:
        raise ValueError("Temporal split produced an empty train or test set")
    x_train = [_vectorize(example.feature_values, example.action, action_list) for example in train]
    y_train = [int(example.converted_within_7_days) for example in train]
    if len(set(y_train)) < 2:
        raise ValueError("Training labels must contain both conversion classes")
    model = LogisticRegression(max_iter=500, class_weight="balanced")
    model.fit(x_train, y_train)
    classifier = ResponseClassifier(model, action_list)
    predictions = [
        classifier.predict_probability(example.feature_values, example.action)
        for example in test
    ]
    actual = [int(example.converted_within_7_days) for example in test]
    ranked_pairs = sorted(zip(predictions, actual), reverse=True)
    top_k = ranked_pairs[: min(10, len(ranked_pairs))]
    return classifier, {
        "train_examples": float(len(train)),
        "test_examples": float(len(test)),
        "test_conversion_rate": sum(actual) / len(actual),
        "top_10_precision": sum(label for _, label in top_k) / len(top_k),
    }


def observation_key(period: int, day_of_month: int) -> int:
    """Return an ordering key for the simulated period/day axis."""
    return period * 31 + day_of_month


def _event_day(event: dict[str, str], effects: dict[str, Any]) -> int:
    value = effects.get("day_of_month", event.get("day_of_month", 1))
    try:
        return int(value or 1)
    except (TypeError, ValueError):
        return 1


def _event_actions(event_type: str, effects: dict[str, Any]) -> set[str]:
    values = {event_type.lower()}
    values.update(str(value).lower() for value in effects.values() if isinstance(value, str))
    actions = set()
    for action, categories in ACTION_CATEGORIES.items():
        if values.intersection(categories):
            actions.add(action)
    return actions


def _transaction_actions(transaction: dict[str, str]) -> set[str]:
    category = transaction["category"].lower()
    actions = {
        action
        for action, categories in ACTION_CATEGORIES.items()
        if category in categories
    }
    if category == "savings":
        actions.add("offer_savings_account")
    return actions


def _load_account_owners(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["account_id"]: row["individual_id"]
            for row in csv.DictReader(handle)
        }


def _load_response_events(data_dir: Path) -> dict[str, dict[str, list[int]]]:
    responses: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    event_path = data_dir / "event.csv"
    with event_path.open(newline="", encoding="utf-8") as handle:
        for event in csv.DictReader(handle):
            try:
                effects = json.loads(event["effects"] or "{}")
            except json.JSONDecodeError:
                effects = {}
            event_key = observation_key(int(event["period"]), _event_day(event, effects))
            for action in _event_actions(event["type"], effects):
                responses[event["individual_id"]][action].append(event_key)
    return responses


def _load_transaction_responses(
    data_dir: Path,
    account_owners: dict[str, str],
    responses: dict[str, dict[str, list[int]]],
) -> None:
    transaction_path = data_dir / "transaction.csv"
    with transaction_path.open(newline="", encoding="utf-8") as handle:
        for transaction in csv.DictReader(handle):
            individual_id = account_owners.get(transaction["account_id"])
            if individual_id is None:
                continue
            day = int(transaction["day_of_month"] or 1)
            event_key = observation_key(int(transaction["period"]), day)
            for action in _transaction_actions(transaction):
                responses[individual_id][action].append(event_key)


def _load_observations(data_dir: Path) -> list[tuple[str, int, int, dict[str, Any]]]:
    """Load historical customer states used as prediction cut-offs.

    ``individual_state.csv`` is the period-based financial state in this
    repository. It has no day column, so state observations use day 1.
    """
    observations = []
    path = data_dir / "individual_state.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            observations.append(
                (
                    row["individual_id"],
                    int(row["period"]),
                    1,
                    {
                        "income_chf": float(row["income_chf"]),
                        "marital_status": row["marital_status"],
                        "employment": row["employment_type"],
                        "has_employer": bool(row["employer_id"]),
                    },
                )
            )
    return observations


def build_response_examples(
    data_dir: str | Path,
    actions: Iterable[str] = ACTIONS,
    window_days: int = 7,
) -> list[ResponseExample]:
    """Build labelled customer/action examples without using future features."""
    data_path = Path(data_dir)
    account_owners = _load_account_owners(data_path / "account.csv")
    responses = _load_response_events(data_path)
    _load_transaction_responses(data_path, account_owners, responses)
    action_list = tuple(actions)
    examples = []
    for individual_id, period, day, features in _load_observations(data_path):
        start = observation_key(period, day)
        for action in action_list:
            converted = any(
                start < response_key <= start + window_days
                for response_key in responses.get(individual_id, {}).get(action, ())
            )
            examples.append(
                ResponseExample(
                    individual_id=individual_id,
                    period=period,
                    day_of_month=day,
                    action=action,
                    converted_within_7_days=converted,
                    feature_values=features,
                )
            )
    return examples
