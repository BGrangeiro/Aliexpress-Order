from __future__ import annotations

from datetime import date
from decimal import Decimal

from aliexpress_orders_sync.database import OrderFilters, OrderRepository
from aliexpress_orders_sync.models import Order


def _order(
    order_id: str,
    status: str,
    tracking: str = "",
    responsible: str = "riquelme",
    description: str = "Produto completo",
) -> Order:
    return Order(
        order_id=order_id,
        order_date=date(2026, 6, 8),
        item_description=description,
        quantity=2,
        total_value=Decimal("100.00"),
        currency="BRL",
        responsible=responsible,
        delivery_status=status,
        tracking_number=tracking,
        payment_method="Pix",
    )


def test_repository_filters_multiple_tracking_and_builds_dashboard(tmp_path):
    repository = OrderRepository(tmp_path / "pedidos.db")
    repository.upsert_orders(
        [
            _order("multi", "Awaiting delivery", "TRACK111111 | TRACK222222"),
            _order("single", "Completed", "TRACK333333"),
            _order("none", "Canceled"),
        ],
        account_key="conta1",
        account_email="cliente@example.com",
    )

    result = repository.list_orders(OrderFilters(tracking="multiple"))
    stats = repository.dashboard_stats()

    assert result["total"] == 1
    assert result["orders"][0]["order_id"] == "multi"
    assert result["orders"][0]["tracking_count"] == 2
    assert result["orders"][0]["tracking_numbers"] == ["TRACK111111", "TRACK222222"]
    assert stats == {
        "total": 3,
        "completed": 1,
        "canceled": 1,
        "multiple_tracking": 1,
        "in_progress": 1,
    }


def test_lightweight_database_update_preserves_description_and_tracking(tmp_path):
    repository = OrderRepository(tmp_path / "pedidos.db")
    repository.upsert_orders(
        [_order("same", "Awaiting delivery", "TRACK111111 | TRACK222222")],
        account_key="conta1",
    )
    repository.upsert_orders(
        [_order("same", "Completed", "", description="Produto...")],
        account_key="conta1",
        preserve_existing_description=True,
    )

    order = repository.list_orders()["orders"][0]

    assert order["description"] == "Produto completo"
    assert order["status"] == "Completed"
    assert order["tracking_numbers"] == ["TRACK111111", "TRACK222222"]


def test_repository_searches_order_description_and_tracking(tmp_path):
    repository = OrderRepository(tmp_path / "pedidos.db")
    repository.upsert_orders(
        [_order("8210000000000001", "Completed", "BR123456789XX", description="Microfone FIFINE AM8")],
        account_key="conta1",
    )

    by_description = repository.list_orders(OrderFilters(search="FIFINE"))
    by_tracking = repository.list_orders(OrderFilters(search="BR123456789XX"))

    assert by_description["total"] == 1
    assert by_tracking["total"] == 1


def test_repository_ignores_orders_before_2026(tmp_path):
    repository = OrderRepository(tmp_path / "pedidos.db")
    old_order = Order(
        order_id="old",
        order_date=date(2025, 12, 31),
        item_description="Pedido antigo",
        quantity=1,
        total_value=Decimal("10.00"),
        currency="BRL",
        responsible="riquelme",
        delivery_status="Completed",
        tracking_number="",
        payment_method="Pix",
    )

    created, updated = repository.upsert_orders([old_order], account_key="conta1")

    assert (created, updated) == (0, 0)
    assert repository.count_orders() == 0


def test_repository_builds_analytics_and_advanced_filters(tmp_path):
    repository = OrderRepository(tmp_path / "pedidos.db")
    repository.upsert_orders(
        [
            _order("one", "Completed", "TRACK111111", description="Microfone"),
            _order(
                "two",
                "Canceled",
                "TRACK222222 | TRACK333333",
                description="Relógio",
            ),
            _order("three", "Awaiting delivery", "", description="Microfone"),
        ],
        account_key="conta1",
    )

    analytics = repository.analytics(OrderFilters(payment_method="Pix", min_total=50))

    assert analytics["summary"]["total_orders"] == 3
    assert analytics["summary"]["gross_value"] == 300.0
    assert analytics["summary"]["total_items"] == 6
    assert analytics["tracking"] == {"none": 1, "single": 1, "multiple": 1}
    assert analytics["statuses"][0]["value"] == 1
    assert analytics["top_products"][0]["label"] == "Microfone"


def test_repository_filters_orders_by_responsible(tmp_path):
    repository = OrderRepository(tmp_path / "pedidos.db")
    repository.upsert_orders([_order("one", "Completed", responsible="Riquelme")], account_key="r1")
    repository.upsert_orders([_order("two", "Completed", responsible="Neto")], account_key="n1")

    result = repository.list_orders(OrderFilters(responsible="Riquelme"))

    assert result["total"] == 1
    assert result["orders"][0]["responsible"] == "Riquelme"
