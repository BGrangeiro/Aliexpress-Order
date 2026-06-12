from __future__ import annotations

from aliexpress_orders_sync.accounts import (
    add_account_profile,
    delete_account_profile,
    load_account_profiles,
    update_account_profile,
)


def test_load_account_profiles(tmp_path):
    accounts_file = tmp_path / "contas.txt"
    accounts_file.write_text(
        "conta1|riquelmesenna577@gmail.com|riquelme|./chrome-session-conta-1\n"
        "conta2|riquelmestayler@gmail.com|neto|./chrome-session-conta-2\n",
        encoding="utf-8",
    )

    profiles = load_account_profiles(accounts_file)

    assert len(profiles) == 2
    assert profiles[0].email == "riquelmesenna577@gmail.com"
    assert profiles[0].responsible == "riquelme"
    assert profiles[0].session_dir == tmp_path / "chrome-session-conta-1"
    assert profiles[1].responsible == "neto"


def test_add_account_profile_persists_display_name(tmp_path):
    accounts_file = tmp_path / "contas.txt"
    profile = add_account_profile(
        accounts_file,
        "nova@example.com",
        "Jeferson",
        "Conta principal",
        tmp_path / "chrome-profile",
    )

    loaded = load_account_profiles(accounts_file)

    assert profile.key.startswith("jeferson-")
    assert loaded[0].email == "nova@example.com"
    assert loaded[0].responsible == "Jeferson"
    assert loaded[0].display_name == "Conta principal"

    updated = update_account_profile(
        accounts_file,
        profile.key,
        "alterada@example.com",
        "Neto",
        "Conta alterada",
    )
    assert updated.responsible == "Neto"
    assert load_account_profiles(accounts_file)[0].email == "alterada@example.com"

    deleted = delete_account_profile(accounts_file, profile.key)
    assert deleted.key == profile.key
    assert load_account_profiles(accounts_file) == []
