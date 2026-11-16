"""Auditoria, mensagens de erro e CORS."""
import sqlite3
from pathlib import Path

import pytest


def banco(api):
    return sqlite3.connect(api.SQLITE_DB)


def test_auditoria_registra_quem_alterou_sem_guardar_senha(api, cliente, entrar, dev):
    entrar("FERNANDO", "errada")
    r = cliente.put("/api/pedidos/1/itens/5/status", headers=dev, json={"status": "Pronto", "qtd_produzida": 40})
    assert r.status_code == 200
    cliente.put("/api/usuarios/FERNANDO", headers=dev, json={"senha": "outra-senha-9"})

    con = banco(api)
    usuario, acao, detalhes = con.execute(
        "SELECT usuario, acao, detalhes FROM auditoria WHERE acao LIKE 'PUT %itens/5/status%' ORDER BY id DESC").fetchone()
    assert usuario == "FERNANDO" and "Pronto" in detalhes
    assert con.execute("SELECT COUNT(*) FROM auditoria WHERE acao='login_falhou'").fetchone()[0] >= 1
    vazou = con.execute("SELECT COUNT(*) FROM auditoria WHERE detalhes LIKE '%senha-dev-9%' "
                        "OR detalhes LIKE '%outra-senha%' OR detalhes LIKE '%errada%'").fetchone()[0]
    assert vazou == 0


def test_erro_interno_nao_mostra_detalhe_mas_vai_para_o_log(api, cliente, admin, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("SELECT secreto FROM TABELA_INTERNA")

    monkeypatch.setattr(api, "get_pedidos_processados", explode)
    r = cliente.get("/api/pedidos", headers=admin)
    assert r.status_code == 500 and "TABELA_INTERNA" not in r.get_data(as_text=True)
    for h in api.logger.handlers:
        h.flush()
    log = (Path(api.BASE_DIR) / "logs" / "fivel.log").read_text(encoding="utf-8")
    assert "TABELA_INTERNA" in log and "/api/pedidos" in log


def test_rota_api_inexistente(cliente, admin):
    assert cliente.get("/api/nao-existe", headers=admin).status_code == 404


@pytest.mark.parametrize("origem, liberada", [
    ("http://192.168.0.15:5173", True),       # IP da rede local
    ("http://192.168.1.15:3000", True),
    ("http://COMPUTADOR:5173", True),         # nome do computador
    ("https://site-malicioso.com", False),
])
def test_cors(cliente, origem, liberada):
    r = cliente.options("/api/pedidos", headers={"Origin": origem, "Access-Control-Request-Method": "GET"})
    assert (r.headers.get("Access-Control-Allow-Origin") == origem) is liberada
