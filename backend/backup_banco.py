"""Backup diário do banco local (kanban_status.db).

A API chama fazer_backup() de hora em hora; só a primeira chamada do dia cria a cópia.
Também pode ser rodado à mão:  python backup_banco.py          (cria o de hoje, se faltar)
                               python backup_banco.py --agora  (refaz o de hoje)
                               python backup_banco.py --listar
Para restaurar: pare o serviço FIVEL_API e copie o arquivo do dia desejado por cima do
kanban_status.db (apague kanban_status.db-wal e -shm, se existirem).
"""
import argparse
import glob
import os
import sqlite3
from datetime import date, datetime, timedelta

DIAS_RETENCAO = 30
PREFIXO = "kanban_status_"


def pasta_padrao(base_dir):
    return os.getenv("FIVEL_BACKUP_DIR") or os.path.join(base_dir, "backups_banco")


def _data_do_arquivo(caminho):
    nome = os.path.basename(caminho)
    try:
        return datetime.strptime(nome[len(PREFIXO):-len(".db")], "%Y-%m-%d").date()
    except ValueError:
        return None


def fazer_backup(origem, pasta, hoje=None, forcar=False):
    """Copia o banco para <pasta>/kanban_status_AAAA-MM-DD.db. Devolve o caminho criado,
    ou None se o backup de hoje já existe. A cópia usa a API de backup do SQLite (segura com
    a API rodando) e só é aceita se passar no integrity_check."""
    hoje = hoje or date.today()
    if not os.path.exists(origem):
        raise FileNotFoundError(origem)
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f"{PREFIXO}{hoje:%Y-%m-%d}.db")
    if os.path.exists(destino) and not forcar:
        return None

    parcial = destino + ".parcial"
    if os.path.exists(parcial):
        os.remove(parcial)
    fonte = sqlite3.connect(origem, timeout=20.0)
    copia = sqlite3.connect(parcial)
    try:
        fonte.backup(copia)
        copia.execute("PRAGMA journal_mode=DELETE")
        resultado = copia.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        copia.close()
        fonte.close()
    if resultado != "ok":
        os.remove(parcial)
        raise RuntimeError(f"Backup reprovado no integrity_check: {resultado}")
    os.replace(parcial, destino)
    limpar_antigos(pasta, hoje)
    return destino


def limpar_antigos(pasta, hoje=None, dias=DIAS_RETENCAO):
    """Apaga só os backups deste módulo com mais de `dias` dias. Outros arquivos ficam."""
    hoje = hoje or date.today()
    limite = hoje - timedelta(days=dias)
    removidos = []
    for caminho in glob.glob(os.path.join(pasta, PREFIXO + "*.db")):
        dia = _data_do_arquivo(caminho)
        if dia and dia < limite:
            os.remove(caminho)
            removidos.append(caminho)
    return removidos


def listar_backups(pasta):
    arquivos = [c for c in glob.glob(os.path.join(pasta, PREFIXO + "*.db")) if _data_do_arquivo(c)]
    return sorted(arquivos, key=_data_do_arquivo, reverse=True)


if __name__ == "__main__":
    base = os.path.abspath(os.path.dirname(__file__))
    parser = argparse.ArgumentParser(description="Backup do banco local do FIVEL")
    parser.add_argument("--agora", action="store_true", help="refaz o backup de hoje mesmo se já existir")
    parser.add_argument("--listar", action="store_true", help="lista os backups existentes")
    args = parser.parse_args()
    pasta = pasta_padrao(base)
    if args.listar:
        for c in listar_backups(pasta):
            print(f"{c}  ({os.path.getsize(c) / 1024:.0f} KB)")
    else:
        criado = fazer_backup(os.path.join(base, "kanban_status.db"), pasta, forcar=args.agora)
        print(f"Backup criado: {criado}" if criado else "O backup de hoje já existe (use --agora para refazer).")
