from __future__ import annotations

from datetime import date
from decimal import Decimal

from openpyxl import load_workbook

from aliexpress_orders_sync.excel_sync import sync_orders_to_excel
from aliexpress_orders_sync.models import Order


def test_sync_creates_updates_and_styles_workbook(tmp_path):
    excel_path = tmp_path / "pedidos.xlsx"
    order = Order(
        order_id="1234567890",
        order_date=date(2026, 6, 2),
        item_description="Produto teste",
        quantity=2,
        total_value=Decimal("20.00"),
        currency="USD",
        responsible="Maria",
        delivery_status="Cancelado",
        tracking_number="LP123456789CN",
    )

    created, updated = sync_orders_to_excel([order], excel_path)
    assert (created, updated) == (1, 0)

    changed_order = Order(**{**order.__dict__, "delivery_status": "Entregue"})
    created, updated = sync_orders_to_excel([changed_order], excel_path)
    assert (created, updated) == (0, 1)

    workbook = load_workbook(excel_path, data_only=False)
    sheet = workbook.active

    assert sheet.max_row == 2
    assert sheet["A1"].value == "Data do Pedido"
    assert sheet["B1"].value == "Descrição do Item"
    assert sheet["I1"].value == "Nº Rastreio"
    assert sheet["B2"].value == "Produto teste"
    assert sheet["B2"].alignment.horizontal == "left"
    assert sheet["A1"].alignment.horizontal == "center"
    assert sheet["A1"].alignment.wrap_text is True
    assert sheet.column_dimensions["B"].width >= 36
    assert sheet["A2"].alignment.horizontal == "center"
    assert sheet["C2"].alignment.horizontal == "center"
    assert sheet["E2"].value == "=D2/C2"
    assert sheet["G2"].value == "Entregue"
    assert sheet["H2"].value == "1234567890"
    assert sheet["I2"].value == "LP123456789CN"


def test_sync_normalizes_canceled_status_and_empty_description(tmp_path):
    excel_path = tmp_path / "pedidos.xlsx"
    order = Order(
        order_id="1234567891",
        order_date=date(2026, 6, 2),
        item_description="",
        quantity=1,
        total_value=Decimal("10.00"),
        currency="BRL",
        responsible="Maria",
        delivery_status="Cancelado",
        tracking_number="",
    )

    sync_orders_to_excel([order], excel_path)
    workbook = load_workbook(excel_path, data_only=False)
    sheet = workbook.active

    assert sheet["B2"].value == "Não identificado"
    assert sheet["G2"].value == "Canceled"
