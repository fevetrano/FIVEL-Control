import os
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
import traceback
import fdb
from dotenv import load_dotenv

# --- CARREGA O CAMINHO ABSOLUTO DA DLL E SUAS DEPENDÊNCIAS ---
caminho_dll = os.path.abspath("fbclient.dll")

if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(os.path.dirname(caminho_dll))

try:
    fdb.load_api(caminho_dll)
except Exception as e:
    print(f"Aviso ao carregar DLL: {e}")

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


# --- ROTAS DA API ---


@app.route("/api/pedidos", methods=["GET"])
def obter_pedidos():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Consulta com pedido do cliente e endereço fallback
        query = """
            SELECT 
                p.ID_NUMPED AS ID_PEDIDO,
                p.PEDIDO_CLIENTE,
                p.EMISSAO,
                p.DATA_ENTREGA AS PRAZO,
                p.TOTAL_PESO AS PESO_TOTAL_PEDIDO,
                p.TOTAL_GERAL,
                p.CANCELADO,
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
                
                i.ID_PRODUTO,
                i.QUANT AS QUANTIDADE,
                i.COMP AS COMPRIMENTO,
                i.LARG AS LARGURA,
                i.ALT AS ALTURA,
                i.ID_ONDAFAB AS TIPO_ONDA,
                i.ID_QUALIDFAB AS QUALIDADE_PAPEL,
                i.PESO_TOT AS PESO_ITEM,
                i.VLUNIT AS PRECO_UNITARIO
            FROM PEDIDOS p
            LEFT JOIN CLIENTES c ON p.ID_CLIENTE = c.ID_CLIENTE
            LEFT JOIN PEDITEM i ON p.ID_NUMPED = i.ID_NUMPED
            WHERE p.EMISSAO >= '2026-05-01'
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

        # Função auxiliar para limpar e sanitizar strings vindas do banco
        def limpar_texto(valor):
            if valor is None:
                return ""
            if isinstance(valor, bytes):
                try:
                    return valor.decode("latin-1", errors="replace").strip()
                except Exception:
                    return str(valor).strip()
            return str(valor).strip()

        for reg in registros:
            row = dict(zip(colunas, reg))

            if not row.get("id_pedido"):
                continue

            id_ped = str(row["id_pedido"])

            if id_ped not in pedidos_map:
                dt_emissao = row.get("emissao")
                data_emissao_formatada = ""
                if dt_emissao:
                    try:
                        if isinstance(dt_emissao, datetime):
                            data_emissao_formatada = dt_emissao.strftime("%d/%m/%Y")
                        else:
                            data_emissao_formatada = dt_emissao.strftime("%d/%m/%Y")
                    except Exception:
                        data_emissao_formatada = str(dt_emissao)

                dt_entrega = row.get("prazo")
                data_entrega_formatada = ""
                dias_restantes = 999999  # Valor alto padrao caso nao tenha prazo para ordenacao facil

                if dt_entrega:
                    try:
                        if isinstance(dt_entrega, datetime):
                            dt_entrega_date = dt_entrega.date()
                        else:
                            dt_entrega_date = dt_entrega

                        data_entrega_formatada = dt_entrega_date.strftime("%d/%m/%Y")
                        dias_restantes = (dt_entrega_date - hoje).days
                    except Exception:
                        pass

                peso_tot_kg = (
                    float(row["peso_total_pedido"])
                    if row.get("peso_total_pedido")
                    else 0.0
                )
                faturamento_tot = (
                    float(row["total_geral"]) if row.get("total_geral") else 0.0
                )

                cliente_fantasia = limpar_texto(row.get("cliente_fantasia"))
                cliente_razao = limpar_texto(row.get("cliente_razao"))
                cliente_nome = cliente_fantasia or cliente_razao or "Cliente Sem Nome"

                cidade = limpar_texto(row.get("cidade"))
                end = limpar_texto(row.get("endereco"))
                num = str(row.get("numero")) if row.get("numero") is not None else ""
                bairro = limpar_texto(row.get("bairro"))

                # Monta a string do endereço completo
                partes_endereco = [p for p in [end, num, bairro] if p]
                endereco_comp = ", ".join(partes_endereco)

                pedidos_map[id_ped] = {
                    "id": id_ped,
                    "id_pedido": int(id_ped),
                    "pedido_cliente": limpar_texto(row.get("pedido_cliente")),
                    "cliente": cliente_nome,
                    "razao_social": cliente_razao,
                    "cidade_bloco": cidade,
                    "endereco_completo": endereco_comp,
                    "status": "Pendente",
                    "peso_total_kg": round(peso_tot_kg, 2),
                    "peso_total_ton": round(peso_tot_kg / 1000, 2),
                    "faturamento_total": round(faturamento_tot, 2),
                    "data_emissao": data_emissao_formatada,
                    "raw_emissao": str(dt_emissao) if dt_emissao else "",
                    "data_entrega": data_entrega_formatada,
                    "raw_entrega": str(dt_entrega) if dt_entrega else "",
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
                        "id_produto": limpar_texto(row["id_produto"]),
                        "quantidade": row.get("quantidade") or 0,
                        "comprimento": row.get("comprimento") or 0,
                        "largura": row.get("largura") or 0,
                        "altura": row.get("altura") or 0,
                        "tipo_onda": limpar_texto(row.get("tipo_onda")),
                        "qualidade_papel": limpar_texto(row.get("qualidade_papel")),
                        "peso_item": (
                            float(row["peso_item"]) if row.get("peso_item") else 0.0
                        ),
                        "preco_unitario": (
                            float(row["preco_unitario"])
                            if row.get("preco_unitario")
                            else 0.0
                        ),
                    }
                )
                pedidos_map[id_ped]["total_itens"] = len(pedidos_map[id_ped]["itens"])

        lista_pedidos = list(pedidos_map.values())

        # --- ORDENAÇÃO DINÂMICA VIA PARÂMETROS DA URL ---
        # Exemplo: /api/pedidos?ordenar_por=data_entrega&ordem=asc
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


@app.route("/api/pedidos/status-lote", methods=["PUT"])
def atualizar_status_lote():
    conn = None
    try:
        dados = request.get_json()
        ids = dados.get("ids", [])
        novo_status = dados.get("status", "Em Entrega")

        if not ids:
            return jsonify({"erro": "Nenhum ID fornecido"}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        for id_pedido in ids:
            cur.execute(
                "UPDATE PEDIDOS SET KANBAN = ? WHERE ID_NUMPED = ?",
                (novo_status[0], id_pedido),
            )

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
        print("ERRO NO UPDATE:", str(e))
        return (
            jsonify({"erro": f"Erro ao atualizar status no Firebird: {str(e)}"}),
            500,
        )

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
