"""Usuários, sessões e auditoria do FIVEL Control (SQLite local)."""
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SQLITE_DB = os.path.join(BASE_DIR, "kanban_status.db")

PERFIS = ("admin", "vendas")
DURACAO_SESSAO = timedelta(hours=12)
SENHA_MINIMA = 8

# Proteção contra tentativa de senha em sequência: 5 erros bloqueiam o login por 5 minutos.
MAX_TENTATIVAS = 5
BLOQUEIO_SEG = 300
_tentativas = {}
_tentativas_lock = threading.Lock()

FORMATO_DATA = "%Y-%m-%d %H:%M:%S"


def _conn():
    conn = sqlite3.connect(SQLITE_DB, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _agora():
    return datetime.now().strftime(FORMATO_DATA)


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def init_tabelas():
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            login TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            perfil TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT
        )
    """)
    # Guarda só o hash do token: quem ler o banco não consegue usar as sessões.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessoes (
            token_hash TEXT PRIMARY KEY,
            usuario_id INTEGER NOT NULL,
            criado_em TEXT NOT NULL,
            expira_em TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT NOT NULL,
            usuario TEXT,
            acao TEXT NOT NULL,
            detalhes TEXT
        )
    """)
    conn.commit()
    conn.close()


def _validar_senha(senha):
    if not senha or len(senha) < SENHA_MINIMA:
        raise ValueError(f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres.")


def criar_usuario(nome, login, senha, perfil):
    login = (login or "").strip().lower()
    if not login or not (nome or "").strip():
        raise ValueError("Nome e login são obrigatórios.")
    if perfil not in PERFIS:
        raise ValueError(f"Perfil inválido. Use: {', '.join(PERFIS)}.")
    _validar_senha(senha)
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO usuarios (nome, login, senha_hash, perfil, ativo, criado_em) VALUES (?, ?, ?, ?, 1, ?)",
            (nome.strip(), login, generate_password_hash(senha), perfil, _agora()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"Já existe um usuário com o login '{login}'.")
    finally:
        conn.close()


def alterar_senha(login, senha):
    _validar_senha(senha)
    conn = _conn()
    cur = conn.execute(
        "UPDATE usuarios SET senha_hash = ? WHERE login = ?",
        (generate_password_hash(senha), (login or "").strip().lower()),
    )
    # Senha nova derruba as sessões abertas com a senha antiga.
    conn.execute(
        "DELETE FROM sessoes WHERE usuario_id = (SELECT id FROM usuarios WHERE login = ?)",
        ((login or "").strip().lower(),),
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise ValueError(f"Usuário '{login}' não encontrado.")


def definir_ativo(login, ativo):
    conn = _conn()
    cur = conn.execute(
        "UPDATE usuarios SET ativo = ? WHERE login = ?", (1 if ativo else 0, (login or "").strip().lower())
    )
    if not ativo:
        conn.execute(
            "DELETE FROM sessoes WHERE usuario_id = (SELECT id FROM usuarios WHERE login = ?)",
            ((login or "").strip().lower(),),
        )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise ValueError(f"Usuário '{login}' não encontrado.")


def listar_usuarios():
    conn = _conn()
    rows = conn.execute(
        "SELECT nome, login, perfil, ativo, criado_em FROM usuarios ORDER BY nome"
    ).fetchall()
    conn.close()
    return [
        {"nome": r[0], "login": r[1], "perfil": r[2], "ativo": bool(r[3]), "criado_em": r[4]}
        for r in rows
    ]


def _bloqueado(login):
    with _tentativas_lock:
        falhas, ate = _tentativas.get(login, (0, 0))
        return falhas >= MAX_TENTATIVAS and time.time() < ate


def _registrar_falha(login):
    with _tentativas_lock:
        falhas, ate = _tentativas.get(login, (0, 0))
        if time.time() >= ate and falhas >= MAX_TENTATIVAS:
            falhas = 0
        falhas += 1
        _tentativas[login] = (falhas, time.time() + BLOQUEIO_SEG)


def autenticar(login, senha):
    """Retorna (token, usuario, erro). Em caso de erro, token e usuario são None."""
    login = (login or "").strip().lower()
    if _bloqueado(login):
        return None, None, "Muitas tentativas erradas. Aguarde 5 minutos e tente de novo."

    conn = _conn()
    row = conn.execute(
        "SELECT id, nome, login, senha_hash, perfil, ativo FROM usuarios WHERE login = ?", (login,)
    ).fetchone()
    conn.close()

    if not row or not row[5] or not check_password_hash(row[3], senha or ""):
        _registrar_falha(login)
        return None, None, "Usuário ou senha incorretos."

    with _tentativas_lock:
        _tentativas.pop(login, None)
    usuario = {"id": row[0], "nome": row[1], "login": row[2], "perfil": row[4]}
    return criar_sessao(row[0]), usuario, None


def criar_sessao(usuario_id):
    token = secrets.token_urlsafe(32)
    agora = datetime.now()
    conn = _conn()
    conn.execute("DELETE FROM sessoes WHERE expira_em < ?", (agora.strftime(FORMATO_DATA),))
    conn.execute(
        "INSERT INTO sessoes (token_hash, usuario_id, criado_em, expira_em) VALUES (?, ?, ?, ?)",
        (_hash_token(token), usuario_id, agora.strftime(FORMATO_DATA), (agora + DURACAO_SESSAO).strftime(FORMATO_DATA)),
    )
    conn.commit()
    conn.close()
    return token


def usuario_da_sessao(token):
    if not token:
        return None
    conn = _conn()
    row = conn.execute(
        """SELECT u.id, u.nome, u.login, u.perfil
           FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
           WHERE s.token_hash = ? AND s.expira_em > ? AND u.ativo = 1""",
        (_hash_token(token), _agora()),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "nome": row[1], "login": row[2], "perfil": row[3]}


def encerrar_sessao(token):
    if not token:
        return
    conn = _conn()
    conn.execute("DELETE FROM sessoes WHERE token_hash = ?", (_hash_token(token),))
    conn.commit()
    conn.close()


def registrar_auditoria(usuario, acao, detalhes=None):
    if detalhes is not None and not isinstance(detalhes, str):
        detalhes = json.dumps(detalhes, ensure_ascii=False, default=str)
    if detalhes and len(detalhes) > 1000:
        detalhes = detalhes[:1000] + "..."
    conn = _conn()
    conn.execute(
        "INSERT INTO auditoria (data_hora, usuario, acao, detalhes) VALUES (?, ?, ?, ?)",
        (_agora(), usuario, acao, detalhes),
    )
    conn.commit()
    conn.close()
