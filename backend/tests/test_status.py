"""Status das OFs, regra dos 90%, baixa de OC e bipador (status rápido)."""
from datetime import date

import pytest

from simulador import FakeFirebird, usar_firebird


def ofs(api):
    return api.carregar_kanban_local()["ofs"]


def test_trocar_status_preserva_quantidade_e_data(api):
    api.safe_update_status("ofs", "1234", "Produção", 500.0)
    data_producao = ofs(api)["1234"]["data_producao"]
    assert data_producao

    api.safe_update_status("ofs", "1234", "Pronto", None)
    assert ofs(api)["1234"]["qtd_produzida"] == 500.0
    assert ofs(api)["1234"]["data_producao"] == data_producao

    api.safe_update_status("ofs", "1234", "Parcial", 300.0)
    assert ofs(api)["1234"]["qtd_produzida"] == 300.0, "quantidade informada substitui a anterior"

    api.safe_update_status_lote("ofs", {"1234": "Produção"})
    assert ofs(api)["1234"]["qtd_produzida"] == 300.0
    assert ofs(api)["1234"]["data_producao"] == data_producao


def test_pendente_nao_grava_data_de_producao(api):
    api.safe_update_status("ofs", "999", "Pendente", None)
    assert ofs(api)["999"]["data_producao"] is None


@pytest.mark.parametrize("manual, banco, total, parcial, esperado", [
    ("Pronto", None, True, False, "Faturada"),      # faturado >= 90% vence o manual
    ("Pronto", None, False, True, "Pronto"),        # faturado parcial: manual vence
    (None, "Produção", False, True, "Parcial"),
    (None, "Compras", False, False, "Compras"),
])
def test_regra_dos_90_por_cento(api, manual, banco, total, parcial, esperado):
    assert api.obter_status_final_of(manual, banco, total, parcial) == esperado


# --- Baixa de OC ---
def fb_baixa(oc, ofs_da_oc):
    return FakeFirebird([
        ("SELECT STATUS, DATA_RECEBIDA FROM OC_CHAPA", [oc] if oc else []),
        ("FROM OC_CHAPA_OF co", ofs_da_oc),
        ("UPDATE OC_CHAPA", []),
    ])


def test_baixa_de_oc_inexistente(api, cliente, admin, monkeypatch):
    usar_firebird(monkeypatch, api, fb_baixa(None, []))
    assert cliente.put("/api/compras/50/baixa", headers=admin).status_code == 404


def test_baixa_de_oc_ja_recebida(api, cliente, admin, monkeypatch):
    fb = usar_firebird(monkeypatch, api, fb_baixa(("RECEBIDA", date(2026, 11, 2)), []))
    r = cliente.put("/api/compras/51/baixa", headers=admin)
    assert r.status_code == 409 and "02/11/2026" in r.get_json()["erro"]
    assert not fb.sqls("UPDATE")


def test_baixa_de_oc_move_so_pendente_e_compras(api, cliente, admin, monkeypatch):
    api.safe_update_status("ofs", "10", "Compras")
    api.safe_update_status("ofs", "11", "Pendente")
    api.safe_update_status("ofs", "12", "Pronto", 80.0)
    api.safe_update_status("ofs", "13", "Parcial")
    api.safe_update_status("ofs", "15", "Faturada")
    # (id da OF, liquidada no Cartmaster)
    fb = usar_firebird(monkeypatch, api, fb_baixa(("ABERTA", None), [
        (10, None), (11, "N"), (12, None), (13, None), (14, "S"), (15, None), (16, None)]))
    r = cliente.put("/api/compras/52/baixa", headers=admin)
    st = ofs(api)
    assert r.status_code == 200
    assert st["10"]["status"] == "Produção" and st["11"]["status"] == "Produção"
    assert st["12"]["status"] == "Pronto" and st["12"]["qtd_produzida"] == 80.0
    assert st["13"]["status"] == "Parcial"
    assert "16" not in st, "OF sem status manual não ganha status manual"
    assert sorted(r.get_json()["avisos"]) == ["OF 14 já está faturada.", "OF 15 já está faturada."]
    assert fb.sqls("UPDATE OC_CHAPA") and fb.commits == 1


# --- Bipador / status rápido ---
def fb_of(linha):
    return FakeFirebird([("FROM ORDFAB WHERE ID_NUMOF", [linha] if linha else [])])


def test_bipador_of_inexistente(api, cliente, admin, monkeypatch):
    usar_firebird(monkeypatch, api, fb_of(None))
    r = cliente.put("/api/ofs/status-rapido", json={"id_of": "777", "status": "Pronto"}, headers=admin)
    assert r.status_code == 404 and "777" in r.get_json()["erro"]
    assert "777" not in ofs(api)


def test_bipador_of_com_letra(cliente, admin):
    r = cliente.put("/api/ofs/status-rapido", json={"id_of": "77a", "status": "Pronto"}, headers=admin)
    assert r.status_code == 400


def test_bipador_of_faturada(api, cliente, admin, monkeypatch):
    usar_firebird(monkeypatch, api, fb_of(("S", None)))
    r = cliente.put("/api/ofs/status-rapido", json={"id_of": "778", "status": "Pronto"}, headers=admin)
    assert r.status_code == 409


def test_bipador_of_valida(api, cliente, admin, monkeypatch):
    usar_firebird(monkeypatch, api, fb_of((None, None)))
    r = cliente.put("/api/ofs/status-rapido", json={"id_of": "779", "status": "Pronto", "qtd_produzida": "120,5"}, headers=admin)
    assert r.status_code == 200
    assert ofs(api)["779"]["qtd_produzida"] == 120.5, "aceita vírgula decimal"
    assert cliente.put("/api/ofs/status-rapido", json={"id_of": "779", "status": "Xyz"}, headers=admin).status_code == 400
    r = cliente.put("/api/ofs/status-rapido", json={"id_of": "779", "status": "Pronto", "qtd_produzida": -1}, headers=admin)
    assert r.status_code == 400


@pytest.mark.parametrize("rota, corpo", [
    ("/api/pedidos/1/itens/779/status", {"status": "qualquer"}),
    ("/api/pedidos/1/status", {"status": "qualquer"}),
    ("/api/pedidos/status-lote", {"ids": [1], "status": "x"}),
])
def test_status_invalido_e_recusado(cliente, admin, rota, corpo):
    assert cliente.put(rota, json=corpo, headers=admin).status_code == 400
