import os
import json
import traceback
import threading
from datetime import date, datetime
from dotenv import load_dotenv
import fdb
from flask import Flask, jsonify, request
from flask_cors import CORS

# --- CARREGA O CAMINHO ABSOLUTO DA DLL E SUAS DEPENDÊNCIAS ---
caminho_dll = os.path.abspath("fbclient.dll")

if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(os.path.dirname(caminho_dll))
    except Exception as e:
        print(f"Aviso ao adicionar diretório DLL: {e}")

try:
    fdb.load_api(caminho_dll)
except Exception as e:
    print(f"Aviso ao carregar DLL do Firebird: {e}")

load_dotenv()

app = Flask(__name__)
CORS(app)


# --- SISTEMA DE ARQUIVO LOCAL PARA STATUS (COM PROTEÇÃO DE THREAD) ---
KANBAN_FILE = "kanban_status.json"
json_lock = threading.Lock()


def carregar_kanban_local():
    with json_lock:
        if os.path.exists(KANBAN_FILE):
            try:
                with open(KANBAN_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"pedidos": {}, "ofs": {}}


def salvar_kanban_local(dados):
    with json_lock:
        with open(KANBAN_FILE, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=4)


# --- FUNÇÃO DE CONEXÃO COM O FIREBIRD ---
def get_db_connection():
    return fdb.connect(
        host=os.getenv("FIREBIRD_HOST"),
        database=os.getenv("FIREBIRD_DATABASE"),
        user=os.getenv("FIREBIRD_USER"),
        password=os.getenv("FIREBIRD_PASSWORD"),
        port=int(os.getenv("FIREBIRD_PORT", 3050)),
        charset="NONE",
    )


# --- FUNÇÕES AUXILIARES ---
def limpar_texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, bytes):
        try:
            return valor.decode("latin-1", errors="replace").strip()
        except Exception:
            return str(valor).strip()
    return str(valor).strip()


def format_date_safe(dt):
    if not dt:
        return ""
    if isinstance(dt, (datetime, date)):
        return dt.strftime("%d/%m/%Y")
    return str(dt)


def build_of_db_status_map(cur):
    cur.execute("""
        SELECT co.ID_NUMOF, c.STATUS, c.DATA_RECEBIDA
        FROM OC_CHAPA_OF co
        JOIN OC_CHAPA c ON co.ID_ORDCOMPRA = c.ID_ORDCOMPRA
    """)
    of_status_db = {}
    for row in cur.fetchall():
        if not row[0]:
            continue
        id_of = str(row[0])
        status_oc = limpar_texto(row[1]).upper()
        data_rec = row[2]
        is_recebida = status_oc == "RECEBIDA" or data_rec is not None

        if id_of not in of_status_db:
            of_status_db[id_of] = "Produção" if is_recebida else "Compras"
        else:
            if not is_recebida:
                of_status_db[id_of] = "Compras"
    return of_status_db


# --- ROTAS DA API ---


@app.route("/api/pedidos", methods=["GET"])
def obter_pedidos():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        of_status_db = build_of_db_status_map(cur)
        kanban_local = carregar_kanban_local()
        status_pedidos_local = kanban_local.get("pedidos", {})
        status_ofs_local = kanban_local.get("ofs", {})

        query = """
            SELECT 
                p.ID_NUMPED AS ID_PEDIDO,
                p.PEDIDO_CLIENTE,
                p.EMISSAO,
                p.DATA_ENTREGA AS PRAZO,
                p.TOTAL_PESO AS PESO_TOTAL_PEDIDO,
                p.TOTAL_GERAL,
                c.NOME AS CLIENTE_RAZAO,
                COALESCE(c.GUERRA, c.NOME) AS CLIENTE_FANTASIA,
                COALESCE(NULLIF(TRIM(c.ENT_CIDADE), ''), c.CIDADE) AS CIDADE,
                COALESCE(NULLIF(TRIM(c.ENT_ENDERECO), ''), c.ENDERECO) AS ENDERECO,
                COALESCE(c.ENT_NUMERO, c.NUMERO) AS NUMERO,
                COALESCE(NULLIF(TRIM(c.ENT_BAIRRO), ''), c.BAIRRO) AS BAIRRO,
                i.ID_PRODUTO,
                i.REFERENCIA,
                i.QUANT AS QUANTIDADE,
                i.PESO_TOT AS PESO_ITEM,
                i.VLUNIT AS PRECO_UNITARIO,
                i.FECHA,
                o.ID_NUMOF
            FROM PEDIDOS p
            LEFT JOIN CLIENTES c ON p.ID_CLIENTE = c.ID_CLIENTE
            LEFT JOIN PEDITEM i ON p.ID_NUMPED = i.ID_NUMPED
            LEFT JOIN ORDFAB o ON (o.ID_NUMPED = i.ID_NUMPED AND o.ID_PRODUTO = i.ID_PRODUTO)
            WHERE p.EMISSAO >= '2026-07-01'
              AND NOT EXISTS (
                  SELECT 1 FROM FISCAL f WHERE f.ID_NUMPED = p.ID_NUMPED
              )
            ORDER BY p.ID_NUMPED DESC;
        """

        cur.execute(query)
        colunas = [desc[0].lower() for desc in cur.description]
        registros = cur.fetchall()

        pedidos_map = {}
        hoje = datetime.now().date()

        for reg in registros:
            row = dict(zip(colunas, reg))
            if not row.get("id_pedido"):
                continue

            id_ped = str(row["id_pedido"])

            if id_ped not in pedidos_map:
                dt_emissao = row.get("emissao")
                data_emissao_formatada = format_date_safe(dt_emissao)
                raw_emissao_str = (
                    dt_emissao.strftime("%Y-%m-%d")
                    if isinstance(dt_emissao, (datetime, date))
                    else str(dt_emissao or "")
                )

                dt_entrega = row.get("prazo")
                data_entrega_formatada = ""
                raw_entrega_str = ""
                dias_restantes = 999999

                if dt_entrega:
                    try:
                        if isinstance(dt_entrega, datetime):
                            dt_entrega_date = dt_entrega.date()
                        elif isinstance(dt_entrega, date):
                            dt_entrega_date = dt_entrega
                        else:
                            dt_entrega_date = None

                        if dt_entrega_date:
                            data_entrega_formatada = dt_entrega_date.strftime(
                                "%d/%m/%Y"
                            )
                            raw_entrega_str = dt_entrega_date.strftime("%Y-%m-%d")
                            dias_restantes = (dt_entrega_date - hoje).days
                    except Exception:
                        pass

                peso_tot_kg = float(row.get("peso_total_pedido") or 0.0)
                faturamento_tot = float(row.get("total_geral") or 0.0)

                cliente_fantasia = limpar_texto(row.get("cliente_fantasia"))
                cliente_razao = limpar_texto(row.get("cliente_razao"))
                cidade = limpar_texto(row.get("cidade"))

                partes_end = [
                    limpar_texto(row.get("endereco")),
                    str(row.get("numero") or ""),
                    limpar_texto(row.get("bairro")),
                ]
                endereco_comp = ", ".join([p for p in partes_end if p])

                status_pedido = status_pedidos_local.get(id_ped, "Pendente")

                pedidos_map[id_ped] = {
                    "id": id_ped,
                    "id_pedido": int(id_ped),
                    "pedido_cliente": limpar_texto(row.get("pedido_cliente")),
                    "cliente": cliente_fantasia or cliente_razao or "Cliente Sem Nome",
                    "cidade_bloco": cidade,
                    "endereco_completo": endereco_comp,
                    "status": status_pedido,
                    "peso_total_kg": round(peso_tot_kg, 2),
                    "faturamento_total": round(faturamento_tot, 2),
                    "data_emissao": data_emissao_formatada,
                    "raw_emissao": raw_emissao_str,
                    "data_entrega": data_entrega_formatada,
                    "raw_entrega": raw_entrega_str,
                    "dias_restantes": (
                        dias_restantes if dias_restantes != 999999 else None
                    ),
                    "total_itens": 0,
                    "itens": [],
                }

            if row.get("id_produto") or row.get("id_numof"):
                id_of_val = row.get("id_numof")
                id_of_str = (
                    str(id_of_val)
                    if id_of_val is not None
                    else f"ITEM-{len(pedidos_map[id_ped]['itens']) + 1}"
                )
                fecha_val = limpar_texto(row.get("fecha")).upper()

                status_of = status_ofs_local.get(id_of_str)

                if not status_of:
                    if fecha_val in ["P", "S", "1", "TRUE", "SIM", "OK", "PRONTO"]:
                        status_of = "Pronto"
                    else:
                        status_of = of_status_db.get(id_of_str, "Pendente")

                concluido_bool = status_of == "Pronto"

                pedidos_map[id_ped]["itens"].append(
                    {
                        "id_numof": id_of_val,
                        "id_produto": limpar_texto(row.get("id_produto")),
                        "referencia": limpar_texto(row.get("referencia")),
                        "quantidade": float(row.get("quantidade") or 0.0),
                        "peso_item": float(row.get("peso_item") or 0.0),
                        "preco_unitario": float(row.get("preco_unitario") or 0.0),
                        "fecha": limpar_texto(row.get("fecha")),
                        "concluido": concluido_bool,
                        "statusOF": status_of,
                    }
                )
                pedidos_map[id_ped]["total_itens"] = len(pedidos_map[id_ped]["itens"])

        lista_pedidos = list(pedidos_map.values())

        for pedido in lista_pedidos:
            if len(pedido["itens"]) > 0 and pedido["status"] != "Pronto":
                todas_concluidas = all(
                    item.get("concluido", False) for item in pedido["itens"]
                )
                if todas_concluidas:
                    pedido["status"] = "Pronto"

        ordenar_por = request.args.get("ordenar_por", "id_pedido").lower()
        ordem = request.args.get("ordem", "desc").lower()
        reverse_bool = ordem == "desc"

        if ordenar_por in ["id_pedido", "id", "numero"]:
            lista_pedidos.sort(key=lambda x: x["id_pedido"], reverse=reverse_bool)
        elif ordenar_por in ["emissao", "data_emissao"]:
            lista_pedidos.sort(key=lambda x: x["raw_emissao"], reverse=reverse_bool)
        elif ordenar_por in ["data_entrega", "entrega"]:
            lista_pedidos.sort(key=lambda x: x["raw_entrega"], reverse=reverse_bool)
        elif ordenar_por in ["prazo", "dias_restantes"]:
            lista_pedidos.sort(
                key=lambda x: (
                    x["dias_restantes"] if x["dias_restantes"] is not None else 999999
                ),
                reverse=reverse_bool,
            )

        return jsonify(lista_pedidos), 200

    except Exception as e:
        print("\n" + "=" * 50)
        print("ERRO OCORRIDO NA CONSULTA AO FIREBIRD:")
        traceback.print_exc()
        print("=" * 50 + "\n")
        return jsonify({"erro": f"Erro ao consultar Firebird: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/compras", methods=["GET"])
def obter_compras():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        of_status_db = build_of_db_status_map(cur)
        kanban_local = carregar_kanban_local()
        status_ofs_local = kanban_local.get("ofs", {})

        query = """
            SELECT 
                c.ID_ORDCOMPRA, c.EMISSAO, c.DATA_ENTREGA, c.NOME_FORNECEDOR, 
                c.TOTAL_KG, c.TOTAL_GERAL, c.STATUS, c.DATA_RECEBIDA,
                ci.ITEM, ci.QUANT AS QUANT_CHAPA, ci.PESO AS PESO_CHAPA, ci.VLTOT,
                co.ID_NUMOF, co.NOME AS CLIENTE, co.QUANT AS QUANT_OF,
                p.REFERENCIA, p.FECHA
            FROM OC_CHAPA c
            LEFT JOIN OC_CHAPA_ITEM ci ON c.ID_ORDCOMPRA = ci.ID_ORDCOMPRA
            LEFT JOIN OC_CHAPA_OF co ON c.ID_ORDCOMPRA = co.ID_ORDCOMPRA AND ci.ITEM = co.ITEM
            LEFT JOIN ORDFAB o ON o.ID_NUMOF = co.ID_NUMOF
            LEFT JOIN PEDITEM p ON p.ID_NUMPED = o.ID_NUMPED AND p.ID_PRODUTO = o.ID_PRODUTO
            WHERE c.ID_ORDCOMPRA >= 1863
            ORDER BY c.ID_ORDCOMPRA DESC
        """

        cur.execute(query)
        colunas = [desc[0].lower() for desc in cur.description]
        registros = cur.fetchall()

        compras_map = {}

        for reg in registros:
            row = dict(zip(colunas, reg))
            id_compra = str(row.get("id_ordcompra"))

            if not id_compra or id_compra == "None":
                continue

            if id_compra not in compras_map:
                compras_map[id_compra] = {
                    "idCompra": row.get("id_ordcompra"),
                    "dataEmissao": format_date_safe(row.get("emissao")),
                    "dataPrevisao": format_date_safe(row.get("data_entrega")),
                    "fornecedor": limpar_texto(row.get("nome_fornecedor")),
                    "pesoTotalKg": float(row.get("total_kg") or 0.0),
                    "valorTotal": float(row.get("total_geral") or 0.0),
                    "status": limpar_texto(row.get("status")),
                    "dataRecebida": format_date_safe(row.get("data_recebida")),
                    "itens_map": {},
                    "soma_itens_kg": 0.0,
                    "soma_itens_vltot": 0.0,
                }

            id_item = row.get("item")
            id_of = row.get("id_numof")

            if id_item is not None:
                id_item_str = str(id_item)
                if id_item_str not in compras_map[id_compra]["itens_map"]:
                    peso_item_chapa = float(row.get("peso_chapa") or 0.0)
                    vltot_item = float(row.get("vltot") or 0.0)

                    compras_map[id_compra]["itens_map"][id_item_str] = {
                        "item": id_item,
                        "quantidadeChapa": float(row.get("quant_chapa") or 0.0),
                        "pesoChapa": peso_item_chapa,
                        "vltot": vltot_item,
                        "ofs": [],
                    }
                    compras_map[id_compra]["soma_itens_kg"] += peso_item_chapa
                    compras_map[id_compra]["soma_itens_vltot"] += vltot_item

                if id_of:
                    id_of_str = str(id_of)
                    status_of = status_ofs_local.get(id_of_str)

                    if not status_of:
                        fecha_of = limpar_texto(row.get("fecha")).upper()
                        if fecha_of in ["P", "S", "1", "TRUE", "SIM", "OK", "PRONTO"]:
                            status_of = "Pronto"
                        else:
                            status_of = of_status_db.get(id_of_str, "Pendente")

                    compras_map[id_compra]["itens_map"][id_item_str]["ofs"].append(
                        {
                            "idOF": id_of,
                            "cliente": limpar_texto(row.get("cliente")),
                            "quantOF": float(row.get("quant_of") or 0.0),
                            "referencia": limpar_texto(row.get("referencia"))
                            or f"OF #{id_of}",
                            "statusOF": status_of,
                        }
                    )

        for comp in compras_map.values():
            comp["itens"] = list(comp["itens_map"].values())
            if comp["pesoTotalKg"] == 0.0:
                comp["pesoTotalKg"] = round(comp["soma_itens_kg"], 2)
            if comp["valorTotal"] == 0.0:
                comp["valorTotal"] = round(comp["soma_itens_vltot"], 2)

            del comp["itens_map"], comp["soma_itens_kg"], comp["soma_itens_vltot"]

        return jsonify(list(compras_map.values())), 200

    except Exception as e:
        print("ERRO AO CARREGAR COMPRAS:", str(e))
        traceback.print_exc()
        return jsonify({"erro": f"Erro ao consultar Firebird: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/compras/<int:id_compra>/baixa", methods=["PUT"])
def dar_baixa_compra(id_compra):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "UPDATE OC_CHAPA SET STATUS = 'RECEBIDA', DATA_RECEBIDA = 'TODAY' WHERE ID_ORDCOMPRA = ?",
            (id_compra,),
        )

        cur.execute(
            "SELECT DISTINCT ID_NUMOF FROM OC_CHAPA_OF WHERE ID_ORDCOMPRA = ?",
            (id_compra,),
        )
        ofs = cur.fetchall()

        if ofs:
            kanban_local = carregar_kanban_local()
            for row in ofs:
                if row[0]:
                    kanban_local["ofs"][str(row[0])] = "Produção"
            salvar_kanban_local(kanban_local)

        conn.commit()
        return (
            jsonify(
                {"sucesso": True, "mensagem": "Baixa efetuada com sucesso no Firebird."}
            ),
            200,
        )

    except Exception as e:
        if conn:
            conn.rollback()
        print("ERRO AO DAR BAIXA NA COMPRA:", str(e))
        traceback.print_exc()
        return jsonify({"erro": f"Erro ao atualizar baixa: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/pedidos/<int:id_pedido>/status", methods=["PUT"])
def atualizar_status_unidade(id_pedido):
    try:
        dados = request.get_json() or {}
        novo_status = dados.get("status", "Pendente")

        kanban_local = carregar_kanban_local()
        kanban_local["pedidos"][str(id_pedido)] = novo_status
        salvar_kanban_local(kanban_local)

        return (
            jsonify({"sucesso": True, "id_pedido": id_pedido, "status": novo_status}),
            200,
        )
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/pedidos/<int:id_pedido>/itens/<path:id_of>/status", methods=["PUT"])
def atualizar_status_of(id_pedido, id_of):
    try:
        dados = request.get_json() or {}
        novo_status = dados.get("status", "Pendente")

        kanban_local = carregar_kanban_local()
        kanban_local["ofs"][str(id_of)] = novo_status
        salvar_kanban_local(kanban_local)

        return jsonify({"sucesso": True, "id_of": id_of, "status": novo_status}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/ofs/status-rapido", methods=["PUT"])
def atualizar_status_rapido_of():
    try:
        dados = request.get_json() or {}
        id_of = dados.get("id_of")
        novo_status = dados.get("status")

        if not id_of or not novo_status:
            return jsonify({"erro": "ID da OF e Status são obrigatórios."}), 400

        kanban_local = carregar_kanban_local()
        kanban_local["ofs"][str(id_of)] = novo_status
        salvar_kanban_local(kanban_local)

        return jsonify({"sucesso": True, "id_of": id_of, "status": novo_status}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/pedidos/status-lote", methods=["PUT"])
def atualizar_status_lote():
    try:
        dados = request.get_json() or {}
        ids = dados.get("ids", [])
        novo_status = dados.get("status", "Pendente")

        if not ids:
            return jsonify({"erro": "Nenhum ID fornecido"}), 400

        kanban_local = carregar_kanban_local()
        for id_ped in ids:
            kanban_local["pedidos"][str(id_ped)] = novo_status
        salvar_kanban_local(kanban_local)

        return (
            jsonify({"sucesso": True, "mensagem": f"{len(ids)} pedidos atualizados."}),
            200,
        )

    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- ROTAS DE RESUMO E DASHBOARD ---


@app.route("/api/resumo/pedidos", methods=["GET"])
def obter_resumo_pedidos():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        query = """
            SELECT 
                COALESCE(SUM(p.TOTAL_GERAL), 0) AS FATURAMENTO_ACUMULADO,
                COALESCE(SUM(p.TOTAL_PESO), 0) AS PESO_TOTAL_KG,
                COUNT(p.ID_NUMPED) AS PEDIDOS_ATIVOS
            FROM PEDIDOS p
            WHERE p.EMISSAO >= '2026-07-01'
              AND NOT EXISTS (
                  SELECT 1 FROM FISCAL f WHERE f.ID_NUMPED = p.ID_NUMPED
              )
        """
        cur.execute(query)
        res = cur.fetchone()

        fat_acumulado = float(res[0] or 0.0)
        peso_total_kg = float(res[1] or 0.0)
        pedidos_ativos = int(res[2] or 0)

        return (
            jsonify(
                {
                    "faturamento_acumulado": round(fat_acumulado, 2),
                    "volume_carga_total_kg": round(peso_total_kg, 2),
                    "volume_carga_total_ton": round(peso_total_kg / 1000, 2),
                    "pedidos_ativos": pedidos_ativos,
                }
            ),
            200,
        )
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/resumo/mapa", methods=["GET"])
def obter_resumo_mapa():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        query_entregue_mes = """
            SELECT COALESCE(SUM(f.OI_BRUTO), 0) AS PESO_ENTREGUE_MES_KG
            FROM FISCAL f
            WHERE f.EMISS_ANO = ?
              AND f.EMISS_MES = ?
              AND f.ID_EMPRESA IN (1, 2)
              AND (f.CANCELADA IS NULL OR f.CANCELADA <> 'S')
              AND (f.IGNORAR_PESO IS NULL OR f.IGNORAR_PESO <> 'S')
        """
        hoje = datetime.now()
        cur.execute(query_entregue_mes, (hoje.year, hoje.month))
        res_entregue = cur.fetchone()
        peso_entregue_mes_kg = float(res_entregue[0] or 0.0)

        return (
            jsonify(
                {
                    "faturamento_pronto": 0,
                    "peso_pronto_kg": 0,
                    "peso_pronto_ton": 0,
                    "peso_entregue_mes_kg": round(peso_entregue_mes_kg, 2),
                    "peso_entregue_mes_ton": round(peso_entregue_mes_kg / 1000, 2),
                }
            ),
            200,
        )
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/resumo/dashboard", methods=["GET"])
def obter_resumo_dashboard():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        hoje = datetime.now()
        ano_atual = hoje.year
        mes_atual = hoje.month

        cur.execute(
            "SELECT COALESCE(SUM(TOTNOTA),0), COALESCE(SUM(OI_BRUTO),0), COUNT(NF) FROM FISCAL WHERE EMISS_ANO = ? AND EMISS_MES = ? AND ID_EMPRESA IN (1, 2) AND (CANCELADA IS NULL OR CANCELADA <> 'S') AND (IGNORAR_PESO IS NULL OR IGNORAR_PESO <> 'S')",
            (ano_atual, mes_atual),
        )
        res_fiscal = cur.fetchone()

        cur.execute(
            "SELECT COALESCE(SUM(TOTAL_GERAL),0), COALESCE(SUM(TOTAL_PESO),0), COUNT(ID_NUMPED) FROM PEDIDOS p WHERE EMISSAO >= '2026-07-01' AND NOT EXISTS (SELECT 1 FROM FISCAL f WHERE f.ID_NUMPED = p.ID_NUMPED)"
        )
        res_carteira = cur.fetchone()

        of_status_db = build_of_db_status_map(cur)
        kanban_local = carregar_kanban_local()
        status_ofs_local = kanban_local.get("ofs", {})

        cur.execute(
            "SELECT o.ID_NUMOF, p.FECHA FROM ORDFAB o JOIN PEDIDOS ped ON ped.ID_NUMPED = o.ID_NUMPED JOIN PEDITEM p ON p.ID_NUMPED = o.ID_NUMPED AND p.ID_PRODUTO = o.ID_PRODUTO WHERE ped.EMISSAO >= '2026-07-01' AND NOT EXISTS (SELECT 1 FROM FISCAL f WHERE f.ID_NUMPED = ped.ID_NUMPED)"
        )
        todas_ofs = cur.fetchall()

        kanban_distrib = {"Pendente": 0, "Compras": 0, "Produção": 0, "Pronto": 0}
        for row in todas_ofs:
            of_id = str(row[0])
            fecha_val = limpar_texto(row[1]).upper()

            status = status_ofs_local.get(of_id)
            if not status:
                if fecha_val in ["P", "S", "1", "TRUE", "SIM", "OK", "PRONTO"]:
                    status = "Pronto"
                else:
                    status = of_status_db.get(of_id, "Pendente")

            if status in kanban_distrib:
                kanban_distrib[status] += 1
            else:
                kanban_distrib["Pendente"] += 1

        return (
            jsonify(
                {
                    "faturamento_mes": round(float(res_fiscal[0] or 0.0), 2),
                    "peso_mes_kg": round(float(res_fiscal[1] or 0.0), 2),
                    "total_nfs_mes": int(res_fiscal[2] or 0),
                    "faturamento_carteira": round(float(res_carteira[0] or 0.0), 2),
                    "peso_carteira_kg": round(float(res_carteira[1] or 0.0), 2),
                    "total_pedidos_carteira": int(res_carteira[2] or 0),
                    "distribuicao_kanban": kanban_distrib,
                    "mes_referencia": f"{mes_atual:02d}/{ano_atual}",
                }
            ),
            200,
        )

    except Exception as e:
        print("ERRO AO GERAR DASHBOARD:", str(e))
        traceback.print_exc()
        return jsonify({"erro": f"Erro ao consultar Firebird: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
