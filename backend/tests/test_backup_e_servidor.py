"""Backup diário do banco local e inicialização do servidor (Waitress)."""
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path


def test_backup_cria_copia_valida_uma_vez_por_dia(api, tmp_path):
    api.safe_update_status("ofs", "1234", "Pronto", 50.0)
    pasta = tmp_path / "copias"
    hoje = date(2026, 11, 16)

    criado = api.backup_banco.fazer_backup(api.SQLITE_DB, str(pasta), hoje=hoje)
    assert criado and Path(criado).name == "kanban_status_2026-11-16.db"
    con = sqlite3.connect(criado)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT status, qtd_produzida FROM kanban_status WHERE chave='1234'").fetchone() == ("Pronto", 50.0)
    con.close()

    assert api.backup_banco.fazer_backup(api.SQLITE_DB, str(pasta), hoje=hoje) is None, "segunda vez no dia não refaz"
    assert api.backup_banco.fazer_backup(api.SQLITE_DB, str(pasta), hoje=hoje, forcar=True) == criado
    assert not list(pasta.glob("*.parcial"))


def test_backup_apaga_so_copias_com_mais_de_30_dias(api, tmp_path):
    pasta = tmp_path / "copias"
    pasta.mkdir()
    for nome in ("kanban_status_2026-10-01.db", "kanban_status_2026-10-17.db", "kanban_status_2026-10-16.db",
                 "kanban_status_xyz.db", "outro_arquivo.db"):
        (pasta / nome).write_bytes(b"")
    api.backup_banco.fazer_backup(api.SQLITE_DB, str(pasta), hoje=date(2026, 11, 16))
    restantes = sorted(p.name for p in pasta.iterdir())
    assert restantes == ["kanban_status_2026-10-17.db", "kanban_status_2026-11-16.db",
                         "kanban_status_xyz.db", "outro_arquivo.db"]


def test_backup_diario_da_api(api):
    criado = api.executar_backup_diario()
    assert criado and os.path.dirname(criado) == os.path.join(api.BASE_DIR, "backups_banco")
    assert api.executar_backup_diario() is None


def test_falha_no_backup_nao_derruba_a_api(api, monkeypatch):
    monkeypatch.setattr(api, "SQLITE_DB", os.path.join(api.BASE_DIR, "nao_existe.db"))
    assert api.executar_backup_diario() is None
    for h in api.logger.handlers:
        h.flush()
    log = (Path(api.BASE_DIR) / "logs" / "fivel.log").read_text(encoding="utf-8")
    assert "Falha no backup" in log


def test_pasta_de_backup_configuravel(api, monkeypatch, tmp_path):
    monkeypatch.setenv("FIVEL_BACKUP_DIR", str(tmp_path / "outro_disco"))
    assert api.backup_banco.pasta_padrao("C:/qualquer") == str(tmp_path / "outro_disco")


def test_servidor_sobe_com_waitress(api, monkeypatch):
    import waitress

    chamadas = []
    monkeypatch.setattr(waitress, "serve", lambda app, **k: chamadas.append((app, k)))
    monkeypatch.setenv("FIVEL_PORT", "5001")
    api.iniciar_servidor()
    assert chamadas == [(api.app, {"host": "0.0.0.0", "port": 5001, "threads": api.THREADS_SERVIDOR})]


def test_sem_waitress_usa_servidor_do_flask(api, monkeypatch):
    chamadas = []
    monkeypatch.setitem(sys.modules, "waitress", None)  # simula "não instalado"
    monkeypatch.setattr(api.app, "run", lambda **k: chamadas.append(k))
    api.iniciar_servidor()
    assert chamadas and chamadas[0]["port"] == 5000
