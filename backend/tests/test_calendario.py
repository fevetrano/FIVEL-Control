"""Calendário de pesos e fechamento mensal automático."""
from datetime import date, datetime

from simulador import FakeFirebird, data_fixa, usar_firebird


def test_valores_iniciais_do_historico(api):
    out = api.ler_fechamento(2026, 10)
    nov = api.ler_fechamento(2026, 11)
    assert out["saida_kg"] == 32407.89 and out["saida_origem"] == "manual"
    assert nov["aberto_inicio_kg"] == 9957.09 and nov["aberto_origem"] == "manual"


def test_fechamento_gravado_nunca_e_sobrescrito(api):
    api.registrar_fechamento(2026, 11, "aberto", 1.0, "automatico")
    assert api.ler_fechamento(2026, 11)["aberto_inicio_kg"] == 9957.09
    api.init_sqlite_db()
    assert api.ler_fechamento(2026, 10)["saida_kg"] == 32407.89


def test_calendario_de_novembro(api, cliente, admin, monkeypatch):
    fb = usar_firebird(monkeypatch, api, FakeFirebird([
        ("FROM PEDIDOS p", [(date(2026, 11, 3), 1000.0), (datetime(2026, 11, 3, 10, 0), 500.0),
                            (date(2026, 11, 5), None), (date(2026, 11, 30), 250.5)]),
    ]))
    data_fixa(monkeypatch, api, date(2026, 11, 5))
    r = cliente.get("/api/calendario_pesos?mes=11&ano=2026", headers=admin)
    d = r.get_json()
    assert r.status_code == 200
    assert d["dias_calendario"]["3"] == 1500.0
    assert d["dias_calendario"]["30"] == 250.5
    assert d["entrada_mes_kg"] == 1750.5
    assert d["saida_mes_anterior_kg"] == 32407.89 and d["saida_registrada"] is True
    assert d["peso_entrada_kg"] == 9957.09
    assert abs(d["total_mes_kg"] - (9957.09 + 1750.5)) < 1e-6
    sql = fb.sqls("FROM PEDIDOS p")[0]
    assert "NOT IN (15931)" in sql and "CANCELADO" in sql


def test_mes_anterior_ao_historico_calcula_saida_no_erp(api, cliente, admin, monkeypatch):
    usar_firebird(monkeypatch, api, FakeFirebird([
        ("FROM FISCAL", [(1000.0,)]),
        ("FROM RECEBIMENTOS r", [(234.5,)]),
        ("FROM PEDIDOS p", []),
    ]))
    d = cliente.get("/api/calendario_pesos?mes=10&ano=2026", headers=admin).get_json()
    assert d["saida_mes_anterior_kg"] == 1234.5 and d["saida_registrada"] is False
    assert d["peso_entrada_kg"] is None and d["total_mes_kg"] is None


def test_mes_invalido(cliente, admin):
    assert cliente.get("/api/calendario_pesos?mes=13&ano=2026", headers=admin).status_code == 400


def test_fechamento_automatico_na_virada_do_mes(api, monkeypatch):
    usar_firebird(monkeypatch, api, FakeFirebird([("FROM FISCAL", [(30000.0,)]), ("FROM RECEBIMENTOS r", [(500.0,)])]))
    monkeypatch.setattr(api, "get_pedidos_processados", lambda *a, **k: [
        {"raw_emissao": "2026-11-20", "status": "Pendente", "peso_total_kg": 4000.0},
        {"raw_emissao": "2026-11-28", "status": "Faturada", "peso_total_kg": 999.0},
        {"raw_emissao": "2026-12-01", "status": "Pendente", "peso_total_kg": 50.0},
        {"raw_emissao": "", "status": "Pendente", "peso_total_kg": 7.0},
    ])
    data_fixa(monkeypatch, api, date(2026, 12, 1))
    api.garantir_fechamentos()
    nov, dez = api.ler_fechamento(2026, 11), api.ler_fechamento(2026, 12)
    assert nov["saida_kg"] == 30500.0 and nov["saida_origem"] == "automatico"
    # Aberto em 01/12 = só pedidos emitidos antes de 01/12 e não faturados
    assert dez["aberto_inicio_kg"] == 4000.0
    assert nov["aberto_inicio_kg"] == 9957.09

    monkeypatch.setattr(api, "get_pedidos_processados",
                        lambda *a, **k: [{"raw_emissao": "2026-11-20", "status": "Pendente", "peso_total_kg": 1.0}])
    api.garantir_fechamentos()
    assert api.ler_fechamento(2026, 12)["aberto_inicio_kg"] == 4000.0, "o fechamento roda uma vez só por mês"


def test_sistema_desligado_por_meses_grava_todos_os_meses(api, monkeypatch):
    usar_firebird(monkeypatch, api, FakeFirebird([("FROM FISCAL", [(10.0,)]), ("FROM RECEBIMENTOS r", [(0.0,)])]))
    monkeypatch.setattr(api, "get_pedidos_processados", lambda *a, **k: [])
    data_fixa(monkeypatch, api, date(2027, 3, 2))
    api.garantir_fechamentos()
    for ano, mes in ((2026, 11), (2026, 12), (2027, 1), (2027, 2)):
        assert api.ler_fechamento(ano, mes)["saida_kg"] == 10.0
