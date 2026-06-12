from __future__ import annotations

from decimal import Decimal

from aliexpress_orders_sync.config import Settings
from aliexpress_orders_sync.scraper import (
    _parse_order_block,
    _parse_payment_method,
    _parse_tracking_number,
    _parse_tracking_numbers,
)


def _settings(tmp_path) -> Settings:
    return Settings(
        excel_path=tmp_path / "pedidos.xlsx",
        responsible_default="Comprador",
        account_id="auto",
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
    assert order.item_description == "Caixa de som para jogos FIFINE com som surround estéreo"
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
    assert order.item_description == "Fifine microfone dinâmico usb/xlr com controle rgb/jack de fone"
    assert order.quantity == 10
    assert order.total_value == Decimal("1977.90")
    assert order.currency == "BRL"
    assert order.delivery_status == "Awaiting delivery"
    assert order.tracking_number == ""


def test_parse_order_block_from_to_pay_card(tmp_path):
    text = """
    To pay
    Order date: Jun 3, 2026
    Order ID: 8211316977266710
    Copy
    Order details
    AY A Store
    51 Pcs/Set Silver Color Chic Jewelry Set For Women Fashion Butterfly He...
    Nobox Silver Color
    R$ 23,90 x1
    Total:R$ 28,83
    Pay now
    Pay with Pix
    Edit address
    When you click to pay, orders with shared discounts are paid together
    Free returns · Fast delivery
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.order_id == "8211316977266710"
    assert order.order_date.isoformat() == "2026-06-03"
    assert order.item_description == "51 Pcs/Set Silver Color Chic Jewelry Set For Women Fashion Butterfly He"
    assert order.quantity == 1
    assert order.total_value == Decimal("28.83")
    assert order.delivery_status == "To pay"


def test_parse_order_block_prefers_full_product_title(tmp_path):
    text = """
    Completed
    Order date: Jun 5, 2026
    Order ID: 8219999999999999
    Loja Teste Store
    KZ EDX PRO 10mm Dual Magnetic Circuit...
    R$50,00 x1
    Total:R$50,00
    KZ EDX PRO 10mm Dual Magnetic Circuit Dynamic Drive Earphone HIFI Bass Earbud Sport Noise Cancelling Headset
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.item_description == (
        "KZ EDX PRO 10mm Dual Magnetic Circuit Dynamic Drive Earphone HIFI Bass "
        "Earbud Sport Noise Cancelling Headset"
    )


def test_parse_current_aliexpress_ref_number_card(tmp_path):
    text = """
    Awaiting delivery
    Date: Jun 9, 2026
    Ref. Number: 8211549687890032
    Copy
    Details
    DIY Motherboard Kit Store
    Novo X99 U9 MÁQUINISTA X99 Conjunto de placa-mãe Kit Opcional LGA2011-3
    Motherboard+CPU
    R$367,24 x1
    Total:R$505,51
    Confirm received
    Track status
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.order_id == "8211549687890032"
    assert order.order_date.isoformat() == "2026-06-09"
    assert order.item_description.startswith("Novo X99 U9 MÁQUINISTA")
    assert order.total_value == Decimal("505.51")


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
    assert order.item_description == (
        "Qiyida x99 conjunto de placa-mãe com LGA2011-3 xeon e5 2630 v4 cpu "
        "ddr4 16gb reg ecc memória pci 16x nvme m.2 sata x99 h5"
    )
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
    assert order.item_description == (
        "KZ EDX PRO 10mm Dual Magnetic Circuit Dynamic Drive Earphone HIFI Bass "
        "Earbud Sport Noise Cancelling Headset KZ ZSTX ZSN PRO ZAS"
    )
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


def test_parse_multiple_tracking_numbers_from_packages():
    text = """
    Package 1
    Tracking number: 888002028480977
    Package 2
    Tracking number: LP123456789CN
    Package 3
    Número de rastreamento: NM987654321BR
    """

    assert _parse_tracking_numbers(text) == [
        "888002028480977",
        "LP123456789CN",
        "NM987654321BR",
    ]


def test_parse_payment_method_from_order_details_text():
    text = """
    Order details
    Payment method: Pix
    Payment time: Jun 1, 2026
    """

    assert _parse_payment_method(text) == "Pix"


def test_rejects_order_date_as_payment_method():
    text = """
    Payment method:
    Pedido feito em: 8 jun, 2026
    Total: R$62,33
    """

    assert _parse_payment_method(text) == ""


def test_parse_portuguese_short_month_date_and_sortable_order(tmp_path):
    text = """
    Canceled
    Pedido feito em: 8 jun, 2026
    Order ID: 8211730278056710
    Loja Teste Store
    9 velocidade aplicativo controlado vibrador
    R$62,33 x1
    Total:R$62,33
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.order_date.isoformat() == "2026-06-08"
    assert order.payment_method == ""


def test_parse_order_block_from_portuguese_card(tmp_path):
    text = """
    Concluído
    Data do pedido: 01/06/2026
    Número do pedido: 8211279521850032
    Loja Oficial FIFINE
    Fifine microfone dinâmico usb/xlr com controle rgb/jack de fone
    AM8, brasil
    R$224,79 x10
    Total:R$1.977,90
    Detalhes do pedido
    """

    order = _parse_order_block(text, _settings(tmp_path))

    assert order is not None
    assert order.order_id == "8211279521850032"
    assert order.order_date.isoformat() == "2026-06-01"
    assert order.quantity == 10
    assert order.total_value == Decimal("1977.90")
    assert order.delivery_status == "Concluído"


def test_parse_tracking_and_payment_from_portuguese_details():
    text = """
    Método de pagamento: Pix
    Hora do pagamento: 01/06/2026
    Número de rastreamento: 888002028480977
    Copiar
    """

    assert _parse_payment_method(text) == "Pix"
    assert _parse_tracking_number(text) == "888002028480977"
