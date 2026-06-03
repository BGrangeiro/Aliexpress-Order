from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .config import Settings


@dataclass(frozen=True)
class AccountProfile:
    key: str
    email: str
    responsible: str
    session_dir: Path


def choose_account(settings: Settings) -> Settings:
    """Ask which configured AliExpress account should be used for this run."""

    if not settings.ask_account:
        return settings

    profiles = load_account_profiles(settings.account_profiles_path)
    if not profiles:
        print(f"Nenhuma conta encontrada em {settings.account_profiles_path}.")
        print("Continuando com a configuração do .env.")
        return settings

    print("")
    print("Selecione a conta AliExpress para esta execução:")
    for index, profile in enumerate(profiles, start=1):
        print(f"{index}. {profile.email} -> Responsável: {profile.responsible}")

    selected = _prompt_profile_index(len(profiles))
    profile = profiles[selected - 1]
    print(f"Conta selecionada: {profile.email} -> {profile.responsible}")
    print(f"Sessão do navegador: {profile.session_dir}")
    print("")

    return replace(
        settings,
        account_id=profile.responsible,
        responsible_default=profile.responsible,
        session_dir=profile.session_dir,
    )


def load_account_profiles(path: Path) -> list[AccountProfile]:
    if not path.exists():
        return []

    profiles: list[AccountProfile] = []
    base_dir = path.resolve().parent
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 4:
            continue

        session_dir = Path(parts[3]).expanduser()
        if not session_dir.is_absolute():
            session_dir = base_dir / session_dir

        profiles.append(
            AccountProfile(
                key=parts[0],
                email=parts[1],
                responsible=parts[2],
                session_dir=session_dir,
            )
        )
    return profiles


def _prompt_profile_index(profile_count: int) -> int:
    while True:
        answer = input("Digite o número da conta: ").strip()
        try:
            selected = int(answer)
        except ValueError:
            print("Digite apenas o número da conta.")
            continue

        if 1 <= selected <= profile_count:
            return selected
        print(f"Escolha um número entre 1 e {profile_count}.")
