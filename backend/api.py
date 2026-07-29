import os
from datetime import datetime, date
from flask import Flask, jsonify, request
from flask_cors import CORS
import traceback
import fdb
from dotenv import load_dotenv

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


# --- FUNÇÃO DE CONEXÃO COM O FIREBIRD ---
def get_db_connection():
    return fdb.connect(
        host=os.getenv("FIREBIRD_HOST"),
        database=os.getenv("FIREBIRD_DATABASE"),
        user=os.getenv("FIREBIRD_USER"),
        password=os.getenv("FIREBIRD_PASSWORD"),
        port=int(os.getenv("FIREBIRD_PORT", 3050)),
        charset="NONE",  # Usa 'NONE' para desativar a transliteração estrita do Firebird
    )


# --- FUNÇÃO AUXILIAR DE SANITIZAÇÃO E LIMPEZA DE STRING ---
def limpar_texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, bytes):
        try:
            return valor.decode("latin-1", errors="replace").strip()
        except Exception:
            return str(valor).strip()
    return str(valor).strip()


# --- ROTAS DA API ---


@app.route("/api/pedidos", methods=["GET"])
def obter_pedidos():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Consulta com LEFT JOIN em ORDFAB para buscar o ID_NUMOF (Número da OF)
        query = """
            SELECT 
                i.ID_NUMPED AS ID_PEDIDO,
                p.PEDIDO_CLIENTE,
                p.EMISSAO,
                p.DATA_ENTREGA AS PRAZO,
                p.TOTAL_PESO AS PESO_TOTAL_PEDIDO,
                p.TOTAL_GERAL,
                p.CANCELADO,
                p.KANBAN AS STATUS_KANBAN,
                c.ID_CLIENTE,
                c.NOME AS CLIENTE_RAZAO,
                COALESCE(c.GUERRA, c.NOME) AS CLIENTE_FANTASIA,
                
                -- Fallback do Endereço (se entrega for NULO, usa o principal)
                COALESCE(NULLIF(TRIM(c.ENT_ENDERECO), ''), c.ENDERECO) AS ENDERECO,
                COALESCE(c.ENT_NUMERO, c.NUMERO) AS NUMERO,
                COALESCE(NULLIF(TRIM(c.ENT_BAIRRO), ''), c.BAIRRO) AS BAIRRO,
                COALESCE(NULLIF(TRIM(c.ENT_CIDADE), ''), c.CIDADE) AS CIDADE,
                COALESCE(NULLIF(TRIM(c.ENT_ID_ESTADO), ''), c.ID_ESTADO) AS UF,
                COALESCE(NULLIF(TRIM(c.ENT_CEP), ''), c.CEP) AS CEP,
                
                -- Campos da Tabela PEDITEM
                i.ID_PRODUTO,
                i.REFERENCIA,
                i.QUANT AS QUANTIDADE,
                i.COMP AS COMPRIMENTO,
                i.LARG AS LARGURA,
                i.ALT AS ALTURA,
                i.ID_ONDAFAB AS TIPO_ONDA,
                i.ID_QUALIDFAB AS QUALIDADE_PAPEL,
                i.PESO_TOT AS PESO_ITEM,
                i.VLUNIT AS PRECO_UNITARIO,
                i.FECHA,

                -- Campo da Tabela ORDFAB (Número da OF)
                o.ID_NUMOF
            FROM PEDIDOS p
            LEFT JOIN CLIENTES c ON p.ID_CLIENTE = c.ID_CLIENTE
            LEFT JOIN PEDITEM i ON p.ID_NUMPED = i.ID_NUMPED
            LEFT JOIN ORDFAB o ON (o.ID_NUMPED = i.ID_NUMPED AND o.ID_PRODUTO = i.ID_PRODUTO)
            WHERE p.EMISSAO >= '2026-07-01'
              AND NOT EXISTS (
                  SELECT 1 FROM FISCAL f WHERE f.ID_NUMPED = p.ID_NUMPED
              )
            ORDER BY i.ID_NUMPED DESC;
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
                data_emissao_formatada = ""
                raw_emissao_str = ""

                if dt_emissao:
                    try:
                        if isinstance(dt_emissao, (datetime, date)):
                            data_emissao_formatada = dt_emissao.strftime("%d/%m/%Y")
                            raw_emissao_str = dt_emissao.strftime("%Y-%m-%d")
                        else:
                            data_emissao_formatada = str(dt_emissao)
                            raw_emissao_str = str(dt_emissao)
                    except Exception:
                        data_emissao_formatada = str(dt_emissao)

                dt_entrega = row.get("prazo")
                data_entrega_formatada = ""
                raw_entrega_str = ""
                dias_restantes = 999999  # Valor sentinela para ordenação

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
                cliente_nome = cliente_fantasia or cliente_razao or "Cliente Sem Nome"

                cidade = limpar_texto(row.get("cidade"))
                end = limpar_texto(row.get("endereco"))
                num = str(row.get("numero")) if row.get("numero") is not None else ""
                bairro = limpar_texto(row.get("bairro"))

                # Endereço Formatado
                partes_endereco = [p for p in [end, num, bairro] if p]
                endereco_comp = ", ".join(partes_endereco)

                # Mapeia KANBAN (Letra) -> Frontend Status (Apenas: Pendente, Compras, Produção, Pronto)
                status_bruto = limpar_texto(row.get("status_kanban")).upper()
                if status_bruto == "P":
                    status_frontend = "Pronto"
                elif status_bruto == "C":
                    status_frontend = "Compras"
                elif status_bruto == "R":
                    status_frontend = "Produção"
                else:
                    status_frontend = "Pendente"

                pedidos_map[id_ped] = {
                    "id": id_ped,
                    "id_pedido": int(id_ped),
                    "pedido_cliente": limpar_texto(row.get("pedido_cliente")),
                    "cliente": cliente_nome,
                    "razao_social": cliente_razao,
                    "cidade_bloco": cidade,
                    "endereco_completo": endereco_comp,
                    "status": status_frontend,
                    "peso_total_kg": round(peso_tot_kg, 2),
                    "peso_total_ton": round(peso_tot_kg / 1000, 2),
                    "faturamento_total": round(faturamento_tot, 2),
                    "data_emissao": data_emissao_formatada,
                    "raw_emissao": raw_emissao_str,
                    "data_entrega": data_entrega_formatada,
                    "raw_entrega": raw_entrega_str,
                    "dias_restantes": (
                        dias_restantes if dias_restantes != 999999 else None
                    ),
                    "latitude": -23.6939,
                    "longitude": -46.5650,
                    "total_itens": 0,
                    "itens": [],
                }

            if row.get("id_produto"):
                pedidos_map[id_ped]["itens"].append(
                    {
                        "id_numof": row.get(
                            "id_numof"
                        ),  # Número serial real da OF (ex: 29206)
                        "id_produto": limpar_texto(row["id_produto"]),
                        "referencia": limpar_texto(row.get("referencia")),
                        "quantidade": float(row.get("quantidade") or 0.0),
                        "comprimento": row.get("comprimento") or 0,
                        "largura": row.get("largura") or 0,
                        "altura": row.get("altura") or 0,
                        "tipo_onda": limpar_texto(row.get("tipo_onda")),
                        "qualidade_papel": limpar_texto(row.get("qualidade_papel")),
                        "peso_item": float(row.get("peso_item") or 0.0),
                        "preco_unitario": float(row.get("preco_unitario") or 0.0),
                        "fecha": limpar_texto(row.get("fecha")),
                    }
                )
                pedidos_map[id_ped]["total_itens"] = len(pedidos_map[id_ped]["itens"])

        lista_pedidos = list(pedidos_map.values())

        # --- ORDENAÇÃO DINÂMICA VIA PARÂMETROS DA URL ---
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


@app.route("/api/pedidos/<int:id_pedido>/status", methods=["PUT"])
def atualizar_status_unidade(id_pedido):
    conn = None
    try:
        dados = request.get_json() or {}
        novo_status = dados.get("status", "Pendente")

        # Mapeamento do Frontend para a letra da coluna KANBAN no Firebird
        mapeamento = {
            "Pronto": "P",
            "Compras": "C",
            "Produção": "R",
            "Pendente": "N",
        }

        letra_kanban = mapeamento.get(novo_status, "N")

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "UPDATE PEDIDOS SET KANBAN = ? WHERE ID_NUMPED = ?",
            (letra_kanban, id_pedido),
        )

        conn.commit()

        return (
            jsonify({"sucesso": True, "id_pedido": id_pedido, "status": novo_status}),
            200,
        )

    except Exception as e:
        if conn:
            conn.rollback()
        print("ERRO NO UPDATE DE STATUS INDIVIDUAL:", str(e))
        return jsonify({"erro": f"Erro ao atualizar status no Firebird: {str(e)}"}), 500

    finally:
        if conn:
            conn.close()


@app.route("/api/pedidos/status-lote", methods=["PUT"])
def atualizar_status_lote():
    conn = None
    try:
        dados = request.get_json() or {}
        ids = dados.get("ids", [])
        novo_status = dados.get("status", "Pendente")

        if not ids:
            return jsonify({"erro": "Nenhum ID fornecido"}), 400

        mapeamento = {
            "Pronto": "P",
            "Compras": "C",
            "Produção": "R",
            "Pendente": "N",
        }

        letra_kanban = mapeamento.get(novo_status, "N")

        conn = get_db_connection()
        cur = conn.cursor()

        # Otimização com executemany
        parametros = [(letra_kanban, id_ped) for id_ped in ids]
        cur.executemany("UPDATE PEDIDOS SET KANBAN = ? WHERE ID_NUMPED = ?", parametros)

        conn.commit()

        return (
            jsonify(
                {
                    "sucesso": True,
                    "mensagem": f"{len(ids)} pedidos atualizados com sucesso.",
                }
            ),
            200,
        )

    except Exception as e:
        if conn:
            conn.rollback()
        print("ERRO NO UPDATE EM LOTE:", str(e))
        return (
            jsonify({"erro": f"Erro ao atualizar status no Firebird: {str(e)}"}),
            500,
        )

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
