"""Cada teste roda numa cópia do backend em pasta temporária, com banco SQLite próprio.
O Firebird real e a internet ficam bloqueados: o teste que precisar deles tem de simular."""
import logging
import shutil
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ARQUIVOS = ("api.py", "auth.py", "backup_banco.py", "gerenciar_usuarios.py")
MODULOS = ("api", "auth", "backup_banco")


def _bloqueado(*args, **kwargs):
    raise AssertionError("O teste tentou usar o Firebird real ou a internet; simule a chamada.")


@pytest.fixture
def api(tmp_path, monkeypatch):
    for nome in ARQUIVOS:
        shutil.copy(BACKEND / nome, tmp_path / nome)
    for var in ("FIVEL_BACKUP_DIR", "CORS_ORIGINS", "GOOGLE_MAPS_API_KEY", "FIVEL_PORT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))
    for m in MODULOS:
        sys.modules.pop(m, None)

    import api as modulo

    monkeypatch.setattr(modulo, "get_db_connection", _bloqueado)
    monkeypatch.setattr(modulo.requests, "get", _bloqueado)
    monkeypatch.setattr(modulo.requests, "post", _bloqueado)
    yield modulo

    logger = logging.getLogger("fivel")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    for m in MODULOS:
        sys.modules.pop(m, None)


@pytest.fixture
def cliente(api):
    return api.app.test_client()


@pytest.fixture
def entrar(cliente):
    def _entrar(login, senha):
        r = cliente.post("/api/auth/login", json={"login": login, "senha": senha})
        token = (r.get_json(silent=True) or {}).get("token")
        return r, ({"Authorization": f"Bearer {token}"} if r.status_code == 200 else {})
    return _entrar


@pytest.fixture
def criar_e_entrar(api, entrar):
    def _criar(login, senha, perfil):
        api.auth.criar_usuario(login.title(), login, senha, perfil)
        r, headers = entrar(login, senha)
        assert r.status_code == 200, r.get_json()
        return headers
    return _criar


@pytest.fixture
def dev(criar_e_entrar):
    return criar_e_entrar("FERNANDO", "senha-dev-9", "dev")


@pytest.fixture
def admin(criar_e_entrar):
    return criar_e_entrar("PRIMO", "senha-primo-1", "admin")


@pytest.fixture
def vendas(criar_e_entrar):
    return criar_e_entrar("ESCRITORIO", "senha-vendas-1", "vendas")
