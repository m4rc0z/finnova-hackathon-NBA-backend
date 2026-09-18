import csv
import json
from pathlib import Path
from pydantic import BaseModel
from src.parsers.csv_parser import DataLoader
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request

COLLECTIONS = {
    "accounts": "accounts",
    "account-balances": "account_balances",
    "employers": "employers",
    "events": "events",
    "transactions": "transactions",
    "interactions": "interactions",
    "individuals": "individuals",
    "individual-states": "individual_states",
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.loader = DataLoader("data/")
    yield

app = FastAPI(
    title="Finnova NBA Data API",
    version="0.1.0",
    lifespan=lifespan,
)

def get_collection(request: Request, collection: str) -> list[Any]:
    attribute = COLLECTIONS.get(collection)
    if attribute is None:
        raise HTTPException(status_code=404, detail=f"Unknown collection: {collection}")
    return getattr(request.app.state.loader, attribute)

def matches_filters(
    item: Any,
    run_id: str | None,
    period: int | None,
    individual_id: str | None,
    account_id: str | None,
) -> bool:
    if run_id is not None and getattr(item, "run_id", None) != run_id:
        return False
    if period is not None and getattr(item, "period", None) != period:
        return False
    if individual_id is not None and getattr(item, "individual_id", None) != individual_id:
        return False
    if account_id is not None and getattr(item, "account_id", None) != account_id:
        return False
    return True

@app.get("/health")
@app.get("/api/status")
def health(request: Request) -> dict[str, str]:
    status = "loaded" if hasattr(request.app.state, "loader") else "loading"
    return {"status": "ok", "data": status}

@app.get("/api/v1/{collection}", responses={404: {"description": "Unknown collection"}})
def list_collection(
    request: Request,
    collection: str,
    run_id: str | None = None,
    period: int | None = None,
    individual_id: str | None = None,
    account_id: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict[str, Any]:
    items = get_collection(request, collection)
    filtered_items = [
        item
        for item in items
        if matches_filters(item, run_id, period, individual_id, account_id)
    ]
    page = filtered_items[offset : offset + limit]
    return {
        "collection": collection,
        "total": len(filtered_items),
        "offset": offset,
        "limit": limit,
        "items": [item.model_dump() for item in page],
    }

@app.get("/api/v1/{collection}/{item_id}", responses={404: {"description": "Item not found"}})
def get_item(
    request: Request,
    collection: str,
    item_id: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    items = get_collection(request, collection)
    id_field = {
        "accounts": "account_id",
        "account-balances": "account_id",
        "employers": "employer_id",
        "events": "event_id",
        "transactions": "txn_id",
        "interactions": "interaction_id",
        "individuals": "individual_id",
        "individual-states": "individual_id",
    }[collection]
    matches = [
        item
        for item in items
        if getattr(item, id_field, None) == item_id
        and (run_id is None or getattr(item, "run_id", None) == run_id)
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="Item not found")
    if len(matches) > 1:
        return {"items": [item.model_dump() for item in matches]}
    return matches[0].model_dump()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000)