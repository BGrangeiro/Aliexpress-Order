from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

import pytest

from aliexpress_orders_sync.accounts import AccountProfile
from aliexpress_orders_sync.config import Settings
from aliexpress_orders_sync.models import Order
from aliexpress_orders_sync.web_service import ServiceConflictError, WebMonitorService


def _settings(tmp_path) -> Settings:
    return Settings(
        excel_path=tmp_path / "data" / "pedidos.xlsx",
        responsible_default="fallback",
        account_id="auto",
        check_interval_minutes=1,
        session_dir=tmp_path / "session",
        orders_url="https://www.aliexpress.com/p/order/index.html",
        headless=False,
        default_tipo="Entrada",
        browser_channel="chrome",
        cdp_url="http://127.0.0.1:9222",
        browser_executable=None,
        ask_account=False,
        account_profiles_path=tmp_path / "contas.txt",
        database_path=tmp_path / "data" / "pedidos.db",
    )


def _profile(tmp_path) -> AccountProfile:
    return AccountProfile(
        key="conta1",
        email="cliente@example.com",
        responsible="cliente",
        session_dir=tmp_path / "chrome-profile",
    )


def _order(responsible: str) -> Order:
    return Order(
        order_id="8211316977266710",
        order_date=date(2026, 6, 3),
        item_description="Kit de joias",
        quantity=1,
        total_value=Decimal("28.83"),
        currency="BRL",
        responsible=responsible,
        delivery_status="To pay",
        tracking_number="",
        payment_method="Pix",
    )


def _wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("A operação assíncrona não terminou dentro do prazo.")


def test_full_sync_updates_database_and_web_orders(tmp_path):
    opened = []

    def fetcher(settings):
        return [_order(settings.responsible_default)]

    service = WebMonitorService(
        base_dir=tmp_path,
        settings=_settings(tmp_path),
        profiles=[_profile(tmp_path)],
        full_fetcher=fetcher,
        summary_fetcher=fetcher,
        browser_opener=lambda settings: opened.append(settings.account_id),
    )

    service.run_full_sync("conta1")
    _wait_until(lambda: not service.snapshot()["busy"])

    state = service.snapshot()
    result = service.orders()
    orders = result["orders"]

    assert state["status"] == "Concluído"
    assert state["last_result"] == {"read": 1, "created": 1, "updated": 0}
    assert orders[0]["description"] == "Kit de joias"
    assert orders[0]["responsible"] == "cliente"
    assert service.settings.database_path.exists()
    assert opened == []


def test_monitor_runs_immediately_and_can_be_stopped(tmp_path):
    calls = {"browser": 0, "summary": 0}

    def browser_opener(_settings):
        calls["browser"] += 1

    def summary_fetcher(settings):
        calls["summary"] += 1
        return [_order(settings.responsible_default)]

    service = WebMonitorService(
        base_dir=tmp_path,
        settings=_settings(tmp_path),
        profiles=[_profile(tmp_path)],
        full_fetcher=summary_fetcher,
        summary_fetcher=summary_fetcher,
        browser_opener=browser_opener,
    )

    service.start_monitoring("conta1")
    _wait_until(lambda: service.snapshot()["last_result"]["read"] == 1)

    with pytest.raises(ServiceConflictError):
        service.select_account("conta1")

    service.stop_monitoring()
    _wait_until(lambda: not service.snapshot()["monitoring"])

    assert calls["browser"] == 1
    assert calls["summary"] == 1
    assert service.snapshot()["status"] == "Parado"


def test_open_browser_runs_for_selected_account(tmp_path):
    opened = []
    service = WebMonitorService(
        base_dir=tmp_path,
        settings=_settings(tmp_path),
        profiles=[_profile(tmp_path)],
        full_fetcher=lambda _settings: [],
        summary_fetcher=lambda _settings: [],
        browser_opener=lambda settings: opened.append(settings.account_id),
    )

    service.open_browser("conta1")
    _wait_until(lambda: not service.snapshot()["busy"])

    assert opened == ["cliente"]
    assert service.snapshot()["status"] == "Navegador aberto"


def test_service_adds_account_and_exposes_display_name(tmp_path):
    service = WebMonitorService(
        base_dir=tmp_path,
        settings=_settings(tmp_path),
        profiles=[_profile(tmp_path)],
        full_fetcher=lambda _settings: [],
        summary_fetcher=lambda _settings: [],
        browser_opener=lambda _settings: None,
    )

    account = service.add_account(
        email="nova@example.com",
        responsible="Jeferson",
        display_name="Conta nova",
    )

    assert account["display_name"] == "Conta nova"
    assert any(item["email"] == "nova@example.com" for item in service.accounts())

    updated = service.update_account(
        account["key"],
        email="alterada@example.com",
        responsible="Neto",
        display_name="Conta alterada",
    )
    assert updated["responsible"] == "Neto"

    deleted = service.delete_account(account["key"])
    assert deleted["key"] == account["key"]
    assert not any(item["key"] == account["key"] for item in service.accounts())
