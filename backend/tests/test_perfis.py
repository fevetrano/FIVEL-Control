"""O que cada perfil pode ver e fazer: Dev (tudo + usuários), Admin (tudo menos usuários), Vendas."""
import pytest

from simulador import FakeFirebird, usar_firebird

PEDIDOS = [{
    "id": "1", "id_pedido": 1, "cliente": "Cliente X", "status": "Pendente",
    "peso_total_kg": 10.0, "peso_total_pedido_bruto": 20.0, "faturamento_total": 99.0,
    "itens": [{"id_numof": 5, "statusOF": "Produção", "qtd_prog": 100, "peso_of": 7.0,
               "peso_restante": 3.0, "preco_unitario": 1.5}],
}]
CAMPOS_OCULTOS = ("peso_total_kg", "faturamento_total", "peso_of", "peso_restante",
                  "preco_unitario", "peso_total_pedido_bruto")


@pytest.fixture
def pedidos_simulados(api, monkeypatch):
    monkeypatch.setattr(api, "get_pedidos_processados",
                        lambda *a, **k: [dict(p, itens=[dict(i) for i in p["itens"]]) for p in PEDIDOS])


# --- Vendas ---
def test_vendas_ve_pedidos_sem_peso_nem_valor(cliente, vendas, admin, pedidos_simulados):
    d = cliente.get("/api/pedidos", headers=vendas).get_json()
    assert d[0]["cliente"] == "Cliente X"
    assert not any(campo in str(d) for campo in CAMPOS_OCULTOS)
    assert d[0]["itens"][0]["statusOF"] == "Produção" and d[0]["itens"][0]["qtd_prog"] == 100

    d = cliente.get("/api/pedidos", headers=admin).get_json()
    assert d[0]["faturamento_total"] == 99.0 and d[0]["itens"][0]["preco_unitario"] == 1.5


def test_vendas_ve_orcamentos_com_preco_sem_peso(api, cliente, vendas, monkeypatch):
    usar_firebird(monkeypatch, api, FakeFirebird([("FROM ORCAMENT o", [])]))
    assert cliente.get("/api/orcamentos", headers=vendas).status_code == 200
    d = api.ocultar_valores([{"total_geral": 10.0, "total_peso": 5.0, "itens": [{"vl_unit": 1.0, "vl_tot": 2.0}]}])
    assert d == [{"total_geral": 10.0, "itens": [{"vl_unit": 1.0, "vl_tot": 2.0}]}]


@pytest.mark.parametrize("metodo, rota", [
    ("get", "/api/compras"), ("get", "/api/estoque"), ("get", "/api/resumo/dashboard"),
    ("get", "/api/calendario_pesos"), ("put", "/api/compras/1/baixa"), ("get", "/api/geocode"),
    ("get", "/api/usuarios"), ("post", "/api/usuarios"), ("put", "/api/pedidos/status-lote"),
])
def test_vendas_bloqueado(cliente, vendas, metodo, rota):
    assert getattr(cliente, metodo)(rota, headers=vendas, json={}).status_code == 403


def test_vendas_pode_alterar(cliente, vendas, pedidos_simulados):
    assert cliente.put("/api/pedidos/1/itens/5/status", headers=vendas, json={"status": "Pronto"}).status_code == 200
    assert cliente.put("/api/pedidos/1/status", headers=vendas, json={"status": "Faturada"}).status_code == 200
    assert cliente.put("/api/orcamentos/1/nota", headers=vendas, json={"anotacao": "ligar"}).status_code == 200
    assert cliente.post("/api/comercial/clientes/9/ignorar", headers=vendas, json={"ignorar": True}).status_code == 200


# --- Admin ---
def test_admin_usa_tudo_menos_usuarios(cliente, admin, pedidos_simulados):
    assert cliente.get("/api/estoque", headers=admin).status_code == 200
    assert cliente.put("/api/pedidos/1/itens/5/status", headers=admin, json={"status": "Pronto"}).status_code == 200
    assert "faturamento_total" in str(cliente.get("/api/pedidos", headers=admin).get_json())
    assert cliente.get("/api/usuarios", headers=admin).status_code == 403
    novo = {"nome": "X", "login": "x", "senha": "12345", "perfil": "dev"}
    assert cliente.post("/api/usuarios", headers=admin, json=novo).status_code == 403
    assert cliente.put("/api/usuarios/FERNANDO", headers=admin, json={"senha": "abcd"}).status_code == 403


# --- Dev ---
def test_dev_gerencia_usuarios(api, cliente, entrar, dev):
    novo = {"nome": "Maria", "login": "Maria", "senha": "senha-maria-1", "perfil": "vendas"}
    assert cliente.post("/api/usuarios", headers=dev, json=novo).status_code == 201
    curta = {"nome": "A", "login": "a", "senha": "1", "perfil": "vendas"}
    assert cliente.post("/api/usuarios", headers=dev, json=curta).status_code == 400

    lista = cliente.get("/api/usuarios", headers=dev).get_json()
    assert any(u["login"] == "MARIA" for u in lista) and "senha_hash" not in str(lista)

    assert cliente.put("/api/usuarios/maria", headers=dev, json={"senha": "outra-senha-9"}).status_code == 200
    r, _ = entrar("maria", "outra-senha-9")
    assert r.status_code == 200

    assert cliente.put("/api/usuarios/maria", headers=dev, json={"perfil": "admin"}).status_code == 200
    assert [u["perfil"] for u in api.auth.listar_usuarios() if u["login"] == "MARIA"] == ["admin"]
    assert cliente.put("/api/usuarios/MARIA", headers=dev, json={"perfil": "chefe"}).status_code == 400


def test_login_novo_e_gravado_em_maiusculas(api, cliente, dev):
    novo = {"nome": "Teste", "login": "teste minusculo", "senha": "abcd", "perfil": "vendas"}
    assert cliente.post("/api/usuarios", headers=dev, json=novo).status_code == 201
    assert any(u["login"] == "TESTE MINUSCULO" for u in api.auth.listar_usuarios())


def test_dev_nao_desativa_nem_rebaixa_a_si_mesmo(cliente, dev):
    assert cliente.put("/api/usuarios/fernando", headers=dev, json={"ativo": False}).status_code == 400
    assert cliente.put("/api/usuarios/FERNANDO", headers=dev, json={"perfil": "admin"}).status_code == 400


# --- Comercial ---
def test_recorrencia_filtra_empresa_bloqueados_e_desativados(api, cliente, admin, monkeypatch):
    fb = usar_firebird(monkeypatch, api, FakeFirebird([("FROM CLIENTES c", [])]))
    cliente.get("/api/comercial/recorrencia", headers=admin)
    sql = fb.sqls("FROM CLIENTES c")[0]
    assert "ID_EMPRESA IN (1, 2)" in sql and "PEDIDO_BLOQUEADO" in sql and "p.DESATIVADO" in sql
