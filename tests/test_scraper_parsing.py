from __future__ import annotations

from decimal import Decimal

from aliexpress_orders_sync.config import Settings
from aliexpress_orders_sync.scraper import _parse_order_block, _parse_tracking_number


def _settings(tmp_path) -> Settings:
    return Settings(
        excel_path=tmp_path / "pedidos.xlsx",
        responsible_default="Comprador",
        check_interval_minutes=60,
        session_dir=tmp_path / "session",
        orders_url="https://www.aliexpress.com/p/order/index.html",
        headless=False,
        default_tipo="Entrada",
        browser_channel="chrome",
        cdp_url="http://127.0.0.1:9222",
        browser_executable=None,
    )


def test_parse_order_block_from_aliexpress_completed_card(tmp_path):
    text = """
    Completed
    Order date: Apr 17, 2026
    Order ID: 8211248473050032
    FIFINE Official Store
    Caixa de som para jogos FIFINE com som surround estéreo
    R$198,21 x1
    Total:R$198,21
    Order details
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.order_id == "8211248473050032"
    assert order.order_date.isoformat() == "2026-04-17"
    assert order.item_description == "Caixa de som para jogos"
    assert order.quantity == 1
    assert order.total_value == Decimal("198.21")
    assert order.currency == "BRL"
    assert order.delivery_status == "Completed"
    assert order.tracking_number == ""


def test_parse_order_block_uses_total_and_quantity_from_card(tmp_path):
    text = """
    Awaiting delivery
    Order date: Jun 1, 2026
    Order ID: 8211279521850032
    FIFINE Official Store
    Fifine microfone dinâmico usb/xlr com controle rgb/jack de fone
    AM8, brazil
    R$224,79   x10
    Total:R$1.977,90
    Confirm received
    Track order
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.order_id == "8211279521850032"
    assert order.order_date.isoformat() == "2026-06-01"
    assert order.item_description == "Fifine microfone dinâmico usb/xlr"
    assert order.quantity == 10
    assert order.total_value == Decimal("1977.90")
    assert order.currency == "BRL"
    assert order.delivery_status == "Awaiting delivery"
    assert order.tracking_number == ""


def test_parse_quantity_does_not_use_x99_from_product_name(tmp_path):
    text = """
    Completed
    Order date: Feb 26, 2025
    Order ID: 8198183370400032
    Pioneer Technology Store
    Qiyida x99 conjunto de placa-mãe com LGA2011-3 xeon e5 2630 v4 cpu ddr4 16gb reg ecc memória pci 16x nvme m.2 sata x99 h5
    Motherboard CPU RAM, brazil
    R$178,56   x1
    Total:R$178,56
    Fast delivery
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.item_description == "Qiyida x99"
    assert order.quantity == 1
    assert order.total_value == Decimal("178.56")


def test_expired_status_becomes_canceled(tmp_path):
    text = """
    Expired
    Order date: Jan 4, 2025
    Order ID: 8198183370400033
    Loja Teste Store
    KZ EDX PRO 10mm Dual Magnetic Circuit Dynamic Drive Earphone HIFI Bass Earbud Sport Noise Cancelling Headset KZ ZSTX ZSN PRO ZAS
    R$50,00 x1
    Total:R$50,00
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.item_description == "KZ EDX PRO"
    assert order.delivery_status == "Canceled"


def test_canceled_status_and_empty_name_fallback(tmp_path):
    text = """
    Canceled
    Order date: May 21, 2026
    Order ID: 8211046420430032
    R$509,41 x19
    Total:R$9.678,79
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.delivery_status == "Canceled"
    assert order.item_description == "Não identificado"


def test_parse_tracking_number_from_order_details_text():
    text = """
    JT EXPress
    Tracking number: 888002028480977
    Copy
    Package Collected by carrier
    """

    assert _parse_tracking_number(text) == "888002028480977"
