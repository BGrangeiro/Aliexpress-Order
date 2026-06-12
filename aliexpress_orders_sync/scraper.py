from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

from .config import Settings
from .models import Order

ALIEXPRESS_HOME_URL = "https://www.aliexpress.com/"
MONITOR_TAB_HASH = "orders-sync-monitor"

ORDER_ID_RE = re.compile(
    r"(?:"
    r"Order\s*(?:ID|No\.?|number)?|"
    r"Ref\.?\s*(?:Number|No\.?)|"
    r"(?:N[oº]|N[uú]mero)\s*(?:do\s*)?pedido|"
    r"ID\s*do\s*pedido|"
    r"Pedido\s*(?:ID|numero|n[uú]mero|N[oº])?"
    r")\D*(\d{8,})",
    re.I,
)
TOTAL_MONEY_RE = re.compile(
    r"(?:Total|Valor\s*total)\s*:?\s*(R\$|US\$|\$|BRL|USD)\s*([\d.,]+)|"
    r"(?:Total|Valor\s*total)\s*:?\s*([\d.,]+)\s*(BRL|USD)",
    re.I,
)
MONEY_RE = re.compile(r"(R\$|US\$|\$|BRL|USD)\s*([\d.,]+)|([\d.,]+)\s*(BRL|USD)", re.I)
TRACKING_NUMBER_RE = re.compile(
    r"(?:Tracking\s*(?:number|no\.?)|N[uú]mero\s*de\s*rastre(?:io|amento)|Numero\s*de\s*rastre(?:io|amento)|C[oó]digo\s*de\s*rastre(?:io|amento)|Codigo\s*de\s*rastre(?:io|amento))\s*:?\s*([A-Z0-9][A-Z0-9\-]{6,})",
    re.I,
)
PAYMENT_METHOD_LABEL_RE = re.compile(
    r"(Payment\s*method|M[eé]todo\s*de\s*pagamento|Metodo\s*de\s*pagamento|Forma\s*de\s*pagamento|Pagamento)",
    re.I,
)
QUANTITY_RE = re.compile(r"(?:Qty|Quantidade|Qtd)\D*(\d+)", re.I)
UNIT_PRICE_QUANTITY_RE = re.compile(
    r"(?:R\$|US\$|\$|BRL|USD)\s*[\d.,]+\s*x\s*(\d+)\b|[\d.,]+\s*(?:BRL|USD)\s*x\s*(\d+)\b",
    re.I,
)
DATE_PATTERNS = [
    re.compile(r"(\d{2})/(\d{2})/(\d{4})"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
    re.compile(r"(\d{1,2})\s+([A-Za-z]{3,9})\s*,?\s+(\d{4})"),
    re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})"),
]

STATUS_HINTS = [
    "Entregue",
    "A caminho",
    "Aguardando envio",
    "Aguardando entrega",
    "Despachado",
    "Enviado",
    "Cancelado",
    "Finalizado",
    "Concluído",
    "Concluido",
    "Awaiting shipment",
    "Awaiting delivery",
    "Shipped",
    "Delivered",
    "Finished",
    "Canceled",
    "Cancelled",
    "In transit",
    "Completed",
    "To pay",
    "A pagar",
    "Para pagar",
]

MONTHS = {
    "jan": 1,
    "january": 1,
    "fev": 2,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "abr": 4,
    "apr": 4,
    "april": 4,
    "mai": 5,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "ago": 8,
    "aug": 8,
    "august": 8,
    "set": 9,
    "sep": 9,
    "september": 9,
    "out": 10,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dez": 12,
    "dec": 12,
    "december": 12,
}


class BrowserConnectionError(RuntimeError):
    """Raised when the CDP browser is not reachable."""


def login(settings: Settings) -> None:
    """Open a persistent browser profile so the user can log in once."""

    if settings.cdp_url:
        open_browser(settings)
        print("Faça login na AliExpress na janela do Chrome/Edge que foi aberta.")
        print("Depois de confirmar que 'Meus Pedidos' carregou, pressione Enter aqui.")
        input()
        return

    with sync_playwright() as playwright:
        context = _new_context(playwright, settings)
        page = context.new_page()
        page.goto(settings.orders_url, wait_until="domcontentloaded")
        print("Faça login na AliExpress na janela aberta.")
        print("Depois de confirmar que 'Meus Pedidos' carregou, pressione Enter aqui.")
        input()
        context.close()


def fetch_orders(settings: Settings) -> list[Order]:
    """Fetch and normalize all loaded AliExpress orders."""

    return _fetch_orders(settings, include_order_details=True)


def fetch_orders_summary(settings: Settings) -> list[Order]:
    """Fetch only the visible My Orders cards without opening Order details."""

    return _fetch_orders(settings, include_order_details=False)


def _fetch_orders(settings: Settings, include_order_details: bool) -> list[Order]:
    with sync_playwright() as playwright:
        if settings.cdp_url:
            browser = _connect_over_cdp(playwright, settings)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = _page_for_orders(context)
            page.goto(_monitor_orders_url(settings.orders_url), wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(5_000)
            if include_order_details:
                _load_all_orders(page)
            account_id = _resolve_account_id(page, settings)
            orders = _extract_orders_from_page(page, settings)
            _raise_if_orders_were_not_parsed(page, orders)
            orders = [replace(order, responsible=account_id) for order in orders]
            if include_order_details:
                orders = _enrich_orders_with_order_details(page, orders, settings.orders_url)
            # Do not close a CDP-connected browser: keeping the real profile open
            # helps Chrome persist cookies just like a normal browsing session.
            return orders

        context = _new_context(playwright, settings)
        page = context.new_page()
        page.goto(_monitor_orders_url(settings.orders_url), wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(5_000)
        if include_order_details:
            _load_all_orders(page)
        account_id = _resolve_account_id(page, settings)
        orders = _extract_orders_from_page(page, settings)
        _raise_if_orders_were_not_parsed(page, orders)
        orders = [replace(order, responsible=account_id) for order in orders]
        if include_order_details:
            orders = _enrich_orders_with_order_details(page, orders, settings.orders_url)
        context.close()
        return orders


def ensure_browser_is_open(settings: Settings, wait_seconds: int = 3) -> None:
    open_browser(settings)
    print("Abrindo Chrome/Edge com a porta de sincronização...")
    import time

    time.sleep(wait_seconds)


def _connect_over_cdp(playwright, settings: Settings):
    try:
        return playwright.chromium.connect_over_cdp(settings.cdp_url)
    except Exception as exc:
        raise BrowserConnectionError(
            f"Nenhum Chrome/Edge conectado em {settings.cdp_url}. "
            "Abra com: python -m aliexpress_orders_sync.main open-browser"
        ) from exc


def open_browser(settings: Settings) -> None:
    """Open regular Chrome/Edge with remote debugging for manual login."""

    _open_browser_urls(settings, [settings.orders_url])


def open_browser_workspace(settings: Settings) -> None:
    """Open AliExpress for the user and a separate My Orders tab for monitoring."""

    _open_browser_urls(settings, [_monitor_orders_url(settings.orders_url), ALIEXPRESS_HOME_URL])


def _open_browser_urls(settings: Settings, urls: list[str]) -> None:
    executable = _find_browser_executable(settings)
    settings.session_dir.mkdir(parents=True, exist_ok=True)
    port = _port_from_cdp_url(settings.cdp_url or "http://127.0.0.1:9222")
    command = [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={settings.session_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        *urls,
    ]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _new_context(playwright, settings: Settings) -> BrowserContext:
    settings.session_dir.mkdir(parents=True, exist_ok=True)
    launch_options = {
        "user_data_dir": str(settings.session_dir),
        "headless": settings.headless,
        "viewport": {"width": 1366, "height": 900},
    }
    if settings.browser_channel:
        launch_options["channel"] = settings.browser_channel
    return playwright.chromium.launch_persistent_context(**launch_options)


def _page_for_orders(context: BrowserContext) -> Page:
    for page in context.pages:
        if MONITOR_TAB_HASH in page.url or "/p/order/" in page.url:
            return page
    return context.new_page()


def _monitor_orders_url(orders_url: str) -> str:
    base_url = orders_url.split("#", 1)[0]
    return f"{base_url}#{MONITOR_TAB_HASH}"


def _find_browser_executable(settings: Settings) -> str:
    if settings.browser_executable:
        return settings.browser_executable

    candidates = [
        shutil.which("chrome"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "Chrome/Edge não encontrado. Instale o Google Chrome ou configure BROWSER_EXECUTABLE no .env."
    )


def _port_from_cdp_url(cdp_url: str) -> str:
    match = re.search(r":(\d+)", cdp_url)
    return match.group(1) if match else "9222"


def _load_all_orders(page: Page) -> None:
    """Scroll and click 'View orders' until the page stops loading older orders."""

    previous_order_count = -1
    stable_rounds = 0

    for _ in range(200):
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(900)
        clicked = _click_view_orders(page)
        page.wait_for_timeout(1800 if clicked else 700)

        order_count = len(ORDER_ID_RE.findall(_safe_body_text(page)))
        if order_count == previous_order_count and not clicked:
            stable_rounds += 1
        else:
            stable_rounds = 0

        previous_order_count = order_count
        if stable_rounds >= 4:
            break


def _click_view_orders(page: Page) -> bool:
    patterns = [
        re.compile(r"^\s*View\s+orders\s*$", re.I),
        re.compile(r"^\s*Ver\s+pedidos\s*$", re.I),
        re.compile(r"^\s*Ver\s+mais\s+pedidos\s*$", re.I),
        re.compile(r"^\s*Mostrar\s+mais\s*$", re.I),
        re.compile(r"^\s*Ver\s+mais\s*$", re.I),
        re.compile(r"^\s*View\s+more\s*$", re.I),
        re.compile(r"^\s*Load\s+more\s*$", re.I),
    ]

    for pattern in patterns:
        locator = page.get_by_text(pattern)
        try:
            for index in range(locator.count() - 1, -1, -1):
                element = locator.nth(index)
                if not element.is_visible(timeout=500):
                    continue
                element.scroll_into_view_if_needed(timeout=1500)
                element.click(timeout=3000)
                return True
        except Exception:
            continue
    return False


def _safe_body_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""


def _raise_if_orders_were_not_parsed(page: Page, orders: list[Order]) -> None:
    if orders:
        return
    text = _safe_body_text(page)
    if ORDER_ID_RE.search(text):
        raise RuntimeError(
            "A AliExpress exibiu pedidos, mas o layout não pôde ser interpretado. "
            "Nenhum dado foi salvo; atualize o scraper antes de tentar novamente."
        )


def _extract_orders_from_page(page: Page, settings: Settings) -> list[Order]:
    text_blocks = _extract_order_blocks_from_dom(page)
    if not text_blocks:
        text_blocks = _extract_order_blocks_from_selectors(page)
    if not text_blocks:
        text_blocks = _split_order_blocks(_safe_body_text(page))

    orders_by_id: dict[str, Order] = {}
    for block in text_blocks:
        order = _parse_order_block(block, settings)
        if order:
            orders_by_id[order.order_id] = order
    return list(orders_by_id.values())


def _resolve_account_id(page: Page, settings: Settings) -> str:
    configured = str(settings.account_id or "").strip()
    if configured and configured.lower() != "auto":
        print(f"Conta configurada: {configured}")
        return configured

    detected = _detect_account_id(page)
    if detected:
        print(f"Conta detectada: {detected}")
        return detected

    fallback = settings.responsible_default or "Conta não identificada"
    print(f"Conta não detectada automaticamente. Usando fallback: {fallback}")
    return fallback


def _detect_account_id(page: Page) -> str:
    try:
        value = page.evaluate(
            """
            () => {
              const clean = (value) => String(value || '')
                .replace(/\\s+/g, ' ')
                .replace(/^hi[,!]?\\s*/i, '')
                .replace(/^ol[aá][,!]?\\s*/i, '')
                .trim();

              const emailRe = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}/i;
              const bad = /^(account|minha conta|meus pedidos|orders|order details|aliexpress|cart|carrinho|copy)$/i;
              const candidates = [];

              const bodyText = document.body ? document.body.innerText || '' : '';
              const email = bodyText.match(emailRe);
              if (email) candidates.push(email[0]);

              const selectorHints = [
                '[class*="account"]',
                '[class*="user"]',
                '[class*="member"]',
                '[class*="profile"]',
                '[data-role*="account"]',
                '[data-spm*="account"]',
                'a[href*="account"]',
                'a[href*="login"]'
              ];

              for (const selector of selectorHints) {
                for (const element of Array.from(document.querySelectorAll(selector))) {
                  const text = clean(element.innerText || element.textContent || '');
                  if (text && text.length >= 3 && text.length <= 80 && !bad.test(text)) {
                    candidates.push(text);
                  }
                }
              }

              for (const script of Array.from(document.scripts || [])) {
                const text = script.textContent || '';
                const scriptEmail = text.match(emailRe);
                if (scriptEmail) candidates.push(scriptEmail[0]);

                const nameMatch = text.match(/"(?:firstName|displayName|nick|nickname|loginId|memberName|userName)"\\s*:\\s*"([^"]{3,80})"/i);
                if (nameMatch) candidates.push(nameMatch[1]);
              }

              try {
                for (let index = 0; index < localStorage.length; index += 1) {
                  const key = localStorage.key(index);
                  const stored = localStorage.getItem(key) || '';
                  const storedEmail = stored.match(emailRe);
                  if (storedEmail) candidates.push(storedEmail[0]);

                  const storedName = stored.match(/"(?:firstName|displayName|nick|nickname|loginId|memberName|userName)"\\s*:\\s*"([^"]{3,80})"/i);
                  if (storedName) candidates.push(storedName[1]);
                }
              } catch (error) {}

              const normalized = [];
              for (const candidate of candidates.map(clean)) {
                if (!candidate || bad.test(candidate)) continue;
                if (/^\\d+$/.test(candidate)) continue;
                if (candidate.length < 3 || candidate.length > 80) continue;
                if (!normalized.includes(candidate)) normalized.push(candidate);
              }

              const emailCandidate = normalized.find((candidate) => emailRe.test(candidate));
              return emailCandidate || normalized[0] || '';
            }
            """
        )
        return str(value or "").strip()
    except Exception:
        return ""


def _enrich_orders_with_order_details(page: Page, orders: list[Order], orders_url: str) -> list[Order]:
    if not orders:
        return orders

    detail_urls = _detail_urls_by_order_id(page)
    enriched: list[Order] = []

    for index, order in enumerate(orders, start=1):
        print(f"Buscando detalhes {index}/{len(orders)} - pedido {order.order_id}...")
        tracking_number = order.tracking_number
        payment_method = order.payment_method
        if not tracking_number or not payment_method:
            detail_url = detail_urls.get(order.order_id)
            if detail_url:
                tracking_number, payment_method = _fetch_order_details_from_url(page.context, detail_url)
            else:
                tracking_number, payment_method = _fetch_order_details_by_click(page, order.order_id, orders_url)
        if tracking_number:
            print(f"  Rastreio encontrado: {tracking_number}")
        else:
            print("  Rastreio não encontrado.")
        if payment_method:
            print(f"  Pagamento encontrado: {payment_method}")
        else:
            print("  Pagamento não encontrado.")
        enriched.append(
            replace(
                order,
                tracking_number=tracking_number or "",
                payment_method=payment_method or "",
            )
        )

    return enriched


def _detail_urls_by_order_id(page: Page) -> dict[str, str]:
    try:
        raw_urls = page.evaluate(
            """
            () => {
              const result = {};
              const orderRe = /(?:Order\\s*(?:ID|No\\.?|number)?|Ref\\.?\\s*(?:Number|No\\.?)|(?:N[oº]|N[uú]mero)\\s*(?:do\\s*)?pedido|ID\\s*do\\s*pedido|Pedido\\s*(?:ID|numero|n[uú]mero|N[oº])?)\\D*(\\d{8,})/i;
              const detailsRe = /Order\\s+details|Details|Detalhes\\s+do\\s+pedido|Detalhes\\s+da\\s+compra/i;
              const elements = Array.from(document.querySelectorAll('div, section, li, article'));

              for (const element of elements) {
                const text = (element.innerText || '').trim();
                const match = text.match(orderRe);
                if (!match || !detailsRe.test(text)) continue;

                const links = Array.from(element.querySelectorAll('a'));
                const detail = links.find((link) => detailsRe.test(link.innerText || ''));
                if (detail && detail.href) result[match[1]] = detail.href;
              }
              return result;
            }
            """
        )
        return {str(order_id): str(url) for order_id, url in raw_urls.items() if url}
    except Exception:
        return {}


def _fetch_order_details_from_url(context: BrowserContext, detail_url: str) -> tuple[str, str]:
    detail_page = context.new_page()
    try:
        detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=90_000)
        detail_page.wait_for_timeout(2_000)
        return _extract_order_details_from_detail_page(detail_page)
    except Exception:
        return "", ""
    finally:
        detail_page.close()


def _fetch_order_details_by_click(page: Page, order_id: str, orders_url: str) -> tuple[str, str]:
    detail_page = page
    opened_new_page = False
    try:
        pages_before = set(page.context.pages)
        if not _click_order_details(page, order_id):
            return "", ""
        page.wait_for_timeout(2_500)

        new_pages = [candidate for candidate in page.context.pages if candidate not in pages_before]
        if new_pages:
            detail_page = new_pages[-1]
            opened_new_page = True
            detail_page.wait_for_load_state("domcontentloaded", timeout=90_000)
            detail_page.wait_for_timeout(1_500)
        else:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass

        return _extract_order_details_from_detail_page(detail_page)
    except Exception:
        return "", ""
    finally:
        if opened_new_page:
            detail_page.close()
        else:
            try:
                page.goto(orders_url, wait_until="domcontentloaded", timeout=90_000)
                page.wait_for_timeout(2_000)
                _load_all_orders(page)
            except Exception:
                pass


def _extract_order_details_from_detail_page(page: Page) -> tuple[str, str]:
    detail_text = _safe_body_text(page)
    payment_method = _parse_payment_method(detail_text)
    tracking_numbers = _parse_tracking_numbers(detail_text)

    pages_before = set(page.context.pages)
    _click_package_collected(page)
    page.wait_for_timeout(1_500)

    new_pages = [candidate for candidate in page.context.pages if candidate not in pages_before]
    if new_pages:
        tracking_page = new_pages[-1]
        try:
            tracking_page.wait_for_load_state("domcontentloaded", timeout=90_000)
            tracking_page.wait_for_timeout(1_500)
            tracking_numbers.extend(_parse_tracking_numbers(_safe_body_text(tracking_page)))
            return _join_tracking_numbers(tracking_numbers), payment_method
        except Exception:
            return _join_tracking_numbers(tracking_numbers), payment_method
        finally:
            tracking_page.close()

    tracking_numbers.extend(_parse_tracking_numbers(_safe_body_text(page)))
    return _join_tracking_numbers(tracking_numbers), payment_method


def _click_order_details(page: Page, order_id: str) -> bool:
    try:
        point = page.evaluate(
            """
            (orderId) => {
              const detailsRe = /Order\\s+details|Details|Detalhes\\s+do\\s+pedido|Detalhes\\s+da\\s+compra/i;
              const elements = Array.from(document.querySelectorAll('div, section, li, article'));
              const cards = elements
                .filter((element) => (element.innerText || '').includes(orderId))
                .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);

              for (const card of cards) {
                const candidates = Array.from(card.querySelectorAll('a, button, div, span'))
                  .filter((element) => detailsRe.test((element.innerText || '').trim()))
                  .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);

                for (const candidate of candidates) {
                  const clickable = candidate.closest('a,button,[role="button"]') || candidate;
                  clickable.scrollIntoView({ block: 'center', inline: 'center' });
                  const rect = clickable.getBoundingClientRect();
                  if (rect.width <= 0 || rect.height <= 0) continue;
                  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
                }
              }
              return null;
            }
            """,
            order_id,
        )
        if not point:
            return False
        page.mouse.click(point["x"], point["y"])
        return True
    except Exception:
        return False


def _click_package_collected(page: Page) -> bool:
    try:
        point = page.evaluate(
            """
            () => {
              const directPattern = /(Package\\s+collected\\s+by\\s+carrier|Collected\\s+by\\s+carrier|Shipping\\s+in\\s+\\d+\\s+packages?|View\\s+tracking\\s+info|Pacote\\s+coletado|Ver\\s+rastreamento|Rastreamento|Informa[cç][oõ]es?\\s+de\\s+(?:rastreamento|envio))/i;
              const estimatedPattern = /Estimated\\s+delivery\\s+date|Data\\s+estimada\\s+de\\s+entrega/i;
              const elements = Array.from(document.querySelectorAll('a, button, div, span, section, article'));

              const fromEstimatedBlock = [];
              for (const element of elements) {
                const text = (element.innerText || '').trim();
                if (!estimatedPattern.test(text)) continue;

                let current = element;
                for (let depth = 0; current && depth < 4; depth += 1) {
                  const currentText = (current.innerText || '').trim();
                  if (currentText && currentText.length < 1200 && /tracking|package|shipping|carrier|rastreamento|pacote|envio/i.test(currentText)) {
                    fromEstimatedBlock.push(current);
                  }
                  current = current.parentElement;
                }
              }

              const direct = elements.filter((element) => directPattern.test((element.innerText || '').trim()));
              const candidates = [...direct, ...fromEstimatedBlock]
                .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);

              for (const element of candidates) {
                const clickable = element.closest('a,button,[role="button"]') || element;
                clickable.scrollIntoView({ block: 'center', inline: 'center' });
                const rect = clickable.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
              }

              for (const element of fromEstimatedBlock) {
                element.scrollIntoView({ block: 'center', inline: 'center' });
                const rect = element.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                return { x: rect.right - 24, y: rect.top + rect.height / 2 };
              }
              return null;
            }
            """
        )
        if not point:
            return False
        page.mouse.click(point["x"], point["y"])
        page.wait_for_timeout(1000)
        return True
    except Exception:
        return False


def _extract_order_blocks_from_dom(page: Page) -> list[str]:
    """Find the smallest visible DOM blocks that look like complete order cards."""

    try:
        blocks = page.evaluate(
            """
            () => {
              const orderRe = /(?:Order\\s*(?:ID|No\\.?|number)?|Ref\\.?\\s*(?:Number|No\\.?)|(?:N[oº]|N[uú]mero)\\s*(?:do\\s*)?pedido|ID\\s*do\\s*pedido|Pedido\\s*(?:ID|numero|n[uú]mero|N[oº])?)\\D*\\d{8,}/i;
              const totalRe = /(?:Total|Valor\\s*total)\\s*:?\\s*(R\\$|US\\$|\\$|BRL|USD)/i;
              const qtyRe = /(R\\$|US\\$|\\$|BRL|USD)\\s*[\\d.,]+\\s*x\\s*\\d+\\b/i;
              const elements = Array.from(document.querySelectorAll('div, section, li, article'));
              const candidates = [];

              for (const element of elements) {
                const text = (element.innerText || '').trim();
                if (!orderRe.test(text) || !totalRe.test(text)) continue;

                let complete = qtyRe.test(text);
                let current = element;
                let depth = 0;

                while (!complete && current.parentElement && depth < 6) {
                  current = current.parentElement;
                  const parentText = (current.innerText || '').trim();
                  complete = qtyRe.test(parentText) && totalRe.test(parentText) && orderRe.test(parentText);
                  depth += 1;
                }

                let finalText = (current.innerText || '').trim();
                if (complete && finalText.length < 5000) {
                  let withContext = finalText;
                  let parent = current.parentElement;
                  let parentDepth = 0;
                  while (parent && parentDepth < 2) {
                    const parentText = (parent.innerText || '').trim();
                    if (parentText.length > finalText.length && parentText.length < 5000) {
                      withContext = parentText;
                    }
                    parent = parent.parentElement;
                    parentDepth += 1;
                  }
                  candidates.push(withContext);
                }
              }

              const byOrderId = new Map();
              for (const text of candidates) {
                const match = text.match(/(?:Order\\s*(?:ID|No\\.?|number)?|Ref\\.?\\s*(?:Number|No\\.?)|(?:N[oº]|N[uú]mero)\\s*(?:do\\s*)?pedido|ID\\s*do\\s*pedido|Pedido\\s*(?:ID|numero|n[uú]mero|N[oº])?)\\D*(\\d{8,})/i);
                if (!match) continue;
                const existing = byOrderId.get(match[1]);
                if (!existing || text.length < existing.length) byOrderId.set(match[1], text);
              }
              return Array.from(byOrderId.values()).map((text) => {
                const match = text.match(/(?:Order\\s*(?:ID|No\\.?|number)?|Ref\\.?\\s*(?:Number|No\\.?)|(?:N[oº]|N[uú]mero)\\s*(?:do\\s*)?pedido|ID\\s*do\\s*pedido|Pedido\\s*(?:ID|numero|n[uú]mero|N[oº])?)\\D*(\\d{8,})/i);
                if (!match) return text;
                const card = elements
                  .filter((element) => (element.innerText || '').includes(match[1]))
                  .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length)[0];
                if (!card) return text;
                const fullLabels = Array.from(card.querySelectorAll('[title], [aria-label], img[alt]'))
                  .flatMap((element) => [
                    element.getAttribute('title'),
                    element.getAttribute('aria-label'),
                    element.getAttribute('alt'),
                  ])
                  .filter((value) => value && value.trim().length >= 12)
                  .map((value) => value.trim())
                  .filter((value, index, all) => all.indexOf(value) === index);
                return fullLabels.length ? `${text}\\n${fullLabels.join('\\n')}` : text;
              });
            }
            """
        )
        return [str(block).strip() for block in blocks if str(block).strip()]
    except Exception:
        return []


def _extract_order_blocks_from_selectors(page: Page) -> list[str]:
    candidate_selectors = [
        "[data-pl='order-card']",
        "[data-spm*='order']",
        ".order-item",
        ".order-card",
        "div:has-text('Order ID')",
        "div:has-text('Ref. Number')",
        "div:has-text('Ref Number')",
        "div:has-text('Número do pedido')",
        "div:has-text('Nº do pedido')",
        "div:has-text('ID do pedido')",
        "div:has-text('Pedido')",
    ]

    text_blocks: list[str] = []
    for selector in candidate_selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 1000)
            for index in range(count):
                text = locator.nth(index).inner_text(timeout=1500).strip()
                if text and ORDER_ID_RE.search(text):
                    text_blocks.append(text)
        except Exception:
            continue
    return text_blocks


def _split_order_blocks(text: str) -> list[str]:
    matches = list(ORDER_ID_RE.finditer(text))
    blocks: list[str] = []
    for index, match in enumerate(matches):
        start = max(0, match.start() - 250)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append(text[start:end])
    return blocks


def _parse_order_block(text: str, settings: Settings) -> Order | None:
    order_id_match = ORDER_ID_RE.search(text)
    if not order_id_match:
        return None

    quantity = _parse_quantity(text)
    total_value, currency = _parse_money(text)

    return Order(
        order_id=order_id_match.group(1),
        order_date=_parse_date(text),
        item_description=_parse_item_description(text),
        quantity=quantity,
        total_value=total_value,
        currency=currency,
        responsible=settings.responsible_default,
        delivery_status=_parse_status(text),
        tracking_number=_parse_tracking_number(text),
        payment_method=_parse_payment_method(text),
    )


def _parse_quantity(text: str) -> int:
    match = QUANTITY_RE.search(text) or UNIT_PRICE_QUANTITY_RE.search(text)
    if match:
        raw_quantity = next((group for group in match.groups() if group), None)
        return max(1, int(raw_quantity))
    return 1


def _parse_item_description(text: str) -> str:
    full_name = _extract_product_name(text)
    if full_name:
        return full_name
    return _fallback_item_description(text)


def _extract_product_name(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    skip_patterns = [
        re.compile(
            r"^(completed|awaiting|entregue|cancelado|canceled|cancelled|expired|expirado|to\s+pay|a\s+pagar|para\s+pagar)\b",
            re.I,
        ),
        re.compile(r"^order\s+date\b", re.I),
        re.compile(r"^date\s*:", re.I),
        re.compile(r"^data\s+do\s+pedido\b", re.I),
        re.compile(r"^order\s+id\b", re.I),
        re.compile(r"^ref\.?\s*(number|no\.?)\b", re.I),
        re.compile(r"^(n[oº]|n[uú]mero|id)\s+do\s+pedido\b", re.I),
        re.compile(r"^pedido\b", re.I),
        re.compile(r"^(copy|copiar)$", re.I),
        re.compile(r"^order\s+details$", re.I),
        re.compile(r"^details$", re.I),
        re.compile(r"^detalhes\s+do\s+pedido$", re.I),
        re.compile(r"^total\s*:", re.I),
        re.compile(r"^valor\s+total\s*:", re.I),
        re.compile(r"(R\$|US\$|\$|BRL|USD)\s*[\d.,]+", re.I),
        re.compile(
            r"(coupon|returns|delivery|refund|review|cart|remove|track|confirm|received|pay\s+now|pay\s+with|edit\s+address|shared\s+discounts|cupom|devolu[cç][aã]o|entrega|reembolso|avalia[cç][aã]o|carrinho|remover|rastrear|confirmar|recebido|pagar|pagamento|endere[cç]o)",
            re.I,
        ),
        re.compile(r"^(choice|plus|brand\+?)$", re.I),
        re.compile(r"store\b", re.I),
        re.compile(r"^copy\b", re.I),
    ]

    candidates: list[str] = []
    for line in lines:
        if any(pattern.search(line) for pattern in skip_patterns):
            continue
        if "," in line and len(line.split()) <= 4:
            continue
        if len(line) >= 5:
            candidates.append(line)

    if not candidates:
        return ""
    return max(candidates, key=len).replace("...", "").strip()


def _fallback_item_description(text: str) -> str:
    text_lower = text.lower()
    known_products = [
        ("fifine", "Fifine microfone dinâmico usb/xlr"),
        ("amazfit", "Amazfit"),
        ("kz edx pro", "KZ EDX PRO"),
        ("qiyida", "Qiyida x99"),
        ("caixa de som", "Caixa de som para jogos"),
        ("smartwatch", "Smartwatch"),
    ]
    for needle, description in known_products:
        if needle in text_lower:
            return description
    return "Não identificado"


def _parse_tracking_number(text: str) -> str:
    numbers = _parse_tracking_numbers(text)
    return numbers[0] if numbers else ""


def _parse_tracking_numbers(text: str) -> list[str]:
    numbers: list[str] = []
    for match in TRACKING_NUMBER_RE.finditer(text):
        number = match.group(1).strip()
        if number not in numbers:
            numbers.append(number)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        label_pattern = r"Tracking\s*(?:number|no\.?)|N[uú]mero\s*de\s*rastre(?:io|amento)|Numero\s*de\s*rastre(?:io|amento)|C[oó]digo\s*de\s*rastre(?:io|amento)|Codigo\s*de\s*rastre(?:io|amento)"
        if re.search(label_pattern, line, re.I):
            nearby = " ".join(lines[index : index + 4])
            label_match = re.search(label_pattern, nearby, re.I)
            value_text = nearby[label_match.end() :] if label_match else nearby
            number_match = re.search(r"\b[A-Z0-9][A-Z0-9\-]{6,}\b", value_text)
            if number_match and number_match.group(0) not in numbers:
                numbers.append(number_match.group(0))
    return numbers


def _join_tracking_numbers(numbers: list[str]) -> str:
    unique: list[str] = []
    for number in numbers:
        cleaned = str(number or "").strip()
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return " | ".join(unique)


def _parse_payment_method(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for index, line in enumerate(lines):
        label_match = PAYMENT_METHOD_LABEL_RE.search(line)
        if not label_match:
            continue

        value = _clean_payment_method(line[label_match.end() :])
        if value:
            return value

        for nearby in lines[index + 1 : index + 4]:
            value = _clean_payment_method(nearby)
            if value:
                return value
    return ""


def _clean_payment_method(value: str) -> str:
    value = re.sub(r"^[\s:：-]+", "", value or "").strip()
    if not value:
        return ""

    value = re.split(
        r"\s{2,}|(?:Payment\s*time|Order\s*time|Paid\s*on|Amount|Total|Copy|Hora\s*do\s*pagamento|Data\s*do\s*pedido|Pago\s*em|Valor|Copiar)\s*:?",
        value,
        maxsplit=1,
        flags=re.I,
    )[0].strip(" :：-")
    if not value:
        return ""

    if PAYMENT_METHOD_LABEL_RE.fullmatch(value) or re.fullmatch(r"(copy|details?|total|amount)", value, re.I):
        return ""
    return value[:80] if _is_valid_payment_method(value) else ""


def _is_valid_payment_method(value: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"pix|boleto(?:\s+banc[aá]rio)?|"
            r"credit\s*card|debit\s*card|card\s+ending|"
            r"cart[aã]o(?:\s+de)?\s+(?:cr[eé]dito|d[eé]bito)|"
            r"visa|mastercard|master\s*card|american\s+express|amex|elo|hipercard|"
            r"paypal|google\s+pay|apple\s+pay|mercado\s+pago|alipay|webmoney|klarna|"
            r"bank\s+transfer|wire\s+transfer|transfer[eê]ncia\s+banc[aá]ria"
            r")\b",
            value,
            re.I,
        )
    )


def _parse_money(text: str) -> tuple[Decimal | None, str]:
    match = TOTAL_MONEY_RE.search(text) or MONEY_RE.search(text)
    if not match:
        return None, ""

    currency = (match.group(1) or match.group(4) or "").upper()
    raw_value = match.group(2) or match.group(3) or ""
    normalized = _normalize_decimal(raw_value)
    if currency == "$":
        currency = "USD"
    if currency == "R$":
        currency = "BRL"
    return normalized, currency


def _normalize_decimal(value: str) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        return Decimal(value)
    except Exception:
        return None


def _parse_date(text: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            if pattern.pattern.startswith("(\\d{4})"):
                return datetime.strptime(match.group(0), "%Y-%m-%d").date()
            if match.group(1).isalpha():
                month = MONTHS.get(match.group(1).lower())
                if month:
                    return date(int(match.group(3)), month, int(match.group(2)))
            if match.group(2).isalpha():
                month = MONTHS.get(match.group(2).lower())
                if month:
                    return date(int(match.group(3)), month, int(match.group(1)))
            return datetime.strptime(match.group(0), "%d/%m/%Y").date()
        except ValueError:
            continue
    return None


def _parse_status(text: str) -> str:
    if re.search(r"\b(expired|expirado|canceled|cancelled|cancelado)\b", text, re.I):
        return "Canceled"
    for status in STATUS_HINTS:
        if re.search(re.escape(status), text, re.I):
            return "Canceled" if status in {"Canceled", "Cancelled"} else status
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        line_lower = line.lower()
        if any(word in line_lower for word in ["status", "entrega", "shipment", "delivered", "shipped"]):
            return line[:120]
    return "Não identificado"
