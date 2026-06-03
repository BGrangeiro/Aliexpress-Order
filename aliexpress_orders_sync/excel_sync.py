from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .models import Order

HEADERS = [
    "Data do Pedido",
    "Descrição do Item",
    "Quantidade",
    "Valor Total",
    "Valor Unitário",
    "Responsável",
    "Status de Entrega",
    "Número do Pedido",
    "Nº Rastreio",
]

DESCRIPTION_COLUMN = 2
QUANTITY_COLUMN = 3
TOTAL_COLUMN = 4
UNIT_VALUE_COLUMN = 5
RESPONSIBLE_COLUMN = 6
STATUS_COLUMN = 7
ORDER_ID_COLUMN = 8
TRACKING_COLUMN = 9

HEADER_FILL = PatternFill("solid", fgColor="2F6F57")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SOFT_GRID = Side(style="thin", color="E8EEF2")
SOFT_BORDER = Border(left=SOFT_GRID, right=SOFT_GRID, top=SOFT_GRID, bottom=SOFT_GRID)
WHITE_FILL = PatternFill("solid", fgColor="FFFFFF")
ZEBRA_FILL = PatternFill("solid", fgColor="F7FAF9")


def sync_orders_to_excel(orders: list[Order], excel_path: Path) -> tuple[int, int]:
    """Create or update the workbook, returning (created_rows, updated_rows)."""

    excel_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = load_workbook(excel_path) if excel_path.exists() else _create_workbook()
    sheet = workbook.active

    if not orders:
        if not excel_path.exists():
            _ensure_header(sheet)
            _format_sheet(sheet)
            workbook.save(excel_path)
        return 0, 0

    _ensure_schema(sheet)

    existing_rows = _order_id_to_row(sheet)
    created = 0
    updated = 0

    for order in orders:
        if not order.order_id:
            continue

        if order.order_id in existing_rows:
            row = existing_rows[order.order_id]
            _write_order(sheet, row, order)
            updated += 1
        else:
            row = sheet.max_row + 1
            _write_order(sheet, row, order)
            existing_rows[order.order_id] = row
            created += 1

    _format_sheet(sheet)
    _force_formula_recalculation(workbook)
    workbook.save(excel_path)
    return created, updated


def _create_workbook() -> Workbook:
    workbook = Workbook()
    workbook.active.title = "Pedidos"
    return workbook


def _ensure_schema(sheet) -> None:
    current_headers = [sheet.cell(row=1, column=index).value for index in range(1, len(HEADERS) + 1)]
    if current_headers != HEADERS:
        sheet.delete_rows(1, sheet.max_row)
        sheet.data_validations.dataValidation = []
        sheet.conditional_formatting._cf_rules.clear()
    _ensure_header(sheet)


def _ensure_header(sheet) -> None:
    for column_index, header in enumerate(HEADERS, start=1):
        cell = sheet.cell(row=1, column=column_index)
        cell.value = header
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = SOFT_BORDER


def _order_id_to_row(sheet) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for row in range(2, sheet.max_row + 1):
        order_id = sheet.cell(row=row, column=ORDER_ID_COLUMN).value
        if order_id:
            mapping[str(order_id)] = row
    return mapping


def _write_order(sheet, row: int, order: Order) -> None:
    total_value = _decimal_to_float(order.total_value)
    quantity = max(1, int(order.quantity or 1))

    sheet.cell(row=row, column=1, value=order.order_date)
    sheet.cell(row=row, column=DESCRIPTION_COLUMN, value=order.item_description or "Não identificado")
    sheet.cell(row=row, column=QUANTITY_COLUMN, value=quantity)
    sheet.cell(row=row, column=TOTAL_COLUMN, value=total_value)
    sheet.cell(row=row, column=UNIT_VALUE_COLUMN, value=f"=D{row}/C{row}")
    sheet.cell(row=row, column=RESPONSIBLE_COLUMN, value=order.responsible)
    sheet.cell(row=row, column=STATUS_COLUMN, value=_normalize_status(order.delivery_status))
    sheet.cell(row=row, column=ORDER_ID_COLUMN, value=order.order_id)
    sheet.cell(row=row, column=TRACKING_COLUMN, value=order.tracking_number or "")

    sheet.cell(row=row, column=1).number_format = "DD/MM/YYYY"
    sheet.cell(row=row, column=TOTAL_COLUMN).number_format = _money_format(order.currency)
    sheet.cell(row=row, column=UNIT_VALUE_COLUMN).number_format = _money_format(order.currency)


def _format_sheet(sheet) -> None:
    sheet.freeze_panes = "A2"
    widths = {
        "A": 18,
        "B": 36,
        "C": 14,
        "D": 16,
        "E": 17,
        "F": 24,
        "G": 24,
        "H": 24,
        "I": 28,
    }
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    sheet.row_dimensions[1].height = 28
    _align_cells(sheet)
    _style_rows(sheet)
    sheet.auto_filter.ref = f"A1:I{max(sheet.max_row, 1)}"


def _align_cells(sheet) -> None:
    center = Alignment(horizontal="center", vertical="center")
    description = Alignment(horizontal="left", vertical="center")

    for row in sheet.iter_rows(min_row=1, max_row=max(sheet.max_row, 1), min_col=1, max_col=len(HEADERS)):
        for cell in row:
            if cell.row == 1:
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            else:
                cell.alignment = description if cell.column == DESCRIPTION_COLUMN else center


def _style_rows(sheet) -> None:
    for row_index in range(2, sheet.max_row + 1):
        row_fill = ZEBRA_FILL if row_index % 2 == 0 else WHITE_FILL
        for column_index in range(1, len(HEADERS) + 1):
            cell = sheet.cell(row=row_index, column=column_index)
            cell.border = SOFT_BORDER
            cell.fill = row_fill


def _force_formula_recalculation(workbook) -> None:
    workbook.calculation.calcMode = "auto"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True


def _normalize_status(status: str) -> str:
    if str(status).strip().lower() in {"cancelado", "canceled", "cancelled", "expired", "expirado"}:
        return "Canceled"
    return status


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _money_format(currency: str) -> str:
    if currency.upper() in {"BRL", "R$", "BR"}:
        return 'R$ #,##0.00'
    if currency.upper() in {"USD", "US$", "$"}:
        return 'US$ #,##0.00'
    return '#,##0.00'
