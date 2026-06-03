from __future__ import annotations

from aliexpress_orders_sync.accounts import load_account_profiles


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
