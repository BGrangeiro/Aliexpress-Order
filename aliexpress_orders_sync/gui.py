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
from .excel_sync import sync_orders_to_excel
from .scraper import BrowserConnectionError, ensure_browser_is_open, fetch_orders, fetch_orders_summary, open_browser


APP_TITLE = "AliExpress Pedidos"


def main() -> None:
    app = AliExpressOrdersApp()
    app.mainloop()


class AliExpressOrdersApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x620")
        self.minsize(760, 560)

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

        self.selected_profile = tk.StringVar(value=self.profiles[0].key if self.profiles else "")
        self.status_text = tk.StringVar(value="Pronto para verificar pedidos.")
        self.excel_text = tk.StringVar(value=f"Planilha fixa: {self.settings.excel_path.resolve()}")
        self.interval_text = tk.StringVar(
            value=f"Intervalo automatico: {self.settings.check_interval_minutes} minuto(s)"
        )
        self.last_check_text = tk.StringVar(value="Ultima verificacao: -")
        self.next_check_text = tk.StringVar(value="Proxima verificacao: -")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_log_queue)

    def _build_ui(self) -> None:
        self.configure(background="#F5F7F8")

        container = ttk.Frame(self, padding=18)
        container.pack(fill="both", expand=True)

        title = ttk.Label(container, text=APP_TITLE, font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            container,
            text="Escolha a conta, verifique completo quando quiser ou deixe o monitoramento leve ligado.",
            font=("Segoe UI", 10),
        )
        subtitle.pack(anchor="w", pady=(4, 16))

        account_frame = ttk.LabelFrame(container, text="Conta")
        account_frame.pack(fill="x")

        account_row = ttk.Frame(account_frame, padding=12)
        account_row.pack(fill="x")

        ttk.Label(account_row, text="Conta logada:").pack(side="left")

        account_values = [_profile_label(profile) for profile in self.profiles] or ["Usar configuracao do .env"]
        self.account_combo = ttk.Combobox(account_row, values=account_values, state="readonly", width=48)
        self.account_combo.pack(side="left", padx=(10, 8), fill="x", expand=True)
        self.account_combo.current(0)

        ttk.Button(account_row, text="?", width=3, command=self._show_accounts_help).pack(side="left")

        ttk.Label(container, textvariable=self.excel_text, font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 4))
        ttk.Label(container, textvariable=self.status_text, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(container, textvariable=self.interval_text, font=("Segoe UI", 9)).pack(anchor="w")
        ttk.Label(container, textvariable=self.last_check_text, font=("Segoe UI", 9)).pack(anchor="w")
        ttk.Label(container, textvariable=self.next_check_text, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 14))

        actions = ttk.Frame(container)
        actions.pack(fill="x", pady=(0, 12))

        self.open_browser_button = ttk.Button(
            actions,
            text="Abrir navegador / login",
            command=self._open_browser_for_selected_account,
        )
        self.open_browser_button.pack(side="left")

        self.sync_button = ttk.Button(
            actions,
            text="Verificar pedidos",
            command=self._start_sync,
        )
        self.sync_button.pack(side="left", padx=(10, 0))

        self.monitor_button = ttk.Button(
            actions,
            text="Iniciar monitoramento",
            command=self._start_monitoring,
        )
        self.monitor_button.pack(side="left", padx=(10, 0))

        self.stop_monitor_button = ttk.Button(
            actions,
            text="Parar monitoramento",
            command=self._stop_monitoring,
            state="disabled",
        )
        self.stop_monitor_button.pack(side="left", padx=(10, 0))

        ttk.Button(actions, text="Limpar logs", command=self._clear_logs).pack(side="right")

        log_frame = ttk.LabelFrame(container, text="Logs")
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_frame,
            height=16,
            wrap="word",
            state="disabled",
            background="#FFFFFF",
            foreground="#1F2933",
            borderwidth=0,
            padx=10,
            pady=10,
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self._log("App aberto.")
        self._log(f"Arquivo .env: {self.env_path}")
        if self.profiles:
            self._log(f"{len(self.profiles)} conta(s) encontrada(s) em {self.settings.account_profiles_path}.")
        else:
            self._log("Nenhuma conta encontrada no contas.txt; usando configuracao do .env.")

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
                    f"- {profile.email}\n  Responsavel: {profile.responsible}\n  Sessao: {profile.session_dir}"
                    for profile in self.profiles
                ],
                "",
                "A conta escolhida define a pasta de cookies/login e o valor da coluna Responsavel.",
                "Se trocar de conta, feche o navegador da conta anterior antes de abrir a nova.",
            ]
            message = "\n".join(lines)
        messagebox.showinfo("Contas disponiveis", message)

    def _open_browser_for_selected_account(self) -> None:
        settings = self._selected_settings()
        try:
            open_browser(settings)
        except Exception as exc:
            messagebox.showerror("Erro ao abrir navegador", str(exc))
            self._log(f"Erro ao abrir navegador: {exc}")
            return

        self.status_text.set("Navegador aberto. Faca login se necessario e deixe a janela aberta.")
        self._log(f"Navegador aberto para a conta: {settings.account_id}")
        self._log("Se a AliExpress pedir login/captcha, resolva na janela aberta antes de verificar.")

    def _start_sync(self) -> None:
        if self.monitoring:
            messagebox.showinfo("Monitoramento ativo", "Pare o monitoramento antes de verificar manualmente.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Sincronizacao em andamento", "A verificacao de pedidos ja esta rodando.")
            return

        settings = self._selected_settings()
        self._set_busy(True)
        self.status_text.set("Verificando pedidos...")
        self._log("")
        self._log(f"Iniciando verificacao da conta: {settings.account_id}")

        self.worker = threading.Thread(target=self._sync_worker, args=(settings,), daemon=True)
        self.worker.start()

    def _start_monitoring(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Sincronizacao em andamento", "Aguarde a verificacao atual terminar.")
            return
        if self.monitoring:
            messagebox.showinfo("Monitoramento ativo", "O monitoramento ja esta rodando.")
            return

        settings = self._selected_settings()
        self.monitor_stop.clear()
        self.monitoring = True
        self.monitor_stop_requested = False
        self._set_busy(True)
        self.status_text.set(f"Monitorando conta: {settings.account_id}")
        self.last_check_text.set("Ultima verificacao: iniciando agora")
        self.next_check_text.set("Proxima verificacao: calculando...")
        self._log("")
        self._log(f"Monitoramento leve iniciado para a conta: {settings.account_id}")
        self._log("Ele le apenas My Orders e nao abre Order details item por item.")
        self._log(f"Intervalo: {settings.check_interval_minutes} minuto(s)")

        self.monitor_thread = threading.Thread(target=self._monitor_worker, args=(settings,), daemon=True)
        self.monitor_thread.start()

    def _stop_monitoring(self) -> None:
        if not self.monitoring:
            return
        self.monitor_stop_requested = True
        self.monitor_stop.set()
        self.stop_monitor_button.configure(state="disabled")
        self.status_text.set("Parando monitoramento apos o ciclo atual...")
        self.next_check_text.set("Proxima verificacao: monitoramento parando")
        self._log("Solicitacao de parada recebida. Se estiver verificando agora, aguarde o ciclo terminar.")

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
                print(f"[{_format_time(started_at)}] Ciclo automatico iniciado.")
                self.log_queue.put(("monitor_cycle_started", started_at))

                try:
                    _sync_once(settings, include_order_details=False)
                except Exception as exc:
                    print(f"Erro inesperado no ciclo automatico: {exc}")

                finished_at = datetime.now()
                next_check = finished_at + timedelta(seconds=interval_seconds)
                self.log_queue.put(("monitor_cycle_finished", finished_at, next_check))

                if self.monitor_stop.is_set():
                    break

                print(f"Proxima verificacao: {_format_time(next_check)}")
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

    def _drain_log_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple):
                    self._handle_queue_event(item)
                elif item == "__DONE__":
                    self.status_text.set("Verificacao concluida.")
                    self._set_busy(False)
                    messagebox.showinfo("Concluido", "Verificacao de pedidos concluida.")
                elif item == "__ERROR__":
                    self.status_text.set("Erro na verificacao.")
                    self._set_busy(False)
                    messagebox.showerror("Erro", "A verificacao encontrou um erro. Veja os logs.")
                elif item is not None:
                    self._log(item, from_queue=True)
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _handle_queue_event(self, item: tuple) -> None:
        event = item[0]
        if event == "monitor_cycle_started":
            started_at = item[1]
            self.status_text.set("Monitorando... verificando pedidos agora.")
            self.last_check_text.set(f"Ultima verificacao: {_format_time(started_at)}")
            self.next_check_text.set("Proxima verificacao: em calculo")
        elif event == "monitor_cycle_finished":
            finished_at = item[1]
            next_check = item[2]
            self.status_text.set("Monitorando em segundo plano.")
            self.last_check_text.set(f"Ultima verificacao: {_format_time(finished_at)}")
            self.next_check_text.set(f"Proxima verificacao: {_format_time(next_check)}")
        elif event == "monitor_stopped":
            self.monitoring = False
            self.monitor_stop_requested = False
            self.status_text.set("Monitoramento parado.")
            self.next_check_text.set("Proxima verificacao: -")
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
    if include_order_details:
        print("Modo: verificacao completa com Order details.")
    else:
        print("Modo: monitoramento leve, lendo apenas My Orders.")

    try:
        orders = fetch_orders(settings) if include_order_details else fetch_orders_summary(settings)
    except BrowserConnectionError:
        ensure_browser_is_open(settings)
        print("Chrome/Edge aberto. Se pedir login ou captcha, resolva na janela aberta.")
        try:
            orders = fetch_orders(settings) if include_order_details else fetch_orders_summary(settings)
        except BrowserConnectionError:
            print("Nao consegui conectar no Chrome/Edge pela porta 9222.")
            print("Clique em 'Abrir navegador / login', faca login e tente novamente.")
            return

    created, updated = sync_orders_to_excel(orders, settings.excel_path)
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
