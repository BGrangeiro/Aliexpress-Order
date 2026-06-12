from __future__ import annotations

import sys
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .accounts import (
    AccountProfile,
    add_account_profile,
    delete_account_profile,
    load_account_profiles,
    update_account_profile,
)
from .config import Settings, load_settings
from .database import OrderFilters, OrderRepository
from .scraper import (
    BrowserConnectionError,
    fetch_orders,
    fetch_orders_summary,
    open_browser_workspace,
)

SyncFetcher = Callable[[Settings], list]
BrowserOpener = Callable[[Settings], None]


class ServiceConflictError(RuntimeError):
    pass


class AccountNotFoundError(ValueError):
    pass


class WebMonitorService:
    def __init__(
        self,
        base_dir: Path | None = None,
        settings: Settings | None = None,
        profiles: list[AccountProfile] | None = None,
        full_fetcher: SyncFetcher = fetch_orders,
        summary_fetcher: SyncFetcher = fetch_orders_summary,
        browser_opener: BrowserOpener = open_browser_workspace,
    ) -> None:
        self.base_dir = (base_dir or app_base_dir()).resolve()
        self.settings = settings or _load_web_settings(self.base_dir)
        self.profiles = profiles if profiles is not None else load_account_profiles(self.settings.account_profiles_path)
        self.full_fetcher = full_fetcher
        self.summary_fetcher = summary_fetcher
        self.browser_opener = browser_opener
        self.repository = OrderRepository(self.settings.database_path)

        self.state_lock = threading.RLock()
        self.database_lock = threading.Lock()
        self.operation_lock = threading.Lock()
        self.monitor_stop = threading.Event()
        self.monitor_thread: threading.Thread | None = None
        self.operation_thread: threading.Thread | None = None

        self.selected_account_key = self.profiles[0].key if self.profiles else ""
        self.status = "Pronto"
        self.status_detail = "Agente conectado e aguardando comando."
        self.busy = False
        self.monitoring = False
        self.last_check: datetime | None = None
        self.next_check: datetime | None = None
        self.last_result = {"read": 0, "created": 0, "updated": 0}
        self.started_at = datetime.now()
        self.logs: deque[dict[str, str]] = deque(maxlen=250)
        self._log("Sistema web iniciado.")
        if self.profiles:
            self._log(f"{len(self.profiles)} conta(s) carregada(s).")
        else:
            self._log("Nenhuma conta encontrada; usando a configuração do .env.", "warning")

    def accounts(self) -> list[dict[str, str]]:
        return [
            {
                "key": profile.key,
                "email": profile.email,
                "responsible": profile.responsible,
                "display_name": profile.display_name or profile.email,
            }
            for profile in self.profiles
        ]

    def responsibles(self) -> list[str]:
        preferred = ["Jeferson", "Riquelme", "Neto"]
        available = {profile.responsible.strip() for profile in self.profiles if profile.responsible.strip()}
        result = [name for name in preferred if name.lower() in {value.lower() for value in available}]
        result.extend(
            sorted(
                (value for value in available if value.lower() not in {name.lower() for name in result}),
                key=str.lower,
            )
        )
        return result

    def add_account(self, email: str, responsible: str, display_name: str) -> dict[str, str]:
        with self.state_lock:
            if self.busy or self.monitoring:
                raise ServiceConflictError("Pare a operação atual antes de cadastrar uma conta.")
        profile = add_account_profile(
            self.settings.account_profiles_path,
            email=email,
            responsible=responsible,
            display_name=display_name,
            session_dir=self.settings.session_dir,
        )
        with self.state_lock:
            self.profiles.append(profile)
            if not self.selected_account_key:
                self.selected_account_key = profile.key
        self._log(f"Conta cadastrada: {profile.email} -> {profile.responsible}", "success")
        return {
            "key": profile.key,
            "email": profile.email,
            "responsible": profile.responsible,
            "display_name": profile.display_name,
        }

    def update_account(
        self,
        account_key: str,
        email: str,
        responsible: str,
        display_name: str,
    ) -> dict[str, str]:
        self._ensure_accounts_editable()
        profile = update_account_profile(
            self.settings.account_profiles_path,
            key=account_key,
            email=email,
            responsible=responsible,
            display_name=display_name,
        )
        with self.state_lock:
            self.profiles = [
                profile if item.key == account_key else item
                for item in self.profiles
            ]
        self.repository.update_account_metadata(account_key, profile.email, profile.responsible)
        self._log(f"Conta atualizada: {profile.email} -> {profile.responsible}", "success")
        return self._serialize_profile(profile)

    def delete_account(self, account_key: str) -> dict[str, str]:
        self._ensure_accounts_editable()
        profile = delete_account_profile(self.settings.account_profiles_path, account_key)
        with self.state_lock:
            self.profiles = [item for item in self.profiles if item.key != account_key]
            if self.selected_account_key == account_key:
                self.selected_account_key = self.profiles[0].key if self.profiles else ""
        self._log(
            f"Conta removida: {profile.email}. O histórico de pedidos foi preservado.",
            "warning",
        )
        return self._serialize_profile(profile)

    def _ensure_accounts_editable(self) -> None:
        with self.state_lock:
            if self.busy or self.monitoring:
                raise ServiceConflictError("Pare a operação atual antes de alterar contas.")

    @staticmethod
    def _serialize_profile(profile: AccountProfile) -> dict[str, str]:
        return {
            "key": profile.key,
            "email": profile.email,
            "responsible": profile.responsible,
            "display_name": profile.display_name or profile.email,
        }

    def select_account(self, account_key: str) -> None:
        profile = self._profile(account_key)
        with self.state_lock:
            if self.busy or self.monitoring:
                raise ServiceConflictError("Pare a operação atual antes de trocar de conta.")
            self.selected_account_key = profile.key
            self.status_detail = f"Conta selecionada: {profile.email}"
        self._log(f"Conta selecionada: {profile.email} -> {profile.responsible}")

    def open_browser(self, account_key: str | None = None) -> None:
        settings = self._settings_for(account_key)
        self._start_operation(
            name="Abrindo navegador",
            detail="Criando a aba de navegação e a aba reservada de My Orders.",
            target=lambda: self._open_browser_operation(settings),
        )

    def start_monitoring(self, account_key: str | None = None) -> None:
        settings = self._settings_for(account_key)
        with self.state_lock:
            if self.monitoring:
                raise ServiceConflictError("O monitoramento já está ativo.")
            if self.busy:
                raise ServiceConflictError("Aguarde a operação atual terminar.")
            self.monitoring = True
            self.busy = True
            self.status = "Monitorando"
            self.status_detail = "Preparando o navegador e a aba My Orders."
            self.next_check = None
            self.monitor_stop.clear()

        self._log(f"Monitoramento iniciado para {settings.account_id}.")
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(settings,),
            name="aliexpress-monitor",
            daemon=True,
        )
        self.monitor_thread.start()

    def stop_monitoring(self) -> None:
        with self.state_lock:
            if not self.monitoring:
                return
            self.status = "Parando"
            self.status_detail = "Aguardando a verificação atual terminar."
            self.next_check = None
        self.monitor_stop.set()
        self._log("Parada do monitoramento solicitada.")

    def run_full_sync(self, account_key: str | None = None) -> None:
        settings = self._settings_for(account_key)
        self._start_operation(
            name="Verificação completa",
            detail="Lendo todos os pedidos, rastreios e formas de pagamento.",
            target=lambda: self._sync_operation(settings, include_details=True),
        )

    def snapshot(self) -> dict:
        with self.state_lock:
            profile = self._selected_profile()
            return {
                "status": self.status,
                "status_detail": self.status_detail,
                "busy": self.busy,
                "monitoring": self.monitoring,
                "selected_account_key": self.selected_account_key,
                "selected_account": {
                    "email": profile.email if profile else "",
                    "responsible": profile.responsible if profile else self.settings.responsible_default,
                },
                "last_check": _iso(self.last_check),
                "next_check": _iso(self.next_check),
                "last_result": dict(self.last_result),
                "database_path": str(self.settings.database_path.resolve()),
                "uptime_seconds": int((datetime.now() - self.started_at).total_seconds()),
                "logs": list(self.logs),
            }

    def orders(
        self,
        filters: OrderFilters | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        return self.repository.list_orders(filters, limit, offset)

    def dashboard(self, filters: OrderFilters | None = None) -> dict:
        return self.repository.dashboard_stats(filters)

    def statuses(self) -> list[str]:
        return self.repository.available_statuses()

    def filter_options(self) -> dict:
        return self.repository.filter_options()

    def analytics(self, filters: OrderFilters | None = None) -> dict:
        return self.repository.analytics(filters)

    def shutdown(self) -> None:
        self.monitor_stop.set()

    def _start_operation(self, name: str, detail: str, target: Callable[[], None]) -> None:
        with self.state_lock:
            if self.monitoring:
                raise ServiceConflictError("Pare o monitoramento antes desta operação.")
            if self.busy:
                raise ServiceConflictError("Já existe uma operação em andamento.")
            self.busy = True
            self.status = name
            self.status_detail = detail

        self.operation_thread = threading.Thread(
            target=self._operation_wrapper,
            args=(target,),
            name="aliexpress-operation",
            daemon=True,
        )
        self.operation_thread.start()

    def _operation_wrapper(self, target: Callable[[], None]) -> None:
        if not self.operation_lock.acquire(blocking=False):
            self._finish_with_error("Outra operação já está usando o agente.")
            return
        try:
            target()
        except Exception as exc:
            self._finish_with_error(str(exc))
        finally:
            self.operation_lock.release()

    def _open_browser_operation(self, settings: Settings) -> None:
        self._log(f"Abrindo AliExpress para {settings.account_id}.")
        self.browser_opener(settings)
        with self.state_lock:
            self.status = "Navegador aberto"
            self.status_detail = "Uma aba está livre e a outra foi reservada para My Orders."
            self.busy = False
        self._log("Chrome aberto com duas abas.")

    def _monitor_loop(self, settings: Settings) -> None:
        interval_seconds = max(60, settings.check_interval_minutes * 60)
        try:
            self.browser_opener(settings)
            self._log("Navegador preparado para o monitoramento.")
            while not self.monitor_stop.is_set():
                started = datetime.now()
                with self.state_lock:
                    self.status = "Monitorando"
                    self.status_detail = "Verificando a aba My Orders."
                    self.last_check = started
                    self.next_check = None

                self._log(f"Verificação leve iniciada para {settings.account_id}.")
                try:
                    self._sync_operation(
                        settings,
                        include_details=False,
                        keep_busy=True,
                        account_key=self.selected_account_key or settings.account_id,
                    )
                except Exception as exc:
                    self._log(f"Falha na verificação: {exc}", "error")
                    with self.state_lock:
                        self.status = "Atenção"
                        self.status_detail = str(exc)

                finished = datetime.now()
                next_check = finished + timedelta(seconds=interval_seconds)
                with self.state_lock:
                    self.last_check = finished
                    self.next_check = next_check
                    if not self.monitor_stop.is_set():
                        self.status = "Monitorando"
                        self.status_detail = "Aguardando a próxima verificação."

                if self.monitor_stop.wait(interval_seconds):
                    break
        except Exception as exc:
            self._log(f"Monitoramento interrompido: {exc}", "error")
            with self.state_lock:
                self.status = "Erro"
                self.status_detail = str(exc)
        finally:
            with self.state_lock:
                self.monitoring = False
                self.busy = False
                self.next_check = None
                if self.status != "Erro":
                    self.status = "Parado"
                    self.status_detail = "Monitoramento pausado."
            self._log("Monitoramento parado.")

    def _sync_operation(
        self,
        settings: Settings,
        include_details: bool,
        keep_busy: bool = False,
        account_key: str | None = None,
    ) -> None:
        mode = "completa" if include_details else "leve"
        fetcher = self.full_fetcher if include_details else self.summary_fetcher
        account_key = account_key or self.selected_account_key or settings.account_id
        profile = self._profile(account_key) if self.profiles else None
        try:
            orders = fetcher(settings)
        except BrowserConnectionError:
            self._log("Chrome desconectado; tentando abrir novamente.", "warning")
            self.browser_opener(settings)
            orders = fetcher(settings)

        with self.database_lock:
            created, updated = self.repository.upsert_orders(
                orders,
                account_key=account_key,
                account_email=profile.email if profile else "",
                preserve_existing_description=not include_details,
            )
            self.repository.record_sync(
                account_key=account_key,
                mode=mode,
                read_count=len(orders),
                created_count=created,
                updated_count=updated,
            )

        with self.state_lock:
            self.last_result = {
                "read": len(orders),
                "created": created,
                "updated": updated,
            }
            self.last_check = datetime.now()
            if not keep_busy:
                self.status = "Concluído"
                self.status_detail = f"Verificação {mode} finalizada."
                self.busy = False

        level = "success" if created or updated else "info"
        self._log(
            f"Verificação {mode}: {len(orders)} lido(s), {created} novo(s), {updated} atualizado(s).",
            level,
        )

    def _finish_with_error(self, message: str) -> None:
        with self.state_lock:
            self.status = "Erro"
            self.status_detail = message
            self.busy = False
        self._log(message, "error")

    def _settings_for(self, account_key: str | None) -> Settings:
        with self.state_lock:
            if account_key:
                if self.busy or self.monitoring:
                    if account_key != self.selected_account_key:
                        raise ServiceConflictError("Pare a operação atual antes de trocar de conta.")
                else:
                    self.selected_account_key = account_key
            profile = self._profile(self.selected_account_key) if self.profiles else None

        if not profile:
            return self.settings
        return replace(
            self.settings,
            account_id=profile.responsible,
            responsible_default=profile.responsible,
            session_dir=profile.session_dir,
            ask_account=False,
        )

    def _profile(self, account_key: str) -> AccountProfile:
        for profile in self.profiles:
            if profile.key == account_key:
                return profile
        raise AccountNotFoundError(f"Conta não encontrada: {account_key}")

    def _selected_profile(self) -> AccountProfile | None:
        if not self.profiles:
            return None
        try:
            return self._profile(self.selected_account_key)
        except AccountNotFoundError:
            return self.profiles[0]

    def _log(self, message: str, level: str = "info") -> None:
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "message": message,
            "level": level,
        }
        with self.state_lock:
            self.logs.append(entry)

def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _load_web_settings(base_dir: Path) -> Settings:
    env_path = base_dir / ".env"
    settings = load_settings(env_path if env_path.exists() else ".env")
    return replace(
        settings,
        excel_path=_resolve_path(settings.excel_path, base_dir),
        session_dir=_resolve_path(settings.session_dir, base_dir),
        account_profiles_path=_resolve_path(settings.account_profiles_path, base_dir),
        database_path=_resolve_path(settings.database_path, base_dir),
        ask_account=False,
    )


def _resolve_path(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else base_dir / path


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None
