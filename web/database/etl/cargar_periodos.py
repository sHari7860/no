from sqlalchemy import create_engine, text
import re

engine = create_engine("postgresql+psycopg2://postgres:123456@localhost:5432/UNITEC")

def extraer_periodo(nombre_archivo):
    """Extrae el periodo del nombre del archivo Excel"""
    match = re.search(r'(\d{5})\.xlsx$', nombre_archivo)
    if match:
        ultimos_5 = match.group(1)  # '20261'
        año = ultimos_5[:4]  # '2026'
        semestre = ultimos_5[4]  # '1'
        return f"{año}-{semestre}"
    return "2026-1"

# PERIODO OBTENIDO DEL NOMBRE DEL ARCHIVO
archivo = "Matriculas520820261.xlsx"
periodo = extraer_periodo(archivo)

print(f"Periodo detectado: {periodo}")

with engine.begin() as conn:
    conn.execute(
        text("""
            INSERT INTO periodos (periodo)
            VALUES (:periodo)
            ON CONFLICT (periodo) DO NOTHING;
        """),
        {"periodo": periodo}
    )

print("Periodo cargado correctamente")