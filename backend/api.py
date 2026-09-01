import os
import json
import sqlite3
import traceback
import threading
import time
from datetime import date, datetime
import requests
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
import fdb
from flask import Flask, jsonify, request
from flask_cors import CORS

# --- CARREGA O CAMINHO ABSOLUTO DA DLL E SUAS DEPENDÊNCIAS ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
caminho_dll = os.path.join(BASE_DIR, "fbclient.dll")
if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(os.path.dirname(caminho_dll))
    except Exception as e:
        print(f"Aviso ao adicionar diretório DLL: {e}")

try:
    fdb.load_api(caminho_dll)
except Exception as e:
    print(f"Aviso ao carregar DLL do Firebird: {e}")

env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=env_path)
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
                qtd_produzida REAL,
                PRIMARY KEY (categoria, chave)
            )
        """)
        try:
            cur.execute("ALTER TABLE kanban_status ADD COLUMN data_producao TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cur.execute("ALTER TABLE kanban_status ADD COLUMN qtd_produzida REAL")
        except sqlite3.OperationalError:
            pass

        cur.execute("""
            CREATE TABLE IF NOT EXISTS orcamento_notas (
                id_orcamento TEXT PRIMARY KEY,
                anotacao TEXT NOT NULL,
                data_atualizacao TEXT NOT NULL,
                status TEXT DEFAULT 'Em Aberto'
            )
        """)

        try:
            cur.execute("ALTER TABLE orcamento_notas ADD COLUMN status TEXT DEFAULT 'Em Aberto'")
        except sqlite3.OperationalError:
            pass


        cur.execute("""
            CREATE TABLE IF NOT EXISTS clientes_geolocalizacao (
                id_cliente INTEGER PRIMARY KEY,
                endereco_consultado TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                place_id TEXT,
                origem TEXT,
                data_atualizacao TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS estoque_manual (
                id_estoque INTEGER PRIMARY KEY AUTOINCREMENT,
                id_ft_principal TEXT NOT NULL,
                referencia TEXT,
                peso_conjunto REAL,
                preco_conjunto REAL,
                id_qualidfab TEXT,
                id_ondafab TEXT,
                nome_cliente TEXT,
                gramatura TEXT,
                quantidade REAL,
                data_criacao TEXT
            )
        """)
        conn.commit()
        conn.close()


init_sqlite_db()


def carregar_kanban_local():
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT categoria, chave, status, data_producao, qtd_produzida FROM kanban_status"
        )
        rows = cur.fetchall()
        conn.close()

        resultado = {"pedidos": {}, "ofs": {}}
        for cat, chave, st, dp, qp in rows:
            if cat in resultado:
                if cat == "ofs":
                    resultado[cat][str(chave)] = {
                        "status": st,
                        "data_producao": dp,
                        "qtd_produzida": qp,
                    }
                else:
                    resultado[cat][str(chave)] = st
        return resultado


def safe_update_status(categoria, chave, valor, qtd_produzida=None):
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()

        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data_prod = agora if valor == "Produção" else None

        if valor == "Produção":
            cur.execute(
                "SELECT data_producao FROM kanban_status WHERE categoria=? AND chave=?",
                (categoria, str(chave)),
            )
            row = cur.fetchone()
            if row and row[0]:
                data_prod = row[0]

        cur.execute(
            "INSERT OR REPLACE INTO kanban_status (categoria, chave, status, data_producao, qtd_produzida) VALUES (?, ?, ?, ?, ?)",
            (categoria, str(chave), str(valor), data_prod, qtd_produzida),
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
            data_prod = agora if valor == "Produção" else None
            if valor == "Produção":
                cur.execute(
                    "SELECT data_producao FROM kanban_status WHERE categoria=? AND chave=?",
                    (categoria, str(chave)),
                )
                row = cur.fetchone()
                if row and row[0]:
                    data_prod = row[0]

            cur.execute(
                "INSERT OR REPLACE INTO kanban_status (categoria, chave, status, data_producao, qtd_produzida) VALUES (?, ?, ?, ?, COALESCE((SELECT qtd_produzida FROM kanban_status WHERE categoria=? AND chave=?), NULL))",
                (categoria, str(chave), str(valor), data_prod, categoria, str(chave)),
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
        fb_library_name=caminho_dll
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
        SELECT co.ID_NUMOF, c.STATUS, c.DATA_RECEBIDA, c.ID_ORDCOMPRA
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
        id_compra = row[3]
        is_recebida = status_oc == "RECEBIDA" or data_rec is not None

        if id_of not in of_status_db:
            of_status_db[id_of] = {"status": "Produção" if is_recebida else "Compras", "id_compra": id_compra}
        else:
            if not is_recebida:
                of_status_db[id_of]["status"] = "Compras"
                of_status_db[id_of]["id_compra"] = id_compra

    _of_status_cache = of_status_db
    _of_status_cache_time = agora
    return _of_status_cache


def obter_status_final_of(
    status_manual, status_banco, is_faturada_total, is_faturada_parcial
):
    if status_manual:
        return status_manual
    if is_faturada_total:
        return "Faturada"
    if is_faturada_parcial:
        return "Parcial"
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


def get_pedidos_processados(ordenar_por="id_pedido", ordem="desc"):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        of_status_db = build_of_db_status_map(cur)
        kanban_local = carregar_kanban_local()
        status_pedidos_local = kanban_local.get("pedidos", {})
        status_ofs_local = kanban_local.get("ofs", {})

        # Query de OFs com filtro direto da fábrica
        query = """
            SELECT 
                p.ID_NUMPED AS ID_PEDIDO, p.PEDIDO_CLIENTE, p.EMISSAO, p.DATA_ENTREGA AS PRAZO_PEDIDO, p.ID_EMPRESA,
                p.TOTAL_PESO AS PESO_TOTAL_PEDIDO, p.TOTAL_GERAL, c.ID_CLIENTE, c.NOME AS CLIENTE_RAZAO,
                COALESCE(c.GUERRA, c.NOME) AS CLIENTE_FANTASIA, COALESCE(NULLIF(TRIM(c.ENT_CIDADE), ''), c.CIDADE) AS CIDADE,
                COALESCE(NULLIF(TRIM(c.ENT_ENDERECO), ''), c.ENDERECO) AS ENDERECO,
                COALESCE(c.ENT_NUMERO, c.NUMERO) AS NUMERO, COALESCE(NULLIF(TRIM(c.ENT_BAIRRO), ''), c.BAIRRO) AS BAIRRO,
                COALESCE(NULLIF(TRIM(c.ENT_CEP), ''), c.CEP) AS CEP,
                i.ID_PRODUTO, i.REFERENCIA, i.QUANT AS QTD_ITEM_TOTAL, i.PESO_TOT AS PESO_ITEM_TOTAL,
                i.VLUNIT AS PRECO_UNITARIO, i.FECHA,
                o.ID_NUMOF, o.QTDPROG AS QTD_OF_PROG, o.DTPROG AS DTPROG_OF,
                (
                    COALESCE((SELECT SUM(inf.QUANT) 
                     FROM ITEMNF inf 
                     JOIN FISCAL f ON (inf.NF = f.NF AND inf.ID_EMPRESA = f.ID_EMPRESA)
                     WHERE inf.ID_NUMOF = o.ID_NUMOF 
                       AND (f.CANCELADA IS NULL OR f.CANCELADA <> 'S')), 0)
                    +
                    COALESCE((SELECT SUM(pfi.QUANT) 
                     FROM PFITEM pfi
                     JOIN RECEBIMENTOS r ON (pfi.ID_PF = r.ID_PF AND pfi.ID_EMPRESA = r.ID_EMPRESA)
                     WHERE pfi.ID_NUMOF = o.ID_NUMOF 
                       AND r.TIPOREC = 'RECIBO'), 0)
                ) AS QTD_JA_FATURADA_OF,
                i.COMP, i.LARG, i.ALT, i.ID_ONDAFAB AS ONDA_PEDITEM, i.ID_QUALIDFAB AS QUALID_PEDITEM,
                ft.GRAMATURA, ft.FECHAMENTO AS FECHA_FT, ft.ID_ONDAFAB AS ONDA_FT, ft.ID_QUALIDFAB AS QUALID_FT,
                ft.DESCRICAO_COR1, ft.DESCRICAO_COR2
            FROM PEDIDOS p
            LEFT JOIN CLIENTES c ON p.ID_CLIENTE = c.ID_CLIENTE
            JOIN PEDITEM i ON p.ID_NUMPED = i.ID_NUMPED
            LEFT JOIN ORDFAB o ON (o.ID_NUMPED = i.ID_NUMPED AND o.ID_PRODUTO = i.ID_PRODUTO)
            LEFT JOIN FT ft ON (i.ID_PRODUTO = ft.ID_PRODUTO AND ft.DESATIVADO <> 'S')
            WHERE (p.EMISSAO >= '2026-07-01' OR p.DATA_ENTREGA >= '2026-07-01' OR o.DTPROG >= '2026-07-01')
              AND p.ID_EMPRESA IN (1, 2)
              AND (p.CANCELADO IS NULL OR p.CANCELADO <> 'S')
              AND (p.PEDIDO_BLOQUEADO IS NULL OR p.PEDIDO_BLOQUEADO <> 'S')
              AND (p.DESATIVADO IS NULL OR p.DESATIVADO <> 'S')
              AND (o.DESATIVADO IS NULL OR o.DESATIVADO <> 'S')
              AND (o.LIQUIDADO IS NULL OR o.LIQUIDADO <> 'S')
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

                partes_end = [
                    limpar_texto(row.get("endereco")),
                    str(row.get("numero") or ""),
                    limpar_texto(row.get("bairro")),
                    limpar_texto(row.get("cidade")),
                    limpar_texto(row.get("cep")),
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
                    "id_empresa": row.get("id_empresa"),
                    "pedido_cliente": limpar_texto(row.get("pedido_cliente")),
                    "cliente": cliente_final,
                    "id_cliente": row.get("id_cliente"),
                    "cidade_bloco": limpar_texto(row.get("cidade")),
                    "endereco_completo": endereco_comp,
                    "cep": limpar_texto(row.get("cep")),
                    "data_emissao": data_emissao_formatada,
                    "raw_emissao": raw_emissao_str,
                    "data_entrega": "",
                    "raw_entrega": "",
                    "dias_restantes": 999999,
                    "itens": [],
                    "has_faturado_of": False,
                    "has_ativa_of": False,
                }

            id_of_val = row.get("id_numof")
            prod_id = str(row.get("id_produto") or "PROD")
            id_of_str = str(id_of_val) if id_of_val is not None else f"ITEM-{prod_id}"

            # 1. MATEMÁTICA PURA DE PESO (Usando a Venda como Verdade Absoluta)
            qtd_item_total = float(row.get("qtd_item_total") or 0.0)
            peso_item_total = float(row.get("peso_item_total") or 0.0)
            # Pega o peso de 1 única caixa exatamente como foi vendida
            peso_unitario_real = (
                (peso_item_total / qtd_item_total) if qtd_item_total > 0 else 0.0
            )

            # 2. Aplica o peso unitário exato na Quantidade da OF
            qtd_of = float(row.get("qtd_of_prog") or qtd_item_total)
            peso_of = qtd_of * peso_unitario_real

            preco_unitario = float(row.get("preco_unitario") or 0.0)
            qtd_faturada_of = float(row.get("qtd_ja_faturada_of") or 0.0)

            # 3. Tolerância de 10% para Liquidação Automática
            is_faturada_total = False
            is_faturada_parcial = False

            if qtd_of > 0:
                if qtd_faturada_of >= (qtd_of * 0.90):
                    is_faturada_total = True
                elif qtd_faturada_of > 0:
                    is_faturada_parcial = True
            elif qtd_faturada_of > 0:
                is_faturada_total = True

            of_local = status_ofs_local.get(id_of_str, {})
            status_manual = (
                of_local.get("status") if isinstance(of_local, dict) else None
            )
            data_producao = (
                of_local.get("data_producao") if isinstance(of_local, dict) else None
            )
            qtd_produzida_real = (
                of_local.get("qtd_produzida") if isinstance(of_local, dict) else None
            )

            status_banco_dict = of_status_db.get(id_of_str) or {}
            status_banco = status_banco_dict.get("status") if isinstance(status_banco_dict, dict) else status_banco_dict
            id_ordcompra = status_banco_dict.get("id_compra") if isinstance(status_banco_dict, dict) else None

            status_of = obter_status_final_of(
                status_manual, status_banco, is_faturada_total, is_faturada_parcial
            )

            if status_of == "Faturada":
                qtd_restante_of = 0.0
                peso_restante_of = 0.0
                pedidos_map[id_ped]["has_faturado_of"] = True
            else:
                qtd_restante_of = max(0.0, qtd_of - qtd_faturada_of)
                peso_restante_of = qtd_restante_of * peso_unitario_real
                pedidos_map[id_ped]["has_ativa_of"] = True

            if qtd_faturada_of > 0:
                pedidos_map[id_ped]["has_faturado_of"] = True

            # 4. Data e Prazo individuais da OF
            dtprog_of = row.get("dtprog_of") or row.get("prazo_pedido")
            data_of_formatada = ""
            raw_of_date_str = ""
            dias_restantes_of = 999999

            if dtprog_of:
                try:
                    dt_of_date = (
                        dtprog_of.date()
                        if isinstance(dtprog_of, datetime)
                        else dtprog_of if isinstance(dtprog_of, date) else None
                    )
                    if dt_of_date:
                        data_of_formatada = dt_of_date.strftime("%d/%m/%Y")
                        raw_of_date_str = dt_of_date.strftime("%Y-%m-%d")
                        dias_restantes_of = (dt_of_date - hoje).days
                except Exception:
                    pass

            # Atualiza o prazo do pedido para a próxima OF ativa
            if (
                status_of != "Faturada"
                and dias_restantes_of < pedidos_map[id_ped]["dias_restantes"]
            ):
                pedidos_map[id_ped]["dias_restantes"] = dias_restantes_of
                pedidos_map[id_ped]["data_entrega"] = data_of_formatada
                pedidos_map[id_ped]["raw_entrega"] = raw_of_date_str

            onda = limpar_texto(row.get("onda_ft") or row.get("onda_peditem"))
            qualidade = limpar_texto(row.get("qualid_ft") or row.get("qualid_peditem"))
            gramatura = limpar_texto(row.get("gramatura"))
            fecha_calc = limpar_texto(row.get("fecha_ft") or row.get("fecha"))
            cor1 = limpar_texto(row.get("descricao_cor1"))
            cor2 = limpar_texto(row.get("descricao_cor2"))

            pedidos_map[id_ped]["itens"].append(
                {
                    "id_numof": id_of_val,
                    "id_produto": prod_id,
                    "referencia": limpar_texto(row.get("referencia")),
                    "qtd_prog": qtd_of,
                    "qtd_restante": qtd_restante_of,
                    "peso_of": peso_of,
                    "peso_restante": peso_restante_of,
                    "preco_unitario": preco_unitario,
                    "fecha": fecha_calc,
                    "concluido": (status_of in ["Pronto", "Faturada"]),
                    "statusOF": status_of,
                    "data_producao": data_producao,
                    "qtd_produzida": qtd_produzida_real,
                    "data_programada": data_of_formatada,
                    "raw_dtprog": raw_of_date_str,
                    "dias_restantes_of": (
                        dias_restantes_of if dias_restantes_of != 999999 else None
                    ),
                    "onda": onda,
                    "qualidade": qualidade,
                    "gramatura": gramatura,
                    "cor1": cor1,
                    "cor2": cor2,
                    "comp": row.get("comp"),
                    "larg": row.get("larg"),
                    "alt": row.get("alt"),
                    "id_compra": id_ordcompra,
                }
            )

        lista_pedidos = []
        for id_ped, pedido in pedidos_map.items():
            if pedido["dias_restantes"] == 999999:
                pedido["dias_restantes"] = None

            peso_aberto_pedido = 0.0
            valor_aberto_pedido = 0.0
            itens_ativos_pedido = 0

            for item in pedido["itens"]:
                if item["statusOF"] != "Faturada":
                    # Hierarquia de Qtd: Se tiver Lançamento Manual (qtd_produzida), usa ele para recalcular.
                    qtd_calc = (
                        float(item["qtd_produzida"])
                        if item["qtd_produzida"] not in [None, ""]
                        else float(item["qtd_restante"] or 0.0)
                    )
                    peso_unit = (
                        float(item["peso_of"] / item["qtd_prog"])
                        if float(item["qtd_prog"] or 0.0) > 0
                        else 0.0
                    )

                    peso_aberto_pedido += qtd_calc * peso_unit
                    valor_aberto_pedido += qtd_calc * float(
                        item["preco_unitario"] or 0.0
                    )
                    itens_ativos_pedido += 1

            # Mantém em RAW float para exibir as decimais exatas no Frontend
            pedido["peso_total_kg"] = peso_aberto_pedido
            pedido["peso_total_pedido_bruto"] = float(row.get("peso_total_pedido") or 0.0)
            pedido["faturamento_total"] = valor_aberto_pedido
            pedido["total_itens_abertos"] = itens_ativos_pedido

            # Alerta de Entrega Parcial
            pedido["has_entrega_parcial"] = (
                pedido["has_faturado_of"] and pedido["has_ativa_of"]
            )

            del pedido["has_faturado_of"], pedido["has_ativa_of"]

            # Controle de Status Final do Pedido
            manual_ped = status_pedidos_local.get(str(id_ped))
            if manual_ped:
                pedido["status"] = manual_ped
            elif itens_ativos_pedido == 0:
                pedido["status"] = "Faturada"
            else:
                abertos = [i for i in pedido["itens"] if i["statusOF"] != "Faturada"]
                if len(abertos) > 0 and all(i["statusOF"] == "Pronto" for i in abertos):
                    pedido["status"] = "Pronto"
                else:
                    pedido["status"] = "Pendente"

            lista_pedidos.append(pedido)

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

        return lista_pedidos

    except Exception as e:
        traceback.print_exc()
        raise e
    finally:
        if conn:
            conn.close()

@app.route("/api/pedidos", methods=["GET"])
def obter_pedidos():
    try:
        ordenar_por = request.args.get("ordenar_por", "id_pedido").lower()
        ordem = request.args.get("ordem", "desc").lower()
        lista_pedidos = get_pedidos_processados(ordenar_por, ordem)
        return jsonify(lista_pedidos), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500


@app.route("/api/calendario_pesos", methods=["GET"])
def obter_calendario_pesos():
    conn = None
    try:
        mes_param = request.args.get("mes")
        ano_param = request.args.get("ano")
        if not mes_param or not ano_param:
            hoje = datetime.now()
            mes_param = hoje.month
            ano_param = hoje.year

        mes = int(mes_param)
        ano = int(ano_param)

        data_inicio_mes = datetime(ano, mes, 1).date()

        if mes == 1:
            mes_anterior = 12
            ano_anterior = ano - 1
        else:
            mes_anterior = mes - 1
            ano_anterior = ano

        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            """SELECT COALESCE(SUM(OI_BRUTO), 0) FROM FISCAL 
               WHERE EMISS_ANO = ? AND EMISS_MES = ? AND ID_EMPRESA IN (1, 2) 
                 AND (CANCELADA IS NULL OR CANCELADA <> 'S') 
                 AND (IGNORAR_PESO IS NULL OR IGNORAR_PESO <> 'S')""",
            (ano_anterior, mes_anterior),
        )
        peso_nfs = float(cur.fetchone()[0] or 0.0)

        cur.execute(
            """SELECT COALESCE(SUM(pfi.PESOTOTAL), 0)
               FROM RECEBIMENTOS r
               JOIN PFITEM pfi ON pfi.ID_PF = r.ID_PF AND pfi.ID_EMPRESA = r.ID_EMPRESA
               WHERE EXTRACT(YEAR FROM r.EMISSAO) = ? 
                 AND EXTRACT(MONTH FROM r.EMISSAO) = ?
                 AND r.ID_EMPRESA IN (1, 2)
                 AND r.TIPOREC = 'RECIBO'
                 AND (r.CONTABILIZA IS NULL OR r.CONTABILIZA = 'S')""",
            (ano_anterior, mes_anterior),
        )
        peso_recs = float(cur.fetchone()[0] or 0.0)
        
        peso_saida_anterior = peso_nfs + peso_recs
        conn.close()

        lista_pedidos = get_pedidos_processados()
        
        backlog_anterior_kg = 0.0
        entrada_mes_kg = 0.0
        dias_calendario = {str(dia): 0.0 for dia in range(1, 32)}

        for pedido in lista_pedidos:
            raw_emissao = pedido.get("raw_emissao")
            if not raw_emissao:
                continue

            try:
                dt_emissao = datetime.strptime(raw_emissao, "%Y-%m-%d").date()
            except ValueError:
                continue

            if dt_emissao < data_inicio_mes:
                peso_aberto = pedido.get("peso_total_kg", 0.0)
                if pedido.get("status") != "Faturada" and peso_aberto > 0:
                    backlog_anterior_kg += peso_aberto
            elif dt_emissao.month == mes and dt_emissao.year == ano:
                peso_bruto = pedido.get("peso_total_pedido_bruto", 0.0)
                entrada_mes_kg += peso_bruto
                dias_calendario[str(dt_emissao.day)] += peso_bruto

        return jsonify({
            "saida_mes_anterior_kg": peso_saida_anterior,
            "backlog_anterior_kg": backlog_anterior_kg,
            "entrada_mes_kg": entrada_mes_kg,
            "dias_calendario": dias_calendario,
            "mes": mes,
            "ano": ano
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn and not conn.closed:
            conn.close()

@app.route("/api/orcamentos", methods=["GET"])
def obter_orcamentos():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        notas_locais = {}
        with db_lock:
            sqlite_conn = get_sqlite_conn()
            scur = sqlite_conn.cursor()
            scur.execute(
                "SELECT id_orcamento, anotacao, data_atualizacao, status FROM orcamento_notas"
            )
            for row in scur.fetchall():
                notas_locais[str(row[0])] = {
                    "anotacao": row[1],
                    "data_atualizacao": row[2],
                    "status": row[3] if row[3] else 'Em Aberto'
                }
            sqlite_conn.close()

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
            if not id_orc or id_orc == "None":
                continue

            if id_orc not in orc_map:
                dt_emissao = row.get("emissao")
                raw_emissao_str = (
                    dt_emissao.strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(dt_emissao, (datetime, date))
                    else str(dt_emissao or "")
                )

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
                    "status": nota_local.get("status", "Em Aberto"),
                    "itens": [],
                }

            if row.get("referencia"):
                orc_map[id_orc]["itens"].append(
                    {
                        "referencia": limpar_texto(row.get("referencia")),
                        "modelo": limpar_texto(row.get("modelo_caixa")),
                        "fechamento": limpar_texto(row.get("fechamento")),
                        "comp": row.get("comp"),
                        "larg": row.get("larg"),
                        "alt": row.get("alt"),
                        "quantidade": float(row.get("quant") or 0.0),
                        "vl_unit": float(row.get("vlunit") or 0.0),
                        "vl_tot": float(row.get("vltot") or 0.0),
                        "onda": limpar_texto(row.get("id_ondafab")),
                        "qualidade": limpar_texto(row.get("id_qualidfab")),
                        "cor1": limpar_texto(row.get("cor1")),
                        "cor2": limpar_texto(row.get("cor2")),
                        "aprovado": limpar_texto(row.get("aprovado")),
                    }
                )

        return jsonify(list(orc_map.values())), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/orcamentos/<id_orcamento>/nota", methods=["PUT"])
def atualizar_nota_orcamento(id_orcamento):
    try:
        dados = request.json
        nova_nota = dados.get("anotacao", "")
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")

        with db_lock:
            conn = get_sqlite_conn()
            cur = conn.cursor()
            
            cur.execute("SELECT status FROM orcamento_notas WHERE id_orcamento = ?", (id_orcamento,))
            row = cur.fetchone()
            status_atual = row[0] if row else 'Em Aberto'
            
            cur.execute(
                "INSERT OR REPLACE INTO orcamento_notas (id_orcamento, anotacao, data_atualizacao, status) VALUES (?, ?, ?, ?)",
                (id_orcamento, nova_nota, agora, status_atual),
            )
            conn.commit()
            conn.close()

        return jsonify({"mensagem": "Nota atualizada", "data_atualizacao": agora}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500

@app.route("/api/orcamentos/<id_orcamento>/status", methods=["PUT"])
def atualizar_status_orcamento(id_orcamento):
    try:
        dados = request.json
        novo_status = dados.get("status", "Em Aberto")
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")

        with db_lock:
            conn = get_sqlite_conn()
            cur = conn.cursor()
            
            cur.execute("SELECT anotacao, data_atualizacao FROM orcamento_notas WHERE id_orcamento = ?", (id_orcamento,))
            row = cur.fetchone()
            anotacao_atual = row[0] if row else ""
            data_atualizacao_atual = row[1] if row else agora
            
            cur.execute(
                "INSERT OR REPLACE INTO orcamento_notas (id_orcamento, anotacao, data_atualizacao, status) VALUES (?, ?, ?, ?)",
                (id_orcamento, anotacao_atual, data_atualizacao_atual, novo_status),
            )
            conn.commit()
            conn.close()

        return jsonify({"mensagem": "Status atualizado", "novo_status": novo_status}), 200
    except Exception as e:
        traceback.print_exc()
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
                ci.ITEM, ci.QUANT AS QUANT_CHAPA, ci.PESO AS PESO_CHAPA, (ci.QUANT * COALESCE(ci.PR_FL, 0)) AS VLTOT, ci.LARG, ci.COMP, co.ID_NUMOF, co.NOME AS CLIENTE, co.QUANT AS QUANT_OF,
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
                    larg = row.get("larg") or 0
                    comp = row.get("comp") or 0
                    compras_map[id_compra]["itens_map"][id_item_str] = {
                        "item": id_item,
                        "quantidadeChapa": float(row.get("quant_chapa") or 0.0),
                        "pesoChapa": peso_chapa,
                        "vltot": vltot_item,
                        "medida": f"{larg}x{comp} mm",
                        "ofs": [],
                    }
                    compras_map[id_compra]["soma_itens_kg"] += peso_chapa
                    compras_map[id_compra]["soma_itens_vltot"] += vltot_item

                if id_of:
                    id_of_str = str(id_of)
                    of_local = status_ofs_local.get(id_of_str, {})
                    status_manual = (
                        of_local.get("status") if isinstance(of_local, dict) else None
                    )
                    status_banco_dict = of_status_db.get(id_of_str) or {}
                    status_banco = status_banco_dict.get("status") if isinstance(status_banco_dict, dict) else status_banco_dict

                    status_of = obter_status_final_of(
                        status_manual, status_banco, False, False
                    )

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
        dados = request.get_json() or {}
        novo_status = dados.get("status", "Pendente")
        qtd_produzida = dados.get("qtd_produzida")
        qtd_val = (
            float(qtd_produzida)
            if qtd_produzida is not None and str(qtd_produzida).strip() != ""
            else None
        )

        safe_update_status("ofs", id_of, novo_status, qtd_val)
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/ofs/status-rapido", methods=["PUT"])
def atualizar_status_rapido_of():
    try:
        dados = request.get_json() or {}
        id_of, novo_status = dados.get("id_of"), dados.get("status")
        qtd_produzida = dados.get("qtd_produzida")
        if not id_of or not novo_status:
            return jsonify({"erro": "Obrigatórios"}), 400

        qtd_val = (
            float(qtd_produzida)
            if qtd_produzida is not None and str(qtd_produzida).strip() != ""
            else None
        )
        safe_update_status("ofs", id_of, novo_status, qtd_val)
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
            """SELECT COALESCE(SUM(OI_BRUTO), 0) FROM FISCAL 
               WHERE EMISS_ANO = ? AND EMISS_MES = ? AND ID_EMPRESA IN (1, 2) 
                 AND (CANCELADA IS NULL OR CANCELADA <> 'S') 
                 AND (IGNORAR_PESO IS NULL OR IGNORAR_PESO <> 'S')""",
            (hoje.year, hoje.month),
        )
        peso_nfs = float(cur.fetchone()[0] or 0.0)

        cur.execute(
            """SELECT COALESCE(SUM(pfi.PESOTOTAL), 0)
               FROM RECEBIMENTOS r
               JOIN PFITEM pfi ON pfi.ID_PF = r.ID_PF AND pfi.ID_EMPRESA = r.ID_EMPRESA
               WHERE EXTRACT(YEAR FROM r.EMISSAO) = ? 
                 AND EXTRACT(MONTH FROM r.EMISSAO) = ?
                 AND r.ID_EMPRESA IN (1, 2)
                 AND r.TIPOREC = 'RECIBO'
                 AND (r.CONTABILIZA IS NULL OR r.CONTABILIZA = 'S')""",
            (hoje.year, hoje.month),
        )
        peso_recs = float(cur.fetchone()[0] or 0.0)

        return (
            jsonify({"peso_entregue_mes_kg": peso_nfs + peso_recs}),
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

        # Ruycepel (ID 1)
        cur.execute(
            """SELECT COALESCE(SUM(TOTNOTA),0), COALESCE(SUM(TOTIPI),0), COALESCE(SUM(OI_BRUTO),0), COUNT(NF) 
                       FROM FISCAL 
                       WHERE EMISS_ANO = ? AND EMISS_MES = ? AND ID_EMPRESA = 1 
                         AND (CANCELADA IS NULL OR CANCELADA <> 'S') 
                         AND (IGNORAR_PESO IS NULL OR IGNORAR_PESO <> 'S')""",
            (hoje.year, hoje.month),
        )
        row1_nf = cur.fetchone()

        cur.execute(
            """SELECT COALESCE(SUM(i.VALOR), 0), COUNT(DISTINCT r.ID_RECEBIMENTOS)
                       FROM RECEBIMENTOS r
                       JOIN RECEBITENS i ON r.ID_RECEBIMENTOS = i.ID_RECEBIMENTOS
                       WHERE EXTRACT(YEAR FROM r.EMISSAO) = ? AND EXTRACT(MONTH FROM r.EMISSAO) = ?
                         AND r.ID_EMPRESA = 1 AND r.TIPOREC = 'RECIBO' AND (r.CONTABILIZA IS NULL OR r.CONTABILIZA = 'S')""",
            (hoje.year, hoje.month),
        )
        row1_rec = cur.fetchone()

        cur.execute(
            """SELECT COALESCE(SUM(pfi.PESOTOTAL), 0) FROM RECEBIMENTOS r JOIN PFITEM pfi ON pfi.ID_PF = r.ID_PF AND pfi.ID_EMPRESA = r.ID_EMPRESA WHERE EXTRACT(YEAR FROM r.EMISSAO) = ? AND EXTRACT(MONTH FROM r.EMISSAO) = ? AND r.ID_EMPRESA = 1 AND r.TIPOREC = 'RECIBO' AND (r.CONTABILIZA IS NULL OR r.CONTABILIZA = 'S')""",
            (hoje.year, hoje.month),
        )
        peso1_rec = float(cur.fetchone()[0] or 0.0)

        # Elly (ID 2)
        cur.execute(
            """SELECT COALESCE(SUM(TOTNOTA),0), COALESCE(SUM(TOTIPI),0), COALESCE(SUM(OI_BRUTO),0), COUNT(NF) 
                       FROM FISCAL 
                       WHERE EMISS_ANO = ? AND EMISS_MES = ? AND ID_EMPRESA = 2 
                         AND (CANCELADA IS NULL OR CANCELADA <> 'S') 
                         AND (IGNORAR_PESO IS NULL OR IGNORAR_PESO <> 'S')""",
            (hoje.year, hoje.month),
        )
        row2_nf = cur.fetchone()

        cur.execute(
            """SELECT COALESCE(SUM(i.VALOR), 0), COUNT(DISTINCT r.ID_RECEBIMENTOS)
                       FROM RECEBIMENTOS r
                       JOIN RECEBITENS i ON r.ID_RECEBIMENTOS = i.ID_RECEBIMENTOS
                       WHERE EXTRACT(YEAR FROM r.EMISSAO) = ? AND EXTRACT(MONTH FROM r.EMISSAO) = ?
                         AND r.ID_EMPRESA = 2 AND r.TIPOREC = 'RECIBO' AND (r.CONTABILIZA IS NULL OR r.CONTABILIZA = 'S')""",
            (hoje.year, hoje.month),
        )
        row2_rec = cur.fetchone()

        cur.execute(
            """SELECT COALESCE(SUM(pfi.PESOTOTAL), 0) FROM RECEBIMENTOS r JOIN PFITEM pfi ON pfi.ID_PF = r.ID_PF AND pfi.ID_EMPRESA = r.ID_EMPRESA WHERE EXTRACT(YEAR FROM r.EMISSAO) = ? AND EXTRACT(MONTH FROM r.EMISSAO) = ? AND r.ID_EMPRESA = 2 AND r.TIPOREC = 'RECIBO' AND (r.CONTABILIZA IS NULL OR r.CONTABILIZA = 'S')""",
            (hoje.year, hoje.month),
        )
        peso2_rec = float(cur.fetchone()[0] or 0.0)

        e1_tot_nota, e1_tot_ipi, e1_peso_nf, e1_qtd_nf = (
            float(row1_nf[0] or 0),
            float(row1_nf[1] or 0),
            float(row1_nf[2] or 0),
            int(row1_nf[3] or 0),
        )
        e1_fat_rec, e1_qtd_rec = float(row1_rec[0] or 0), int(row1_rec[1] or 0)

        e2_tot_nota, e2_tot_ipi, e2_peso_nf, e2_qtd_nf = (
            float(row2_nf[0] or 0),
            float(row2_nf[1] or 0),
            float(row2_nf[2] or 0),
            int(row2_nf[3] or 0),
        )
        e2_fat_rec, e2_qtd_rec = float(row2_rec[0] or 0), int(row2_rec[1] or 0)

        return (
            jsonify(
                {
                    "ruycepel": {
                        "com_ipi": round(e1_tot_nota + e1_fat_rec, 2),
                        "sem_ipi": round((e1_tot_nota - e1_tot_ipi) + e1_fat_rec, 2),
                        "peso_mes_kg": round(e1_peso_nf + peso1_rec, 2),
                        "total_nfs_mes": e1_qtd_nf + e1_qtd_rec,
                    },
                    "elly": {
                        "com_ipi": round(e2_tot_nota + e2_fat_rec, 2),
                        "sem_ipi": round((e2_tot_nota - e2_tot_ipi) + e2_fat_rec, 2),
                        "peso_mes_kg": round(e2_peso_nf + peso2_rec, 2),
                        "total_nfs_mes": e2_qtd_nf + e2_qtd_rec,
                    },
                    "total": {
                        "com_ipi": round(
                            e1_tot_nota + e1_fat_rec + e2_tot_nota + e2_fat_rec, 2
                        ),
                        "sem_ipi": round(
                            (e1_tot_nota - e1_tot_ipi)
                            + e1_fat_rec
                            + (e2_tot_nota - e2_tot_ipi)
                            + e2_fat_rec,
                            2,
                        ),
                        "peso_mes_kg": round(
                            e1_peso_nf + peso1_rec + e2_peso_nf + peso2_rec, 2
                        ),
                        "total_nfs_mes": e1_qtd_nf
                        + e1_qtd_rec
                        + e2_qtd_nf
                        + e2_qtd_rec,
                    },
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


@app.route("/api/ft/<path:id_ft>", methods=["GET"])
def obter_ft(id_ft):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        id_ft_int = int(id_ft) if id_ft.isdigit() else -1

        query = """
            SELECT 
                f.ID_FT_PRINCIPAL, f.REFERENCIA, f.PESO_CONJUNTO, f.PRECO_CONJUNTO,
                f.ID_QUALIDFAB, f.ID_ONDAFAB, f.GRAMATURA, c.NOME AS NOME_CLIENTE
            FROM FT f
            LEFT JOIN CLIENTES c ON f.ID_CLIENTE = c.ID_CLIENTE
            WHERE f.ID_FT_PRINCIPAL = ? OR f.ID_PRODUTO = ?
        """
        cur.execute(query, (id_ft_int, id_ft))
        row = cur.fetchone()
        
        if row:
            colunas = [desc[0].lower() for desc in cur.description]
            dados = dict(zip(colunas, row))
            import decimal
            for k, v in dados.items():
                if isinstance(v, bytes):
                    dados[k] = limpar_texto(v)
                elif isinstance(v, decimal.Decimal):
                    dados[k] = float(v)
            return jsonify(dados), 200
        else:
            return jsonify({"erro": "FT não encontrada"}), 404
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/estoque", methods=["GET", "POST"])
def gerenciar_estoque():
    if request.method == "POST":
        try:
            dados = request.get_json() or {}
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            acao = dados.get("acao", "novo")
            id_ft = str(dados.get("id_ft_principal", ""))
            qtd_input = float(dados.get("quantidade", 0.0) or 0.0)
            
            with db_lock:
                conn = get_sqlite_conn()
                cur = conn.cursor()
                
                if acao in ["somar", "substituir"]:
                    cur.execute("SELECT id_estoque, quantidade FROM estoque_manual WHERE id_ft_principal = ?", (id_ft,))
                    row = cur.fetchone()
                    if row:
                        id_estoque = row[0]
                        nova_qtd = (float(row[1]) + qtd_input) if acao == "somar" else qtd_input
                        cur.execute("UPDATE estoque_manual SET quantidade = ? WHERE id_estoque = ?", (nova_qtd, id_estoque))
                        conn.commit()
                        conn.close()
                        return jsonify({"sucesso": True, "acao": "atualizado", "nova_quantidade": nova_qtd}), 200

                cur.execute("""
                    INSERT INTO estoque_manual (
                        id_ft_principal, referencia, peso_conjunto, preco_conjunto,
                        id_qualidfab, id_ondafab, nome_cliente, gramatura, quantidade, data_criacao
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    id_ft,
                    dados.get("referencia", ""),
                    float(dados.get("peso_conjunto", 0.0) or 0.0),
                    float(dados.get("preco_conjunto", 0.0) or 0.0),
                    dados.get("id_qualidfab", ""),
                    dados.get("id_ondafab", ""),
                    dados.get("nome_cliente", ""),
                    dados.get("gramatura", ""),
                    qtd_input,
                    agora
                ))
                conn.commit()
                conn.close()
            return jsonify({"sucesso": True, "acao": "inserido"}), 201
        except Exception as e:
            traceback.print_exc()
            return jsonify({"erro": str(e)}), 500

    # Caso seja GET, retorna o estoque
    try:
        with db_lock:
            conn = get_sqlite_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM estoque_manual ORDER BY id_estoque DESC")
            colunas = [desc[0] for desc in cur.description]
            registros = [dict(zip(colunas, row)) for row in cur.fetchall()]
            conn.close()
            
        estoque_formatado = []
        for r in registros:
            estoque_formatado.append({
                "id_estoque": r.get("id_estoque"),
                "id_produto": r.get("id_ft_principal"),
                "referencia": r.get("referencia"),
                "cliente": r.get("nome_cliente"),
                "quantidade": r.get("quantidade"),
                "onda": r.get("id_ondafab"),
                "qualidade": r.get("id_qualidfab"),
                "gramatura": r.get("gramatura"),
                "peso_total": (float(r.get("peso_conjunto") or 0.0) * float(r.get("quantidade") or 0.0)),
                "valor_total": (float(r.get("preco_conjunto") or 0.0) * float(r.get("quantidade") or 0.0)),
                "comp": "-", "larg": "-", "alt": "-",
                "is_manual": True
            })
            
        return jsonify(estoque_formatado), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500

@app.route("/api/estoque/<int:id_estoque>", methods=["PUT"])
def editar_estoque(id_estoque):
    try:
        dados = request.get_json() or {}
        acao = dados.get("acao", "substituir")
        qtd_input = float(dados.get("quantidade", 0.0) or 0.0)
        
        with db_lock:
            conn = get_sqlite_conn()
            cur = conn.cursor()
            
            nova_qtd = qtd_input
            if acao == "somar":
                cur.execute("SELECT quantidade FROM estoque_manual WHERE id_estoque = ?", (id_estoque,))
                row = cur.fetchone()
                if row:
                    nova_qtd = float(row[0]) + qtd_input

            cur.execute("""
                UPDATE estoque_manual SET
                    referencia = ?, peso_conjunto = ?, preco_conjunto = ?,
                    id_qualidfab = ?, id_ondafab = ?, nome_cliente = ?, gramatura = ?, quantidade = ?
                WHERE id_estoque = ?
            """, (
                dados.get("referencia", ""),
                float(dados.get("peso_conjunto", 0.0) or 0.0),
                float(dados.get("preco_conjunto", 0.0) or 0.0),
                dados.get("id_qualidfab", ""),
                dados.get("id_ondafab", ""),
                dados.get("nome_cliente", ""),
                dados.get("gramatura", ""),
                nova_qtd,
                id_estoque
            ))
            conn.commit()
            conn.close()
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500


@app.route("/api/estoque/<int:id_estoque>", methods=["DELETE"])
def deletar_estoque(id_estoque):
    try:
        with db_lock:
            conn = get_sqlite_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM estoque_manual WHERE id_estoque = ?", (id_estoque,))
            conn.commit()
            conn.close()
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500


@app.route("/api/geocode", methods=["GET"])
def geocode_cliente():
    id_cliente = request.args.get("id_cliente")
    endereco_completo = request.args.get("endereco")
    
    if not id_cliente or not endereco_completo:
        return jsonify({"erro": "id_cliente e endereco sao obrigatorios"}), 400
        
    try:
        # Check SQLite Cache
        with db_lock:
            conn = get_sqlite_conn()
            cur = conn.cursor()
            cur.execute("SELECT latitude, longitude FROM clientes_geolocalizacao WHERE id_cliente = ?", (id_cliente,))
            row = cur.fetchone()
            if row:
                conn.close()
                return jsonify({"lat": row[0], "lng": row[1], "cached": True}), 200
            
        # Not in cache, call Google Maps
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            if conn: conn.close()
            return jsonify({"erro": "API Key nao configurada"}), 500
            
        url = f"https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": endereco_completo,
            "components": "country:BR",
            "key": api_key
        }
        resp = requests.get(url, params=params)
        data = resp.json()
        
        if data.get("status") == "OK" and len(data.get("results", [])) > 0:
            result = data["results"][0]
            lat = result["geometry"]["location"]["lat"]
            lng = result["geometry"]["location"]["lng"]
            place_id = result.get("place_id", "")
            origem = result["geometry"].get("location_type", "GOOGLE")
            
            # Save to cache
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with db_lock:
                cur.execute("""
                    INSERT OR REPLACE INTO clientes_geolocalizacao 
                    (id_cliente, endereco_consultado, latitude, longitude, place_id, origem, data_atualizacao)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (id_cliente, endereco_completo, lat, lng, place_id, origem, agora))
                conn.commit()
                conn.close()
                
            return jsonify({"lat": lat, "lng": lng, "cached": False}), 200
        else:
            print(f"DEBUG: Geocode Google falhou: {data}. Tentando Nominatim...")
            try:
                nom_url = "https://nominatim.openstreetmap.org/search"
                nom_params = {"q": endereco_completo, "format": "json", "limit": 1}
                nom_headers = {"User-Agent": "FivelControl/1.0"}
                nom_resp = requests.get(nom_url, params=nom_params, headers=nom_headers)
                nom_data = nom_resp.json()
                
                if isinstance(nom_data, list) and len(nom_data) > 0:
                    result = nom_data[0]
                    lat = float(result["lat"])
                    lng = float(result["lon"])
                    place_id = str(result.get("place_id", ""))
                    origem = "NOMINATIM"
                    
                    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    with db_lock:
                        cur.execute("""
                            INSERT OR REPLACE INTO clientes_geolocalizacao 
                            (id_cliente, endereco_consultado, latitude, longitude, place_id, origem, data_atualizacao)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (id_cliente, endereco_completo, lat, lng, place_id, origem, agora))
                        conn.commit()
                        conn.close()
                    return jsonify({"lat": lat, "lng": lng, "cached": False}), 200
                else:
                    print(f"DEBUG: Nominatim falhou. Tentando BrasilAPI via CEP...")
                    import re
                    cep_match = re.search(r'\b\d{5}-?\d{3}\b', endereco_completo)
                    if cep_match:
                        cep = cep_match.group(0).replace('-', '')
                        b_url = f"https://brasilapi.com.br/api/cep/v2/{cep}"
                        b_resp = requests.get(b_url, timeout=5)
                        if b_resp.status_code == 200:
                            b_data = b_resp.json()
                            if "location" in b_data and "coordinates" in b_data["location"]:
                                coords = b_data["location"]["coordinates"]
                                if coords.get("latitude") and coords.get("longitude"):
                                    lat = float(coords["latitude"])
                                    lng = float(coords["longitude"])
                                    place_id = b_data.get("cep", "")
                                    origem = "BRASILAPI"
                                    
                                    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    with db_lock:
                                        cur.execute("""
                                            INSERT OR REPLACE INTO clientes_geolocalizacao 
                                            (id_cliente, endereco_consultado, latitude, longitude, place_id, origem, data_atualizacao)
                                            VALUES (?, ?, ?, ?, ?, ?, ?)
                                        """, (id_cliente, endereco_completo, lat, lng, place_id, origem, agora))
                                        conn.commit()
                                        conn.close()
                                    return jsonify({"lat": lat, "lng": lng, "cached": False}), 200
            except Exception as ex_nom:
                print(f"ERRO nos fallbacks de geocode: {str(ex_nom)}")
                
            if conn:
                conn.close()
            return jsonify({"erro": "Nao foi possivel geolocalizar o endereco"}), 500
    except Exception as e:
        print(f"ERRO no geocode: {str(e)}")
        if conn:
            conn.close()
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500

@app.route("/api/rastreamento", methods=["GET"])
def obter_rastreamento():
    try:
        numero_romaneio = request.args.get("numero")
        if not numero_romaneio:
            return jsonify({"erro": "Numero do romaneio nao fornecido"}), 400

        conn = None
        cur = None
        with db_lock:
            conn = get_sqlite_conn()
            cur = conn.cursor()
            
            # 1. BuscarПеdidios
            cur.execute("""
                SELECT id_pedido, status
                FROM pedidos
                WHERE numero_romaneio = ?
            """, (numero_romaneio,))
            pedidos = [{"id": r[0], "status": r[1]} for r in cur.fetchall()]

            # 2. Buscar OFs
            cur.execute("""
                SELECT id_of, status
                FROM ofs
                WHERE numero_romaneio = ?
            """, (numero_romaneio,))
            ofs = [{"id": r[0], "status": r[1]} for r in cur.fetchall()]

            # 3. Buscar Categ_compras
            cur.execute("""
                SELECT id_compra, status
                FROM categ_compras
                WHERE numero_romaneio = ?
            """, (numero_romaneio,))
            compras = [{"id": r[0], "status": r[1]} for r in cur.fetchall()]

            # 4. Buscar Estoque_manual
            cur.execute("""
                SELECT id_estoque, status
                FROM estoque_manual
                WHERE numero_romaneio = ?
            """, (numero_romaneio,))
            estoques = [{"id": r[0], "status": r[1]} for r in cur.fetchall()]

        # 5. Buscar Estoque_auto
        estoque_auto = []
        cur.execute("""
            SELECT id_ft_principal, cliente, quantidade, data_criacao
            FROM estoque_auto
            WHERE numero_romaneio = ?
        """, (numero_romaneio,))
        rows_auto = cur.fetchall()
        
        colunas_auto = [desc[0] for desc in cur.description]
        for row in rows_auto:
            d = dict(zip(colunas_auto, row))
            # Formatar para o padrão desejado
            estoque_auto.append({
                "id_estoque": d.get("id_estoque"),
                "cliente": d.get("cliente"),
                "quantidade": d.get("quantidade"),
                "data_criacao": d.get("data_criacao")
            })

        # Montar resposta
        hoje = datetime.now()
        return jsonify(
            {
                "numero_romaneio": numero_romaneio,
                "componentes": {
                    "pedidos": pedidos,
                    "ofs": ofs,
                    "compras_recebidas": compras,
                    "estoque_manual": estoques,
                    "estoque_automatico": estoque_auto,
                    "total_nfs_mes": len(compras) + len(estoques)
                },
                "mes_referencia": f"{hoje.month:02d}/{hoje.year}",
            }
        ), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


def decode_polyline(polyline_str):
    index, lat, lng = 0, 0, 0
    coordinates = []
    changes = {'latitude': 0, 'longitude': 0}
    while index < len(polyline_str):
        for unit in ['latitude', 'longitude']:
            shift, result = 0, 0
            while True:
                byte = ord(polyline_str[index]) - 63
                index += 1
                result |= (byte & 0x1f) << shift
                shift += 5
                if not byte >= 0x20:
                    break
            if (result & 1):
                changes[unit] = ~(result >> 1)
            else:
                changes[unit] = (result >> 1)
        lat += changes['latitude']
        lng += changes['longitude']
        coordinates.append([lat / 100000.0, lng / 100000.0])
    return coordinates


@app.route("/api/optimize_route", methods=["POST"])
def optimize_route():
    try:
        body = request.get_json() or {}
        pedidos = body.get("pedidos", [])
        
        if not pedidos:
            return jsonify({"erro": "Nenhum pedido selecionado"}), 400
            
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            return jsonify({"erro": "API Key nao configurada"}), 500
            
        # Fabric Coordinates (Ruycepel Embalagens)
        origem = {
            "location": {
                "latLng": {
                    "latitude": -23.70938551545255,
                    "longitude": -46.59345608749334
                }
            }
        }
        
        waypoints = []
        for p in pedidos:
            waypoints.append({
                "location": {
                    "latLng": {
                        "latitude": p["lat"],
                        "longitude": p["lng"]
                    }
                }
            })
            
        # Call Google Routes API
        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.optimizedIntermediateWaypointIndex,routes.polyline.encodedPolyline"
        }
        payload = {
            "origin": origem,
            "destination": origem, # Round trip
            "intermediates": waypoints,
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "optimizeWaypointOrder": True
        }
        
        resp = requests.post(url, headers=headers, json=payload)
        data = resp.json()
        
        if "routes" in data and len(data["routes"]) > 0:
            route = data["routes"][0]
            polyline_str = route.get("polyline", {}).get("encodedPolyline", "")
            waypoint_order = route.get("optimizedIntermediateWaypointIndex", [])
            
            if not waypoint_order:
                waypoint_order = list(range(len(waypoints)))
                
            lifo_order = list(reversed(waypoint_order))
            
            # Map waypoint indices to actual order IDs
            pedidos_ids = [p["id"] for p in pedidos]
            ordem_entregas_ids = [pedidos_ids[i] for i in waypoint_order]
            lifo_entregas_ids = [pedidos_ids[i] for i in lifo_order]
            
            coordenadas = decode_polyline(polyline_str) if polyline_str else []
            
            return jsonify({
                "coordenadas": coordenadas,
                "ordem_entregas": ordem_entregas_ids,
                "lifo_entregas": lifo_entregas_ids
            }), 200
        else:
            print("DEBUG: Google Routes failed. Falling back to OSRM...")
            
            # Origin coordinates
            lat_origem = origem['location']['latLng']['latitude']
            lng_origem = origem['location']['latLng']['longitude']
            
            coords_str = f"{lng_origem},{lat_origem}"
            for p in pedidos:
                coords_str += f";{p['lng']},{p['lat']}"
                
            osrm_url = f"http://router.project-osrm.org/trip/v1/driving/{coords_str}?roundtrip=true&source=first&destination=last&overview=full"
            osrm_resp = requests.get(osrm_url)
            osrm_data = osrm_resp.json()
            
            if osrm_data.get("code") == "Ok":
                trip = osrm_data["trips"][0]
                polyline_str = trip["geometry"]
                
                # OSRM returns waypoints in original input order.
                # Each waypoint has a 'waypoint_index' showing its position in the trip.
                # We sort the pedidos indices (0..N-1) by their trip position.
                ordered_pedidos = sorted(
                    range(len(pedidos)),
                    key=lambda i: osrm_data["waypoints"][i+1]["waypoint_index"]
                )
                waypoint_order = ordered_pedidos
                
                if not waypoint_order:
                    waypoint_order = list(range(len(pedidos)))
                    
                lifo_order = list(reversed(waypoint_order))
                
                pedidos_ids = [p["id"] for p in pedidos]
                ordem_entregas_ids = [pedidos_ids[i] for i in waypoint_order]
                lifo_entregas_ids = [pedidos_ids[i] for i in lifo_order]
                
                coordenadas = decode_polyline(polyline_str) if polyline_str else []
                
                return jsonify({
                    "coordenadas": coordenadas,
                    "ordem_entregas": ordem_entregas_ids,
                    "lifo_entregas": lifo_entregas_ids
                }), 200
            else:
                return jsonify({"erro": "Nenhuma rota retornada", "detalhes": osrm_data}), 400
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
