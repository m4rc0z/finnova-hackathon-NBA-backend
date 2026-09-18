import csv
import json
from pathlib import Path
from pydantic import BaseModel
from src.parsers.csv_parser import DataLoader

if __name__ == "__main__":
    loader = DataLoader("data/")
    print(f"Accounts:          {len(loader.accounts)}")
    print(f"Account Balances:  {len(loader.account_balances)}")
    print(f"Employers:         {len(loader.employers)}")
    print(f"Events:            {len(loader.events)}")
    print(f"Transactions:      {len(loader.transactions)}")
    print(f"Interactions:      {len(loader.interactions)}")
    print(f"Individuals:       {len(loader.individuals)}")
    print(f"Individual States: {len(loader.individual_states)}")