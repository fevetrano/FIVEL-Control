"""Aba Faturados e as NFs/recibos de cada pedido."""
from datetime import date, datetime

from simulador import FakeFirebird


def test_notas_agrupadas_por_pedido(api):
    fb = FakeFirebird([
        # (pedido, NF, emissão, peso)
        ("FROM FISCAL f", [
            (100, 11849, date(2026, 10, 29), 500.0),
            (100, 11800, date(2026, 10, 10), 250.0),      # parcial anterior do mesmo pedido
            (None, 11900, date(2026, 10, 30), 1.0),       # NF sem pedido: ignorada
            (101, 11850, datetime(2026, 10, 29, 9, 0), None),
        ]),
        # (pedido, ID_PF do recibo, emissão, peso)
        ("FROM RECEBIMENTOS r", [
            (100, 77, date(2026, 11, 2), 30.0),
            (102, 78, date(2026, 11, 3), 10.0),
        ]),
    ])
    notas = api.obter_notas_por_pedido(fb.cursor())

    assert sorted(notas) == ["100", "101", "102"]
    p100 = notas["100"]
    assert [(n["tipo"], n["numero"]) for n in p100["notas"]] == [("NF", "11800"), ("NF", "11849"), ("Recibo", "77")]
    assert p100["notas"][1]["data"] == "29/10/2026" and p100["notas"][1]["raw_data"] == "2026-10-29"
    assert p100["peso_kg"] == 780.0, "NFs parciais e recibo somam no peso faturado"
    assert notas["101"]["peso_kg"] == 0.0 and notas["101"]["notas"][0]["raw_data"] == "2026-10-29"
    assert notas["102"]["notas"][0]["tipo"] == "Recibo"

    sql_nf = fb.sqls("FROM FISCAL f")[0]
    sql_recibo = fb.sqls("FROM RECEBIMENTOS r")[0]
    assert "CANCELADA" in sql_nf and "COALESCE(inf.ID_NUMPED, o.ID_NUMPED)" in sql_nf
    assert "TIPOREC = 'RECIBO'" in sql_recibo

    consultas = len(fb.log)
    api.obter_notas_por_pedido(fb.cursor())
    assert len(fb.log) == consultas, "dentro de 30 s usa o cache"


def test_lista_de_faturados(api, cliente, admin, vendas, monkeypatch):
    pedidos = [
        {"id": "1", "id_pedido": 1, "status": "Faturada", "data_ultima_nf": "2026-11-02", "raw_emissao": "2026-10-01",
         "peso_faturado_kg": 5.0, "notas_fiscais": [{"tipo": "NF", "numero": "10"}], "itens": []},
        {"id": "2", "id_pedido": 2, "status": "Pendente", "data_ultima_nf": "2026-11-09", "raw_emissao": "2026-10-02",
         "peso_faturado_kg": 1.0, "notas_fiscais": [], "itens": []},
        {"id": "3", "id_pedido": 3, "status": "Faturada", "data_ultima_nf": "2026-11-09", "raw_emissao": "2026-10-03",
         "peso_faturado_kg": 7.0, "notas_fiscais": [{"tipo": "NF", "numero": "11"}, {"tipo": "NF", "numero": "12"}], "itens": []},
        {"id": "4", "id_pedido": 4, "status": "Faturada", "data_ultima_nf": "", "raw_emissao": "2026-09-01",
         "peso_faturado_kg": 0.0, "notas_fiscais": [], "itens": []},
    ]
    monkeypatch.setattr(api, "get_pedidos_processados",
                        lambda *a, **k: [dict(p) for p in pedidos] if k.get("incluir_liquidadas") else [])

    d = cliente.get("/api/pedidos/faturados", headers=admin).get_json()
    assert [p["id_pedido"] for p in d] == [3, 1, 4], "só Faturada, NF mais recente primeiro"
    assert [n["numero"] for n in d[0]["notas_fiscais"]] == ["11", "12"]

    d = cliente.get("/api/pedidos/faturados", headers=vendas).get_json()
    assert d and d[0]["notas_fiscais"] and "peso_faturado_kg" not in str(d)
