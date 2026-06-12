from __future__ import annotations

import contextlib
import queue
import sys
import threading
import tkinter as tk
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

from .accounts import AccountProfile, load_account_profiles
from .config import Settings, load_settings
from .excel_sync import sync_orders_to_excel_resilient
from .scraper import (
    BrowserConnectionError,
    fetch_orders,
    fetch_orders_summary,
    open_browser_workspace,
)


APP_TITLE = "AliExpress Monitor"
PRIMARY = "#F45D22"
PRIMARY_DARK = "#D94A14"
GREEN = "#267456"
INK = "#17212B"
MUTED = "#667085"
BG = "#F3F6F8"
CARD = "#FFFFFF"
BORDER = "#D9E2E7"


def main() -> None:
    app = AliExpressOrdersApp()
    app.mainloop()


class AliExpressOrdersApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("940x680")
        self.minsize(860, 620)

        self.base_dir = _app_base_dir()
        self.env_path = self.base_dir / ".env"
        self.settings = _load_gui_settings(self.env_path, self.base_dir)
        self.profiles = load_account_profiles(self.settings.account_profiles_path)

        self.log_queue: queue.Queue[object] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.monitor_thread: threading.Thread | None = None
        self.monitor_stop = threading.Event()
        self.monitoring = False
        self.monitor_stop_requested = False

        self.status_text = tk.StringVar(value="Pronto")
        self.status_detail_text = tk.StringVar(value="Abra a AliExpress pelo app para usar a aba de monitoramento.")
        self.last_check_text = tk.StringVar(value="-")
        self.next_check_text = tk.StringVar(value="-")
        self.account_text = tk.StringVar(value="-")
        self.excel_text = tk.StringVar(value=str(self.settings.excel_path.resolve()))

        self._configure_styles()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_log_queue)

    def _configure_styles(self) -> None:
        self.configure(background=BG)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD, relief="flat")
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=CARD, foreground=INK, font=("Segoe UI", 10))
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=INK, font=("Segoe UI Semibold", 22))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Metric.TLabel", background=CARD, foreground=INK, font=("Segoe UI Semibold", 18))
        style.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(16, 10))
        style.map("Primary.TButton", background=[("active", PRIMARY_DARK), ("!disabled", PRIMARY)])
        style.configure("Secondary.TButton", font=("Segoe UI", 10), padding=(14, 10))
        style.configure("Danger.TButton", font=("Segoe UI", 10), padding=(14, 10))
        style.configure("TCombobox", padding=6)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="App.TFrame", padding=22)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="App.TFrame")
        header.pack(fill="x")

        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Monitore novos pedidos em My Orders sem atrapalhar a navegacao do cliente.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 18))

        top_grid = ttk.Frame(root, style="App.TFrame")
        top_grid.pack(fill="x")
        top_grid.columnconfigure(0, weight=2)
        top_grid.columnconfigure(1, weight=1)

        self._build_account_card(top_grid).grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self._build_status_card(top_grid).grid(row=0, column=1, sticky="nsew")

        actions = ttk.Frame(root, style="App.TFrame")
        actions.pack(fill="x", pady=(16, 12))

        self.open_browser_button = ttk.Button(
            actions,
            text="Abrir AliExpress",
            style="Primary.TButton",
            command=self._open_aliexpress_for_selected_account,
        )
        self.open_browser_button.pack(side="left")

        self.monitor_button = ttk.Button(
            actions,
            text="Iniciar monitoramento",
            style="Secondary.TButton",
            command=self._start_monitoring,
        )
        self.monitor_button.pack(side="left", padx=(10, 0))

        self.stop_monitor_button = ttk.Button(
            actions,
            text="Parar",
            style="Danger.TButton",
            command=self._stop_monitoring,
            state="disabled",
        )
        self.stop_monitor_button.pack(side="left", padx=(10, 0))

        self.sync_button = ttk.Button(
            actions,
            text="Verificar completo",
            style="Secondary.TButton",
            command=self._start_sync,
        )
        self.sync_button.pack(side="left", padx=(10, 0))

        ttk.Button(actions, text="Limpar logs", style="Secondary.TButton", command=self._clear_logs).pack(side="right")

        self._build_log_card(root).pack(fill="both", expand=True)

        self._log("App aberto.")
        self._log("Use 'Abrir AliExpress' para criar uma aba normal e uma aba My Orders do monitor.")
        if self.profiles:
            self._log(f"{len(self.profiles)} conta(s) encontrada(s).")
        else:
            self._log("Nenhuma conta encontrada em contas.txt; usando configuracao do .env.")
        self._refresh_selected_account_label()

    def _build_account_card(self, parent) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        ttk.Label(card, text="Conta e planilha", style="Card.TLabel", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        ttk.Label(
            card,
            text="A conta escolhida define o responsavel na planilha. O Chrome do app e compartilhado.",
            style="CardMuted.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        account_row = ttk.Frame(card, style="Card.TFrame")
        account_row.pack(fill="x")
        account_row.columnconfigure(0, weight=1)

        values = [_profile_label(profile) for profile in self.profiles] or ["Usar configuracao do .env"]
        self.account_combo = ttk.Combobox(account_row, values=values, state="readonly", width=54)
        self.account_combo.grid(row=0, column=0, sticky="ew")
        self.account_combo.current(0)
        self.account_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_selected_account_label())

        ttk.Button(account_row, text="?", width=3, command=self._show_accounts_help).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(card, text="Conta ativa", style="CardMuted.TLabel").pack(anchor="w", pady=(14, 0))
        ttk.Label(card, textvariable=self.account_text, style="Card.TLabel", font=("Segoe UI Semibold", 11)).pack(
            anchor="w"
        )
        ttk.Label(card, text="Planilha fixa", style="CardMuted.TLabel").pack(anchor="w", pady=(12, 0))
        ttk.Label(card, textvariable=self.excel_text, style="Card.TLabel", wraplength=560).pack(anchor="w")

        return card

    def _build_status_card(self, parent) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        ttk.Label(card, text="Status", style="Card.TLabel", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        ttk.Label(card, textvariable=self.status_text, style="Metric.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Label(card, textvariable=self.status_detail_text, style="CardMuted.TLabel", wraplength=260).pack(
            anchor="w", pady=(2, 14)
        )

        metrics = ttk.Frame(card, style="Card.TFrame")
        metrics.pack(fill="x")
        ttk.Label(metrics, text="Ultima verificacao", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(metrics, textvariable=self.last_check_text, style="Card.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(metrics, text="Proxima", style="CardMuted.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Label(metrics, textvariable=self.next_check_text, style="Card.TLabel").grid(row=3, column=0, sticky="w")
        return card

    def _build_log_card(self, parent) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        ttk.Label(card, text="Atividade", style="Card.TLabel", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        ttk.Label(card, text="Aqui aparecem as verificacoes, pedidos criados e atualizacoes.", style="CardMuted.TLabel").pack(
            anchor="w", pady=(0, 10)
        )

        body = ttk.Frame(card, style="Card.TFrame")
        body.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            body,
            height=13,
            wrap="word",
            state="disabled",
            background="#0F1720",
            foreground="#D8E2EA",
            insertbackground="#D8E2EA",
            borderwidth=0,
            padx=14,
            pady=12,
            font=("Consolas", 9),
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(body, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        return card

    def _show_accounts_help(self) -> None:
        if not self.profiles:
            message = (
                "Nenhuma conta foi encontrada.\n\n"
                "Adicione contas no arquivo contas.txt, no formato:\n"
                "id|email|responsavel_na_planilha|pasta_de_sessao"
            )
        else:
            lines = [
                "Contas disponiveis:",
                "",
                *[
                    f"- {profile.email}\n  Responsavel: {profile.responsible}\n  Chrome compartilhado: {profile.session_dir}"
                    for profile in self.profiles
                ],
                "",
                "Todas usam o mesmo Chrome do app, entao o Google pode mostrar as contas ja logadas.",
            ]
            message = "\n".join(lines)
        messagebox.showinfo("Contas disponiveis", message)

    def _open_aliexpress_for_selected_account(self) -> None:
        settings = self._selected_settings()
        try:
            open_browser_workspace(settings)
        except Exception as exc:
            messagebox.showerror("Erro ao abrir AliExpress", str(exc))
            self._log(f"Erro ao abrir AliExpress: {exc}")
            return

        self.status_text.set("Navegador aberto")
        self.status_detail_text.set("Use a aba AliExpress normalmente. A aba My Orders fica reservada para o monitor.")
        self._log("")
        self._log(f"AliExpress aberto para a conta: {settings.account_id}")
        self._log("Foram abertas duas abas: My Orders do monitor e AliExpress para o cliente.")
        self._log("Se pedir login/captcha, escolha a conta desejada. O Google guarda as contas nesse Chrome do app.")

    def _start_sync(self) -> None:
        if self.monitoring:
            messagebox.showinfo("Monitoramento ativo", "Pare o monitoramento antes da verificacao completa.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Verificacao em andamento", "Aguarde a verificacao atual terminar.")
            return

        settings = self._selected_settings()
        self._set_busy(True)
        self.status_text.set("Verificando")
        self.status_detail_text.set("Busca completa em andamento, incluindo Order details.")
        self._log("")
        self._log(f"Verificacao completa iniciada: {settings.account_id}")

        self.worker = threading.Thread(target=self._sync_worker, args=(settings,), daemon=True)
        self.worker.start()

    def _start_monitoring(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Verificacao em andamento", "Aguarde a verificacao atual terminar.")
            return
        if self.monitoring:
            messagebox.showinfo("Monitoramento ativo", "O monitoramento ja esta rodando.")
            return

        settings = self._selected_settings()
        try:
            open_browser_workspace(settings)
        except Exception as exc:
            messagebox.showerror("Erro ao abrir AliExpress", str(exc))
            self._log(f"Erro ao abrir AliExpress: {exc}")
            return

        self.monitor_stop.clear()
        self.monitoring = True
        self.monitor_stop_requested = False
        self._set_busy(True)
        self.status_text.set("Monitorando")
        self.status_detail_text.set("Lendo somente a aba My Orders do monitor, sem mexer na aba do cliente.")
        self.last_check_text.set("iniciando")
        self.next_check_text.set("calculando")
        self._log("")
        self._log(f"Monitoramento iniciado: {settings.account_id}")
        self._log("Aba do cliente livre; aba My Orders reservada para o app.")
        self._log(f"Intervalo: {settings.check_interval_minutes} minuto(s)")

        self.monitor_thread = threading.Thread(target=self._monitor_worker, args=(settings,), daemon=True)
        self.monitor_thread.start()

    def _stop_monitoring(self) -> None:
        if not self.monitoring:
            return
        self.monitor_stop_requested = True
        self.monitor_stop.set()
        self.stop_monitor_button.configure(state="disabled")
        self.status_text.set("Parando")
        self.status_detail_text.set("Aguardando o ciclo atual terminar.")
        self.next_check_text.set("-")
        self._log("Parada solicitada.")

    def _sync_worker(self, settings: Settings) -> None:
        writer = _QueueWriter(self.log_queue)
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            try:
                _sync_once(settings)
                self.log_queue.put("__DONE__")
            except Exception as exc:
                print(f"Erro inesperado: {exc}")
                self.log_queue.put("__ERROR__")

    def _monitor_worker(self, settings: Settings) -> None:
        writer = _QueueWriter(self.log_queue)
        interval_seconds = max(60, settings.check_interval_minutes * 60)

        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            while not self.monitor_stop.is_set():
                started_at = datetime.now()
                print("")
                print(f"[{_format_time(started_at)}] Checando My Orders.")
                self.log_queue.put(("monitor_cycle_started", started_at))

                try:
                    _sync_once(settings, include_order_details=False)
                except Exception as exc:
                    print(f"Erro inesperado no monitoramento: {exc}")

                finished_at = datetime.now()
                next_check = finished_at + timedelta(seconds=interval_seconds)
                self.log_queue.put(("monitor_cycle_finished", finished_at, next_check))

                if self.monitor_stop.is_set():
                    break

                print(f"Proxima checagem: {_format_time(next_check)}")
                if self.monitor_stop.wait(interval_seconds):
                    break

            print("Monitoramento parado.")
            self.log_queue.put(("monitor_stopped",))

    def _selected_settings(self) -> Settings:
        settings = self.settings
        if not self.profiles:
            return settings

        selected_index = max(0, self.account_combo.current())
        profile = self.profiles[selected_index]
        return replace(
            settings,
            account_id=profile.responsible,
            responsible_default=profile.responsible,
            session_dir=profile.session_dir,
            ask_account=False,
        )

    def _refresh_selected_account_label(self) -> None:
        settings = self._selected_settings()
        self.account_text.set(f"{settings.account_id} - Chrome compartilhado: {settings.session_dir}")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple):
                    self._handle_queue_event(item)
                elif item == "__DONE__":
                    self.status_text.set("Concluido")
                    self.status_detail_text.set("Verificacao completa finalizada.")
                    self._set_busy(False)
                    messagebox.showinfo("Concluido", "Verificacao completa finalizada.")
                elif item == "__ERROR__":
                    self.status_text.set("Erro")
                    self.status_detail_text.set("Veja os logs para detalhes.")
                    self._set_busy(False)
                    messagebox.showerror("Erro", "A verificacao encontrou um erro. Veja os logs.")
                elif item is not None:
                    self._log(str(item), from_queue=True)
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _handle_queue_event(self, item: tuple) -> None:
        event = item[0]
        if event == "monitor_cycle_started":
            started_at = item[1]
            self.status_text.set("Monitorando")
            self.status_detail_text.set("Checando a aba My Orders reservada.")
            self.last_check_text.set(_format_time(started_at))
            self.next_check_text.set("calculando")
        elif event == "monitor_cycle_finished":
            finished_at = item[1]
            next_check = item[2]
            self.status_text.set("Monitorando")
            self.status_detail_text.set("Aguardando a proxima checagem.")
            self.last_check_text.set(_format_time(finished_at))
            self.next_check_text.set(_format_time(next_check))
        elif event == "monitor_stopped":
            self.monitoring = False
            self.monitor_stop_requested = False
            self.status_text.set("Parado")
            self.status_detail_text.set("Monitoramento pausado.")
            self.next_check_text.set("-")
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.sync_button.configure(state=state)
        self.open_browser_button.configure(state=state)
        self.account_combo.configure(state="disabled" if busy else "readonly")
        self.monitor_button.configure(state=state)
        stop_state = "normal" if self.monitoring and not self.monitor_stop_requested else "disabled"
        self.stop_monitor_button.configure(state=stop_state)

    def _on_close(self) -> None:
        if self.monitoring:
            should_close = messagebox.askyesno(
                "Monitoramento ativo",
                "O monitoramento esta rodando. Deseja fechar o app mesmo assim?",
            )
            if not should_close:
                return
            self.monitor_stop.set()
        self.destroy()

    def _clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _log(self, text: str, from_queue: bool = False) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text if from_queue else f"{text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


class _QueueWriter:
    def __init__(self, log_queue: queue.Queue[object]) -> None:
        self.log_queue = log_queue

    def write(self, text: str) -> int:
        if text:
            self.log_queue.put(text)
        return len(text)

    def flush(self) -> None:
        return None


def _sync_once(settings: Settings, include_order_details: bool = True) -> None:
    print(f"Planilha fixa: {settings.excel_path.resolve()}")
    print(f"Conta configurada: {settings.account_id}")
    print("Modo: completo com Order details." if include_order_details else "Modo: leve, apenas My Orders.")

    try:
        orders = fetch_orders(settings) if include_order_details else fetch_orders_summary(settings)
    except BrowserConnectionError:
        open_browser_workspace(settings)
        print("Chrome aberto. Se pedir login/captcha, resolva na janela aberta.")
        try:
            orders = fetch_orders(settings) if include_order_details else fetch_orders_summary(settings)
        except BrowserConnectionError:
            print("Nao consegui conectar no Chrome pela porta 9222.")
            print("Clique em 'Abrir AliExpress', faca login e tente novamente.")
            return

    created, updated, queued = sync_orders_to_excel_resilient(
        orders,
        settings.excel_path,
        preserve_existing_description=not include_order_details,
    )
    if queued:
        print(
            f"A planilha está aberta. {queued} pedido(s) foram guardados e serão aplicados "
            "automaticamente após fechar o Excel."
        )
        return
    print(
        f"Sincronizacao concluida: {len(orders)} pedido(s) lido(s), "
        f"{created} novo(s), {updated} atualizado(s)."
    )
    print(f"Planilha: {settings.excel_path.resolve()}")


def _load_gui_settings(env_path: Path, base_dir: Path) -> Settings:
    settings = load_settings(env_path if env_path.exists() else ".env")
    return replace(
        settings,
        excel_path=_resolve_from_base(settings.excel_path, base_dir),
        session_dir=_resolve_from_base(settings.session_dir, base_dir),
        account_profiles_path=_resolve_from_base(settings.account_profiles_path, base_dir),
        ask_account=False,
    )


def _resolve_from_base(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else base_dir / path


def _app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _profile_label(profile: AccountProfile) -> str:
    return f"{profile.email} -> {profile.responsible}"


def _format_time(value: datetime) -> str:
    return value.strftime("%d/%m/%Y %H:%M:%S")


if __name__ == "__main__":
    main()
