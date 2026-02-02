import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime

ARCHIVO = "Matriculas520820261.xlsx"
PERIODO = "2026-1"

# CONEXIÓN
engine = create_engine(
    "postgresql+psycopg2://postgres:123456@localhost:5432/UNITEC"
)

with engine.connect() as conn:
    # ¿YA SE CARGÓ?
    existe = conn.execute(
        text("""
            SELECT 1
            FROM control_cargas
            WHERE archivo_origen = :archivo
            AND periodo = :periodo
        """),
        {"archivo": ARCHIVO, "periodo": PERIODO}
    ).fetchone()

    if existe:
        print("Este archivo ya fue cargado para este periodo.")
        input("Presiona ENTER para cerrar...")
        exit()

# LEER EXCEL
df = pd.read_excel(ARCHIVO, header=15)

# LIMPIEZA
df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
df.columns = (
    df.columns.str.lower()
    .str.strip()
    .str.replace(" ", "_")
    .str.replace("á", "a")
    .str.replace("é", "e")
    .str.replace("í", "i")
    .str.replace("ó", "o")
    .str.replace("ú", "u")
)
df = df.dropna(how="all")

# METADATOS
df["periodo"] = PERIODO
df["fecha_carga"] = datetime.now()
df["archivo_origen"] = ARCHIVO

# CARGAR DATOS
df.to_sql(
    "matriculas",
    engine,
    if_exists="append",
    index=False
)

# REGISTRAR CARGA
with engine.begin() as conn:
    conn.execute(
        text("""
            INSERT INTO control_cargas
            (archivo_origen, periodo, fecha_carga)
            VALUES (:archivo, :periodo, :fecha)
        """),
        {
            "archivo": ARCHIVO,
            "periodo": PERIODO,
            "fecha": datetime.now()
        }
    )

print("Excel importado correctamente y registrado")
input("Presiona ENTER para cerrar...")
