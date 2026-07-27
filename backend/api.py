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

        # Consulta validada: retorna todos os pedidos ativos sem NF na FISCAL
        query = """
            SELECT 
                p.ID_NUMPED AS ID_PEDIDO,
                p.EMISSAO,
                p.DATA_ENTREGA AS PRAZO,
                p.TOTAL_PESO AS PESO_TOTAL_PEDIDO,
                p.TOTAL_GERAL,
                p.CANCELADO,
                c.ID_CLIENTE,
                c.NOME AS CLIENTE_RAZAO,
                COALESCE(c.GUERRA, c.NOME) AS CLIENTE_FANTASIA,
                c.ENT_ENDERECO AS ENDERECO,
                c.ENT_NUMERO AS NUMERO,
                c.ENT_BAIRRO AS BAIRRO,
                c.ENT_CIDADE AS CIDADE,
                c.ENT_ID_ESTADO AS UF,
                c.ENT_CEP AS CEP,
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
            WHERE NOT EXISTS (
                SELECT 1 FROM FISCAL f WHERE f.ID_NUMPED = p.ID_NUMPED
            )
            ORDER BY p.DATA_ENTREGA ASC;
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
                dt_entrega = row.get("prazo")
                data_entrega_formatada = ""
                dias_restantes = None

                if dt_entrega:
                    try:
                        if isinstance(dt_entrega, datetime):
                            dt_entrega_date = dt_entrega.date()
                        else:
                            dt_entrega_date = dt_entrega

                        data_entrega_formatada = dt_entrega_date.strftime("%d/%m/%Y")
                        dias_restantes = (dt_entrega_date - hoje).days
                    except Exception:
                        dias_restantes = None

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
                num = limpar_texto(row.get("numero"))
                bairro = limpar_texto(row.get("bairro"))

                endereco_comp = f"{end}, {num} - {bairro}".strip(", -")

                pedidos_map[id_ped] = {
                    "id": id_ped,
                    "cliente": cliente_nome,
                    "razao_social": cliente_razao,
                    "cidade_bloco": cidade,
                    "endereco_completo": endereco_comp,
                    "status": "Pendente",
                    "peso_total_kg": round(peso_tot_kg, 2),
                    "peso_total_ton": round(peso_tot_kg / 1000, 2),
                    "faturamento_total": round(faturamento_tot, 2),
                    "data_entrega": data_entrega_formatada,
                    "dias_restantes": dias_restantes,
                    "latitude": -23.6939,
                    "longitude": -46.5650,
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

        lista_pedidos = list(pedidos_map.values())
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
