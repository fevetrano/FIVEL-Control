import firebase_admin
from firebase_admin import credentials, firestore
import os

# Garante que o script ache o arquivo json na mesma pasta dele
diretorio_atual = os.path.dirname(os.path.abspath(__file__))
caminho_credenciais = os.path.join(diretorio_atual, "fivel-control-credentials.json")

# 1. Aponta para o arquivo de credenciais
cred = credentials.Certificate(caminho_credenciais)
firebase_admin.initialize_app(cred)

# 2. Inicializa o cliente do Firestore
db = firestore.client()

print("🚀 Conexão com o Firebase estabelecida com sucesso!")

# 3. Puxa os dados da coleção 'pedidos' que criamos
pedidos_ref = db.collection("pedidos")
docs = pedidos_ref.stream()

print("\n--- LISTA DE PEDIDOS NO BANCO ---")
for doc in docs:
    dados = doc.to_dict()
    cliente = dados.get("cliente", "Sem Nome")
    qtd = dados.get("quantidade", 0)
    peso_uni = dados.get("peso_unitario", 0)
    preco_uni = dados.get("preco_unitario", 0)
    
    # Multiplicações automáticas da produção da cartonagem
    peso_total_kg = qtd * peso_uni
    faturamento_total = qtd * preco_uni
    
    print(f"📦 Cliente: {cliente}")
    print(f"   - Caixas produzidas: {qtd} un")
    print(f"   - Peso Total da Carga: {peso_total_kg:.2f} kg ({peso_total_kg/1000:.2f} Toneladas)")
    print(f"   - Faturamento do Pedido: R$ {faturamento_total:.2f}")
    print("-" * 35)