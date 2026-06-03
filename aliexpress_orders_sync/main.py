from __future__ import annotations

import argparse
import time

from .config import load_settings
from .excel_sync import sync_orders_to_excel
from .scraper import BrowserConnectionError, ensure_browser_is_open, fetch_orders, login, open_browser


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza pedidos da AliExpress com Excel.")
    parser.add_argument(
        "command",
        choices=["open-browser", "login", "sync", "watch"],
        help="open-browser abre Chrome normal; login salva a sessão; sync executa uma vez; watch monitora periodicamente.",
    )
    parser.add_argument("--env", default=".env", help="Caminho do arquivo .env.")
    args = parser.parse_args()

    settings = load_settings(args.env)

    if args.command == "open-browser":
        open_browser(settings)
        print("Chrome/Edge aberto. Faça login na AliExpress e deixe essa janela aberta.")
        return

    if args.command == "login":
        login(settings)
        return

    if args.command == "sync":
        _sync_once(settings)
        return

    while True:
        _sync_once(settings)
        print(f"Aguardando {settings.check_interval_minutes} minuto(s)...")
        time.sleep(settings.check_interval_minutes * 60)


def _sync_once(settings) -> None:
    try:
        orders = fetch_orders(settings)
    except BrowserConnectionError:
        ensure_browser_is_open(settings)
        try:
            orders = fetch_orders(settings)
        except BrowserConnectionError:
            print("Não consegui conectar no Chrome/Edge pela porta 9222.")
            print("Rode este comando, faça login na AliExpress e deixe a janela aberta:")
            print("python -m aliexpress_orders_sync.main open-browser")
            return

    created, updated = sync_orders_to_excel(orders, settings.excel_path)
    print(
        f"Sincronização concluída: {len(orders)} pedido(s) lido(s), "
        f"{created} novo(s), {updated} atualizado(s)."
    )
    print(f"Planilha: {settings.excel_path.resolve()}")


if __name__ == "__main__":
    main()
