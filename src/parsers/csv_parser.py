import csv
import json
from pathlib import Path
from pydantic import BaseModel


# ── Models ────────────────────────────────────────────────────────────────────

class Account(BaseModel):
    account_id: str
    run_id: str
    individual_id: str
    kind: str
    opened_period: int
    closed_period: int | None
    product_name: str


class AccountBalance(BaseModel):
    account_id: str
    run_id: str
    period: int
    balance_chf: float


class Employer(BaseModel):
    employer_id: str
    run_id: str
    sector: str
    region: str
    size_band: str


class Event(BaseModel):
    event_id: str
    run_id: str
    individual_id: str
    counterparty: str | None
    period: int
    type: str
    effects: str
    generated_by: str


class Transaction(BaseModel):
    txn_id: str
    run_id: str
    account_id: str
    period: int
    amount_chf: float
    category: str
    source_event: str | None
    day_of_month: int | None


class Interaction(BaseModel):
    interaction_id: str
    run_id: str
    individual_id: str
    period: int
    type: str
    channel: str
    direction: str
    category: str
    subject: str
    notes: str | None
    priority: str
    status: str
    resolution: str | None
    product: str | None
    stage: str | None
    probability: float | None
    expected_value: float | None
    duration_min: int | None
    source_event_id: str | None
    closed_period: int | None
    generated_by: str


class Individual(BaseModel):
    individual_id: str
    run_id: str
    period: int
    income_chf: float
    employer_id: str | None
    marital_status: str
    household_id: str
    education_level: str
    employment: str


class IndividualAttributes(BaseModel):
    age: int
    bmi: float | None = None
    plz: str | None = None
    sex: str | None = None
    city: str | None = None
    canton: str
    sector: str | None = None
    street: str | None = None
    stress: int
    values: dict


class IndividualState(BaseModel):
    individual_id: str
    run_id: str
    birth_period: int
    sex: str
    attributes: IndividualAttributes
    death_period: int | None


# ── DataLoader ────────────────────────────────────────────────────────────────

class DataLoader:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.accounts: list[Account] = []
        self.account_balances: list[AccountBalance] = []
        self.employers: list[Employer] = []
        self.events: list[Event] = []
        self.transactions: list[Transaction] = []
        self.interactions: list[Interaction] = []
        self.individuals: list[Individual] = []
        self.individual_states: list[IndividualState] = []
        self._load_all()

    def _load_all(self):
        self.accounts = self._parse(
            "account.csv",
            lambda row: Account(
                account_id=row["account_id"],
                run_id=row["run_id"],
                individual_id=row["individual_id"],
                kind=row["kind"],
                opened_period=int(row["opened_period"]),
                closed_period=int(row["closed_period"]) if row["closed_period"] else None,
                product_name=row["product_name"],
            ),
        )
        self.account_balances = self._parse(
            "account_balance.csv",
            lambda row: AccountBalance(
                account_id=row["account_id"],
                run_id=row["run_id"],
                period=int(row["period"]),
                balance_chf=float(row["balance_chf"]),
            ),
        )
        self.employers = self._parse(
            "employer.csv",
            lambda row: Employer(
                employer_id=row["employer_id"],
                run_id=row["run_id"],
                sector=row["sector"],
                region=row["region"],
                size_band=row["size_band"],
            ),
        )
        self.events = self._parse(
            "event.csv",
            lambda row: Event(
                event_id=row["event_id"],
                run_id=row["run_id"],
                individual_id=row["individual_id"],
                counterparty=row["counterparty_id"] if row["counterparty_id"] else None,  # 👈 Fix
                period=int(row["period"]),
                type=row["type"],
                effects=row["effects"],
                generated_by=row["generated_by"],
            ),
        )
        self.transactions = self._parse(
            "transaction.csv",
            lambda row: Transaction(
                txn_id=row["txn_id"],
                run_id=row["run_id"],
                account_id=row["account_id"],
                period=int(row["period"]),
                amount_chf=float(row["amount_chf"]),
                category=row["category"],
                source_event=row["source_event_id"] if row["source_event_id"] else None,
                day_of_month=int(row["day_of_month"]) if row["day_of_month"] else None,
            ),
        )
        self.interactions = self._parse(
            "interaction.csv",
            lambda row: Interaction(
                interaction_id=row["interaction_id"],
                run_id=row["run_id"],
                individual_id=row["individual_id"],
                period=int(row["period"]),
                type=row["type"],
                channel=row["channel"],
                direction=row["direction"],
                category=row["category"],
                subject=row["subject"],
                notes=row["notes"] if row["notes"] else None,
                priority=row["priority"],
                status=row["status"],
                resolution=row["resolution"] if row["resolution"] else None,
                product=row["product"] if row["product"] else None,
                stage=row["stage"] if row["stage"] else None,
                probability=float(row["probability"]) if row["probability"] else None,
                expected_value=float(row["expected_value"]) if row["expected_value"] else None,
                duration_min=int(row["duration_min"]) if row["duration_min"] else None,
                source_event_id=row["source_event_id"] if row["source_event_id"] else None,
                closed_period=int(row["closed_period"]) if row["closed_period"] else None,
                generated_by=row["generated_by"],
            ),
        )
        self.individuals = self._parse(
            "individual_state.csv",
            lambda row: Individual(
                individual_id=row["individual_id"],
                run_id=row["run_id"],
                period=int(row["period"]),
                income_chf=float(row["income_chf"]),
                employer_id=row["employer_id"] if row["employer_id"] else None,
                marital_status=row["marital_status"],
                household_id=row["household_id"],
                education_level=row["education_level"],
                employment=row["employment_type"],
            ),
        )
        self.individual_states = self._parse(
            "individual.csv",
            lambda row: IndividualState(
                individual_id=row["individual_id"],
                run_id=row["run_id"],
                birth_period=int(row["birth_period"]),
                sex=row["sex"],
                attributes=IndividualAttributes(**json.loads(row["attributes"])),
                death_period=int(row["death_period"]) if row["death_period"] else None,
            ),
        )

    def _parse(self, filename: str, factory) -> list:
        filepath = self.data_dir / filename
        results = []
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                results.append(factory(row))
        return results
