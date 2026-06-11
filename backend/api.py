from flask import Flask, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone
import os


app = Flask(__name__)
# Permite que o seu Frontend (React) acesse essa API sem bloqueios de segurança
CORS(app)

# --- CONFIGURAÇÃO DO BANCO DE DADOS (FIREBASE) ---
diretorio_atual = os.path.dirname(os.path.abspath(__file__))
caminho_credenciais = os.path.join(
    diretorio_atual, "fivel-control-credentials.json")

cred = credentials.Certificate(caminho_credenciais)
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- ROTA DA API ---


@app.route('/api/pedidos', methods=['GET'])
def obter_pedidos():
    try:
        pedidos_ref = db.collection("pedidos")
        docs = pedidos_ref.stream()

        lista_pedidos = []

        for doc in docs:
            dados = doc.to_dict()

            # Pegando os dados do Firestore
            cliente = dados.get("cliente", "Sem Nome")
            qtd = dados.get("quantidade", 0)
            peso_uni = dados.get("peso_unitario", 0)
            preco_uni = dados.get("preco_unitario", 0)

            # Pegando as novas coordenadas (padrão 0 se não encontrar)
            lat = dados.get("latitude", 0)
            lng = dados.get("longitude", 0)
            status = dados.get("status", "Pendente")
            cidade_bloco = dados.get("cidade_bloco", "")

            # Executando a lógica de negócio e cálculos automáticos da cartonagem
            peso_total_kg = qtd * peso_uni
            faturamento_total = qtd * preco_uni

            data_criacao = dados.get("data")
            data_entrega_ts = dados.get("data_entrega")

            dias_restantes = None
            data_entrega_formatada = ""

            if data_entrega_ts:
                # Converte o timestamp do Firebase para o formato de data do Python
                dt_entrega = data_entrega_ts.datetime if hasattr(
                    data_entrega_ts, 'datetime') else data_entrega_ts
                data_entrega_formatada = dt_entrega.strftime("%d/%m/%Y")

                # Calcula a diferença de dias até hoje (considerando apenas a data, sem horas)
                hoje = datetime.now(timezone.utc).date()
                entrega_date = dt_entrega.date()

                # Se for positivo, faltam X dias. Se for negativo, está atrasado há X dias.
                dias_restantes = (entrega_date - hoje).days

            # Organiza as informações em um formato limpo para o React ler
            lista_pedidos.append({
                "id": doc.id,
                "cliente": cliente,
                "quantidade": qtd,
                "peso_unitario": peso_uni,
                "preco_unitario": preco_uni,
                "peso_total_kg": round(peso_total_kg, 2),
                "peso_total_ton": round(peso_total_kg / 1000, 2),
                "faturamento_total": round(faturamento_total, 2),
                "latitude": lat,
                "longitude": lng,
                "status": status,
                "cidade_bloco": cidade_bloco,
                "data_entrega": data_entrega_formatada,
                "dias_restantes": dias_restantes
            })

        # Retorna a lista completa convertida em formato JSON (texto que a web entende)
        return jsonify(lista_pedidos), 200

    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- INICIALIZAÇÃO DO SERVIDOR ---
if __name__ == '__main__':
    # O servidor vai rodar na porta 5000 por padrão
    app.run(debug=True, port=5000)
