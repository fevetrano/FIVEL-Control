"""Login, cadastro de usuários, sessões e o script de terminal."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def banco(api):
    return sqlite3.connect(api.SQLITE_DB)


def test_sem_login_nao_entra(cliente):
    assert cliente.get("/api/pedidos").status_code == 401
    assert cliente.get("/api/pedidos", headers={"Authorization": "Bearer xyz"}).status_code == 401
    assert cliente.get("/").status_code == 200, "a tela de login continua abrindo"


@pytest.mark.parametrize("login, senha, perfil", [
    ("curta", "123", "admin"),          # senha abaixo do mínimo
    ("x", "senha-forte-1", "chefe"),    # perfil inexistente
])
def test_cadastro_invalido(api, login, senha, perfil):
    with pytest.raises(ValueError):
        api.auth.criar_usuario("Nome", login, senha, perfil)


def test_login_duplicado(api):
    api.auth.criar_usuario("Fernando", "fernando", "senha-dev-9", "dev")
    with pytest.raises(ValueError):
        api.auth.criar_usuario("Outro", "FERNANDO", "senha-forte-1", "admin")


def test_senha_guardada_so_como_hash(api):
    api.auth.criar_usuario("Fernando", "fernando", "senha-dev-teste", "dev")
    hashes = [r[0] for r in banco(api).execute("SELECT senha_hash FROM usuarios")]
    assert all("senha-dev-teste" not in h and len(h) > 50 for h in hashes)


def test_login_em_maiusculas_e_sessao(api, cliente, entrar):
    api.auth.criar_usuario("Fernando", "fernando", "senha-dev-9", "dev")
    r, _ = entrar("FERNANDO", "errada")
    assert r.status_code == 401 and r.get_json()["erro"] == "Usuário ou senha incorretos."

    r, headers = entrar("fernando", "senha-dev-9")
    usuario = r.get_json()["usuario"]
    assert r.status_code == 200 and usuario["perfil"] == "dev" and usuario["login"] == "FERNANDO"
    token = r.get_json()["token"]
    assert banco(api).execute("SELECT COUNT(*) FROM sessoes WHERE token_hash = ?", (token,)).fetchone()[0] == 0, \
        "o token não fica em texto no banco"
    assert cliente.get("/api/auth/eu", headers=headers).get_json()["usuario"]["login"] == "FERNANDO"


def test_cinco_erros_bloqueiam_o_login(api, entrar):
    api.auth.criar_usuario("Escritório", "escritorio", "senha-vendas-1", "vendas")
    for _ in range(5):
        entrar("escritorio", "errada")
    r, _ = entrar("escritorio", "senha-vendas-1")
    assert r.status_code == 401 and "Aguarde" in r.get_json()["erro"]
    api.auth._tentativas.clear()
    r, _ = entrar("escritorio", "senha-vendas-1")
    assert r.status_code == 200


def test_logout(cliente, vendas):
    assert cliente.post("/api/auth/logout", headers=vendas).status_code == 200
    assert cliente.get("/api/auth/eu", headers=vendas).status_code == 401


def test_usuario_desativado_perde_acesso(api, cliente, entrar, vendas):
    api.auth.definir_ativo("escritorio", False)
    assert cliente.get("/api/auth/eu", headers=vendas).status_code == 401
    r, _ = entrar("escritorio", "senha-vendas-1")
    assert r.status_code == 401


def test_troca_de_senha_derruba_sessoes(api, cliente, dev):
    api.auth.alterar_senha("Fernando", "senha-nova-123")
    assert cliente.get("/api/auth/eu", headers=dev).status_code == 401


def test_script_de_terminal_lista_usuarios(api):
    api.auth.criar_usuario("Fernando", "fernando", "senha-dev-9", "dev")
    api.auth.criar_usuario("Escritório", "escritorio", "senha-vendas-1", "vendas")
    api.auth.definir_ativo("escritorio", False)
    pasta = Path(api.BASE_DIR)
    saida = subprocess.run([sys.executable, "gerenciar_usuarios.py", "listar"], cwd=pasta,
                           capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert saida.returncode == 0, saida.stderr
    assert "FERNANDO" in saida.stdout and "INATIVO" in saida.stdout
