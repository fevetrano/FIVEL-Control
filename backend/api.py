import os
import re
import json
import sqlite3
import traceback
import threading
import time
from datetime import date, datetime, timedelta
import requests
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
import fdb
from flask import Flask, jsonify, request, send_from_directory
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
dist_local = os.path.join(BASE_DIR, "dist")
dist_dev = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend", "dist"))
FRONTEND_DIST = dist_local if os.path.exists(dist_local) else dist_dev
app = Flask(__name__, static_folder=FRONTEND_DIST, static_url_path="")
CORS(app)


# --- PARÂMETROS DE NEGÓCIO ---
# Pontos de corte: a partir deles os números do ERP são confiáveis.
DATA_CORTE_PEDIDOS = "2026-07-01"
DATA_CORTE_ORCAMENTOS = "2026-01-01"
OC_INICIAL_COMPRAS = 1863
# Pedidos ignorados nas listas (15931: entregas programadas por meses, anterior ao corte).
PEDIDOS_EXCLUIDOS = (15931,)

# Norma do papelão ondulado: variação de 10% na quantidade. Faturou 90% = OF encerrada.
TOLERANCIA_FATURAMENTO = 0.90
STATUS_OF_VALIDOS = ("Pendente", "Compras", "Produção", "Parcial", "Pronto", "Faturada")

COORDENADAS_FABRICA = (-23.70938551545255, -46.59345608749334)

# Timeout (conexão, resposta) em segundos para APIs externas.
TIMEOUT_GEOCODE = (5, 10)
TIMEOUT_ROTAS = (5, 30)

# Histórico mensal: primeiro mês com fechamento automático e os valores
# do fechamento de outubro/2026 informados manualmente.
HISTORICO_INICIO = (2026, 11)
FECHAMENTOS_INICIAIS = {
    (2026, 10): {"saida_kg": 32407.89},
    (2026, 11): {"aberto_inicio_kg": 9957.09},
}
INTERVALO_FECHAMENTO_SEG = 600

SQL_PEDIDOS_EXCLUIDOS = ", ".join(str(int(p)) for p in PEDIDOS_EXCLUIDOS)


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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clientes_ignorados (
                id_cliente TEXT PRIMARY KEY,
                data_ignorado TEXT
            )
        """)
        # Um registro por mês: peso em aberto no dia 01 e peso total faturado no mês.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fechamento_mensal (
                ano INTEGER NOT NULL,
                mes INTEGER NOT NULL,
                aberto_inicio_kg REAL,
                aberto_registrado_em TEXT,
                aberto_origem TEXT,
                saida_kg REAL,
                saida_registrado_em TEXT,
                saida_origem TEXT,
                PRIMARY KEY (ano, mes)
            )
        """)
        conn.commit()
        conn.close()

    for (ano, mes), valores in FECHAMENTOS_INICIAIS.items():
        if "aberto_inicio_kg" in valores:
            registrar_fechamento(ano, mes, "aberto", valores["aberto_inicio_kg"], "manual")
        if "saida_kg" in valores:
            registrar_fechamento(ano, mes, "saida", valores["saida_kg"], "manual")


# --- FECHAMENTO MENSAL (SQLite) ---


def ler_fechamento(ano, mes):
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT aberto_inicio_kg, aberto_registrado_em, aberto_origem, saida_kg, saida_registrado_em, saida_origem "
            "FROM fechamento_mensal WHERE ano = ? AND mes = ?",
            (ano, mes),
        )
        row = cur.fetchone()
        conn.close()
    if not row:
        return None
    return {
        "aberto_inicio_kg": row[0],
        "aberto_registrado_em": row[1],
        "aberto_origem": row[2],
        "saida_kg": row[3],
        "saida_registrado_em": row[4],
        "saida_origem": row[5],
    }


def registrar_fechamento(ano, mes, campo, valor, origem):
    """Grava 'aberto' (peso em aberto no dia 01) ou 'saida' (peso faturado no mês).
    Um valor já registrado nunca é sobrescrito."""
    coluna = {"aberto": "aberto_inicio_kg", "saida": "saida_kg"}[campo]
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO fechamento_mensal (ano, mes) VALUES (?, ?)", (ano, mes))
        cur.execute(
            f"UPDATE fechamento_mensal SET {coluna} = ?, {campo}_registrado_em = ?, {campo}_origem = ? "
            f"WHERE ano = ? AND mes = ? AND {coluna} IS NULL",
            (valor, agora, origem, ano, mes),
        )
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


def _gravar_status(cur, categoria, chave, valor, qtd_produzida, agora):
    # Quantidade e data de produção já gravadas são mantidas quando não informadas,
    # para a troca de status não apagar o apontamento anterior.
    cur.execute(
        "SELECT data_producao, qtd_produzida FROM kanban_status WHERE categoria=? AND chave=?",
        (categoria, str(chave)),
    )
    row = cur.fetchone()
    data_prod = row[0] if row and row[0] else None
    if data_prod is None and valor == "Produção":
        data_prod = agora
    if qtd_produzida is None and row:
        qtd_produzida = row[1]

    cur.execute(
        "INSERT OR REPLACE INTO kanban_status (categoria, chave, status, data_producao, qtd_produzida) VALUES (?, ?, ?, ?, ?)",
        (categoria, str(chave), str(valor), data_prod, qtd_produzida),
    )


def safe_update_status(categoria, chave, valor, qtd_produzida=None):
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _gravar_status(cur, categoria, chave, valor, qtd_produzida, agora)
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
            _gravar_status(cur, categoria, chave, valor, None, agora)
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
    # Faturado dentro da tolerância encerra a OF mesmo com status manual.
    if is_faturada_total:
        return "Faturada"
    if status_manual:
        return status_manual
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

        # Query de OFs com filtro direto da fábrica (parâmetros vêm de constantes do servidor)
        query = f"""
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
            WHERE (p.EMISSAO >= '{DATA_CORTE_PEDIDOS}' OR p.DATA_ENTREGA >= '{DATA_CORTE_PEDIDOS}' OR o.DTPROG >= '{DATA_CORTE_PEDIDOS}')
              AND p.ID_EMPRESA IN (1, 2)
              AND (p.CANCELADO IS NULL OR p.CANCELADO <> 'S')
              AND (p.PEDIDO_BLOQUEADO IS NULL OR p.PEDIDO_BLOQUEADO <> 'S')
              AND (p.DESATIVADO IS NULL OR p.DESATIVADO <> 'S')
              AND (o.DESATIVADO IS NULL OR o.DESATIVADO <> 'S')
              AND (o.LIQUIDADO IS NULL OR o.LIQUIDADO <> 'S')
              AND p.ID_NUMPED NOT IN ({SQL_PEDIDOS_EXCLUIDOS})
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
                    "peso_total_pedido_bruto": float(row.get("peso_total_pedido") or 0.0),
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
                if qtd_faturada_of >= (qtd_of * TOLERANCIA_FATURAMENTO):
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


def mes_anterior(ano, mes):
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


def proximo_mes(ano, mes):
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def calcular_saida_mes_kg(cur, ano, mes):
    """Peso total faturado no mês: NFs + recibos."""
    cur.execute(
        """SELECT COALESCE(SUM(OI_BRUTO), 0) FROM FISCAL
           WHERE EMISS_ANO = ? AND EMISS_MES = ? AND ID_EMPRESA IN (1, 2)
             AND (CANCELADA IS NULL OR CANCELADA <> 'S')
             AND (IGNORAR_PESO IS NULL OR IGNORAR_PESO <> 'S')""",
        (ano, mes),
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
        (ano, mes),
    )
    peso_recs = float(cur.fetchone()[0] or 0.0)
    return peso_nfs + peso_recs


def calcular_peso_aberto_kg(data_inicio_mes):
    """Peso em aberto agora dos pedidos emitidos antes de data_inicio_mes."""
    total = 0.0
    for pedido in get_pedidos_processados():
        try:
            dt_emissao = datetime.strptime(pedido.get("raw_emissao") or "", "%Y-%m-%d").date()
        except ValueError:
            continue
        peso_aberto = pedido.get("peso_total_kg", 0.0)
        if dt_emissao < data_inicio_mes and pedido.get("status") != "Faturada" and peso_aberto > 0:
            total += peso_aberto
    return total


_fechamento_lock = threading.Lock()


def garantir_fechamentos():
    """Fechamento automático: grava o peso faturado de cada mês encerrado desde o início
    do histórico e o peso em aberto no início do mês corrente (uma única vez por mês)."""
    if not _fechamento_lock.acquire(blocking=False):
        return
    try:
        hoje = date.today()
        atual = (hoje.year, hoje.month)
        if atual < HISTORICO_INICIO:
            return

        meses_sem_saida = []
        mes_ref = HISTORICO_INICIO
        while mes_ref < atual:
            fech = ler_fechamento(*mes_ref)
            if not fech or fech["saida_kg"] is None:
                meses_sem_saida.append(mes_ref)
            mes_ref = proximo_mes(*mes_ref)

        if meses_sem_saida:
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                for ano, mes in meses_sem_saida:
                    registrar_fechamento(ano, mes, "saida", calcular_saida_mes_kg(cur, ano, mes), "automatico")
            finally:
                conn.close()

        fech_atual = ler_fechamento(*atual)
        if not fech_atual or fech_atual["aberto_inicio_kg"] is None:
            peso = calcular_peso_aberto_kg(date(atual[0], atual[1], 1))
            registrar_fechamento(atual[0], atual[1], "aberto", peso, "automatico")
    except Exception:
        traceback.print_exc()
    finally:
        _fechamento_lock.release()


def _loop_fechamento():
    while True:
        garantir_fechamentos()
        time.sleep(INTERVALO_FECHAMENTO_SEG)


@app.route("/api/calendario_pesos", methods=["GET"])
def obter_calendario_pesos():
    conn = None
    try:
        hoje = datetime.now()
        mes = int(request.args.get("mes") or hoje.month)
        ano = int(request.args.get("ano") or hoje.year)
        if not 1 <= mes <= 12:
            return jsonify({"erro": "Mês inválido"}), 400

        garantir_fechamentos()
        ano_ant, mes_ant = mes_anterior(ano, mes)

        conn = get_db_connection()
        cur = conn.cursor()

        # Saída do mês anterior: valor congelado no fechamento ou, sem registro, calculado do ERP.
        fech_anterior = ler_fechamento(ano_ant, mes_ant)
        saida_registrada = bool(fech_anterior and fech_anterior["saida_kg"] is not None)
        if saida_registrada:
            saida_anterior = fech_anterior["saida_kg"]
        else:
            saida_anterior = calcular_saida_mes_kg(cur, ano_ant, mes_ant)

        # Entrada diária: todos os pedidos emitidos no dia, inclusive os já faturados.
        cur.execute(
            f"""SELECT p.EMISSAO, p.TOTAL_PESO FROM PEDIDOS p
               WHERE EXTRACT(YEAR FROM p.EMISSAO) = ?
                 AND EXTRACT(MONTH FROM p.EMISSAO) = ?
                 AND p.ID_EMPRESA IN (1, 2)
                 AND (p.CANCELADO IS NULL OR p.CANCELADO <> 'S')
                 AND (p.PEDIDO_BLOQUEADO IS NULL OR p.PEDIDO_BLOQUEADO <> 'S')
                 AND (p.DESATIVADO IS NULL OR p.DESATIVADO <> 'S')
                 AND p.ID_NUMPED NOT IN ({SQL_PEDIDOS_EXCLUIDOS})""",
            (ano, mes),
        )
        dias_calendario = {str(dia): 0.0 for dia in range(1, 32)}
        for emissao, peso in cur.fetchall():
            if emissao:
                dias_calendario[str(emissao.day)] += float(peso or 0.0)
        entrada_mes_kg = sum(dias_calendario.values())

        fech = ler_fechamento(ano, mes)
        peso_entrada = fech["aberto_inicio_kg"] if fech else None

        return jsonify({
            "saida_mes_anterior_kg": saida_anterior,
            "saida_registrada": saida_registrada,
            "peso_entrada_kg": peso_entrada,
            "peso_entrada_registrado_em": fech["aberto_registrado_em"] if fech else None,
            "entrada_mes_kg": entrada_mes_kg,
            "total_mes_kg": (peso_entrada + entrada_mes_kg) if peso_entrada is not None else None,
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

        query = f"""
            SELECT
                o.ID_ORCAMENTO, o.EMISSAO, o.VALIDADE, o.ID_CLIENTE, o.NOME_CLIENTE,
                o.COMPRADOR, o.FONE, o.COND_PAGTO, o.PRAZO_ENTREGA, o.TOTAL_GERAL, o.TOTAL_PESO,
                i.REFERENCIA, i.MODELO_CAIXA, i.FECHAMENTO, i.COMP, i.LARG, i.ALT,
                i.QUANT, i.VLUNIT, i.VLTOT, i.ID_ONDAFAB, i.ID_QUALIDFAB, i.COR1, i.COR2, i.APROVADO
            FROM ORCAMENT o
            LEFT JOIN ORCITEM i ON o.ID_ORCAMENTO = i.ID_ORCAMENTO
            WHERE (o.DESATIVADO IS NULL OR o.DESATIVADO <> 'S')
              AND o.EMISSAO >= '{DATA_CORTE_ORCAMENTOS}'
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

        query = f"""
            SELECT
                c.ID_ORDCOMPRA, c.EMISSAO, c.DATA_ENTREGA, c.NOME_FORNECEDOR, c.TOTAL_KG, c.TOTAL_GERAL, c.STATUS, c.DATA_RECEBIDA,
                ci.ITEM, ci.QUANT AS QUANT_CHAPA, ci.PESO AS PESO_CHAPA, (ci.QUANT * COALESCE(ci.PR_FL, 0)) AS VLTOT, ci.LARG, ci.COMP, co.ID_NUMOF, co.NOME AS CLIENTE, co.QUANT AS QUANT_OF,
                p.REFERENCIA, p.FECHA
            FROM OC_CHAPA c
            LEFT JOIN OC_CHAPA_ITEM ci ON c.ID_ORDCOMPRA = ci.ID_ORDCOMPRA
            LEFT JOIN OC_CHAPA_OF co ON c.ID_ORDCOMPRA = co.ID_ORDCOMPRA AND ci.ITEM = co.ITEM
            LEFT JOIN ORDFAB o ON o.ID_NUMOF = co.ID_NUMOF
            LEFT JOIN PEDITEM p ON p.ID_NUMPED = o.ID_NUMPED AND p.ID_PRODUTO = o.ID_PRODUTO
            WHERE c.ID_ORDCOMPRA >= {OC_INICIAL_COMPRAS}
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
            "SELECT STATUS, DATA_RECEBIDA FROM OC_CHAPA WHERE ID_ORDCOMPRA = ?", (id_compra,)
        )
        oc = cur.fetchone()
        if not oc:
            return jsonify({"erro": f"OC {id_compra} não encontrada."}), 404
        if limpar_texto(oc[0]).upper() == "RECEBIDA" or oc[1] is not None:
            data_rec = format_date_safe(oc[1])
            return jsonify({"erro": f"OC {id_compra} já foi recebida{' em ' + data_rec if data_rec else ''}."}), 409

        cur.execute(
            """SELECT DISTINCT co.ID_NUMOF, o.LIQUIDADO
               FROM OC_CHAPA_OF co
               LEFT JOIN ORDFAB o ON o.ID_NUMOF = co.ID_NUMOF
               WHERE co.ID_ORDCOMPRA = ?""",
            (id_compra,),
        )
        ofs = [(str(r[0]), limpar_texto(r[1]).upper() == "S") for r in cur.fetchall() if r[0]]

        cur.execute(
            "UPDATE OC_CHAPA SET STATUS = 'RECEBIDA', DATA_RECEBIDA = 'TODAY' WHERE ID_ORDCOMPRA = ?",
            (id_compra,),
        )
        conn.commit()
        invalidar_cache_db()

        # Só tira de Pendente/Compras. OF que já avançou mantém o status para não gerar peso fantasma.
        status_ofs_local = carregar_kanban_local().get("ofs", {})
        atualizacoes, avisos = {}, []
        for id_of, liquidada in ofs:
            status_manual = (status_ofs_local.get(id_of) or {}).get("status")
            if liquidada or status_manual == "Faturada":
                avisos.append(f"OF {id_of} já está faturada.")
            elif status_manual in ("Pendente", "Compras"):
                atualizacoes[id_of] = "Produção"
        if atualizacoes:
            safe_update_status_lote("ofs", atualizacoes)

        return jsonify({"sucesso": True, "ofs_para_producao": list(atualizacoes), "avisos": avisos}), 200
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


def ler_qtd_produzida(valor):
    """Quantidade informada pelo operador: None quando vazia. Lança ValueError se inválida."""
    if valor is None or str(valor).strip() == "":
        return None
    qtd = float(str(valor).replace(",", "."))
    if qtd < 0:
        raise ValueError("Quantidade negativa")
    return qtd


@app.route("/api/pedidos/<int:id_pedido>/status", methods=["PUT"])
def atualizar_status_unidade(id_pedido):
    try:
        novo_status = (request.get_json() or {}).get("status", "Pendente")
        if novo_status not in STATUS_OF_VALIDOS:
            return jsonify({"erro": f"Status inválido: {novo_status}"}), 400
        safe_update_status("pedidos", id_pedido, novo_status)
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/pedidos/<int:id_pedido>/itens/<path:id_of>/status", methods=["PUT"])
def atualizar_status_of(id_pedido, id_of):
    try:
        dados = request.get_json() or {}
        novo_status = dados.get("status", "Pendente")
        if novo_status not in STATUS_OF_VALIDOS:
            return jsonify({"erro": f"Status inválido: {novo_status}"}), 400
        try:
            qtd_val = ler_qtd_produzida(dados.get("qtd_produzida"))
        except ValueError:
            return jsonify({"erro": "Quantidade inválida"}), 400

        safe_update_status("ofs", id_of, novo_status, qtd_val)
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/ofs/status-rapido", methods=["PUT"])
def atualizar_status_rapido_of():
    conn = None
    try:
        dados = request.get_json() or {}
        id_of = str(dados.get("id_of") or "").strip()
        novo_status = dados.get("status")
        if not id_of or not novo_status:
            return jsonify({"erro": "Informe a OF e o status."}), 400
        if not id_of.isdigit():
            return jsonify({"erro": f"OF {id_of} inválida: use só números."}), 400
        if novo_status not in STATUS_OF_VALIDOS:
            return jsonify({"erro": f"Status inválido: {novo_status}"}), 400
        try:
            qtd_val = ler_qtd_produzida(dados.get("qtd_produzida"))
        except ValueError:
            return jsonify({"erro": "Quantidade inválida"}), 400

        # Digitação errada não pode criar status para OF inexistente.
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT LIQUIDADO, DESATIVADO FROM ORDFAB WHERE ID_NUMOF = ?", (int(id_of),)
        )
        of = cur.fetchone()
        if not of:
            return jsonify({"erro": f"OF {id_of} não encontrada."}), 404
        if limpar_texto(of[1]).upper() == "S":
            return jsonify({"erro": f"OF {id_of} está desativada."}), 409
        if limpar_texto(of[0]).upper() == "S":
            return jsonify({"erro": f"OF {id_of} já foi faturada."}), 409

        safe_update_status("ofs", id_of, novo_status, qtd_val)
        return jsonify({"sucesso": True}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route("/api/pedidos/status-lote", methods=["PUT"])
def atualizar_status_lote():
    try:
        dados = request.get_json() or {}
        ids, novo_status = dados.get("ids", []), dados.get("status", "Pendente")
        if not ids:
            return jsonify({"erro": "Nenhum ID"}), 400
        if novo_status not in STATUS_OF_VALIDOS:
            return jsonify({"erro": f"Status inválido: {novo_status}"}), 400
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


def _normalizar_endereco(endereco):
    return " ".join(str(endereco or "").upper().split())


def _ler_geocode_cache(id_cliente):
    with db_lock:
        conn = get_sqlite_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT latitude, longitude, endereco_consultado FROM clientes_geolocalizacao WHERE id_cliente = ?",
            (id_cliente,),
        )
        row = cur.fetchone()
        conn.close()
    return row


def _salvar_geocode_cache(id_cliente, endereco, lat, lng, place_id, origem):
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        conn = get_sqlite_conn()
        conn.execute(
            """INSERT OR REPLACE INTO clientes_geolocalizacao
               (id_cliente, endereco_consultado, latitude, longitude, place_id, origem, data_atualizacao)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (id_cliente, endereco, lat, lng, place_id, origem, agora),
        )
        conn.commit()
        conn.close()


def _geocode_google(endereco):
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return None
    resp = requests.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": endereco, "components": "country:BR", "key": api_key},
        timeout=TIMEOUT_GEOCODE,
    )
    data = resp.json()
    if data.get("status") != "OK" or not data.get("results"):
        print(f"DEBUG: Geocode Google sem resultado ({data.get('status')}). Tentando Nominatim...")
        return None
    result = data["results"][0]
    loc = result["geometry"]["location"]
    return loc["lat"], loc["lng"], result.get("place_id", ""), result["geometry"].get("location_type", "GOOGLE")


def _geocode_nominatim(endereco):
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": endereco, "format": "json", "limit": 1, "countrycodes": "br"},
        headers={"User-Agent": "FivelControl/1.0"},
        timeout=TIMEOUT_GEOCODE,
    )
    data = resp.json()
    if not isinstance(data, list) or not data:
        print("DEBUG: Nominatim sem resultado. Tentando BrasilAPI via CEP...")
        return None
    return float(data[0]["lat"]), float(data[0]["lon"]), str(data[0].get("place_id", "")), "NOMINATIM"


def _geocode_brasilapi(endereco):
    cep_match = re.search(r"\b\d{5}-?\d{3}\b", endereco)
    if not cep_match:
        return None
    cep = cep_match.group(0).replace("-", "")
    resp = requests.get(f"https://brasilapi.com.br/api/cep/v2/{cep}", timeout=TIMEOUT_GEOCODE)
    if resp.status_code != 200:
        return None
    coords = (resp.json().get("location") or {}).get("coordinates") or {}
    if not coords.get("latitude") or not coords.get("longitude"):
        return None
    return float(coords["latitude"]), float(coords["longitude"]), cep, "BRASILAPI"


@app.route("/api/geocode", methods=["GET"])
def geocode_cliente():
    id_cliente = request.args.get("id_cliente")
    endereco_completo = request.args.get("endereco")

    if not id_cliente or not endereco_completo:
        return jsonify({"erro": "id_cliente e endereco sao obrigatorios"}), 400

    try:
        # O cache só vale se o endereço não mudou; evita repetir chamadas pagas ao Google.
        cache = _ler_geocode_cache(id_cliente)
        if cache and _normalizar_endereco(cache[2]) == _normalizar_endereco(endereco_completo):
            return jsonify({"lat": cache[0], "lng": cache[1], "cached": True}), 200

        # Cascata Google -> Nominatim -> BrasilAPI: falha ou timeout passa para o próximo.
        for provedor in (_geocode_google, _geocode_nominatim, _geocode_brasilapi):
            try:
                resultado = provedor(endereco_completo)
            except Exception as ex:
                print(f"ERRO no geocode ({provedor.__name__}): {ex}")
                continue
            if resultado:
                lat, lng, place_id, origem = resultado
                _salvar_geocode_cache(id_cliente, endereco_completo, lat, lng, place_id, origem)
                return jsonify({"lat": lat, "lng": lng, "cached": False}), 200

        # Endereço mudou e o novo não foi encontrado: mantém a posição conhecida.
        if cache:
            return jsonify({"lat": cache[0], "lng": cache[1], "cached": True, "desatualizado": True}), 200
        return jsonify({"erro": "Nao foi possivel geolocalizar o endereco"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500


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
                    "latitude": COORDENADAS_FABRICA[0],
                    "longitude": COORDENADAS_FABRICA[1]
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
        
        # Falha ou timeout do Google cai para o OSRM em vez de derrubar a requisição.
        try:
            data = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT_ROTAS).json()
        except Exception as ex:
            print(f"ERRO no Google Routes: {ex}")
            data = {}
        
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
                
            osrm_url = f"https://router.project-osrm.org/trip/v1/driving/{coords_str}?roundtrip=true&source=first&destination=last&overview=full"
            osrm_resp = requests.get(osrm_url, timeout=TIMEOUT_ROTAS)
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

@app.route("/api/comercial/clientes/<id_cliente>/ignorar", methods=["POST"])
def ignorar_cliente_comercial(id_cliente):
    try:
        dados = request.get_json() or {}
        ignorar = dados.get("ignorar", True)
        
        with db_lock:
            conn = get_sqlite_conn()
            cur = conn.cursor()
            if ignorar:
                agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cur.execute("INSERT OR REPLACE INTO clientes_ignorados (id_cliente, data_ignorado) VALUES (?, ?)", (str(id_cliente), agora))
            else:
                cur.execute("DELETE FROM clientes_ignorados WHERE id_cliente = ?", (str(id_cliente),))
            conn.commit()
            conn.close()
        return jsonify({"sucesso": True, "ignorado": ignorar}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500

@app.route("/api/comercial/recorrencia", methods=["GET"])
def obter_recorrencia_comercial():
    conn = None
    try:
        # 1. Carregar clientes ignorados localmente
        clientes_ignorados = set()
        with db_lock:
            sqlite_conn = get_sqlite_conn()
            scur = sqlite_conn.cursor()
            try:
                scur.execute("SELECT id_cliente FROM clientes_ignorados")
                for row in scur.fetchall():
                    clientes_ignorados.add(str(row[0]))
            except sqlite3.OperationalError:
                pass
            sqlite_conn.close()

        conn = get_db_connection()
        cur = conn.cursor()
        
        dois_anos_atras = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
        
        query = f"""
            SELECT 
                c.ID_CLIENTE,
                COALESCE(NULLIF(TRIM(c.GUERRA), ''), c.NOME) AS CLIENTE,
                c.NOME AS RAZAO_SOCIAL,
                c.CIDADE,
                COALESCE(NULLIF(TRIM(c.EMAIL1), ''), NULLIF(TRIM(c.EMAIL2), ''), c.EMAIL_NF1) AS EMAIL,
                CASE 
                    WHEN c.FONE_1 IS NOT NULL AND TRIM(c.FONE_1) <> '' THEN
                        COALESCE('(' || TRIM(c.DDD_FONE_1) || ') ', '') || TRIM(c.FONE_1)
                    WHEN c.FONE_2 IS NOT NULL AND TRIM(c.FONE_2) <> '' THEN
                        COALESCE('(' || TRIM(c.DDD_FONE_2) || ') ', '') || TRIM(c.FONE_2)
                    ELSE NULL
                END AS TELEFONE,
                c.CONTATO_1 AS CONTATO,
                COUNT(p.ID_NUMPED) AS TOTAL_PEDIDOS,
                MIN(p.EMISSAO) AS PRIMEIRO_PEDIDO,
                MAX(p.EMISSAO) AS ULTIMO_PEDIDO
            FROM CLIENTES c
            JOIN PEDIDOS p ON p.ID_CLIENTE = c.ID_CLIENTE
            WHERE p.EMISSAO >= '{dois_anos_atras}'
              AND (p.CANCELADO IS NULL OR p.CANCELADO <> 'S')
              AND (c.DESATIVADO IS NULL OR c.DESATIVADO <> 'S')
            GROUP BY 
                c.ID_CLIENTE, c.GUERRA, c.NOME, c.CIDADE,
                c.EMAIL1, c.EMAIL2, c.EMAIL_NF1,
                c.DDD_FONE_1, c.FONE_1, c.DDD_FONE_2, c.FONE_2, c.CONTATO_1
            HAVING COUNT(p.ID_NUMPED) > 1
        """
        
        cur.execute(query)
        colunas = [desc[0].lower() for desc in cur.description]
        registros = cur.fetchall()
        
        lista_recorrencia = []
        resumo = {"Em Dia": 0, "Atenção": 0, "Atrasado": 0, "Total": 0}
        
        for reg in registros:
            row = dict(zip(colunas, reg))
            id_cliente = str(row.get("id_cliente"))
            
            # Filtra ignorados
            if id_cliente in clientes_ignorados:
                continue
                
            primeiro_pedido = row.get("primeiro_pedido")
            ultimo_pedido = row.get("ultimo_pedido")
            total_pedidos = int(row.get("total_pedidos") or 0)
            
            if not primeiro_pedido or not ultimo_pedido or total_pedidos <= 1:
                continue
                
            p_date = primeiro_pedido.date() if isinstance(primeiro_pedido, datetime) else primeiro_pedido
            u_date = ultimo_pedido.date() if isinstance(ultimo_pedido, datetime) else ultimo_pedido
            
            dias_totais = (u_date - p_date).days
            media_dias = dias_totais / (total_pedidos - 1)
            
            dias_sem_comprar = (datetime.now().date() - u_date).days
            
            # Regras de Faixa de Recorrência
            if media_dias <= 7:
                grupo_recorrencia = "1. Até 1 semana"
            elif media_dias <= 14:
                grupo_recorrencia = "2. 1 a 2 semanas"
            elif media_dias <= 28:
                grupo_recorrencia = "3. 3 a 4 semanas (Mensal)"
            elif media_dias <= 60:
                grupo_recorrencia = "4. Bimestral (2 meses)"
            elif media_dias <= 90:
                grupo_recorrencia = "5. Trimestral (3 meses)"
            elif media_dias <= 180:
                grupo_recorrencia = "6. Semestral (4 a 6 meses)"
            else:
                grupo_recorrencia = "7. Acima de 6 meses"
                
            # Calcular Próxima Compra
            data_prevista = ""
            raw_prevista = ""
            if ultimo_pedido and isinstance(ultimo_pedido, (datetime, date)):
                try:
                    up_date = ultimo_pedido.date() if isinstance(ultimo_pedido, datetime) else ultimo_pedido
                    dt_prevista = up_date + timedelta(days=round(media_dias))
                    data_prevista = dt_prevista.strftime("%d/%m/%Y")
                    raw_prevista = dt_prevista.strftime("%Y-%m-%d")
                except Exception:
                    pass
                    
            # Status de Risco
            if dias_sem_comprar <= media_dias:
                status_risco = "Em Dia"
            elif dias_sem_comprar <= (media_dias * 1.5):
                status_risco = "Atenção"
            else:
                status_risco = "Atrasado"
                
            resumo[status_risco] += 1
            resumo["Total"] += 1
            
            lista_recorrencia.append({
                "id_cliente": id_cliente,
                "cliente": limpar_texto(row.get("cliente")),
                "razao_social": limpar_texto(row.get("razao_social")),
                "cidade": limpar_texto(row.get("cidade")),
                "email": limpar_texto(row.get("email")),
                "telefone": limpar_texto(row.get("telefone")),
                "contato": limpar_texto(row.get("contato")),
                "total_pedidos": int(row.get("total_pedidos") or 0),
                "primeiro_pedido": format_date_safe(row.get("primeiro_pedido")),
                "ultimo_pedido": format_date_safe(row.get("ultimo_pedido")),
                "media_dias": round(media_dias, 1),
                "dias_sem_comprar": dias_sem_comprar,
                "grupo_recorrencia": grupo_recorrencia,
                "data_prevista": data_prevista,
                "raw_prevista": raw_prevista,
                "status_risco": status_risco
            })
            
        return jsonify({
            "clientes": lista_recorrencia,
            "resumo": resumo
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    if os.path.exists(os.path.join(app.static_folder, "index.html")):
        return send_from_directory(app.static_folder, "index.html")
    return jsonify({"mensagem": "API do FIVEL Control ativa. Frontend dist não encontrado."}), 200

if __name__ == "__main__":
    threading.Thread(target=_loop_fechamento, name="fechamento-mensal", daemon=True).start()
    app.run(debug=False, host="0.0.0.0", port=int(os.getenv("FIVEL_PORT", 5000)), threaded=True)
