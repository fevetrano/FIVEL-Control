import os
import fdb
from dotenv import load_dotenv

load_dotenv()

# Carrega DLL do Firebird
caminho_dll = os.path.abspath("fbclient.dll")
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(os.path.dirname(caminho_dll))
try:
    fdb.load_api(caminho_dll)
except Exception:
    pass

conn = fdb.connect(
    host=os.getenv("FIREBIRD_HOST"),
    database=os.getenv("FIREBIRD_DATABASE"),
    user=os.getenv("FIREBIRD_USER"),
    password=os.getenv("FIREBIRD_PASSWORD"),
    port=int(os.getenv("FIREBIRD_PORT", 3050)),
    charset="NONE",
)

cur = conn.cursor()

# Query simplificada sem filtros rígidos
cur.execute("""
    SELECT FIRST 10 p.ID_NUMPED, p.EMISSAO, c.NOME 
    FROM PEDIDOS p 
    LEFT JOIN CLIENTES c ON p.ID_CLIENTE = c.ID_CLIENTE
    WHERE NOT EXISTS (SELECT 1 FROM FISCAL f WHERE f.ID_NUMPED = p.ID_NUMPED)
    ORDER BY p.ID_NUMPED DESC
""")
for r in cur.fetchall():
    print(r)

try:
    cur.execute(query)
    resultados = cur.fetchall()
    print(f"Total de registros retornados na query basica: {len(resultados)}")
    for row in resultados:
        print(row)
except Exception as e:
    print("Erro ao executar query:", e)

conn.close()
