from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from .config import Settings


@dataclass(frozen=True)
class AccountProfile:
    key: str
    email: str
    responsible: str
    session_dir: Path
    display_name: str = ""


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
        if len(parts) not in {4, 5}:
            continue

        session_dir = Path(os.path.expandvars(parts[3])).expanduser()
        if not session_dir.is_absolute():
            session_dir = base_dir / session_dir

        profiles.append(
            AccountProfile(
                key=parts[0],
                email=parts[1],
                responsible=parts[2],
                session_dir=session_dir,
                display_name=parts[4] if len(parts) == 5 else parts[1],
            )
        )
    return profiles


def add_account_profile(
    path: Path,
    email: str,
    responsible: str,
    display_name: str,
    session_dir: Path,
) -> AccountProfile:
    email = email.strip().lower()
    responsible = responsible.strip()
    display_name = display_name.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Informe um e-mail válido.")
    if not responsible:
        raise ValueError("Selecione um responsável.")
    if not display_name:
        raise ValueError("Informe o nome da conta.")

    profiles = load_account_profiles(path)
    if any(profile.email.lower() == email for profile in profiles):
        raise ValueError("Este e-mail já está cadastrado.")

    slug = re.sub(r"[^a-z0-9]+", "-", responsible.lower()).strip("-") or "conta"
    key = f"{slug}-{uuid.uuid4().hex[:8]}"
    profile = AccountProfile(
        key=key,
        email=email,
        responsible=responsible,
        session_dir=session_dir,
        display_name=display_name,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    session_value = str(session_dir)
    line = f"{profile.key}|{profile.email}|{profile.responsible}|{session_value}|{profile.display_name}\n"
    with path.open("a", encoding="utf-8") as accounts_file:
        accounts_file.write(line)
    return profile


def update_account_profile(
    path: Path,
    key: str,
    email: str,
    responsible: str,
    display_name: str,
) -> AccountProfile:
    profiles = load_account_profiles(path)
    current = next((profile for profile in profiles if profile.key == key), None)
    if current is None:
        raise ValueError("Conta não encontrada.")

    email = email.strip().lower()
    responsible = responsible.strip()
    display_name = display_name.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Informe um e-mail válido.")
    if not responsible or not display_name:
        raise ValueError("Responsável e nome da conta são obrigatórios.")
    if any(profile.key != key and profile.email.lower() == email for profile in profiles):
        raise ValueError("Este e-mail já está cadastrado.")

    updated = replace(
        current,
        email=email,
        responsible=responsible,
        display_name=display_name,
    )
    _write_account_profiles(path, [updated if profile.key == key else profile for profile in profiles])
    return updated


def delete_account_profile(path: Path, key: str) -> AccountProfile:
    profiles = load_account_profiles(path)
    current = next((profile for profile in profiles if profile.key == key), None)
    if current is None:
        raise ValueError("Conta não encontrada.")
    _write_account_profiles(path, [profile for profile in profiles if profile.key != key])
    return current


def _write_account_profiles(path: Path, profiles: list[AccountProfile]) -> None:
    header = (
        "# Formato:\n"
        "# id|email|responsavel|pasta_de_sessao|nome_da_conta\n\n"
    )
    lines = [
        "|".join(
            [
                profile.key,
                profile.email,
                profile.responsible,
                str(profile.session_dir),
                profile.display_name or profile.email,
            ]
        )
        for profile in profiles
    ]
    path.write_text(header + "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


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
