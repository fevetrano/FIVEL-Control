import os
import json
import sqlite3
import traceback
import threading
import time
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


# --- SISTEMA DE BANCO DE DADOS SQLITE LOCAL ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SQLITE_DB = os.path.join(BASE_DIR, "kanban_status.db")
db_lock = threading.Lock()


def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_DB, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_sqlite_db():
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kanban_status (
                categoria TEXT NOT NULL,
                chave TEXT NOT NULL,
                status TEXT NOT NULL,
                data_producao TEXT,
                PRIMARY KEY (categoria, chave)
            )
        """)
        try:
            cur.execute("ALTER TABLE kanban_status ADD COLUMN data_producao TEXT")
        except sqlite3.OperationalError:
            pass

        # Criação da nova tabela para anotações de Orçamentos
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orcamento_notas (
                id_orcamento TEXT PRIMARY KEY,
                anotacao TEXT NOT NULL,
                data_atualizacao TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()


init_sqlite_db()


def carregar_kanban_local():
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        cur.execute("SELECT categoria, chave, status, data_producao FROM kanban_status")
        rows = cur.fetchall()
        conn.close()

        resultado = {"pedidos": {}, "ofs": {}}
        for cat, chave, st, dp in rows:
            if cat in resultado:
                if cat == "ofs":
                    resultado[cat][str(chave)] = {"status": st, "data_producao": dp}
                else:
                    resultado[cat][str(chave)] = st
        return resultado


def safe_update_status(categoria, chave, valor):
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data_prod = agora if valor == 'Produção' else None

        if valor == 'Produção':
            cur.execute("SELECT data_producao FROM kanban_status WHERE categoria=? AND chave=?", (categoria, str(chave)))
            row = cur.fetchone()
            if row and row[0]:
                data_prod = row[0]

        cur.execute(
            "INSERT OR REPLACE INTO kanban_status (categoria, chave, status, data_producao) VALUES (?, ?, ?, ?)",
            (categoria, str(chave), str(valor), data_prod),
        )
        conn.commit()
        conn.close()


def safe_delete_status(categoria, chave):
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM kanban_status WHERE categoria = ? AND chave = ?",
            (categoria, str(chave)),
        )
        conn.commit()
        conn.close()


def safe_update_status_lote(categoria, atualizacoes_dict):
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for chave, valor in atualizacoes_dict.items():
            data_prod = agora if valor == 'Produção' else None
            if valor == 'Produção':
                cur.execute("SELECT data_producao FROM kanban_status WHERE categoria=? AND chave=?", (categoria, str(chave)))
                row = cur.fetchone()
                if row and row[0]:
                    data_prod = row[0]

            cur.execute(
                "INSERT OR REPLACE INTO kanban_status (categoria, chave, status, data_producao) VALUES (?, ?, ?, ?)",
                (categoria, str(chave), str(valor), data_prod),
            )
        conn.commit()
        conn.close()


def get_db_connection():
    return fdb.connect(
        host=os.getenv("FIREBIRD_HOST"),
        database=os.getenv("FIREBIRD_DATABASE"),
        user=os.getenv("FIREBIRD_USER"),
        password=os.getenv("FIREBIRD_PASSWORD"),
        port=int(os.getenv("FIREBIRD_PORT", 3050)),
        charset="NONE",
    )


_of_status_cache = {}
_of_status_cache_time = 0
CACHE_TTL = 5


def invalidar_cache_db():
    global _of_status_cache_time
    _of_status_cache_time = 0


def build_of_db_status_map(cur):
    global _of_status_cache, _of_status_cache_time
    agora = time.time()
    if _of_status_cache and (agora - _of_status_cache_time) < CACHE_TTL:
        return _of_status_cache

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

    _of_status_cache = of_status_db
    _of_status_cache_time = agora
    return _of_status_cache


def obter_status_final_of(status_manual, status_banco, tem_nf=False):
    if tem_nf:
        return "Faturada"
    if status_manual:
        return status_manual
    if status_banco:
        return status_banco
    return "Pendente"


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
                p.ID_NUMPED AS ID_PEDIDO, p.PEDIDO_CLIENTE, p.EMISSAO, p.DATA_ENTREGA AS PRAZO,
                p.TOTAL_PESO AS PESO_TOTAL_PEDIDO, p.TOTAL_GERAL, c.NOME AS CLIENTE_RAZAO,
                COALESCE(c.GUERRA, c.NOME) AS CLIENTE_FANTASIA, COALESCE(NULLIF(TRIM(c.ENT_CIDADE), ''), c.CIDADE) AS CIDADE,
                COALESCE(NULLIF(TRIM(c.ENT_ENDERECO), ''), c.ENDERECO) AS ENDERECO,
                COALESCE(c.ENT_NUMERO, c.NUMERO) AS NUMERO, COALESCE(NULLIF(TRIM(c.ENT_BAIRRO), ''), c.BAIRRO) AS BAIRRO,
                i.ID_PRODUTO, i.REFERENCIA, i.QUANT AS QUANTIDADE, i.PESO_TOT AS PESO_ITEM,
                i.VLUNIT AS PRECO_UNITARIO, i.FECHA, o.ID_NUMOF,
                (SELECT COUNT(1) 
                 FROM ITEMNF inf 
                 JOIN FISCAL f ON (inf.NF = f.NF AND inf.ID_EMPRESA = f.ID_EMPRESA)
                 WHERE inf.ID_NUMOF = o.ID_NUMOF 
                   AND (f.CANCELADA IS NULL OR f.CANCELADA <> 'S')) AS OF_FATURADA,
                i.COMP, i.LARG, i.ALT, i.ID_ONDAFAB AS ONDA_PEDITEM, i.ID_QUALIDFAB AS QUALID_PEDITEM,
                ft.GRAMATURA, ft.FECHAMENTO AS FECHA_FT, ft.ID_ONDAFAB AS ONDA_FT, ft.ID_QUALIDFAB AS QUALID_FT,
                ft.DESCRICAO_COR1, ft.DESCRICAO_COR2, ft.PESO_CONJUNTO
            FROM PEDIDOS p
            LEFT JOIN CLIENTES c ON p.ID_CLIENTE = c.ID_CLIENTE
            LEFT JOIN PEDITEM i ON p.ID_NUMPED = i.ID_NUMPED
            LEFT JOIN ORDFAB o ON (o.ID_NUMPED = i.ID_NUMPED AND o.ID_PRODUTO = i.ID_PRODUTO)
            LEFT JOIN FT ft ON (i.ID_PRODUTO = ft.ID_PRODUTO AND ft.DESATIVADO <> 'S')
            WHERE p.EMISSAO >= '2026-07-01'
              AND p.ID_NUMPED <> 15931
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
                        dt_entrega_date = (
                            dt_entrega.date()
                            if isinstance(dt_entrega, datetime)
                            else dt_entrega if isinstance(dt_entrega, date) else None
                        )
                        if dt_entrega_date:
                            data_entrega_formatada = dt_entrega_date.strftime("%d/%m/%Y")
                            raw_entrega_str = dt_entrega_date.strftime("%Y-%m-%d")
                            dias_restantes = (dt_entrega_date - hoje).days
                    except Exception:
                        pass

                partes_end = [
                    limpar_texto(row.get("endereco")),
                    str(row.get("numero") or ""),
                    limpar_texto(row.get("bairro")),
                ]
                endereco_comp = ", ".join([p for p in partes_end if p])
                cliente_final = (
                    limpar_texto(row.get("cliente_fantasia"))
                    or limpar_texto(row.get("cliente_razao"))
                    or "Cliente Sem Nome"
                )

                pedidos_map[id_ped] = {
                    "id": id_ped,
                    "id_pedido": int(id_ped),
                    "pedido_cliente": limpar_texto(row.get("pedido_cliente")),
                    "cliente": cliente_final,
                    "cidade_bloco": limpar_texto(row.get("cidade")),
                    "endereco_completo": endereco_comp,
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

                of_local = status_ofs_local.get(id_of_str, {})
                status_manual = of_local.get("status") if isinstance(of_local, dict) else None
                data_producao = of_local.get("data_producao") if isinstance(of_local, dict) else None

                status_banco = of_status_db.get(id_of_str)
                of_faturada_no_erp = int(row.get("of_faturada") or 0) > 0

                status_of = obter_status_final_of(
                    status_manual, status_banco, of_faturada_no_erp
                )

                onda = limpar_texto(row.get("onda_ft") or row.get("onda_peditem"))
                qualidade = limpar_texto(row.get("qualid_ft") or row.get("qualid_peditem"))
                gramatura = limpar_texto(row.get("gramatura"))
                fecha_calc = limpar_texto(row.get("fecha_ft") or row.get("fecha"))
                cor1 = limpar_texto(row.get("descricao_cor1"))
                cor2 = limpar_texto(row.get("descricao_cor2"))
                peso_conj = row.get("peso_conjunto")

                pedidos_map[id_ped]["itens"].append(
                    {
                        "id_numof": id_of_val,
                        "id_produto": limpar_texto(row.get("id_produto")),
                        "referencia": limpar_texto(row.get("referencia")),
                        "quantidade": float(row.get("quantidade") or 0.0),
                        "peso_item": float(row.get("peso_item") or 0.0),
                        "peso_conjunto": float(peso_conj or 0.0),
                        "preco_unitario": float(row.get("preco_unitario") or 0.0),
                        "fecha": fecha_calc,
                        "concluido": (status_of == "Pronto" or status_of == "Faturada"),
                        "statusOF": status_of,
                        "data_producao": data_producao,
                        "onda": onda,
                        "qualidade": qualidade,
                        "gramatura": gramatura,
                        "cor1": cor1,
                        "cor2": cor2,
                        "comp": row.get("comp"),
                        "larg": row.get("larg"),
                        "alt": row.get("alt")
                    }
                )
                pedidos_map[id_ped]["total_itens"] = len(pedidos_map[id_ped]["itens"])

        lista_pedidos = []
        for id_ped, pedido in pedidos_map.items():
            peso_aberto = 0.0
            valor_aberto = 0.0
            itens_ativos = 0

            for item in pedido["itens"]:
                if item["statusOF"] != "Faturada":
                    peso_aberto += float(item["peso_item"] or 0.0)
                    valor_aberto += float(item["quantidade"] or 0.0) * float(
                        item["preco_unitario"] or 0.0
                    )
                    itens_ativos += 1

            pedido["peso_total_kg"] = round(peso_aberto, 2)
            pedido["faturamento_total"] = round(valor_aberto, 2)
            pedido["total_itens_abertos"] = itens_ativos

            if itens_ativos == 0:
                pedido["status"] = "Faturada"
                if str(id_ped) in status_pedidos_local:
                    safe_delete_status("pedidos", id_ped) 
            else:
                manual_ped = status_pedidos_local.get(str(id_ped))
                if manual_ped:
                    pedido["status"] = manual_ped
                else:
                    abertos = [i for i in pedido["itens"] if i["statusOF"] != "Faturada"]
                    if len(abertos) > 0 and all(i["statusOF"] == "Pronto" for i in abertos):
                        pedido["status"] = "Pronto"
                    else:
                        pedido["status"] = "Pendente"

            # AGORA ANEXA TODOS, INCLUSIVE FATURADOS, PARA QUE O FRONTEND POSSA EXIBI-LOS NA ABA "FATURADOS"
            lista_pedidos.append(pedido)

        ordenar_por = request.args.get("ordenar_por", "id_pedido").lower()
        ordem = request.args.get("ordem", "desc").lower()
        rev = ordem == "desc"

        if ordenar_por in ["id_pedido", "id", "numero"]:
            lista_pedidos.sort(key=lambda x: x["id_pedido"], reverse=rev)
        elif ordenar_por in ["emissao", "data_emissao"]:
            lista_pedidos.sort(key=lambda x: x["raw_emissao"], reverse=rev)
        elif ordenar_por in ["data_entrega", "entrega"]:
            lista_pedidos.sort(key=lambda x: x["raw_entrega"], reverse=rev)
        elif ordenar_por in ["prazo", "dias_restantes"]:
            lista_pedidos.sort(
                key=lambda x: (
                    x["dias_restantes"] if x["dias_restantes"] is not None else 999999
                ),
                reverse=rev,
            )

        return jsonify(lista_pedidos), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/orcamentos", methods=["GET"])
def obter_orcamentos():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Busca anotações do SQLite
        notas_locais = {}
        with db_lock:
            sqlite_conn = get_sqlite_conn()
            scur = sqlite_conn.cursor()
            scur.execute("SELECT id_orcamento, anotacao, data_atualizacao FROM orcamento_notas")
            for row in scur.fetchall():
                notas_locais[str(row[0])] = {"anotacao": row[1], "data_atualizacao": row[2]}
            sqlite_conn.close()

        # Puxa orçamentos limitando pela emissão para não sobrecarregar
        query = """
            SELECT 
                o.ID_ORCAMENTO, o.EMISSAO, o.VALIDADE, o.ID_CLIENTE, o.NOME_CLIENTE,
                o.COMPRADOR, o.FONE, o.COND_PAGTO, o.PRAZO_ENTREGA, o.TOTAL_GERAL, o.TOTAL_PESO,
                i.REFERENCIA, i.MODELO_CAIXA, i.FECHAMENTO, i.COMP, i.LARG, i.ALT,
                i.QUANT, i.VLUNIT, i.VLTOT, i.ID_ONDAFAB, i.ID_QUALIDFAB, i.COR1, i.COR2, i.APROVADO
            FROM ORCAMENT o
            LEFT JOIN ORCITEM i ON o.ID_ORCAMENTO = i.ID_ORCAMENTO
            WHERE (o.DESATIVADO IS NULL OR o.DESATIVADO <> 'S')
              AND o.EMISSAO >= '2026-01-01'
            ORDER BY o.ID_ORCAMENTO DESC
        """
        cur.execute(query)
        colunas = [desc[0].lower() for desc in cur.description]
        registros = cur.fetchall()
        
        orc_map = {}
        for reg in registros:
            row = dict(zip(colunas, reg))
            id_orc = str(row.get("id_orcamento"))
            if not id_orc or id_orc == "None": continue
            
            if id_orc not in orc_map:
                dt_emissao = row.get("emissao")
                raw_emissao_str = dt_emissao.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt_emissao, (datetime, date)) else str(dt_emissao or "")
                
                nota_local = notas_locais.get(id_orc, {})
                
                orc_map[id_orc] = {
                    "id_orcamento": row.get("id_orcamento"),
                    "emissao": format_date_safe(dt_emissao),
                    "raw_emissao": raw_emissao_str,
                    "validade": limpar_texto(row.get("validade")),
                    "cliente": limpar_texto(row.get("nome_cliente")),
                    "comprador": limpar_texto(row.get("comprador")),
                    "telefone": limpar_texto(row.get("fone")),
                    "cond_pagto": limpar_texto(row.get("cond_pagto")),
                    "prazo_entrega": limpar_texto(row.get("prazo_entrega")),
                    "total_geral": float(row.get("total_geral") or 0.0),
                    "total_peso": float(row.get("total_peso") or 0.0),
                    "anotacao": nota_local.get("anotacao", ""),
                    "data_anotacao": nota_local.get("data_atualizacao", ""),
                    "itens": []
                }
            
            if row.get("referencia"):
                orc_map[id_orc]["itens"].append({
                    "referencia": limpar_texto(row.get("referencia")),
                    "modelo": limpar_texto(row.get("modelo_caixa")),
                    "fechamento": limpar_texto(row.get("fechamento")),
                    "comp": row.get("comp"), "larg": row.get("larg"), "alt": row.get("alt"),
                    "quantidade": float(row.get("quant") or 0.0),
                    "vl_unit": float(row.get("vlunit") or 0.0),
                    "vl_tot": float(row.get("vltot") or 0.0),
                    "onda": limpar_texto(row.get("id_ondafab")),
                    "qualidade": limpar_texto(row.get("id_qualidfab")),
                    "cor1": limpar_texto(row.get("cor1")),
                    "cor2": limpar_texto(row.get("cor2")),
                    "aprovado": limpar_texto(row.get("aprovado"))
                })
                
        return jsonify(list(orc_map.values())), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn: conn.close()


@app.route("/api/orcamentos/<int:id_orcamento>/nota", methods=["PUT"])
def salvar_nota_orcamento(id_orcamento):
    try:
        dados = request.get_json() or {}
        nova_nota = dados.get("anotacao", "")
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        with db_lock:
            conn = get_sqlite_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO orcamento_notas (id_orcamento, anotacao, data_atualizacao) VALUES (?, ?, ?)",
                (str(id_orcamento), nova_nota, agora)
            )
            conn.commit()
            conn.close()
            
        return jsonify({"sucesso": True, "data_atualizacao": agora}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


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
                c.ID_ORDCOMPRA, c.EMISSAO, c.DATA_ENTREGA, c.NOME_FORNECEDOR, c.TOTAL_KG, c.TOTAL_GERAL, c.STATUS, c.DATA_RECEBIDA,
                ci.ITEM, ci.QUANT AS QUANT_CHAPA, ci.PESO AS PESO_CHAPA, ci.VLTOT, co.ID_NUMOF, co.NOME AS CLIENTE, co.QUANT AS QUANT_OF,
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
                    peso_chapa = float(row.get("peso_chapa") or 0.0)
                    vltot_item = float(row.get("vltot") or 0.0)
                    compras_map[id_compra]["itens_map"][id_item_str] = {
                        "item": id_item,
                        "quantidadeChapa": float(row.get("quant_chapa") or 0.0),
                        "pesoChapa": peso_chapa,
                        "vltot": vltot_item,
                        "ofs": [],
                    }
                    compras_map[id_compra]["soma_itens_kg"] += peso_chapa
                    compras_map[id_compra]["soma_itens_vltot"] += vltot_item

                if id_of:
                    id_of_str = str(id_of)
                    of_local = status_ofs_local.get(id_of_str, {})
                    status_manual = of_local.get("status") if isinstance(of_local, dict) else None
                    status_banco = of_status_db.get(id_of_str)
                    
                    status_of = obter_status_final_of(status_manual, status_banco)

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
        return jsonify({"erro": str(e)}), 500
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
        conn.commit()

        invalidar_cache_db()
        if ofs:
            atualizacoes = {str(row[0]): "Produção" for row in ofs if row[0]}
            if atualizacoes:
                safe_update_status_lote("ofs", atualizacoes)

        return jsonify({"sucesso": True}), 200
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/pedidos/<int:id_pedido>/status", methods=["PUT"])
def atualizar_status_unidade(id_pedido):
    try:
        safe_update_status(
            "pedidos", id_pedido, request.get_json().get("status", "Pendente")
        )
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/pedidos/<int:id_pedido>/itens/<path:id_of>/status", methods=["PUT"])
def atualizar_status_of(id_pedido, id_of):
    try:
        safe_update_status("ofs", id_of, request.get_json().get("status", "Pendente"))
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/ofs/status-rapido", methods=["PUT"])
def atualizar_status_rapido_of():
    try:
        dados = request.get_json() or {}
        id_of, novo_status = dados.get("id_of"), dados.get("status")
        if not id_of or not novo_status:
            return jsonify({"erro": "Obrigatórios"}), 400
        safe_update_status("ofs", id_of, novo_status)
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/pedidos/status-lote", methods=["PUT"])
def atualizar_status_lote():
    try:
        dados = request.get_json() or {}
        ids, novo_status = dados.get("ids", []), dados.get("status", "Pendente")
        if not ids:
            return jsonify({"erro": "Nenhum ID"}), 400
        safe_update_status_lote("pedidos", {str(i): novo_status for i in ids})
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/resumo/mapa", methods=["GET"])
def obter_resumo_mapa():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        hoje = datetime.now()
        cur.execute(
            "SELECT COALESCE(SUM(OI_BRUTO), 0) FROM FISCAL WHERE EMISS_ANO = ? AND EMISS_MES = ? AND ID_EMPRESA IN (1, 2) AND (CANCELADA IS NULL OR CANCELADA <> 'S') AND (IGNORAR_PESO IS NULL OR IGNORAR_PESO <> 'S')",
            (hoje.year, hoje.month),
        )
        return (
            jsonify({"peso_entregue_mes_kg": round(float(cur.fetchone()[0]), 2)}),
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
        cur.execute(
            "SELECT COALESCE(SUM(TOTNOTA),0), COALESCE(SUM(OI_BRUTO),0), COUNT(NF) FROM FISCAL WHERE EMISS_ANO = ? AND EMISS_MES = ? AND ID_EMPRESA IN (1, 2) AND (CANCELADA IS NULL OR CANCELADA <> 'S') AND (IGNORAR_PESO IS NULL OR IGNORAR_PESO <> 'S')",
            (hoje.year, hoje.month),
        )
        res = cur.fetchone()
        return (
            jsonify(
                {
                    "faturamento_mes": round(float(res[0]), 2),
                    "peso_mes_kg": round(float(res[1]), 2),
                    "total_nfs_mes": int(res[2]),
                    "mes_referencia": f"{hoje.month:02d}/{hoje.year}",
                }
            ),
            200,
        )
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)