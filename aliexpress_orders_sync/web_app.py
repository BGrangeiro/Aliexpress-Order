from __future__ import annotations

import os
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .database import OrderFilters
from .web_service import (
    AccountNotFoundError,
    ServiceConflictError,
    WebMonitorService,
    app_base_dir,
)


class AccountCommand(BaseModel):
    account_key: str | None = None


class AccountCreateCommand(BaseModel):
    email: str
    responsible: str
    display_name: str


service = WebMonitorService()
static_dir = Path(__file__).resolve().parent / "web_static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    service.shutdown()


app = FastAPI(title="AliExpress Pedidos", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(static_dir / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/state")
def state():
    return service.snapshot()


@app.get("/api/accounts")
def accounts():
    return {
        "accounts": service.accounts(),
        "responsibles": service.responsibles(),
    }


@app.post("/api/accounts")
def create_account(command: AccountCreateCommand):
    try:
        account = service.add_account(
            email=command.email,
            responsible=command.responsible,
            display_name=command.display_name,
        )
        return {"account": account}
    except ServiceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/accounts/{account_key}")
def update_account(account_key: str, command: AccountCreateCommand):
    try:
        return {
            "account": service.update_account(
                account_key=account_key,
                email=command.email,
                responsible=command.responsible,
                display_name=command.display_name,
            )
        }
    except ServiceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/accounts/{account_key}")
def delete_account(account_key: str):
    try:
        return {"account": service.delete_account(account_key)}
    except ServiceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/statuses")
def statuses():
    return {"statuses": service.statuses()}


@app.get("/api/filter-options")
def filter_options():
    return service.filter_options()


@app.get("/api/orders")
def orders(
    account_key: str = "",
    responsible: str = "",
    status: str = "",
    tracking: str = Query(default="all", pattern="^(all|multiple|single|none)$"),
    date_from: str = "",
    date_to: str = "",
    search: str = "",
    payment_method: str = "",
    currency: str = "",
    min_total: float | None = Query(default=None, ge=0),
    max_total: float | None = Query(default=None, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    filters = _filters_from_query(
        account_key,
        responsible,
        status,
        tracking,
        date_from,
        date_to,
        search,
        payment_method,
        currency,
        min_total,
        max_total,
    )
    result = service.orders(filters, limit, offset)
    result["stats"] = service.dashboard(filters)
    return result


@app.get("/api/analytics")
def analytics(
    account_key: str = "",
    responsible: str = "",
    status: str = "",
    tracking: str = Query(default="all", pattern="^(all|multiple|single|none)$"),
    date_from: str = "",
    date_to: str = "",
    search: str = "",
    payment_method: str = "",
    currency: str = "",
    min_total: float | None = Query(default=None, ge=0),
    max_total: float | None = Query(default=None, ge=0),
):
    filters = _filters_from_query(
        account_key,
        responsible,
        status,
        tracking,
        date_from,
        date_to,
        search,
        payment_method,
        currency,
        min_total,
        max_total,
    )
    return service.analytics(filters)


@app.post("/api/account")
def select_account(command: AccountCommand):
    if not command.account_key:
        raise HTTPException(status_code=400, detail="Selecione uma conta.")
    _run_command(lambda: service.select_account(command.account_key))
    return {"accepted": True}


@app.post("/api/browser/open")
def open_browser(command: AccountCommand):
    _run_command(lambda: service.open_browser(command.account_key))
    return {"accepted": True}


@app.post("/api/monitor/start")
def start_monitor(command: AccountCommand):
    _run_command(lambda: service.start_monitoring(command.account_key))
    return {"accepted": True}


@app.post("/api/monitor/stop")
def stop_monitor():
    service.stop_monitoring()
    return {"accepted": True}


@app.post("/api/sync/full")
def full_sync(command: AccountCommand):
    _run_command(lambda: service.run_full_sync(command.account_key))
    return {"accepted": True}


def _run_command(command) -> None:
    try:
        command()
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ServiceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _filters_from_query(
    account_key: str,
    responsible: str,
    status: str,
    tracking: str,
    date_from: str,
    date_to: str,
    search: str,
    payment_method: str,
    currency: str,
    min_total: float | None,
    max_total: float | None,
) -> OrderFilters:
    if min_total is not None and max_total is not None and min_total > max_total:
        raise HTTPException(
            status_code=422,
            detail="O valor mínimo não pode ser maior que o valor máximo.",
        )
    return OrderFilters(
        account_key=account_key.strip(),
        responsible=responsible.strip(),
        status=status.strip(),
        tracking=tracking,
        date_from=date_from.strip(),
        date_to=date_to.strip(),
        search=search.strip(),
        payment_method=payment_method.strip(),
        currency=currency.strip(),
        min_total=min_total,
        max_total=max_total,
    )


def run() -> None:
    base_dir = app_base_dir()
    host = os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.getenv("WEB_PORT", "8787"))
    except ValueError:
        port = 8787

    if os.getenv("WEB_OPEN_BROWSER", "true").strip().lower() in {"1", "true", "yes", "sim"}:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    os.chdir(base_dir)
    uvicorn.run(app, host=host, port=port, log_level="info")
